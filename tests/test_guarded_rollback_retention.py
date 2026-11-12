"""Portable isolated retention checks; no PR377 modules or external transport.

Run through tests/run_guarded_independent.py, with its isolated private provider.
Generated cases come only from the pinned public independent certificate scenario.
"""
import hashlib
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import patch

from test_periodic_followups import PeriodicFollowupTests as _Periodic
from test_vehicle_analysis_service import fingerprints, snapshot_hash
from vehicle_saved_result_guard import ERROR, MESSAGE, requires_newer_version
from vehicle_analysis_repository import VehicleAnalysisJobRepository

from guarded_independent_cases import saved, PRODUCER
NOW = datetime.now(timezone.utc)


class SavedFormatTests(TestCase):
    def test_independent_public_producer_cases_are_detected(self):
        self.assertEqual(PRODUCER, '692298445d7d57c9c611328792ef966d27b4ebe9')
        for case in ('active', 'held'):
            for kind in ('analysis', 'periodic'):
                with self.subTest(case=case, kind=kind):
                    self.assertTrue(requires_newer_version(saved(case, kind), periodic=kind=='periodic'))

    def test_ordinary_legacy_envelopes_remain_supported(self):
        for raw in [None, '', '{}', '{"analysis":{"overview":"prior","recommendations":[]}}',
                    json.dumps({'analysis': {'recommendations': [{'priority': '高', 'target': 'brake'}]},
                                'fingerprints': fingerprints()})]:
            self.assertFalse(requires_newer_version(raw), raw)
        self.assertFalse(requires_newer_version(json.dumps({'overview':'prior','recommendations':[],
            'output_contract':'vehicle-preventive-v4','risk_contract':'vehicle-risk-v4',
            'risk_text_contract':'condition-effect-v2','model':'synthetic-model'}), periodic=True))

    def test_new_fields_at_any_depth_are_protected_even_empty(self):
        for key in ['priority_source_proof', 'priority_candidate_carryover', 'priority_input_ref',
                    'priority_confirmation_refs', 'priority_candidate_origin',
                    'priority_historical_confirmations', 'priority_provenance', 'priority_assessment']:
            with self.subTest(key=key):
                for value in [None, {}, [], False, '']:
                    self.assertTrue(requires_newer_version(json.dumps({'analysis': {'recommendations': [{key: value}]}})))
        self.assertTrue(requires_newer_version('{"recommendations":[],"priority_source_proof":{}}', periodic=True))

    def test_corrupt_unknown_and_future_envelopes_are_retained(self):
        for raw in ['{', 'null', '[]', 'false', '{"future_schema":2}',
                    '{"analysis":{"priority_candidate_carryover":{}},"analysis":{}}',
                    '{"sources":{"record":{"snapshot":{"value":NaN}}}}',
                    '{"analysis":[]}', '{"analysis":{"recommendations":[null]}}',
                    '{"fingerprints":{"policy_version":13}}',
                    '{"fingerprints":{"policy_version":"12"}}']:
            with self.subTest(raw=raw):
                self.assertTrue(requires_newer_version(raw))

    def test_malformed_known_nested_fields_are_retained(self):
        samples = [
            {'analysis': {'recommendations': []}, 'sources': ['invalid']},
            {'analysis': {}, 'sources': {'record': 'not-object'}},
            {'analysis': {}, 'sources': {'record': {'url': 65}}},
            {'analysis': {}, 'sources': {'record': {'snapshot': []}}},
            {'analysis': {}, 'sources': {'record': {'unknown_proof': {}}}},
            {'analysis': {'unknown_semantics': True}},
            {'analysis': {'recommendations': [{'unknown_semantics': True}]}},
            {'analysis': {'recommendations': [{'source_ids': 'not-a-list', 'priority': 65}]}},
            {'analysis': {'recommendations': [{'confirmation_steps': [None]}]}},
            {'analysis': {'recommendations': [{'risk_evidence': [{'quote': 'missing id'}]}]}},
            {'analysis': {'recommendations': [{'risk_evidence': 'not-a-list'}]}},
            {'analysis': {'output_contract': 'future-v99'}},
            {'analysis': {'overview': []}}, {'analysis': None},
            {'coverage': []}, {'comparison': []}, {'generated_at': 0},
            {'fingerprints': {'important_hash': []}},
            {'fingerprints': {'has_important_history': 1}},
        ]
        for value in samples:
            with self.subTest(value=value):
                self.assertTrue(requires_newer_version(json.dumps(value)))
        self.assertTrue(requires_newer_version('{"recommendations":[{"source_ids":4}]}', periodic=True))



