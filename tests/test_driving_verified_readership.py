from driving_selection_fixture import fresh_person_proof
"""No.10 acceptance: candidates never authorize a stored report without UUID evidence."""
import csv
import io
import json
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from flask import session
from pypdf import PdfReader
from werkzeug.exceptions import HTTPException
from dkss_app import driving_access
from driving_report_data import version
from driving_identity_fixture import DrivingIdentityFixture
from test_q08_postgres_identity import DisposablePostgres


class VerifiedReadershipTests(DrivingIdentityFixture,unittest.TestCase):
    def manager(self):
        return self.m.User.query.filter_by(company_code='TEST',username='admin').one()

    def grant(self,row,user):
        self.login(self.manager())
        response=self.client.post(f'/safety/driving-reports/{row.id}/reader',data={
            'version':version(row),'person_selection_token':fresh_person_proof(self.client),'reader_username':user.username})
        self.assertEqual(response.status_code,302)

    def import_identity(self,row,**kw):
        with self.m.app.test_request_context():
            admin=self.manager()
            session.update(company_code='TEST',username=admin.username,role='admin',account_identity=admin.account_identity)
            driving_access.resolve_import(row,**kw)

    def assert_private(self,row,user):
        self.login(user)
        _,ctx=self.render(self.url+'&scope=company')
        self.assertEqual(ctx['total'],0);self.assertEqual(ctx['reflection']['candidate_count'],0)
        self.assertEqual(self.client.get(f'/safety/driving-reports/{row.id}').status_code,404)
        for suffix in ['', '&view=comparison','&view=breakdown']:
            response=self.client.get('/safety/driving-reports/export.csv?period=all'+suffix)
            self.assertEqual(response.status_code,200)
            self.assertEqual(len(list(csv.reader(io.StringIO(response.data.decode('utf-8-sig'))))),1)
        response=self.client.get('/safety/driving-reports/export.pdf?period=all')
        self.assertEqual(response.status_code,200)
        text=''.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(response.data)).pages)
        self.assertNotIn('監査人物',text);self.assertNotIn('NO10_PRIVATE',text)
        self.assertNotIn('原本:'+row.source_draft_id,text)
        state=self.client.get('/safety/driving-reports/reflection?period=all').json
        self.assertEqual(state['candidate_count'],0);self.assertEqual(state['items'],[])

    def test_deleted_person_same_name_username_and_numeric_id_never_inherits(self):
        for index,(username,reuse) in enumerate([('retired',False),('different',False),('retired',True)],1):
            old=self.person(username='old'+str(index));old.username='retired';self.m.db.session.commit()
            old_id,old_uuid=old.id,old.account_identity;row=self.save(index)
            self.m.db.session.delete(old);self.m.db.session.commit()
            new=self.person(username=username,ident=old_id if reuse else old_id+100)
            self.assertNotEqual(new.account_identity,old_uuid)
            self.assert_private(row,new)
            self.m.db.session.delete(new);self.m.db.session.commit()

    def test_unbound_report_stays_held_after_duplicate_name_disappears(self):
        old=self.person();row=self.save();new=self.person(username='new')
        self.assert_private(row,new)
        self.m.db.session.delete(old);self.m.db.session.commit();self.assert_private(row,new)

    def test_candidate_and_reidentification_cannot_backfill_legacy_uuid(self):
        person=self.person();row=self.save();raw=row.details_json
        self.import_identity(row)
        self.import_identity(row,reidentify=True)
        self.m.db.session.commit()
        self.assertEqual(driving_access.DrivingReaderAccount.query.count(),0)
        self.assertEqual(row.details_json,raw);self.assert_private(row,person)

    def test_new_name_only_is_candidate_but_not_automatic_past_identity(self):
        person=self.person();row=self.save(commit=False)
        self.import_identity(row);self.m.db.session.commit()
        self.assertEqual(driving_access.DrivingReaderAccount.query.count(),0)
        self.assert_private(row,person)

    def test_verified_code_anchor_auto_saves_uuid_only_in_new_transaction(self):
        person=self.person();anchor=self.save(day='2026-10-01');self.grant(anchor,person)
        legacy=self.save(2,day='2026-10-02')
        self.import_identity(legacy);self.m.db.session.commit()
        self.assertEqual(driving_access.DrivingReaderAccount.query.count(),1)
        fresh=self.save(3,commit=False,day='2026-10-03')
        self.import_identity(fresh)
        self.assertEqual(driving_access.DrivingReaderAccount.query.count(),2)
        self.m.db.session.commit();self.login(person)
        self.assertEqual(self.client.get(f'/safety/driving-reports/{fresh.id}').status_code,200)
        self.assertEqual(self.client.get(f'/safety/driving-reports/{legacy.id}').status_code,404)

    def test_import_rollback_does_not_leave_uuid_or_new_transaction_capability(self):
        person=self.person();anchor=self.save();self.grant(anchor,person)
        row=self.save(2,commit=False,day='2026-10-11');self.import_identity(row)
        self.m.db.session.rollback()
        self.assertEqual(driving_access.DrivingReaderAccount.query.count(),1)
        self.assertEqual(self.m.VehicleDrivingReportRecord.query.count(),1)

    def test_automatic_grant_rechecks_candidate_uuid_before_persisting(self):
        person=self.person();row=self.save()
        with self.m.app.test_request_context():
            admin=self.manager()
            session.update(company_code='TEST',username='admin',role='admin',account_identity=admin.account_identity)
            with self.assertRaises(HTTPException) as error:
                driving_access.assign([row],person.username,'__automatic_identity_v1__',
                                      expected_identity='deleted-generation')
            self.assertEqual(error.exception.code,409)
        self.assertEqual(driving_access.DrivingReaderAccount.query.count(),0)

    def test_previous_accounts_saved_ai_cannot_reappear_for_reused_numeric_id(self):
        old=self.person();row=self.save();self.grant(row,old);self.login(old)
        _,ctx=self.render(self.url)
        executor=self.m.app.extensions['driving_reflection_executor']
        with patch.dict('os.environ',{'OPENAI_API_KEY':'mock-only'}),patch.object(executor,'submit') as submit:
            response=self.client.post('/safety/driving-reports/reflection',data=dict(ctx['filters'],input_key=ctx['reflection']['key']))
            self.assertEqual(response.status_code,202)
            work,*args=submit.call_args.args;document=args[-1]
        evidence=document['evidence'][0]
        with patch('driving_report_reflection.generate',return_value={'items':[{
                'evidence_id':evidence['id'],'action':evidence['allowed_actions'][0]}]}):
            with ThreadPoolExecutor(max_workers=1) as worker:worker.submit(work,*args).result(timeout=15)
        self.assertEqual(self.client.get('/safety/driving-reports/reflection?period=all').json['status'],'completed')
        ident=old.id;self.m.db.session.delete(old);self.m.db.session.commit()
        new=self.person(ident=ident);self.assert_private(row,new)

    def test_reapproval_is_specific_keeps_raw_data_and_admin_company_totals(self):
        person=self.person();row=self.save();other=self.save(2);raw=row.details_json
        self.login(self.manager());page,ctx=self.render(self.url+'&scope=company')
        self.assertEqual(ctx['insights']['summary']['distance'],200)
        self.assertIn('本人未確定',self.client.get(f'/safety/driving-reports/{row.id}').get_data(as_text=True))
        self.grant(row,person);self.login(person)
        self.assertEqual(self.client.get(f'/safety/driving-reports/{row.id}').status_code,200)
        self.assertEqual(self.client.get(f'/safety/driving-reports/{other.id}').status_code,404)
        self.assertEqual(json.loads(row.details_json)['distance'],json.loads(raw)['distance'])
        self.assertEqual(driving_access.DrivingReaderAccount.query.one().account_identity,person.account_identity)

    def test_other_company_and_stale_generation_never_receive_old_report(self):
        old=self.person();row=self.save();self.grant(row,old)
        ident=old.id;self.m.db.session.delete(old);self.m.db.session.commit()
        new=self.person(ident=ident);self.assert_private(row,new)
        self.m.db.session.add(self.m.Company(company_code='OTHER',company_name='Other',active=True,vehicle_limit=1))
        self.m.db.session.commit();outsider=self.person(company='OTHER');self.assert_private(row,outsider)

    def test_initializer_is_repeatable_and_does_not_promote_legacy_people(self):
        person=self.person();row=self.save();raw=row.details_json
        for _ in range(2):driving_access.initialize_driving_access(self.m.app)
        self.assertEqual(driving_access.DrivingReaderAccount.query.count(),0)
        self.assertEqual(row.details_json,raw);self.assert_private(row,person)

    def test_empty_personal_page_explains_exclusion_without_disclosing_held_count(self):
        person=self.person();self.save();self.login(person)
        page,_=self.render(self.url)
        text=page.get_data(as_text=True)
        self.assertIn('実績が0件であることを意味しません',text)
        self.assertIn('本人未確定',text);self.assertNotIn('NO10_PRIVATE',text)


class PostgresVerifiedReadershipTests(DisposablePostgres,VerifiedReadershipTests):
    pass


if __name__=='__main__':unittest.main()
