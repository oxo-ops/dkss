"""Inspection planning integration tests against isolated SQLite and the real routes."""
import json
import unittest
from datetime import date
from test_workflow_regressions import WorkflowRegressionTests as _Workflow


class InspectionPlanTests(unittest.TestCase):
    setUpClass = classmethod(_Workflow.setUpClass.__func__)
    tearDownClass = classmethod(_Workflow.tearDownClass.__func__)
    setUp = _Workflow.setUp
    tearDown = _Workflow.tearDown
    upload_inspection = _Workflow.upload_inspection
    inspection_form = _Workflow.inspection_form

    def change(self, vehicle=None, mon='2026-12', kind='3month', **extra):
        return dict(vehicle_record_id=(vehicle or self.vehicle).id, id=None, version=0,
                    kind=kind, planned_month=mon, period_key=mon,
                    reservation_date=None, factory='', note='', status='planned', **extra)

    def save(self, changes, expected=200):
        preview = self.client.post('/api/vehicle/inspection-plans/preview', json={'changes': changes})
        self.assertEqual(preview.status_code, 200, preview.get_data(as_text=True))
        payload = dict(changes=changes, token=preview.json['token'])
        result = self.client.post('/api/vehicle/inspection-plans/save', json=payload)
        self.assertEqual(result.status_code, expected, result.get_data(as_text=True))
        return payload

    def import_record(self, performed='2026-09-12', mon='2026-12'):
        from test_inspection_document_ai import extraction, pdf_bytes
        source = pdf_bytes(self.m.VehicleDocumentImportDraft.query.count() + 1)
        data = extraction(source); data['records'][0].update(inspection_date=performed, next_inspection_month=mon, next_inspection_date=None)
        self.upload_inspection(data=data, source=source)
        draft = self.m.VehicleDocumentImportDraft.query.filter_by(status='preview').order_by(self.m.VehicleDocumentImportDraft.created_at.desc()).first()
        form = self.inspection_form(draft)
        form['next_inspection_month_' + draft.id + '_0'] = mon or ''
        form['next_inspection_date_' + draft.id + '_0'] = ''
        result = self.client.post(f'/vehicle/data-import/{draft.batch_id}/confirm', data=form)
        self.assertEqual(result.status_code, 302, result.get_data(as_text=True))
        return self.m.VehiclePeriodicInspectionRecord.query.order_by(self.m.VehiclePeriodicInspectionRecord.id.desc()).first()

    def test_month_only_import_updates_header_and_preserves_original(self):
        record = self.import_record()
        plan = self.m.VehicleInspectionPlan.query.one()
        self.assertEqual((plan.planned_month, plan.reservation_date, plan.source), ('2026-12', None, 'document'))
        self.assertEqual(plan.source_record_id, record.id)
        self.assertEqual(json.loads(record.details_json)['next_inspection_month'], '2026-12')
        page = self.client.get(f'/vehicle/karte/{self.vehicle.id}/inspections')
        self.assertEqual(page.status_code, 200)
        self.assertIn('2026年12月予定', page.get_data(as_text=True))
        self.assertNotIn('2026-12-12', page.get_data(as_text=True))
        self.assertEqual(self.m.VehicleMaintenanceRecord.query.count(), 0)
        self.assertEqual(self.m.VehiclePartReplacement.query.count(), 0)

    def test_import_completes_matching_plan_and_creates_next_once(self):
        self.save([self.change(mon='2026-09')])
        record = self.import_record()
        rows = self.m.VehicleInspectionPlan.query.order_by(self.m.VehicleInspectionPlan.id).all()
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[0].status, rows[0].completed_record_id), ('completed', record.id))
        self.m.inspection_plans.sync_record(record); self.m.db.session.commit()
        self.assertEqual(self.m.VehicleInspectionPlan.query.count(), 2)
        self.assertEqual(self.m.VehicleInspectionPlanEvent.query.filter_by(action='completed').count(), 1)

    def test_import_does_not_complete_different_booking_day(self):
        change=self.change(mon='2026-09'); change['reservation_date']='2026-09-20'
        self.save([change]); self.import_record()
        self.assertEqual(self.m.VehicleInspectionPlan.query.filter_by(planned_month='2026-09').one().status, 'planned')

    def test_explicit_date_survives_import_as_date(self):
        self.upload_inspection(); draft=self.m.VehicleDocumentImportDraft.query.one()
        form=self.inspection_form(draft); form['next_inspection_date_'+draft.id+'_0']='2027-01-21'
        self.client.post(f'/vehicle/data-import/{draft.batch_id}/confirm', data=form)
        plan=self.m.VehicleInspectionPlan.query.one()
        self.assertIsNone(plan.reservation_date)
        self.assertEqual(plan.document_date, '2027-01-21')

    def test_manual_booking_is_not_overwritten_by_document(self):
        change=self.change(); change.update(reservation_date='2026-12-18', factory='予約工場', note='確定')
        self.save([change]); self.import_record()
        plan=self.m.VehicleInspectionPlan.query.one()
        self.assertEqual((plan.reservation_date, plan.factory, plan.note), ('2026-12-18','予約工場','確定'))

    def test_cancelled_document_plan_does_not_reappear_in_header(self):
        self.import_record(); p=self.m.VehicleInspectionPlan.query.one()
        change=self.change(); change.update(id=p.id, version=p.version, status='cancelled')
        self.save([change])
        self.assertNotIn('3month', self.m.inspection_plans.summary('TEST', self.vehicle.id))

    def test_older_import_never_reintroduces_superseded_next_period(self):
        self.import_record('2026-09-12','2026-12')
        self.import_record('2026-06-12','2026-09')
        self.assertEqual(self.m.VehicleInspectionPlan.query.count(), 1)
        self.assertEqual(self.m.inspection_plans.summary('TEST', self.vehicle.id)['3month']['planned_month'], '2026-12')

    def test_latest_record_without_next_does_not_resurrect_old_fallback(self):
        self.import_record(); self.m.VehicleInspectionPlan.query.delete(); self.m.db.session.commit()
        self.import_record('2026-10-12',None)
        self.assertNotIn('3month',self.m.inspection_plans.summary('TEST', self.vehicle.id))

    def test_company_and_office_scopes_are_isolated(self):
        m=self.m; self.vehicle.office='犬塚'
        same=m.Vehicle(company_code='TEST',chassis_number='SAME',office='犬塚')
        other=m.Vehicle(company_code='TEST',chassis_number='OTHER',office='別営業所')
        foreign=m.Vehicle(company_code='FOREIGN',chassis_number='SECRET',office='犬塚')
        m.db.session.add_all([same,other,foreign]);m.db.session.commit()
        resp=self.client.get(f'/api/vehicle/inspection-plans?scope=office&vehicle_id={self.vehicle.id}&year=2026')
        self.assertEqual({v['id'] for v in resp.json['vehicles']},{self.vehicle.id,same.id})
        self.assertEqual(self.client.get(f'/api/vehicle/inspection-plans?detail=1&vehicle_id={foreign.id}').status_code,404)
        self.assertEqual(self.client.post('/api/vehicle/inspection-plans/preview',json={'changes':[self.change(vehicle=foreign)]}).status_code,404)
        self.assertEqual(len(self.client.get('/api/vehicle/inspection-plans?scope=company').json['vehicles']),3)

    def test_preview_and_double_save_do_not_write_duplicates(self):
        changes=[self.change()]
        self.assertEqual(self.client.post('/api/vehicle/inspection-plans/preview',json={'changes':changes}).status_code,200)
        self.assertEqual(self.m.VehicleInspectionPlan.query.count(),0)
        payload=self.save(changes)
        self.assertEqual(self.client.post('/api/vehicle/inspection-plans/save',json=payload).status_code,409)
        self.assertEqual(self.m.VehicleInspectionPlan.query.count(),1)

    def test_conflicting_batch_is_atomic_and_preserves_newer_change(self):
        self.save([self.change()]); p=self.m.VehicleInspectionPlan.query.one()
        update=self.change();update.update(id=p.id,version=p.version,factory='変更後')
        changes=[update,self.change(mon='2027-03')]
        preview=self.client.post('/api/vehicle/inspection-plans/preview',json={'changes':changes}).json
        p.note='他の担当者の更新';p.version+=1;self.m.db.session.commit()
        response=self.client.post('/api/vehicle/inspection-plans/save',json=dict(changes=changes,token=preview['token']))
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.m.VehicleInspectionPlan.query.count(),1)
        self.m.db.session.refresh(p);self.assertEqual(p.factory,'')
        self.assertEqual(p.note,'他の担当者の更新')

    def test_new_period_key_cannot_be_forged_and_moved_month_cannot_be_duplicated(self):
        change=self.change();change['period_key']='2027-03'
        self.assertEqual(self.client.post('/api/vehicle/inspection-plans/preview',json={'changes':[change]}).status_code,400)
        self.save([self.change()]);p=self.m.VehicleInspectionPlan.query.one()
        move=self.change(mon='2027-01');move.update(id=p.id,version=p.version,period_key=p.period_key)
        self.save([move])
        self.assertEqual(self.client.post('/api/vehicle/inspection-plans/preview',json={'changes':[self.change(mon='2027-01')]}).status_code,409)
        self.assertEqual(self.m.VehicleInspectionPlan.query.count(),1)

    def test_reservation_month_and_token_tampering_rejected(self):
        changes=[self.change()];changes[0]['reservation_date']='2027-01-01'
        self.assertEqual(self.client.post('/api/vehicle/inspection-plans/preview',json={'changes':changes}).status_code,400)
        changes=[self.change()]
        self.assertEqual(self.client.post('/api/vehicle/inspection-plans/save',json=dict(changes=changes,token='fake')).status_code,409)
        self.assertEqual(self.m.VehicleInspectionPlan.query.count(),0)

    def test_read_only_role_cannot_write(self):
        self.m.User.query.filter_by(username='admin').one().role='user';self.m.db.session.commit()
        with self.client.session_transaction() as s:s['role']='user'
        self.assertEqual(self.client.post('/api/vehicle/inspection-plans/preview',json={'changes':[self.change()]}).status_code,403)
        self.assertEqual(self.client.post('/api/vehicle/inspection-plans/save',json={}).status_code,403)

    def test_annual_candidates_are_months_and_keep_calculated_provenance(self):
        self.import_record()
        data=self.client.get('/api/vehicle/inspection-plans?scope=company&year=2026').json
        candidates=[p for p in data['plans'] if p['kind']=='3month' and p['status']=='candidate']
        self.assertEqual([p['planned_month'] for p in candidates],['2027-03'])
        self.assertIsNone(candidates[0]['reservation_date'])
        candidates[0]['status']='planned';self.save(candidates)
        self.assertEqual(self.m.VehicleInspectionPlan.query.filter_by(planned_month='2027-03').one().source,'calculated')

    def test_expired_certificate_does_not_invent_future_expiry_or_twelve_month_record(self):
        self.vehicle.inspection_expiry='2024-06-01';self.m.db.session.commit()
        data=self.client.get('/api/vehicle/inspection-plans?scope=company&year=2026').json
        self.assertFalse(any(p['kind']=='12month' for p in data['plans']))
        self.assertFalse(any(p['kind']=='12month' for p in data['plans']))
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(),0)

    def test_dashboard_month_only_has_no_fake_days_remaining(self):
        self.vehicle.office='犬塚';self.m.db.session.commit();self.import_record()
        with self.m.app.test_request_context('/'):
            result=self.m.get_dashboard_periodic_schedule('TEST','犬塚',date(2026,10,22))
        self.assertEqual(result['known_count'],1)
        self.assertEqual(result['scheduled'][0]['date'],'2026-12（月予定）')
        self.assertIsNone(result['scheduled'][0]['remaining_days'])

    def test_plan_events_are_visible_in_vehicle_history(self):
        self.save([self.change()])
        page=self.client.get(f'/vehicle/karte/{self.vehicle.id}/history')
        self.assertEqual(page.status_code,200)
        self.assertIn('点検予定',page.get_data(as_text=True))
        self.assertIn('予定月 2026-12',page.get_data(as_text=True))

    def complete(self, performed='2026-09-12', plan=None, **extra):
        payload=dict(vehicle_record_id=self.vehicle.id,kind='3month',performed_date=performed,
                     plan_id=plan.id if plan else None,version=plan.version if plan else 0,factory='先行登録工場',note='',next_month='',**extra)
        preview=self.client.post('/api/vehicle/inspection-plans/execution/preview',json=payload)
        self.assertEqual(preview.status_code,200,preview.get_data(as_text=True))
        self.assertEqual(self.m.inspection_plans.Execution.query.count(),0)
        payload['token']=preview.json['token']
        result=self.client.post('/api/vehicle/inspection-plans/execution/save',json=payload)
        self.assertEqual(result.status_code,200,result.get_data(as_text=True))
        return payload

    def test_manual_execution_before_document_is_visible_and_updates_next_month(self):
        self.complete()
        m=self.m;e=m.inspection_plans.Execution.query.one()
        self.assertEqual(e.performed_date,'2026-09-12');self.assertIsNone(e.source_record_id)
        self.assertEqual(m.VehiclePeriodicInspectionRecord.query.count(),0)
        p=m.VehicleInspectionPlan.query.one()
        self.assertEqual((p.planned_month,p.reservation_date,p.source),('2026-12',None,'calculated'))
        detail=self.client.get(f'/api/vehicle/inspection-plans?detail=1&vehicle_id={self.vehicle.id}').json
        self.assertEqual(detail['latest']['3month']['performed_date'],'2026-09-12')
        self.assertEqual(detail['latest']['3month']['document_status'],'未受領')
        page=self.client.get(f'/vehicle/karte/{self.vehicle.id}/inspections').get_data(as_text=True)
        self.assertIn(f'id="manual-execution-{e.id}"',page)
        self.assertIn('09/12 実施',page)
        history=self.client.get(f'/vehicle/karte/{self.vehicle.id}/history').get_data(as_text=True)
        self.assertIn('点検実施（書類未受領）',history)
        self.assertEqual(m.VehicleMaintenanceRecord.query.count(),0);self.assertEqual(m.VehiclePartReplacement.query.count(),0)

    def test_manual_execution_completes_plan_and_removes_its_warning(self):
        self.vehicle.office='犬塚';self.m.db.session.commit();self.save([self.change(mon='2026-09')])
        plan=self.m.VehicleInspectionPlan.query.one();self.complete(plan=plan)
        self.m.db.session.refresh(plan);self.assertEqual(plan.status,'completed')
        self.assertIsNone(plan.completed_record_id)
        self.assertEqual(self.m.inspection_plans.Execution.query.one().plan_id,plan.id)
        with self.m.app.test_request_context('/'):
            result=self.m.get_dashboard_periodic_schedule('TEST','犬塚',date(2026,10,22))
        self.assertEqual([r['date'] for r in result['scheduled']],['2026-12（月予定）'])

    def test_later_pdf_attaches_to_manual_execution_without_two_actual_rows(self):
        self.save([self.change(mon='2026-09')]);plan=self.m.VehicleInspectionPlan.query.one();self.complete(plan=plan)
        record=self.import_record()
        self.assertEqual(self.m.inspection_plans.Execution.query.one().source_record_id,record.id)
        self.m.db.session.refresh(plan);self.assertEqual(plan.completed_record_id,record.id)
        data=self.client.get('/api/vehicle/inspection-plans?scope=company&year=2026').json
        actual=[p for p in data['plans'] if p['status']=='completed']
        self.assertEqual(len(actual),1);self.assertEqual(actual[0]['performed_date'],'2026-09-12')
        page=self.client.get(f'/vehicle/karte/{self.vehicle.id}/inspections').get_data(as_text=True)
        self.assertNotIn('id="manual-execution-',page);self.assertIn('id="periodic-record-',page)
        self.assertEqual(self.m.VehicleMaintenanceRecord.query.count(),0)

    def test_existing_ocr_actual_is_in_annual_grid_without_prior_plan(self):
        record=self.import_record()
        data=self.client.get('/api/vehicle/inspection-plans?scope=company&year=2026').json
        actual=[p for p in data['plans'] if p['status']=='completed']
        self.assertEqual(len(actual),1);self.assertEqual(actual[0]['completed_record_id'],record.id)
        self.assertTrue(actual[0]['is_history'])

    def test_manual_repeated_save_does_not_duplicate_execution(self):
        payload=self.complete()
        self.assertEqual(self.client.post('/api/vehicle/inspection-plans/execution/save',json=payload).status_code,409)
        self.assertEqual(self.m.inspection_plans.Execution.query.count(),1)
        self.assertEqual(self.m.VehicleInspectionPlan.query.count(),1)

    def test_later_document_replaces_untouched_computed_next_month(self):
        self.complete();self.import_record(mon='2027-01')
        rows=self.m.VehicleInspectionPlan.query.order_by(self.m.VehicleInspectionPlan.id).all()
        self.assertEqual([(r.planned_month,r.status) for r in rows],[('2026-12','cancelled'),('2027-01','planned')])
        self.assertEqual(rows[1].source,'document')
        self.assertEqual(self.m.inspection_plans.summary('TEST',self.vehicle.id)['3month']['planned_month'],'2027-01')

    def test_later_document_keeps_manually_confirmed_booking(self):
        self.complete();p=self.m.VehicleInspectionPlan.query.one();p.reservation_date='2026-12-18';p.version+=1;self.m.db.session.commit()
        self.import_record(mon='2027-01');self.m.db.session.refresh(p)
        self.assertEqual((p.reservation_date,p.status),('2026-12-18','planned'))

    def test_manual_duplicate_existing_document_and_future_date_are_rejected(self):
        self.import_record()
        for day,expected in [('2026-09-12',409),('2099-01-01',400),('invalid',400)]:
            payload=dict(vehicle_record_id=self.vehicle.id,kind='3month',performed_date=day)
            self.assertEqual(self.client.post('/api/vehicle/inspection-plans/execution/preview',json=payload).status_code,expected)
        self.assertEqual(self.m.inspection_plans.Execution.query.count(),0)

    def test_manual_execution_cannot_cross_company_or_write_as_user(self):
        foreign=self.m.Vehicle(company_code='FOREIGN',chassis_number='FOREIGN')
        self.m.db.session.add(foreign);self.m.db.session.commit()
        payload=dict(vehicle_record_id=foreign.id,kind='3month',performed_date='2026-09-12')
        self.assertEqual(self.client.post('/api/vehicle/inspection-plans/execution/preview',json=payload).status_code,404)
        self.m.User.query.filter_by(username='admin').one().role='user';self.m.db.session.commit()
        for endpoint in ['preview','save']:
            self.assertEqual(self.client.post('/api/vehicle/inspection-plans/execution/'+endpoint,json=payload).status_code,403)

    def test_manual_preview_conflict_keeps_everything_unchanged(self):
        self.save([self.change(mon='2026-09')]);plan=self.m.VehicleInspectionPlan.query.one()
        payload=dict(vehicle_record_id=self.vehicle.id,kind='3month',performed_date='2026-09-12',plan_id=plan.id,version=plan.version)
        preview=self.client.post('/api/vehicle/inspection-plans/execution/preview',json=payload).json
        plan.note='他の担当者の更新';plan.version+=1;self.m.db.session.commit()
        payload['token']=preview['token']
        self.assertEqual(self.client.post('/api/vehicle/inspection-plans/execution/save',json=payload).status_code,409)
        self.assertEqual(self.m.inspection_plans.Execution.query.count(),0)
        self.m.db.session.refresh(plan);self.assertEqual(plan.status,'planned')

    def test_manual_execution_keeps_confirmed_next_booking(self):
        change=self.change();change['reservation_date']='2026-12-18';change['factory']='予約確定工場'
        self.save([change]);self.complete()
        plan=self.m.VehicleInspectionPlan.query.one()
        self.assertEqual((plan.reservation_date,plan.factory),('2026-12-18','予約確定工場'))

    def test_rollback_clears_import_queue(self):
        self.upload_inspection(); draft=self.m.VehicleDocumentImportDraft.query.one()
        record=self.m.VehiclePeriodicInspectionRecord(company_code='TEST',vehicle_record_id=self.vehicle.id,inspection_type='3month',inspection_date='2026-09-12',details_json='{"next_inspection_month":"2026-12"}',source_draft_id=draft.id,source_record_index=10,created_by_username='admin')
        self.m.db.session.add(record);self.m.db.session.flush();self.m.db.session.rollback()
        self.vehicle.office='変更';self.m.db.session.commit()
        self.assertEqual(self.m.VehicleInspectionPlan.query.count(),0)

    def test_default_office_resolved_from_user_not_client_session(self):
        m=self.m;user=m.User.query.filter_by(username='admin').one();user.office='安城';self.vehicle.office='安城'
        m.db.session.add_all([m.Office(company_code='TEST',name='安城'),m.Office(company_code='TEST',name='小山'),m.Vehicle(company_code='TEST',chassis_number='OTHER',office='小山'),m.Vehicle(company_code='FOREIGN',chassis_number='SECRET',office='安城')]);m.db.session.commit()
        data=self.client.get('/api/vehicle/inspection-plans').json
        self.assertEqual(data['office'],'安城');self.assertEqual([v['id'] for v in data['vehicles']],[self.vehicle.id]);self.assertEqual(data['offices'],['安城','小山'])
        self.assertEqual(data['month'],data['today'][:7])
        self.assertEqual(len(self.client.get('/api/vehicle/inspection-plans?scope=office&office=小山').json['vehicles']),1)
        self.assertEqual(self.client.get('/api/vehicle/inspection-plans?scope=office&office=他社だけ').status_code,400)

    def test_missing_office_does_not_expand_to_company(self):
        data=self.client.get('/api/vehicle/inspection-plans').json
        self.assertTrue(data['needs_office']);self.assertEqual(data['vehicles'],[])
        self.assertEqual(len(self.client.get('/api/vehicle/inspection-plans?scope=company').json['vehicles']),1)

    def test_expiry_is_unsaved_candidate_with_exact_expiry(self):
        self.vehicle.inspection_expiry='2026-10-25';self.m.db.session.commit()
        data=self.client.get('/api/vehicle/inspection-plans?scope=company&year=2026').json
        row=next(p for p in data['plans'] if p['kind']=='12month')
        self.assertEqual(row['display_state'],'candidate');self.assertEqual(row['expiry_date'],'2026-10-25')
        self.assertEqual(self.m.VehicleInspectionPlan.query.count(),0)

    def test_four_states_and_elapsed_is_not_called_unperformed(self):
        for mon,reservation in [('2026-01',None),('2098-01',None),('2098-02','2098-02-10')]:
            self.save([dict(self.change(mon=mon),reservation_date=reservation)])
        early=self.client.get('/api/vehicle/inspection-plans?scope=company&year=2025').json
        self.assertEqual(next(p for p in early['plans'] if p['id'])['display_state'],'awaiting')
        future=self.client.get('/api/vehicle/inspection-plans?scope=company&year=2097').json
        self.assertEqual({p['display_state'] for p in future['plans'] if p['id']},{'unreserved','reserved'})

    def certificate_payload(self, **extra):
        return dict(vehicle_record_id=self.vehicle.id,kind='vehicle_inspection',performed_date='2026-09-12',confirmed=True,confirmation='工場に実施日を確認',new_expiry='2027-09-11',**extra)

    def certificate_save(self,payload):
        preview=self.client.post('/api/vehicle/inspection-plans/execution/preview',json=payload)
        self.assertEqual(preview.status_code,200,preview.get_data(as_text=True))
        result=self.client.post('/api/vehicle/inspection-plans/execution/save',json=dict(payload,token=preview.json['token']))
        self.assertEqual(result.status_code,200,result.get_data(as_text=True));return preview.json

    def certificate_document(self,vehicle=None):
        from uuid import uuid4
        import hashlib
        d=self.m.VehicleDocumentImportDraft(id=str(uuid4()),batch_id=str(uuid4()),company_code='TEST',created_by_username='admin',document_type='certificate',source_filename='certificate.pdf',source_file=b'%PDF-test',source_sha256=hashlib.sha256(b'%PDF-test').hexdigest(),status='certificate_linked',result_json=json.dumps({'vehicle_record_id':(vehicle or self.vehicle).id}),preview_json='{}')
        self.m.db.session.add(d);self.m.db.session.commit();return d

    def test_annual_execution_completes_unified_plan_and_keeps_evidence(self):
        self.vehicle.inspection_expiry='2026-09-22';self.m.db.session.commit()
        self.save([self.change(mon='2026-09',kind='vehicle_inspection')])
        plan=self.m.VehicleInspectionPlan.query.filter_by(kind='12month').one()
        self.certificate_save(self.certificate_payload(plan_id=plan.id,version=plan.version))
        self.m.db.session.refresh(plan);self.assertEqual(plan.status,'completed')
        self.assertEqual(self.m.VehicleInspectionPlan.query.filter_by(kind='12month',status='completed').count(),1)
        data=self.client.get('/api/vehicle/inspection-plans?scope=company&year=2026').json
        actual=next(p for p in data['plans'] if p['kind']=='12month' and p['status']=='completed')
        self.assertEqual(actual['expiry_date'],'2026-09-22');self.assertEqual(actual['document_status'],'未受領');self.assertEqual(actual['evidence_note'],'工場に実施日を確認')
        self.assertEqual(self.vehicle.inspection_expiry,'2027-09-11')
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(),0)

    def test_master_expiry_edit_is_not_execution(self):
        self.save([self.change(mon='2026-09',kind='vehicle_inspection')]);self.vehicle.inspection_expiry='2027-09-11';self.m.db.session.commit()
        self.assertEqual(self.m.inspection_plans.Execution.query.count(),0)
        self.assertEqual(self.m.VehicleInspectionPlan.query.one().status,'planned')

    def test_certificate_evidence_requires_actual_day_and_confirmation(self):
        for change in [dict(confirmed=False),dict(confirmation=''),dict(performed_date=''),dict(new_expiry='2026-09-11')]:
            payload=self.certificate_payload();payload.update(change)
            self.assertEqual(self.client.post('/api/vehicle/inspection-plans/execution/preview',json=payload).status_code,400)
        self.assertEqual(self.m.inspection_plans.Execution.query.count(),0)

    def test_certificate_document_attaches_later_without_duplicate_or_other_vehicle(self):
        self.certificate_save(self.certificate_payload());doc=self.certificate_document()
        self.certificate_save(self.certificate_payload(document_id=doc.id))
        self.assertEqual(self.m.inspection_plans.Execution.query.count(),1)
        ev=self.m.inspection_plans.Evidence.query.one();self.assertEqual(ev.document_id,doc.id)
        data=self.client.get('/api/vehicle/inspection-plans?scope=company&year=2026').json
        actual=next(p for p in data['plans'] if p['kind']=='12month' and p['status']=='completed')
        self.assertEqual(actual['document_status'],'登録済み');self.assertEqual(self.client.get(actual['record_url']).status_code,200)
        other=self.m.Vehicle(company_code='TEST',chassis_number='OTHER');self.m.db.session.add(other);self.m.db.session.commit()
        wrong=self.certificate_payload(document_id=doc.id);wrong['vehicle_record_id']=other.id
        self.assertEqual(self.client.post('/api/vehicle/inspection-plans/execution/preview',json=wrong).status_code,400)
        with self.client.session_transaction() as ses:ses['company_code']='FOREIGN'
        self.assertNotEqual(self.client.get(actual['record_url']).status_code,200)

    def test_certificate_unknown_expiry_does_not_invent_next_month(self):
        payload=self.certificate_payload();payload['new_expiry']='';self.certificate_save(payload)
        self.assertIsNone(self.m.inspection_plans.Execution.query.one().next_month)
        self.assertEqual(self.m.VehicleInspectionPlan.query.count(),0)

    def test_completion_crosses_fiscal_year_but_retains_original_plan_month(self):
        self.save([self.change(mon='2025-03')]);plan=self.m.VehicleInspectionPlan.query.one()
        self.complete(performed='2025-04-02',plan=plan)
        for year in [2024,2025]:
            data=self.client.get(f'/api/vehicle/inspection-plans?scope=company&year={year}').json
            rows=[p for p in data['plans'] if p['id']==plan.id]
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['planned_month'],'2025-03');self.assertEqual(rows[0]['performed_date'],'2025-04-02')

    def test_annual_alias_prevents_duplicate_plans(self):
        self.save([self.change(kind='vehicle_inspection')])
        self.assertEqual(self.m.VehicleInspectionPlan.query.one().kind, '12month')
        response = self.client.post('/api/vehicle/inspection-plans/preview',
            json={'changes': [self.change(kind='12month')]})
        self.assertEqual(response.status_code, 409)

    def test_legacy_annual_plan_remains_editable_and_completes_from_annual_record(self):
        plan = self.m.VehicleInspectionPlan(company_code='TEST', vehicle_record_id=self.vehicle.id,
            kind='vehicle_inspection', period_key='2026-09', planned_month='2026-09',
            status='planned', version=1, source='manual', factory='', note='')
        self.m.db.session.add(plan); self.m.db.session.commit()
        change = self.change(mon='2026-09', kind='12month')
        change.update(id=plan.id, version=plan.version, reservation_date='2026-09-12')
        self.save([change])
        record = self.m.VehiclePeriodicInspectionRecord(company_code='TEST',
            vehicle_record_id=self.vehicle.id, inspection_type='12month', inspection_date='2026-09-12',
            details_json='{}', source_draft_id=self.certificate_document().id, source_record_index=0, created_by_username='admin')
        self.m.db.session.add(record); self.m.db.session.commit()
        self.assertEqual(plan.kind, 'vehicle_inspection')
        self.assertEqual(plan.status, 'completed')
        rows = self.client.get('/api/vehicle/inspection-plans?scope=company&year=2026').json['plans']
        self.assertEqual([r['kind'] for r in rows if r['id'] == plan.id], ['12month'])

    def test_ad_hoc_multiple_bookings_in_same_month_and_completion_without_recurrence(self):
        first = dict(self.change(mon='2026-09', kind='ad_hoc'), reservation_date='2026-09-12')
        second = dict(self.change(mon='2026-09', kind='ad_hoc'), reservation_date='2026-09-20')
        self.save([first, second])
        plan = self.m.VehicleInspectionPlan.query.filter_by(reservation_date='2026-09-12').one()
        payload = dict(vehicle_record_id=self.vehicle.id, kind='ad_hoc', performed_date='2026-09-12',
                       plan_id=plan.id, version=plan.version)
        self.certificate_save(payload)
        self.assertEqual(plan.status, 'completed')
        self.assertIsNone(self.m.inspection_plans.Execution.query.one().next_month)
        self.assertEqual(self.m.VehicleInspectionPlan.query.count(), 2)
        data = self.client.get('/api/vehicle/inspection-plans?scope=company&year=2026').json
        self.assertEqual(len([r for r in data['plans'] if r['kind'] == 'ad_hoc']), 2)
        self.assertFalse(any(r['kind'] == 'ad_hoc' for r in data['missing']))
        html = self.client.get(f'/vehicle/karte/{self.vehicle.id}/inspections?inspection_view=ad_hoc').get_data(as_text=True)
        self.assertIn('id="manual-execution-', html)
        self.assertIn('突発点検', html)
        self.assertNotIn('突発点検点検', html)

    def test_ad_hoc_ocr_import_preserves_history_without_creating_next_plan(self):
        from test_inspection_document_ai import extraction, pdf_bytes
        source = pdf_bytes(987)
        data = extraction(source)
        data['records'][0].update(inspection_type='ad_hoc', inspection_type_raw='突発点検',
                                  next_inspection_month='2027-01')
        self.upload_inspection(data=data, source=source)
        draft = self.m.VehicleDocumentImportDraft.query.filter_by(status='preview').one()
        form = self.inspection_form(draft)
        form['inspection_type_' + draft.id + '_0'] = 'ad_hoc'
        response = self.client.post(f'/vehicle/data-import/{draft.batch_id}/confirm', data=form)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.one().inspection_type, 'ad_hoc')
        self.assertEqual(self.m.VehicleInspectionPlan.query.count(), 0)
        detail = self.client.get(f'/api/vehicle/inspection-plans?detail=1&vehicle_id={self.vehicle.id}').json
        self.assertIn('ad_hoc', detail['latest'])
        self.assertNotIn('ad_hoc', detail['plans'])

    def test_expiry_candidate_is_shared_by_header_and_detail_without_saving_a_booking(self):
        self.vehicle.inspection_expiry = '2027-07-10'
        self.m.db.session.commit()
        summary = self.m.inspection_plans.summary('TEST', self.vehicle.id)
        annual = summary['12month']
        self.assertEqual(annual['expiry_date'], '2027-07-10')
        self.assertEqual(annual['status'], 'candidate')
        self.assertIsNone(annual['reservation_date'])
        self.assertEqual(self.m.VehicleInspectionPlan.query.count(), 0)
        detail = self.client.get(f'/api/vehicle/inspection-plans?detail=1&vehicle_id={self.vehicle.id}').json
        self.assertEqual(detail['plans']['12month'], annual)
        self.assertNotIn('12month', detail['latest'])
        html = self.client.get(f'/vehicle/karte/{self.vehicle.id}/inspections').get_data(as_text=True)
        card = html.split('data-periodic-summary="12month"', 1)[1].split('</button>', 1)[0]
        self.assertIn('期限 27/07/10', card)
        self.assertIn('予約未登録', card)
        self.assertNotIn('次回未設定', card)
        self.assertNotIn('12month', self.m.inspection_plans.summary('FOREIGN', self.vehicle.id))

    def test_saved_annual_reservation_takes_precedence_over_expiry_candidate(self):
        self.vehicle.inspection_expiry = '2027-07-10'
        self.m.db.session.commit()
        change = dict(self.change(kind='12month', mon='2027-06'), reservation_date='2027-06-25')
        self.save([change])
        annual = self.m.inspection_plans.summary('TEST', self.vehicle.id)['12month']
        self.assertEqual(annual['reservation_date'], '2027-06-25')
        self.assertEqual(annual['status'], 'planned')


del _Workflow

if __name__=='__main__':unittest.main()
