"""R01-R14: new recovery acceptance, not a replay of #335's reader tests."""
import hashlib
import json
import re
import unittest
from html import unescape
from uuid import uuid4
from unittest.mock import patch

from sqlalchemy import select
from dkss_app import driving_access, driving_pending_identity as recovery
from driving_identity_fixture import DrivingIdentityFixture
from test_q08_postgres_identity import DisposablePostgres
from test_driving_report_ai import pdf_bytes


class PendingRecoveryTests(DrivingIdentityFixture, unittest.TestCase):
    def login(self, user):
        super().login(user)
        # The unit fixture deliberately retains an outer app context; a real
        # browser gets a new g on every request. Do not reuse the previous
        # account's cached CSRF token across this fixture's login switch.
        from flask import g
        g.pop('csrf_token', None)

    def setUp(self):
        super().setUp()
        self.admin = self.m.User.query.filter_by(company_code='TEST', username='admin').one()
        self.person_to_confirm = self.person(username='confirmed-person', name='確認対象')
        self.login(self.admin)
        self.m.app.config['WTF_CSRF_ENABLED'] = True
        self.pending = self.m.VehicleImportPending(id=str(uuid4()), company_code='TEST', match_key=str(uuid4()),
            identity_json=json.dumps({'source_vehicle_number': '名古屋100あ1234'}), created_by_username='old-importer')
        self.m.db.session.add(self.pending); self.m.db.session.flush()
        self.item, self.draft = self.seed(1)
        self.url = f'/master/vehicles/pending/{self.pending.id}/driving-reports/{self.item.id}/identity?q=1234'

    def seed(self, index):
        source = pdf_bytes() + ('\n% independent-source-' + str(index)).encode()
        payload = dict(record_date='2026-10-20', vehicle_record_id=None, mileage='1000', distance='120',
            content='SAVED-ORIGINAL-'+str(index), driver_name='保存された旧本人', driver_code='old-person-code',
            source_system='synthetic', report_scope='daily', report_items=[], source_pages=[1],
            _driving_account_choice='old-deleted-selection')
        draft = self.m.VehicleDocumentImportDraft(id=str(uuid4()), batch_id='recovery-batch', company_code='TEST',
            created_by_username='old-importer', document_type='driving_report', status='completed',
            source_filename='saved-'+str(index)+'.pdf', source_file=source,
            source_sha256=hashlib.sha256(source).hexdigest(), preview_json=json.dumps({'records': [payload]}))
        self.m.db.session.add(draft); self.m.db.session.flush()
        item = self.m.VehicleImportPendingRecord(id=str(uuid4()), company_code='TEST', pending_id=self.pending.id,
            source_kind='driving_report', record_key=str(uuid4()), document_draft_id=draft.id, source_record_index=0,
            record_date='2026-10-20', payload_json=json.dumps(payload), created_by_username='old-importer')
        self.m.db.session.add(item); self.m.db.session.flush()
        draft.result_json=json.dumps({'records': [], 'pending_records': [{'pending_record_id': item.id}], 'pending_count': 1})
        self.m.db.session.commit()
        return item, draft

    def snapshot(self):
        return {table.name: sorted((tuple(map(repr, r)) for r in self.m.db.session.execute(select(table))), key=repr)
                for table in self.m.db.metadata.sorted_tables}

    def raw(self):
        return self.draft.source_file, self.draft.source_sha256, self.draft.preview_json, self.item.payload_json

    def form(self, url=None):
        response = self.client.get(url or self.url)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[-1000:])
        html = response.get_data(as_text=True)
        data = {name: unescape(value) for name, value in re.findall(r'<input\b[^>]*name="([^"]+)"[^>]*value="([^"]*)"', html)}
        return dict(data, reader_username=self.person_to_confirm.username, evidence_basis='company_record',
                    checked='yes', decision='confirmed', evidence_reference='')

    def confirm(self, **updates):
        data = self.form(); data.update(updates)
        response = self.client.post(self.url, data=data)
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[-1000:])
        return json.loads(self.item.result_json)[recovery.KEY][-1]

    def apply(self, html=False):
        path = f'/master/vehicles/pending/{self.pending.id}?q=1234'
        page = self.client.get(path)
        match = re.search(r'name="csrf_token"\s+value="([^"]*)"', page.get_data(as_text=True))
        if match:self.apply_data={'csrf_token': unescape(match.group(1)), 'vehicle_record_id': self.vehicle.id}
        self.assertTrue(hasattr(self, 'apply_data'))
        return self.client.post(path, data=self.apply_data,
            headers={'Accept':'text/html','Sec-Fetch-Dest':'document'} if html else {})

    def test_R01_existing_readback_and_optional_reference_confirm_without_reupload(self):
        raw = self.raw(); data = self.form()
        page = self.client.get(self.url).get_data(as_text=True)
        self.assertIn('保存済み日報の本人再確認', page); self.assertIn('SAVED-ORIGINAL-1', page)
        self.assertIn('document-sources/'+self.draft.id, page)
        self.assertNotIn('value="confirmed-person" selected', page)
        self.assertEqual(self.client.post(self.url, data=data).status_code, 302)
        self.assertEqual(self.raw(), raw)
        self.assertEqual(self.m.VehicleDrivingReportRecord.query.count(), 0)
        self.assertEqual(driving_access.DrivingReaderAccount.query.count(), 0)
        self.assertEqual(self.pending.status, 'pending')

    def test_R02_new_confirmation_keeps_old_values_and_prior_result_keys(self):
        self.item.result_json=json.dumps({'legacy_note': 'OLD-TRACE'}); self.m.db.session.commit()
        raw = self.raw(); event = self.confirm()
        result = json.loads(self.item.result_json)
        self.assertEqual(result['legacy_note'], 'OLD-TRACE'); self.assertEqual(self.raw(), raw)
        self.assertEqual(event['account_identity'], self.person_to_confirm.account_identity)
        self.assertEqual(event['actor_identity'], self.admin.account_identity)
        self.assertEqual(event['legacy_selection']['_driving_account_choice'], 'old-deleted-selection')
        self.assertIsNone(event['legacy_selection']['_driving_account_identity'])

    def test_R03_basis_and_explicit_check_required_but_free_text_is_optional(self):
        data = self.form()
        for changes in ({'reader_username': ''}, {'evidence_basis': ''}, {'checked': ''}):
            before=self.snapshot()
            self.assertEqual(self.client.post(self.url, data={**data, **changes}).status_code, 400)
            self.assertEqual(self.snapshot(), before)
        self.confirm(evidence_reference='')

    def test_R04_later_apply_uses_new_evidence_and_preserves_it_on_retry(self):
        raw=self.raw(); event=self.confirm()
        self.assertEqual(self.apply().status_code, 302)
        row=self.m.VehicleDrivingReportRecord.query.one()
        self.assertEqual(driving_access.reader(row).user_id, self.person_to_confirm.id)
        self.assertEqual(json.loads(row.details_json)['driver_name'], '保存された旧本人')
        self.assertEqual(json.loads(row.details_json)['identity_recovery']['event_id'], event['id'])
        self.assertEqual(json.loads(self.item.result_json)[recovery.KEY], [event])
        self.assertEqual(self.raw(), raw)
        before=self.snapshot(); self.assertEqual(self.apply().status_code,302); self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.client.get(self.url).status_code,200)

    def test_R05_409_offers_fixed_get_back_to_original_and_queue(self):
        response=self.apply(html=True)
        self.assertEqual(response.status_code,409)
        self.assertEqual(response.headers['X-DKSS-Import-Recovery'],'1')
        html=response.get_data(as_text=True)
        self.assertIn('最新の状態で本人を確認し直す',html)
        self.assertIn(self.item.id+'/identity',html); self.assertIn('q=1234',html)
        self.assertIn('SAVED-ORIGINAL-1',html)
        self.assertNotIn('value="confirmed"',html)

    def test_R06_hold_after_confirmation_appends_and_keeps_group_pending(self):
        first=self.confirm(); second=self.confirm(decision='hold',reader_username='',checked='',evidence_basis='')
        self.assertEqual(second['previous'],first['id']); self.assertIsNone(second['account_identity'])
        before=self.snapshot(); self.assertEqual(self.apply().status_code,409); self.assertEqual(self.snapshot(),before)
        self.assertEqual(json.loads(self.item.result_json)[recovery.KEY], [first,second])

    def test_R07_non_manager_and_foreign_company_cannot_review_or_save(self):
        data=self.form(); self.login(self.person_to_confirm)
        dashboard=self.client.get('/').get_data(as_text=True)
        csrf=re.search(r'name="csrf-token"\s+content="([^"]*)"',dashboard)
        self.assertIsNotNone(csrf)
        data['csrf_token']=unescape(csrf.group(1))
        before=self.snapshot()
        for response in (self.client.get(self.url),self.client.post(self.url,data=data)):
            self.assertEqual((response.status_code,response.location),(302,'/'))
            self.assertNotIn('SAVED-ORIGINAL',response.get_data(as_text=True))
        self.assertEqual(self.snapshot(),before)
        self.login(self.admin)
        foreign=self.m.VehicleImportPending(id=str(uuid4()),company_code='OTHER',match_key=str(uuid4()),created_by_username='other')
        self.m.db.session.add(self.m.Company(company_code='OTHER',company_name='Other',active=True)); self.m.db.session.add(foreign); self.m.db.session.commit()
        self.assertEqual(self.client.get(self.url.replace(self.pending.id,foreign.id),headers={'Accept':'application/json'}).status_code,404)

    def test_R08_resource_and_person_proofs_are_both_required_and_csrf_is_real(self):
        data=self.form()
        for field in ('person_selection_token','target_token'):
            for value in ('',data[field]+'tampered'):
                before=self.snapshot()
                self.assertEqual(self.client.post(self.url,data={**data,field:value}).status_code,409)
                self.assertEqual(self.snapshot(),before)
        no_csrf={**data}; no_csrf.pop('csrf_token')
        self.assertEqual(self.client.post(self.url,data=no_csrf).status_code,400)
        html_response=self.client.post(self.url,data=no_csrf,headers={'Accept':'text/html','Sec-Fetch-Dest':'document'})
        self.assertEqual(html_response.status_code,400)
        self.assertIn('確認画面へ戻る',html_response.get_data(as_text=True))

    def test_R09_duplicate_post_and_two_forms_never_replace_prior_confirmation(self):
        first=self.form(); second=self.form()
        self.assertEqual(self.client.post(self.url,data=first).status_code,302)
        before=self.snapshot()
        self.assertEqual(self.client.post(self.url,data=second).status_code,409)
        self.assertEqual(self.client.post(self.url,data=first).status_code,409)
        self.assertEqual(self.snapshot(),before)

    def test_R10_changed_payload_never_uses_a_previous_source_binding(self):
        self.confirm()
        p=json.loads(self.item.payload_json); p['distance']='999'; self.item.payload_json=json.dumps(p)
        preview=json.loads(self.draft.preview_json); preview['records'][0]=p; self.draft.preview_json=json.dumps(preview); self.m.db.session.commit()
        before=self.snapshot(); self.assertEqual(self.apply().status_code,409); self.assertEqual(self.snapshot(),before)

    def test_R11_audit_failure_rolls_back_new_event_and_apply_failure_keeps_it(self):
        data=self.form(); before=self.snapshot()
        with patch.object(recovery.audit,'add_audit_log',side_effect=RuntimeError('synthetic-audit-failure')):
            self.assertEqual(self.client.post(self.url,data=data).status_code,500)
        self.assertEqual(self.snapshot(),before)
        event=self.confirm(); before=self.snapshot()
        with patch.object(driving_access,'resolve_import',side_effect=RuntimeError('synthetic-apply-failure')):
            self.assertEqual(self.apply().status_code,500)
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(json.loads(self.item.result_json)[recovery.KEY],[event])

    def test_R12_more_than_ten_pending_sources_remain_reachable_and_atomic(self):
        for index in range(2,13):self.seed(index)
        page=self.client.get(f'/master/vehicles/pending/{self.pending.id}').get_data(as_text=True)
        self.assertEqual(page.count('：原本と本人を確認'),12)
        self.confirm(); before=self.snapshot()
        self.assertEqual(self.apply().status_code,409); self.assertEqual(self.snapshot(),before)

    def test_R13_confirmation_survives_rename_and_audit_retention(self):
        event=self.confirm(); self.person_to_confirm.last_name='改姓後'; self.m.AuditLog.query.delete(); self.m.db.session.commit()
        self.assertEqual(self.apply().status_code,302)
        self.assertEqual(json.loads(self.item.result_json)[recovery.KEY],[event])
        self.assertIn('確認対象',self.client.get(self.url).get_data(as_text=True))

    def test_R14_valid_normal_pending_does_not_require_recovery(self):
        p=json.loads(self.item.payload_json); p['_driving_account_choice']=self.person_to_confirm.username
        p['_driving_account_identity']=self.person_to_confirm.account_identity
        self.item.payload_json=json.dumps(p); self.draft.preview_json=json.dumps({'records':[p]}); self.m.db.session.commit()
        page=self.client.get(f'/master/vehicles/pending/{self.pending.id}').get_data(as_text=True)
        self.assertNotIn('：原本と本人を確認',page)
        self.assertEqual(self.apply().status_code,302)
        self.assertNotIn(recovery.KEY,json.loads(self.item.result_json))

    def test_R07_role_name_without_current_actor_or_active_company_is_insufficient(self):
        data=self.form()
        from flask import session
        from werkzeug.exceptions import HTTPException
        with self.m.app.test_request_context():
            session.update(company_code='TEST',username='admin',role='admin',account_identity='missing-generation',password_changed_at=self.admin.password_changed_at)
            with self.assertRaises(HTTPException) as failure:recovery.permitted()
            self.assertEqual(failure.exception.code,403)
        self.admin.role='itc'; self.m.Company.query.filter_by(company_code='TEST').one().active=False
        self.m.db.session.commit(); self.login(self.admin)
        dashboard=self.client.get('/').get_data(as_text=True)
        csrf=re.search(r'name="csrf-token"\s+content="([^"]*)"',dashboard)
        self.assertIsNotNone(csrf); data['csrf_token']=unescape(csrf.group(1))
        before=self.snapshot()
        self.assertEqual(self.client.post(self.url,data=data,headers={'Accept':'application/json'}).status_code,403)
        self.assertEqual(self.snapshot(),before)

    def test_R08_target_token_cannot_be_reused_on_another_saved_record(self):
        data=self.form(); other,_=self.seed(2)
        before=self.snapshot()
        self.assertEqual(self.client.post(self.url.replace(self.item.id,other.id),data=data).status_code,409)
        self.assertEqual(self.snapshot(),before)

    def test_R09_confirmation_holds_real_person_lock_until_atomic_commit(self):
        from sqlalchemy import text
        from sqlalchemy.exc import OperationalError
        data=self.form(); original=recovery.audit.add_audit_log; observed=[]
        person_id=self.person_to_confirm.id
        def competing(*args,**kwargs):
            with self.m.db.engine.connect() as other:
                transaction=other.begin()
                try:
                    if other.dialect.name=='sqlite':other.exec_driver_sql('PRAGMA busy_timeout=100')
                    else:other.exec_driver_sql("SET LOCAL lock_timeout='100ms'")
                    with self.assertRaises(OperationalError) as blocked:
                        other.execute(text('DELETE FROM "user" WHERE id=:id'),{'id':person_id})
                    if other.dialect.name=='postgresql':self.assertEqual(blocked.exception.orig.pgcode,'55P03')
                    else:self.assertIn(blocked.exception.orig.sqlite_errorcode & 255,(5,6))
                    observed.append(True)
                finally:transaction.rollback()
            return original(*args,**kwargs)
        with patch.object(recovery.audit,'add_audit_log',side_effect=competing):
            self.assertEqual(self.client.post(self.url,data=data).status_code,302)
        self.assertEqual(observed,[True])

    def test_R09_two_managers_racing_save_one_confirmation_without_partial_history(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from sqlalchemy import text
        first=self.form()
        with self.client.session_transaction() as state:claims_one=dict(state)
        other=self.person(username='competing-manager'); other.role='admin'; self.m.db.session.commit(); self.login(other)
        second=self.form()
        with self.client.session_transaction() as state:claims_two=dict(state)
        self.m.db.session.commit()
        ready,release=Event(),Event(); original=recovery.audit.add_audit_log
        def paused(*args,**kwargs):
            if not ready.is_set():
                ready.set()
                if not release.wait(10):raise RuntimeError('confirmation was not released')
            return original(*args,**kwargs)
        def post(data,claims):
            with self.m.app.app_context():
                try:
                    if self.m.db.engine.dialect.name=='sqlite':self.m.db.session.connection().exec_driver_sql('PRAGMA busy_timeout=100')
                    else:self.m.db.session.execute(text("SET LOCAL lock_timeout='100ms'"))
                    client=self.m.app.test_client()
                    with client.session_transaction() as state:state.update(claims)
                    return client.post(self.url,data=data,headers={'Accept':'application/json'}).status_code
                finally:self.m.db.session.remove()
        with patch.object(recovery.audit,'add_audit_log',side_effect=paused),ThreadPoolExecutor(max_workers=2) as pool:
            saving=pool.submit(post,first,claims_one)
            try:
                self.assertTrue(ready.wait(10))
                self.assertEqual(pool.submit(post,second,claims_two).result(timeout=10),409)
            finally:release.set()
            self.assertEqual(saving.result(timeout=10),302)
        self.m.db.session.expire_all()
        events=json.loads(self.item.result_json)[recovery.KEY]
        self.assertEqual(len(events),1); self.assertEqual(events[0]['actor_identity'],self.admin.account_identity)
        self.assertEqual(self.m.VehicleDrivingReportRecord.query.count(),0)

    def test_R10_signed_confirmation_is_rejected_if_stored_uuid_is_modified(self):
        self.confirm(); result=json.loads(self.item.result_json)
        result[recovery.KEY][-1]['account_identity']=self.admin.account_identity
        self.item.result_json=json.dumps(result); self.m.db.session.commit()
        before=self.snapshot(); self.assertEqual(self.apply().status_code,409); self.assertEqual(self.snapshot(),before)

    def test_R10_confirmed_account_replacement_does_not_reuse_old_manual_or_numeric_id(self):
        event=self.confirm(); old=self.person_to_confirm; ident=old.id; name=old.username
        self.m.db.session.delete(old); self.m.db.session.commit()
        replacement=self.person(username=name,ident=ident)
        self.assertNotEqual(replacement.account_identity,event['account_identity'])
        before=self.snapshot(); self.assertEqual(self.apply().status_code,409); self.assertEqual(self.snapshot(),before)
        self.assertEqual(driving_access.DrivingReaderAccount.query.count(),0)

    def test_R11_malformed_history_is_held_without_overwriting_it(self):
        self.item.result_json='not-json'; self.m.db.session.commit()
        before=self.snapshot()
        response=self.client.get(self.url)
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.snapshot(),before); self.assertEqual(self.item.result_json,'not-json')
        self.item.result_json='{}'; self.item.payload_json='broken saved payload'; self.m.db.session.commit()
        before=self.snapshot()
        self.assertEqual(self.client.get(self.url).status_code,409)
        self.assertEqual(self.snapshot(),before)

    def test_R13_confirmation_and_application_actors_remain_distinct(self):
        event=self.confirm(); approver=self.admin.account_identity
        other=self.person(username='second-manager'); other.role='admin'; self.m.db.session.commit(); self.login(other)
        self.assertEqual(self.apply().status_code,302)
        row=self.m.VehicleDrivingReportRecord.query.one()
        self.assertEqual(json.loads(self.item.result_json)[recovery.KEY][0]['actor_identity'],approver)
        grant=driving_access.DrivingReaderAccount.query.one()
        self.assertEqual(grant.actor_identity,other.account_identity)
        self.assertEqual(json.loads(row.details_json)['identity_recovery']['confirmed_by'],event['actor_identity'])


class PostgresPendingRecoveryTests(DisposablePostgres, PendingRecoveryTests):
    pass