class RetentionDatabaseTests(TestCase):
    setUpClass = classmethod(_Periodic.setUpClass.__func__)
    tearDownClass = classmethod(_Periodic.tearDownClass.__func__)
    setUp = _Periodic.setUp
    tearDown = _Periodic.tearDown
    upload_inspection = _Periodic.upload_inspection
    inspection_form = _Periodic.inspection_form
    import_record = _Periodic.import_record
    input = _Periodic.input
    cached = _Periodic.cached

    def analysis(self, raw=None, **fields):
        row = self.m.VehicleKarteAnalysis(company_code='TEST', vehicle_record_id=self.vehicle.id,
            status='pending', input_hash=snapshot_hash(fingerprints()), next_analysis_at=NOW-timedelta(days=1),
            result_json=raw if raw is not None else saved(), lease_token='token', lease_expires_at=NOW-timedelta(days=1))
        for key, value in fields.items():setattr(row, key, value)
        self.m.db.session.add(row);self.m.db.session.commit()
        return row

    def repo(self):
        return VehicleAnalysisJobRepository(db=self.m.db, state_model=self.m.VehicleKarteAnalysis, vehicle_model=self.m.Vehicle)

    def snapshot(self, row):
        self.m.db.session.expire_all()
        return {column.key: getattr(row, column.key) for column in row.__table__.columns}

    def tables(self):
        db=self.m.db
        return {table.name: sorted([repr(tuple(row)) for row in db.session.execute(table.select()).all()])
                for table in db.metadata.sorted_tables}

    def periodic(self, case='held', status='completed'):
        row=self.cached(status=status);row.result_json=saved(case,'periodic');self.m.db.session.commit();return row

    def test_normal_queue_and_job_hold_entire_protected_row_without_paid_work(self):
        for case in ['active','held']:
            with self.subTest(case=case):
                state=self.analysis(saved(case));before=self.snapshot(state)
                with patch.object(self.m,'analyze_vehicle_karte') as ai:
                    queued=self.m.queue_vehicle_karte_analysis(self.vehicle,{'_fingerprints':fingerprints(important='changed')})
                    self.m.db.session.commit()
                    self.assertEqual(queued.id,state.id)
                    self.assertFalse(self.m.run_vehicle_karte_analysis_job(state.id))
                    ai.assert_not_called()
                self.assertEqual(before,self.snapshot(state))
                self.m.db.session.delete(state);self.m.db.session.commit()

    def test_analysis_claim_finish_fail_skip_renew_refuse_latest_protected_row(self):
        state=self.analysis('{}');repo=self.repo()
        # Populate identity map with legacy, then replace it without synchronizing it.
        self.m.VehicleKarteAnalysis.query.filter_by(id=state.id).update({'result_json':saved()},synchronize_session=False)
        self.m.db.session.commit();before=self.snapshot(state)
        self.assertFalse(repo.claim(state.id,state.input_hash,'new-token',NOW))
        self.assertFalse(repo.finish(state.id,'token',claimed_hash=state.input_hash,snapshot_hash='new',
            bundle={'analysis':{'recommendations':[]}},finished=NOW,method='ai'))
        repo.fail(state.id,'token','failure',NOW);repo.skip(state.id,'token')
        with self.assertRaisesRegex(RuntimeError,'ANALYSIS_LEASE_LOST'):repo.renew(state.id,'token',NOW)
        self.assertEqual(before,self.snapshot(state))

    def test_analysis_success_and_failure_races_keep_new_result_and_metadata(self):
        for fail in [False,True]:
            with self.subTest(fail=fail):
                state=self.analysis('{}');expected={}
                def ai(*args,**kwargs):
                    self.m.VehicleKarteAnalysis.query.filter_by(id=state.id).update({'result_json':saved(),'status':'completed'},synchronize_session=False)
                    self.m.db.session.commit();expected.update(self.snapshot(state))
                    if fail:raise RuntimeError('synthetic generation failure')
                    return {'overview':'old result','recommendations':[]}
                with patch.object(self.m,'get_vehicle_karte_analysis_job_data',return_value=({'_fingerprints':fingerprints(),'coverage':{}},{})),patch.object(self.m,'analyze_vehicle_karte',side_effect=ai):
                    self.assertFalse(self.m.run_vehicle_karte_analysis_job(state.id))
                self.assertEqual(expected,self.snapshot(state))
                self.m.db.session.delete(state);self.m.db.session.commit()

    def test_normal_and_periodic_reads_withhold_new_semantics_without_database_mutation(self):
        self.analysis();self.periodic();before=self.tables()
        for path in [f'/vehicle/karte/{self.vehicle.id}/analysis/result',self.api]:
            response=self.client.get(path)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json['status'],'held')
            self.assertEqual(response.json['message'],MESSAGE)
            self.assertFalse(response.json['is_current'])
            self.assertFalse(response.json['can_generate'])
            self.assertIsNone(response.json.get('analysis',response.json.get('result')))
            self.assertIn('no-store',response.headers['Cache-Control'])
        self.assertEqual(before,self.tables())

    def test_periodic_post_statuses_retry_and_missing_input_cannot_clear_or_submit(self):
        row=self.periodic()
        for status in ['completed','running','error','pending']:
            for retry in [False,True]:
                with self.subTest(status=status,retry=retry):
                    row.status=status;row.input_hash='new-format-hash';self.m.db.session.commit();before=self.snapshot(row)
                    with patch.object(self.executor,'submit') as submit:
                        response=self.client.post(self.api,json={'retry':retry})
                        self.assertEqual(response.status_code,409);submit.assert_not_called()
                    self.assertEqual(response.json['error'],ERROR)
                    self.assertEqual(before,self.snapshot(row))

    def test_periodic_worker_does_not_generate_for_protected_or_stale_token(self):
        row=self.periodic();before=self.snapshot(row)
        for token in [row.run_token,'stale-token']:
            with patch('vehicle_periodic_followups.generate_periodic_proposals') as generate:
                self.service.worker('TEST',self.record.id,token,{})
                generate.assert_not_called()
            self.assertEqual(before,self.snapshot(row))

    def test_periodic_success_and_failure_races_recheck_current_bytes(self):
        row=self.cached(status='running');expected={}
        for fail in [False,True]:
            with self.subTest(fail=fail):
                row.result_json='{}';row.status='running';self.m.db.session.commit()
                def generate(*args):
                    self.Proposal.query.filter_by(id=row.id).update({'result_json':saved('held','periodic'),'status':'completed'},synchronize_session=False)
                    self.m.db.session.commit();expected.clear();expected.update(self.snapshot(self.m.db.session.get(self.Proposal,row.id)))
                    if fail:raise RuntimeError('synthetic failure')
                    return {'overview':'old','recommendations':[]}
                with patch('vehicle_periodic_followups.generate_periodic_proposals',side_effect=generate):
                    self.service.worker('TEST',self.record.id,row.run_token,{})
                self.assertEqual(expected,self.snapshot(row))

    def test_periodic_submit_failure_does_not_degrade_concurrent_protected_row(self):
        row=self.cached(status='error');row.input_hash='obsolete';self.m.db.session.commit();expected={}
        def submit(*args):
            self.Proposal.query.filter_by(id=row.id).update({'result_json':saved('held','periodic'),'status':'completed'},synchronize_session=False)
            self.m.db.session.commit();expected.update(self.snapshot(row))
            raise RuntimeError('synthetic submit failure')
        with patch.object(self.executor,'submit',side_effect=submit):
            self.client.post(self.api,json={'retry':True})
        self.assertEqual(expected,self.snapshot(row))

    def test_periodic_start_cas_does_not_clear_result_arriving_after_initial_read(self):
        row=self.cached(status='error');row.input_hash='obsolete';self.m.db.session.commit();expected={}
        # The input builder is a closure. Intercept its shared context dependency.
        original=self.m.get_vehicle_karte_analysis_job_data
        def build(*args):
            self.Proposal.query.filter_by(id=row.id).update({'result_json':saved('held','periodic'),'status':'error'},synchronize_session=False)
            self.m.db.session.commit();expected.update(self.snapshot(row))
            return original(*args)
        # Patch a deterministic boundary in the closure instead of replacing its export.
        function=self.m.app.view_functions['vehicle_periodic_suggestions']
        input_fn=next(cell.cell_contents for name,cell in zip(function.__code__.co_freevars,function.__closure__) if name=='proposal_input')
        cell=next(cell for name,cell in zip(input_fn.__code__.co_freevars,input_fn.__closure__) if name=='analysis_context')
        prior=cell.cell_contents;cell.cell_contents=build
        try:
            with patch.object(self.executor,'submit') as submit:
                response=self.client.post(self.api,json={'retry':True})
                self.assertEqual(response.status_code,409);submit.assert_not_called()
        finally:cell.cell_contents=prior
        self.assertEqual(expected,self.snapshot(row))

    def test_dashboard_withholds_saved_priority_and_reports_retention(self):
        self.analysis(status='completed');before=self.tables()
        with self.m.app.test_request_context('/'):
            result=self.m.get_dashboard_vehicle_attention('TEST',self.vehicle.office,[self.vehicle.id])
        group=result['mine'];self.assertEqual(group['held'],1);self.assertEqual(group['items'],[])
        self.assertEqual(group['missing'],0);self.assertEqual(group['held_message'],MESSAGE)
        self.assertEqual(before,self.tables())

    def test_old_feedback_and_evaluation_forms_cannot_act_on_withheld_saved_proposal(self):
        state=self.analysis(status='completed');item=json.loads(state.result_json)['analysis']['recommendations'][0]
        key,revision=self.m.vehicle_analysis_proposal_ids(item);before=self.tables()
        for suffix,body in [('feedback',{'status':'accepted'}),('evaluation',{'verdict':'appropriate'})]:
            response=self.client.post(f'/vehicle/karte/{self.vehicle.id}/analysis/{suffix}',json={**body,'proposal_id':key,'proposal_revision':revision})
            self.assertEqual(response.status_code,409,response.get_data(as_text=True))
            self.assertEqual(response.json['error'],ERROR)
        self.assertEqual(before,self.tables())

    def test_protected_bundle_cannot_match_legacy_fingerprints(self):
        bundle=json.loads(saved());payload={'_fingerprints':bundle['fingerprints']}
        self.assertFalse(self.m.vehicle_karte_analysis_matches_input(bundle,payload))

    def test_document_delete_and_correction_plan_reject_before_mutation(self):
        import re
        state=self.analysis();draft=self.m.VehicleDocumentImportDraft.query.filter_by(id=self.record.source_draft_id).one()
        before=self.tables()
        url=f'/vehicle/karte/{self.vehicle.id}/documents/{draft.id}/delete'
        response=self.client.get(url);self.assertEqual(response.status_code,200)
        self.assertIn(MESSAGE,response.get_data(as_text=True))
        self.assertEqual(self.client.post(url,data={'confirm_delete':'yes'}).status_code,409)
        page=self.client.get(f'/vehicle/data-import/{draft.id}/kind')
        token=re.search(r'name="kind_token" value="([^"]+)"',page.get_data(as_text=True)).group(1)
        response=self.client.post(f'/vehicle/data-import/{draft.id}/kind',data={'kind_token':token,'document_type':'maintenance'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(before,self.tables())

    def test_document_plan_checks_periodic_result_even_without_normal_result(self):
        self.periodic();draft=self.m.VehicleDocumentImportDraft.query.filter_by(id=self.record.source_draft_id).one();before=self.tables()
        response=self.client.get(f'/vehicle/karte/{self.vehicle.id}/documents/{draft.id}/delete')
        self.assertIn(MESSAGE,response.get_data(as_text=True));self.assertEqual(before,self.tables())


    def test_malformed_saved_result_is_not_queued_claimed_or_overwritten(self):
        raw=json.dumps({'analysis':{'recommendations':[]},'sources':['malformed']})
        state=self.analysis(raw);before=self.snapshot(state)
        self.m.queue_vehicle_karte_analysis(self.vehicle,{'_fingerprints':fingerprints(important='changed')})
        self.m.db.session.commit()
        self.assertFalse(self.repo().finish(state.id,'token',claimed_hash=state.input_hash,
            snapshot_hash='changed',bundle={'analysis':{'recommendations':[]}},finished=NOW,method='ai'))
        self.assertFalse(self.m.run_vehicle_karte_analysis_job(state.id))
        self.assertEqual(before,self.snapshot(state))

    def test_protected_running_periodic_results_do_not_consume_legacy_generation_slots(self):
        for index,record in enumerate([self.import_record('2026-08-12','2026-11'),self.import_record('2026-07-12','2026-10')]):
            self.m.db.session.add(self.Proposal(company_code='TEST',inspection_record_id=record.id,
                input_hash='protected',run_token='protected-'+str(index),status='running',
                result_json=saved('held','periodic'),updated_at=datetime.now(timezone.utc).isoformat()))
        self.m.db.session.commit()
        with patch.object(self.executor,'submit') as submit:
            response=self.client.post(self.api,json={})
            self.assertEqual(response.status_code,202,response.get_data(as_text=True))
            submit.assert_called_once()

    def test_tick_skips_twenty_protected_due_rows_without_starving_legacy_work(self):
        self.analysis();db=self.m.db
        for index in range(19):
            vehicle=self.m.Vehicle(company_code='TEST',chassis_number='HELD-'+str(index),deleted=False)
            db.session.add(vehicle);db.session.flush()
            db.session.add(self.m.VehicleKarteAnalysis(company_code='TEST',vehicle_record_id=vehicle.id,
                status='pending',result_json=saved(),next_analysis_at=NOW-timedelta(days=2)))
        vehicle=self.m.Vehicle(company_code='TEST',chassis_number='LEGACY',deleted=False);db.session.add(vehicle);db.session.flush()
        legacy=self.m.VehicleKarteAnalysis(company_code='TEST',vehicle_record_id=vehicle.id,status='pending',result_json='{}',next_analysis_at=NOW-timedelta(days=1));db.session.add(legacy);db.session.commit();legacy_id=legacy.id
        # Tick scan is irrelevant to runnable selection; no public fetch or AI is made.
        with patch.dict(self.m.app.extensions['dkss'],{'public_knowledge_tick':lambda:None}),patch.object(self.m,'get_vehicle_karte_analysis_job_data',return_value=({},{})),patch.object(self.m,'queue_vehicle_karte_analysis'),patch.object(self.m,'run_vehicle_karte_analysis_job',return_value=True) as run:
            self.m.vehicle_karte_analysis_tick()
        run.assert_called_once_with(legacy_id)

# Imported setup class is not part of this module's discovery.
del _Periodic


from test_document_kind_recovery import DocumentKindRecoveryTests as _Recovery
from test_inspection_document_ai import extraction, pdf_bytes


class CorrectionRetentionTests(TestCase):
    setUpClass = classmethod(_Recovery.setUpClass.__func__)
    tearDownClass = classmethod(_Recovery.tearDownClass.__func__)
    setUp = _Recovery.setUp
    tearDown = _Recovery.tearDown
    upload_inspection = _Recovery.upload_inspection
    inspection_form = _Recovery.inspection_form
    worker = _Recovery.worker
    invoice = _Recovery.invoice
    kind_post = _Recovery.kind_post
    tables = RetentionDatabaseTests.tables

    def test_new_result_after_correction_preparation_stops_final_replacement_atomically(self):
        source=pdf_bytes();data=extraction(source)
        data['records'][0].update(inspection_type='other',next_inspection_date=None,next_inspection_month=None)
        self.upload_inspection(data=data,source=source)
        Draft=self.m.VehicleDocumentImportDraft
        original=Draft.query.one();form=self.inspection_form(original)
        form['inspection_type_'+original.id+'_0']='other'
        self.assertEqual(self.client.post('/vehicle/data-import/'+original.batch_id+'/confirm',data=form).status_code,302)
        self.assertEqual(self.kind_post(original,'maintenance').status_code,303)
        self.worker(invoice=True)
        replacement=Draft.query.filter(Draft.id!=original.id).one()
        state=self.m.VehicleKarteAnalysis.query.filter_by(vehicle_record_id=self.vehicle.id).first()
        if state is None:
            state=self.m.VehicleKarteAnalysis(company_code='TEST',vehicle_record_id=self.vehicle.id)
            self.m.db.session.add(state)
        state.result_json=saved();self.m.db.session.commit()
        before=(original.status,original.source_file,original.result_json,state.result_json,
                self.m.VehiclePeriodicInspectionRecord.query.one().details_json)
        all_before=self.tables()
        replacement_before={column.key:getattr(replacement,column.key) for column in replacement.__table__.columns if column.key!='preview_json'}
        key=replacement.id+'_0'
        form={'include':key,'vehicle_'+key:str(self.vehicle.id),'date_'+key:'2026-08-01','content_'+key:'故障修理','confirm_kind_correction':'yes'}
        response=self.client.post('/vehicle/data-import/'+replacement.batch_id+'/confirm',data=form)
        self.assertIn(response.status_code,[400,409])
        self.m.db.session.expire_all()
        self.assertEqual(before,(original.status,original.source_file,original.result_json,state.result_json,
                self.m.VehiclePeriodicInspectionRecord.query.one().details_json))
        self.assertEqual(self.m.VehicleMaintenanceRecord.query.count(),0)
        after=self.tables()
        # Existing rejected-confirmation flow normalizes only the replacement
        # preview form. Originals, saved results and every business table stay.
        self.assertEqual({k:v for k,v in all_before.items() if k!='vehicle_document_import_draft'},
                         {k:v for k,v in after.items() if k!='vehicle_document_import_draft'})
        self.assertEqual(replacement_before,{column.key:getattr(replacement,column.key)
            for column in replacement.__table__.columns if column.key!='preview_json'})
        all_before=after
        # Check the final replacement hook too, independently of earlier validation.
        from flask import session
        from dkss_app.document_import_queue import metadata
        digest=metadata(replacement.result_json)['correction']['digest']
        with self.m.app.test_request_context('/'):
            session['username']='admin'
            with self.assertRaises(ValueError):
                self.m.app.extensions['dkss']['document_deletion']['replace_source'](
                    self.vehicle,original,replacement,digest)
            self.m.db.session.rollback()
        self.assertEqual(all_before,self.tables())

    def test_parent_lock_conflict_rolls_back_already_flushed_final_correction(self):
        from sqlalchemy.orm import Query
        from sqlalchemy.exc import OperationalError
        from vehicle_saved_result_guard import BUSY_MESSAGE
        source=pdf_bytes();data=extraction(source)
        data['records'][0].update(inspection_type='other',next_inspection_date=None,next_inspection_month=None)
        self.upload_inspection(data=data,source=source)
        Draft=self.m.VehicleDocumentImportDraft
        original=Draft.query.one();form=self.inspection_form(original)
        form['inspection_type_'+original.id+'_0']='other'
        self.assertEqual(self.client.post('/vehicle/data-import/'+original.batch_id+'/confirm',data=form).status_code,302)
        self.assertEqual(self.kind_post(original,'maintenance').status_code,303)
        self.worker(invoice=True)
        replacement=Draft.query.filter(Draft.id!=original.id).one()
        before=self.tables()
        original_before={c.key:getattr(original,c.key) for c in Draft.__table__.columns}
        replacement_before={c.key:getattr(replacement,c.key) for c in Draft.__table__.columns if c.key!='preview_json'}
        key=replacement.id+'_0'
        form={'include':key,'vehicle_'+key:str(self.vehicle.id),'date_'+key:'2026-08-01','content_'+key:'故障修理','confirm_kind_correction':'yes'}
        service=self.m.app.extensions['dkss']['document_deletion']
        replace=service['replace_source'];with_for_update=Query.with_for_update
        class LockNotAvailable(Exception):
            pgcode='55P03'
        def conflict(query,*args,**kwargs):
            if kwargs.get('nowait'):
                raise OperationalError('synthetic parent lock',{},LockNotAvailable())
            return with_for_update(query,*args,**kwargs)
        def final_replace(*args,**kwargs):
            self.assertEqual(self.m.VehicleMaintenanceRecord.query.count(),1)
            with patch.object(Query,'with_for_update',conflict):
                return replace(*args,**kwargs)
        with patch.dict(service,{'replace_source':final_replace}):
            response=self.client.post('/vehicle/data-import/'+replacement.batch_id+'/confirm',data=form)
        self.assertEqual(response.status_code,400)
        self.assertIn(BUSY_MESSAGE,response.get_data(as_text=True))
        after=self.tables();self.m.db.session.expire_all()
        self.assertEqual({k:v for k,v in before.items() if k!='vehicle_document_import_draft'},
                         {k:v for k,v in after.items() if k!='vehicle_document_import_draft'})
        self.assertEqual(original_before,{c.key:getattr(original,c.key) for c in Draft.__table__.columns})
        self.assertEqual(replacement_before,{c.key:getattr(replacement,c.key) for c in Draft.__table__.columns if c.key!='preview_json'})

    def test_document_delete_rechecks_new_result_after_confirmation_was_opened(self):
        import re
        source=pdf_bytes();data=extraction(source)
        data['records'][0].update(inspection_type='other',next_inspection_date=None,next_inspection_month=None)
        self.upload_inspection(data=data,source=source)
        draft=self.m.VehicleDocumentImportDraft.query.one();form=self.inspection_form(draft)
        form['inspection_type_'+draft.id+'_0']='other'
        self.assertEqual(self.client.post('/vehicle/data-import/'+draft.batch_id+'/confirm',data=form).status_code,302)
        url=f'/vehicle/karte/{self.vehicle.id}/documents/{draft.id}/delete'
        page=self.client.get(url)
        token=re.search(r'name="delete_token" value="([^"]+)"',page.get_data(as_text=True)).group(1)
        state=self.m.VehicleKarteAnalysis(company_code='TEST',vehicle_record_id=self.vehicle.id,result_json=saved())
        self.m.db.session.add(state);self.m.db.session.commit()
        before=(draft.status,draft.result_json,draft.source_file,state.result_json)
        all_before=self.tables()
        response=self.client.post(url,data={'delete_token':token,'confirm_delete':'yes'})
        self.assertEqual(response.status_code,409)
        self.m.db.session.expire_all()
        self.assertEqual(before,(draft.status,draft.result_json,draft.source_file,state.result_json))
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(),1)
        self.assertEqual(all_before,self.tables())


del _Recovery
