"""Synthetic PDF originals and isolated SQLite; no real vehicle/legal assertion.

The PDF helper encodes fictional vehicle/date text via an actual ToUnicode CMap.
No source parser, source bytes, identity matcher, or certificate reader is mocked.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta
from io import BytesIO
import hashlib
import json
import unittest
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from sqlalchemy import event
import test_q02_daily_inspection_flow as daily
from dkss_app.priority_certificate_sources import (
    verify_certificate_expiry_literal, read_certificate_expiry_sources,
    certificate_confirmation_options, preview_certificate_confirmation,
    certificate_confirmation_inputs, read_certificate_confirmation_original, STATEMENTS,
)


def original_pdf(text):
    writer = PdfWriter(); page = writer.add_blank_page(width=595, height=842)
    cmap = DecodedStreamObject()
    cmap.set_data(b'/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n'
        b'/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n'
        b'/CMapName /FictionalIdentity def /CMapType 2 def\n'
        b'1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n'
        b'1 beginbfrange\n<0000> <FFFF> <0000>\nendbfrange\n'
        b'endcmap CMapName currentdict /CMap defineresource pop end end')
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type0'), NameObject('/BaseFont'): NameObject('/TestFont'),
        NameObject('/Encoding'): NameObject('/Identity-H'), NameObject('/ToUnicode'): writer._add_object(cmap)})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
        DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(('BT /F1 10 Tf 20 700 Td <' + text.encode('utf-16-be').hex() + '> Tj ET').encode())
    page[NameObject('/Contents')] = writer._add_object(stream)
    output = BytesIO(); writer.write(output); return output.getvalue()


def text_for(expiry, chassis='TEST-12345', model='TESTMODEL'):
    return f'自動車検査証記録事項 車台番号 {chassis} 型式 {model} 有効期間の満了する日 {expiry}'


class CertificateSourceTests(unittest.TestCase):
    setUpClass = classmethod(daily.Q02DailyInspectionFlowTests.setUpClass.__func__)
    tearDownClass = classmethod(daily.Q02DailyInspectionFlowTests.tearDownClass.__func__)
    tearDown = daily.Q02DailyInspectionFlowTests.tearDown
    login = daily.Q02DailyInspectionFlowTests.login
    request = daily.Q02DailyInspectionFlowTests.request

    def setUp(self):
        daily.Q02DailyInspectionFlowTests.setUp(self)
        from dkss_app.vehicle_inspection_plans_models import get_models
        _, _, self.Execution, self.Evidence = get_models(self.db)
        self.day = datetime.now(ZoneInfo('Asia/Tokyo')).date()
        self.vehicle = self.models.Vehicle.query.filter_by(company_code='A').one()
        self.vehicle.chassis_number = 'TEST-12345'; self.vehicle.model_code = 'TESTMODEL'
        self.vehicle.inspection_expiry = self.day.isoformat()
        self.db.session.commit()
        self.document = self.add_document(self.day.isoformat())
        self.selection = {'document_id': self.document.id}

    def add_document(self, expiry, *, raw=None, company='A', vehicle=None):
        vehicle = vehicle or self.vehicle
        raw = original_pdf(text_for(expiry, vehicle.chassis_number, vehicle.model_code)) if raw is None else raw
        doc = self.models.VehicleDocumentImportDraft(id=str(uuid4()), batch_id=str(uuid4()), company_code=company,
            created_by_username='admin', document_type='certificate', source_filename='synthetic-only.pdf',
            source_file=raw, source_sha256=hashlib.sha256(raw).hexdigest(), status='certificate_linked',
            preview_json=json.dumps({'certificate_extraction': {'vehicle': {'chassis_number': vehicle.chassis_number,
                'model_code': vehicle.model_code, 'inspection_expiry': expiry}}}),
            result_json=json.dumps({'vehicle_record_id': vehicle.id, 'identity': {
                'chassis_number': vehicle.chassis_number, 'model_code': vehicle.model_code}}),
            created_at=datetime(2026, 1, 1), completed_at=datetime(2026, 1, 1))
        self.db.session.add(doc); self.db.session.commit(); return doc

    def update(self, previous, new, document, performed=None, kind='vehicle_inspection'):
        execution = self.Execution(company_code='A', vehicle_record_id=self.vehicle.id, kind=kind,
            performed_date=performed or (self.day-timedelta(days=30)).isoformat(),
            created_at='2026-01-01T10:00:00+09:00', created_by='admin')
        self.db.session.add(execution); self.db.session.flush()
        evidence = self.Evidence(execution_id=execution.id, company_code='A', previous_expiry=previous,
            new_expiry=new, document_id=document.id if document else None,
            confirmation='合成試験の実施種別・実施日確認', attachment_confirmation='合成原本の種別確認')
        self.db.session.add(evidence); self.db.session.commit(); return execution, evidence

    def read(self):
        return read_certificate_expiry_sources(self.vehicle, as_of=self.day)

    def preview(self, selection=None, as_of=None):
        return preview_certificate_confirmation(self.vehicle, selection or self.selection, as_of=as_of or self.day)

    def inputs(self, preview=None, as_of=None):
        day = as_of or self.day
        return certificate_confirmation_inputs(preview or self.preview(), event_id=123, confirmed_on=day, as_of=day)

    def test_original_literal_is_not_legal_confirmation(self):
        value = self.read(); self.assertEqual(value['missing_conditions'][-1][:5], '公示による')
        self.assertTrue(value['originals'][0]['literal_verified'])
        self.assertFalse(value['effective_legal_deadline_verified'])
        self.assertIsNone(value['effective_legal_deadline'])
        self.assertNotIn('effective_score', value)
        preview = self.preview()
        self.assertEqual(len(preview['statements']), 4)
        self.assertIn('公示', preview['statements'][-1]['label'])
        self.assertEqual(preview['sources']['timezone'], 'Asia/Tokyo')
        self.assertTrue(preview['display_sources'])

    def test_actual_core_reaches_high_60_on_due_date_and_after_never_operation_decision(self):
        from vehicle_priority_assessment import Candidate, assess_priority
        for delta in (0, -1):
            expiry = (self.day+timedelta(days=delta)).isoformat()
            raw = original_pdf(text_for(expiry))
            self.document.source_file = raw; self.document.source_sha256 = hashlib.sha256(raw).hexdigest()
            extraction = json.loads(self.document.preview_json)
            extraction['certificate_extraction']['vehicle']['inspection_expiry'] = expiry
            self.document.preview_json = json.dumps(extraction); self.vehicle.inspection_expiry = expiry
            self.db.session.commit()
            inputs = self.inputs()
            candidate = Candidate('synthetic', inputs['scope'], inputs['event_id'], timings=inputs['timings'])
            result = assess_priority(candidate, inputs['evidence'], inputs['references'], as_of=self.day)
            self.assertEqual((result['label'], result['effective_score']), ('高', 60))
            self.assertFalse(inputs['skip_assessment'])
            self.assertNotIn('operation', result)

    def test_future_date_is_not_a_zero_or_safe_assessment(self):
        tomorrow = self.day + timedelta(days=1)
        self.document.status = 'deleted'; self.vehicle.inspection_expiry = tomorrow.isoformat(); self.db.session.commit()
        self.document = self.add_document(tomorrow.isoformat()); self.selection = {'document_id': self.document.id}
        result = self.inputs(); self.assertTrue(result['skip_assessment']); self.assertEqual(result['timings'], ())
        self.assertNotIn('priority', result); self.assertNotIn('effective_score', result)

    def test_unselected_invalid_extended_or_handentered_date_cannot_preview(self):
        for value in ({}, {'document_id': self.document.id, 'effective_expiry': self.day.isoformat()},
                {'document_id': 'not-a-uuid'}, {'document_id': True}):
            with self.assertRaises(ValueError):
                preview_certificate_confirmation(self.vehicle, value, as_of=self.day)
        self.assertIn('延長', certificate_confirmation_options(self.vehicle, as_of=self.day)['missing_conditions'][0])
        self.assertEqual({s['key'] for s in self.preview()['statements']}, {key for key, _ in STATEMENTS})

    def test_master_only_changed_date_or_missing_original_cannot_promote(self):
        self.vehicle.inspection_expiry = (self.day + timedelta(days=1)).isoformat(); self.db.session.commit()
        with self.assertRaises(ValueError): self.preview()
        self.document.status = 'deleted'; self.db.session.commit()
        self.assertEqual(certificate_confirmation_options(self.vehicle, as_of=self.day)['fields'][0]['options'], [])
        with self.assertRaises(ValueError): self.preview()

    def test_old_original_plus_verified_connected_update_selects_current_not_upload_max(self):
        old_date = (self.day-timedelta(days=365)).isoformat()
        old = self.add_document(old_date)
        with self.assertRaises(ValueError): self.preview()
        _, evidence = self.update(old_date, self.day.isoformat(), self.document)
        self.assertEqual(self.preview()['selection'], self.selection)
        with self.assertRaises(ValueError): self.preview({'document_id': old.id})
        evidence.previous_expiry = (self.day-timedelta(days=366)).isoformat(); self.db.session.commit()
        with self.assertRaises(ValueError): self.preview()

    def test_later_update_without_original_or_conflicting_new_expiry_blocks(self):
        _, evidence = self.update((self.day-timedelta(days=365)).isoformat(), self.day.isoformat(), None)
        with self.assertRaises(ValueError): self.preview()
        evidence.document_id = self.document.id; evidence.new_expiry = (self.day+timedelta(days=1)).isoformat()
        self.db.session.commit()
        with self.assertRaises(ValueError): self.preview()

    def test_twelve_month_execution_never_becomes_legal_expiry(self):
        before = self.preview()['fingerprint']
        self.update(None, None, None, kind='periodic_12month')
        self.assertEqual(self.read()['registered_updates'], [])
        self.assertEqual(self.preview()['fingerprint'], before)

    def test_foreign_company_vehicle_deleted_identity_checksum_fail_closed(self):
        other = self.models.Vehicle.query.filter_by(company_code='B').one()
        with self.assertRaises(ValueError): preview_certificate_confirmation(other, self.selection, as_of=self.day)
        for attr, value in [('chassis_number', 'OTHER-12345'), ('model_code', 'OTHER'), ('deleted', True)]:
            original = getattr(self.vehicle, attr); setattr(self.vehicle, attr, value); self.db.session.commit()
            with self.assertRaises(ValueError): self.preview()
            setattr(self.vehicle, attr, original); self.db.session.commit()
        self.document.source_sha256 = 'a'*64; self.db.session.commit()
        with self.assertRaises(ValueError): self.preview()

    def test_compacted_company_scoped_original_and_download_are_supported(self):
        original = self.document.source_file
        self.db.session.add(self.models.VehicleDocumentSource(company_code='A', sha256=self.document.source_sha256, content=original))
        self.document.source_file = b''; self.db.session.commit()
        self.assertTrue(self.read()['originals'][0]['literal_verified'])
        value = read_certificate_confirmation_original(self.vehicle, self.document.id, as_of=self.day)
        self.assertEqual(value['data'], original); self.assertEqual(value['mimetype'], 'application/pdf')
        other = self.models.Vehicle.query.filter_by(company_code='B').one()
        with self.assertRaises(ValueError): read_certificate_confirmation_original(other, self.document.id, as_of=self.day)

    def test_human_confirmation_does_not_make_fictional_test_pdf_official(self):
        raw = original_pdf(text_for(self.day.isoformat()) + ' 架空テスト用 実証明不可')
        self.document.source_file = raw; self.document.source_sha256 = hashlib.sha256(raw).hexdigest(); self.db.session.commit()
        self.assertFalse(self.read()['originals'][0]['literal_verified'])
        with self.assertRaises(ValueError): self.preview()

    def test_expiry_label_scoped_identity_date_eras_conflicts_and_no_ocr_fallback(self):
        extraction = {'vehicle': {'chassis_number': 'TEST-12345', 'model_code': 'TESTMODEL'}}
        identity = extraction['vehicle']
        for value, expected in [('令和8年11月11日','2026-11-11'), ('平成31年4月30日','2019-04-30'),
                ('令和元年5月1日','2019-05-01'), ('2026/11/11','2026-11-11')]:
            result = verify_certificate_expiry_literal(original_pdf(text_for(value)), extraction, identity)
            self.assertEqual(result['expiry_on'], expected)
        for text in (text_for('平成31年5月1日'), text_for('2026-02-30'), text_for('2026-11-11','OTHER-12345'),
                text_for('2026-11-11') + ' 有効期間満了日 2027-11-11',
                '車台番号 TEST-12345 型式 TESTMODEL 2026-11-11 有効期間の満了する日 走行距離10'):
            self.assertFalse(verify_certificate_expiry_literal(original_pdf(text), extraction, identity)['literal_verified'])
        self.assertFalse(verify_certificate_expiry_literal(b'image', extraction, identity)['literal_verified'])

    def test_changed_source_next_day_and_unchecked_input_fail_closed(self):
        before = self.preview()
        self.vehicle.office = 'Other synthetic office'; self.db.session.commit()
        self.assertNotEqual(self.preview()['fingerprint'], before['fingerprint'])
        next_day = self.day+timedelta(days=1)
        with patch('dkss_app.priority_certificate_sources._today', return_value=next_day):
            self.assertNotEqual(self.preview(as_of=next_day)['fingerprint'], before['fingerprint'])
            with self.assertRaises(ValueError):
                certificate_confirmation_inputs(before, event_id=123, confirmed_on=self.day, as_of=next_day)
        altered = deepcopy(before); altered['statements'] = []
        with self.assertRaises(ValueError): self.inputs(altered)

    def test_read_only_dirty_session_limits_and_stale_identity_map(self):
        statements = []
        def capture(_c, _cursor, sql, _p, _ctx, _many): statements.append(sql)
        event.listen(self.db.engine, 'before_cursor_execute', capture)
        try: self.preview()
        finally: event.remove(self.db.engine, 'before_cursor_execute', capture)
        self.assertTrue(all(sql.lstrip().upper().startswith('SELECT') for sql in statements))
        self.vehicle.office = 'UNSAVED'
        with patch.object(self.db.session(), 'flush', side_effect=AssertionError('flush forbidden')):
            self.assertEqual(self.read()['originals'], [])
        self.db.session.rollback()
        for name in ('MAX_DOCUMENT_INDEX', 'MAX_DOCUMENTS', 'MAX_ORIGINAL_BYTES', 'MAX_TOTAL_BYTES'):
            with patch('dkss_app.priority_certificate_sources.' + name, 0):
                with self.assertRaises(ValueError): self.preview()
        with self.db.engine.begin() as conn:
            conn.execute(self.models.Vehicle.__table__.update().where(self.models.Vehicle.id == self.vehicle.id).values(model_code='CHANGED'))
        with self.assertRaises(ValueError): self.preview()

    def test_ambiguous_legacy_execution_or_unlinked_vehicle_inspection_cannot_be_ignored(self):
        execution, _ = self.update(None, None, None, kind='12month')
        with self.assertRaises(ValueError): self.preview()
        self.db.session.delete(execution); self.db.session.commit()
        record = self.models.VehiclePeriodicInspectionRecord(company_code='A', vehicle_record_id=self.vehicle.id,
            inspection_type='vehicle_inspection', inspection_date=(self.day-timedelta(days=2)).isoformat(),
            source_draft_id=self.document.id, source_record_index=0, created_by_username='admin')
        self.db.session.add(record); self.db.session.commit()
        with self.assertRaises(ValueError): self.preview()

    def post_preview(self):
        response = self.request('POST', f'/vehicle/karte/{self.vehicle.id}/priority-confirmations/preview',
            json={'kind':'legal_deadline', 'selection': self.selection})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.json

    def confirm_http(self):
        value = self.post_preview()
        response = self.request('POST', f'/vehicle/karte/{self.vehicle.id}/priority-confirmations',
            json={'token':value['token'], 'statements':[row['key'] for row in value['preview']['statements']]})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.json['event_id'], value

    def test_normal_http_optional_preview_confirm_core_original_cancel_without_master_mutation(self):
        from dkss_app.priority_confirmations import active_priority_confirmations, confirmation_statuses
        from vehicle_priority_assessment import Candidate, assess_priority
        before = (self.vehicle.inspection_expiry, self.document.preview_json, self.document.result_json)
        url = f'/vehicle/karte/{self.vehicle.id}/priority-confirmations'
        response = self.request('GET', url, query_string={'kind':'legal_deadline'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['history'], [])
        self.assertEqual(len(response.json['form']['fields'][0]['options']), 1)
        self.assertEqual(active_priority_confirmations(self.vehicle), [])
        event_id, posted = self.confirm_http()
        active = active_priority_confirmations(self.vehicle)
        self.assertEqual(len(active), 1)
        entry = active[0]; self.assertEqual(entry['event_id'], event_id)
        mapped = certificate_confirmation_inputs(entry['preview'], event_id=event_id,
            confirmed_on=date.fromisoformat(entry['confirmed_at'][:10]), as_of=self.day)
        result = assess_priority(Candidate('normal', mapped['scope'], mapped['event_id'], timings=mapped['timings']),
            mapped['evidence'], mapped['references'], as_of=self.day)
        self.assertEqual(result['effective_score'], 60)
        source = self.request('GET', posted['preview']['source_links']['certificate:'+self.document.id]['url'])
        self.assertEqual(source.status_code, 200); self.assertEqual(source.data, self.document.source_file)
        self.assertIn('no-store', source.headers['Cache-Control'])
        history = self.request('GET', url, query_string={'kind':'legal_deadline'}).json['history']
        cancel = self.request('POST', url, json={'token':history[0]['cancel_token']})
        self.assertEqual(cancel.status_code, 200); self.assertEqual(active_priority_confirmations(self.vehicle), [])
        self.assertEqual(confirmation_statuses(self.vehicle)[0]['status'], 'withdrawn')
        self.assertEqual(self.models.ChecklistEvent.query.filter_by(result_type='vehicle_priority').count(), 2)
        self.assertEqual(before, (self.vehicle.inspection_expiry, self.document.preview_json, self.document.result_json))
        self.assertEqual(self.models.VehicleChecklistResult.query.count(), 0)
        self.assertEqual(self.models.Notification.query.count(), 0)

    def test_http_incomplete_statements_source_changes_replay_and_actor_changes_rejected(self):
        url = f'/vehicle/karte/{self.vehicle.id}/priority-confirmations'
        value = self.post_preview(); keys = [s['key'] for s in value['preview']['statements']]
        for statements in ([], keys[:-1], [keys[0]]*len(keys)):
            response = self.request('POST', url, json={'token':value['token'], 'statements':statements})
            self.assertEqual(response.status_code, 409)
        self.vehicle.office = 'Changed'; self.db.session.commit()
        self.assertEqual(self.request('POST', url, json={'token':value['token'], 'statements':keys}).status_code, 409)
        _, value = self.confirm_http()
        self.assertEqual(self.request('POST', url, json={'token':value['token'], 'statements':keys}).status_code, 409)
        value = self.post_preview()
        actor = self.models.User.query.filter_by(company_code='A', username='admin').one()
        password_changed_at = actor.password_changed_at
        self.db.session.delete(actor); self.db.session.flush()
        replacement = self.models.User(company_code='A', username='admin', role='admin', password='unused',
            last_name='Different synthetic actor', first_name='', password_changed_at=password_changed_at)
        self.db.session.add(replacement); self.db.session.commit(); self.login('admin')
        self.assertEqual(self.request('POST', url, json={'token':value['token'], 'statements':keys}).status_code, 409)
        self.assertEqual(self.models.ChecklistEvent.query.filter_by(result_type='vehicle_priority').count(), 1)

    def test_http_today_confirmation_becomes_held_tomorrow_or_when_evidence_changes(self):
        from dkss_app.priority_confirmations import confirmation_statuses
        self.confirm_http()
        self.assertEqual(confirmation_statuses(self.vehicle)[0]['status'], 'active')
        next_day = self.day+timedelta(days=1)
        with patch('dkss_app.priority_certificate_sources._today', return_value=next_day):
            self.assertEqual(confirmation_statuses(self.vehicle, as_of=next_day)[0]['status'], 'held')
        self.document.completed_at = datetime(2026, 1, 2); self.db.session.commit()
        self.assertEqual(confirmation_statuses(self.vehicle)[0]['status'], 'held')

    def test_http_cross_company_nonprivileged_source_and_confirmation_boundaries(self):
        self.login('admin', 'B')
        prefix = f'/vehicle/karte/{self.vehicle.id}/priority-confirmations'
        self.assertEqual(self.request('GET', prefix, query_string={'kind':'legal_deadline'}).status_code, 404)
        self.assertEqual(self.request('GET', prefix+'/certificates/'+self.document.id+'/source').status_code, 404)
        self.login('checker')
        self.assertEqual(self.request('GET', prefix, query_string={'kind':'legal_deadline'}).json['can_confirm'], False)
        response = self.request('POST', prefix+'/preview', json={'kind':'legal_deadline','selection':self.selection})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.models.ChecklistEvent.query.filter_by(result_type='vehicle_priority').count(), 0)

    def test_http_correction_preserves_old_audit_and_only_new_confirmation_is_active(self):
        from dkss_app.priority_confirmations import confirmation_statuses, active_priority_confirmations
        old_id, _ = self.confirm_http()
        prefix = f'/vehicle/karte/{self.vehicle.id}/priority-confirmations'
        value = self.request('POST', prefix+'/preview', json={'kind':'legal_deadline',
            'selection':self.selection, 'replace_event_id':old_id})
        self.assertEqual(value.status_code, 200)
        response = self.request('POST', prefix, json={'token':value.json['token'],
            'statements':[s['key'] for s in value.json['preview']['statements']]})
        self.assertEqual(response.status_code, 200)
        statuses = confirmation_statuses(self.vehicle)
        self.assertEqual([e['status'] for e in statuses], ['withdrawn', 'active'])
        self.assertEqual(len(active_priority_confirmations(self.vehicle)), 1)
        self.assertNotEqual(response.json['event_id'], old_id)
        self.assertEqual(self.models.ChecklistEvent.query.filter_by(result_type='vehicle_priority').count(), 3)

    def test_update_chain_same_day_conflict_and_future_execution_are_not_latest_wins(self):
        self.update((self.day-timedelta(days=365)).isoformat(), self.day.isoformat(), self.document)
        # Legacy storage can coexist with the explicit kind, but it cannot be
        # treated as an unrelated periodic inspection merely to ignore a conflict.
        self.update(None, None, None, kind='12month')
        with self.assertRaises(ValueError): self.preview()
        unknown = self.Execution.query.filter_by(kind='12month').one()
        self.db.session.delete(unknown); self.db.session.commit()
        current = self.Execution.query.filter_by(kind='vehicle_inspection').one()
        current.performed_date = (self.day+timedelta(days=1)).isoformat(); self.db.session.commit()
        with self.assertRaises(ValueError): self.preview()

    def test_fresh_snapshot_holds_when_current_source_identity_is_deleted_or_actor_locked(self):
        value = self.post_preview()
        actor = self.models.User.query.filter_by(company_code='A', username='admin').one()
        actor.login_locked = True; self.db.session.commit()
        response = self.request('POST', f'/vehicle/karte/{self.vehicle.id}/priority-confirmations',
            json={'token':value['token'], 'statements':[s['key'] for s in value['preview']['statements']]})
        self.assertIn(response.status_code, (302, 401))
        self.assertEqual(self.models.ChecklistEvent.query.filter_by(result_type='vehicle_priority').count(), 0)

    def test_unknown_electronic_record_missing_literal_date_is_not_extracted_date_evidence(self):
        raw = original_pdf('自動車検査証 車台番号 TEST-12345 型式 TESTMODEL 電子記録を参照')
        self.document.source_file = raw; self.document.source_sha256 = hashlib.sha256(raw).hexdigest(); self.db.session.commit()
        self.assertFalse(self.read()['originals'][0]['literal_verified'])
        with self.assertRaises(ValueError): self.preview()

    def test_same_day_resolved_legacy_and_explicit_update_conflict_is_not_tiebroken(self):
        from dkss_app.vehicle_inspection_plans_models import get_models
        Plan, _, _, _ = get_models(self.db)
        self.update((self.day-timedelta(days=365)).isoformat(), self.day.isoformat(), self.document)
        other, _ = self.update((self.day-timedelta(days=365)).isoformat(), self.day.isoformat(), self.document, kind='12month')
        plan = Plan(company_code='A', vehicle_record_id=self.vehicle.id, kind='vehicle_inspection',
            period_key=self.day.isoformat()[:7], planned_month=self.day.isoformat()[:7])
        self.db.session.add(plan); self.db.session.flush(); other.plan_id = plan.id; self.db.session.commit()
        with self.assertRaisesRegex(ValueError, '同じ実施日'): self.preview()

    def test_foreign_compacted_blob_cannot_fill_missing_same_company_original(self):
        raw = self.document.source_file
        self.db.session.add(self.models.VehicleDocumentSource(company_code='B', sha256=self.document.source_sha256, content=raw))
        self.document.source_file = b''; self.db.session.commit()
        self.assertEqual(self.read()['originals'], [])
        with self.assertRaises(ValueError): self.preview()

    def test_original_extraction_date_conflict_and_execution_limit_hold_all_sources(self):
        preview = json.loads(self.document.preview_json)
        preview['certificate_extraction']['vehicle']['inspection_expiry'] = (self.day+timedelta(days=1)).isoformat()
        original = self.document.preview_json; self.document.preview_json = json.dumps(preview); self.db.session.commit()
        with self.assertRaises(ValueError): self.preview()
        self.document.preview_json = original; self.db.session.commit()
        self.update((self.day-timedelta(days=365)).isoformat(), self.day.isoformat(), self.document)
        with patch('dkss_app.priority_certificate_sources.MAX_EXECUTIONS', 0):
            with self.assertRaises(ValueError): self.preview()

    def generated(self):
        from dkss_app.priority_confirmed_projection import attach_confirmed_priority_inputs
        from dkss_app.analysis_feedback import vehicle_analysis_proposal_ids
        payload, sources = {'records': []}, {}
        offers = attach_confirmed_priority_inputs(self.vehicle, payload, sources, as_of=self.day)
        self.assertEqual(len(offers), 1)
        offer = offers[0]
        proposal = {'priority':'高', 'category':'整備・点検', 'target':offer['display_target'],
            'title':'合成車検記録の対応確認', 'current_state':'人が確認した原本', 'action':'責任者が対応を確認',
            'source_ids':offer['source_ids'], 'priority_input_ref':offer['ref']}
        proposal['proposal_id'], proposal['proposal_revision'] = vehicle_analysis_proposal_ids(proposal)
        return {'recommendations':[proposal]}, sources

    def test_generation_bound_common_projection_due_today_next_day_and_cancel(self):
        from dkss_app.priority_confirmed_projection import project_registered_confirmed_priorities
        from dkss_app.priority_projection import project_registered_priorities
        event_id, _ = self.confirm_http(); analysis, sources = self.generated()
        result = project_registered_confirmed_priorities(analysis, self.vehicle, sources, as_of=self.day)
        self.assertEqual(result[0][0]['effective_score'], 60)
        self.assertEqual(result[0][0]['confirmation_details']['event_id'], event_id)
        raw_before = deepcopy(analysis)
        next_day = self.day+timedelta(days=1)
        with patch('dkss_app.priority_certificate_sources._today', return_value=next_day):
            result = project_registered_priorities(analysis, self.vehicle, sources, as_of=next_day)
        self.assertEqual(result['recommendations'][0]['priority'], '高')
        self.assertIsNone(result['recommendations'][0]['priority_assessment']['effective_score'])
        self.assertEqual(analysis, raw_before)
        url = f'/vehicle/karte/{self.vehicle.id}/priority-confirmations'
        history = self.request('GET', url, query_string={'kind':'legal_deadline'}).json['history']
        self.assertEqual(self.request('POST', url, json={'token':history[0]['cancel_token']}).status_code, 200)
        result = project_registered_priorities(analysis, self.vehicle, sources, as_of=self.day)
        self.assertEqual(result['recommendations'], [])
        self.assertEqual(analysis, raw_before)

    def test_no_backfill_and_normal_analysis_result_get_uses_saved_generation_proof(self):
        from dkss_app.priority_confirmed_projection import project_registered_confirmed_priorities
        self.confirm_http(); analysis, sources = self.generated()
        without = deepcopy(sources)
        for metadata in without.values(): metadata.pop('priority_confirmation_proof', None)
        self.assertIsNone(project_registered_confirmed_priorities(analysis, self.vehicle, without, as_of=self.day)[0][0])
        old = deepcopy(analysis); old['recommendations'][0].pop('priority_input_ref')
        self.assertEqual(project_registered_confirmed_priorities(old, self.vehicle, sources, as_of=self.day), {})
        bundle = {'analysis':analysis, 'sources':sources, 'fingerprints':{}}
        state = self.models.VehicleKarteAnalysis(company_code='A', vehicle_record_id=self.vehicle.id,
            status='completed', result_json=json.dumps(bundle, ensure_ascii=False))
        self.db.session.add(state); self.db.session.commit(); original = state.result_json
        with patch('dkss_app.analysis.get_vehicle_analysis_read_projection', return_value=(
                {'fingerprints':{}, 'input_summary':{}, 'comparison':None}, True)):
            response = self.request('GET', f'/vehicle/karte/{self.vehicle.id}/analysis/result')
        self.assertEqual(response.status_code, 200)
        item = response.json['analysis']['recommendations'][0]
        self.assertEqual((item['priority'], item['priority_assessment']['effective_score']), ('高', 60))
        self.assertEqual(state.result_json, original)
        self.assertEqual(self.models.VehicleChecklistResult.query.count(), 0)
