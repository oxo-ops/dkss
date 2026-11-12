"""Logical final-gate ordering. PostgreSQL tests separately prove real exclusion."""
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch

import test_analysis_generation_fence as fixture
import test_vehicle_analysis_service as service_fixture
import test_priority_candidate_completion as completion
from vehicle_analysis_repository import VehicleAnalysisJobRepository
from vehicle_analysis_service import snapshot_hash


class FinalSourceGateTests(unittest.TestCase):
    setUpClass = classmethod(fixture.RealConfirmationGenerationFenceTests.setUpClass.__func__)
    tearDownClass = classmethod(fixture.RealConfirmationGenerationFenceTests.tearDownClass.__func__)
    for _name in ('setUp','tearDown','login','request','save','complete','state','decision_data','decide',
                  'snapshot','refs','clock','begin','repair','prepare_pair','confirm','load','cancel'):
        locals()[_name] = getattr(fixture.RealConfirmationGenerationFenceTests, _name)
    del _name

    def run_repair_before_gate(self, prior_candidate):
        from dkss_app import analysis, common, priority_confirmed_projection as projection
        from dkss_app.priority_confirmations import confirmation_statuses
        self.prepare_pair(); self.confirm()
        payload, sources = self.load()
        previous = {'analysis':{'overview':'previous saved','recommendations':[]}, 'sources':{},
                    'fingerprints':{}, 'generated_at':'previous time'}
        if prior_candidate:
            previous.update(analysis=completion.finish(previous['analysis'],payload), sources=sources,
                            fingerprints=payload['_fingerprints'])
        previous_json = json.dumps(previous, ensure_ascii=False)
        row = self.models.VehicleKarteAnalysis(company_code='A', vehicle_record_id=self.vehicle.id,
            input_hash=snapshot_hash(payload['_fingerprints']), result_json=previous_json, status='pending',
            next_analysis_at=datetime.now(timezone.utc)-timedelta(seconds=1))
        self.db.session.add(row); self.db.session.commit()
        sid, vid, rid = row.id, self.vehicle.id, self.row.id
        order=[]; expected={}
        real_gate = VehicleAnalysisJobRepository.lock_vehicle_for_finish
        real_reconcile = projection.reconcile_confirmed_candidates_before_save
        real_finish = VehicleAnalysisJobRepository.finish
        def gate(repository, company, vehicle_id):
            order.append('gate')
            self.assertEqual(order,['model','gate'])
            self.assertEqual((company,vehicle_id),('A',vid))
            original_row=self.row
            try:
                with self.app.app_context():
                    self.row=self.db.session.get(self.models.VehicleChecklistResult,rid)
                    self.repair()  # Real ordinary POST, no subsequent normal recheck.
                    vehicle=self.db.session.get(self.models.Vehicle,vid)
                    self.assertEqual(confirmation_statuses(vehicle,as_of=self.day)[0]['status'],'held')
                    expected['audit']=[(e.id,e.detail_json) for e in self.models.ChecklistEvent.query.order_by(self.models.ChecklistEvent.id)]
                    expected['source']=self.row.operation_judgment_json
            finally:
                self.row=original_row
            return real_gate(repository,company,vehicle_id)
        def reconcile(*args,**kwargs):
            order.append('reconcile')
            return real_reconcile(*args,**kwargs)
        def finish(repository,*args,**kwargs):
            order.append('finish')
            self.assertEqual(order,['model','gate','reconcile','finish'])
            return real_finish(repository,*args,**kwargs)
        def model(value,on_progress=None):
            order.append('model')
            if on_progress:on_progress()
            return {'overview':'new generated','recommendations':[]}
        with patch.object(common,'analyze_vehicle_karte',side_effect=model) as ai, \
                patch.object(VehicleAnalysisJobRepository,'lock_vehicle_for_finish',gate), \
                patch.object(VehicleAnalysisJobRepository,'finish',finish), \
                patch.object(projection,'reconcile_confirmed_candidates_before_save',side_effect=reconcile):
            self.assertTrue(analysis.run_vehicle_karte_analysis_job(sid))
        ai.assert_called_once()
        self.db.session.expire_all()
        saved=self.db.session.get(self.models.VehicleKarteAnalysis,sid)
        bundle=json.loads(saved.result_json)
        self.assertEqual(len(bundle['analysis']['recommendations']),int(prior_candidate))
        self.assertEqual([(e.id,e.detail_json) for e in self.models.ChecklistEvent.query.order_by(self.models.ChecklistEvent.id)],expected['audit'])
        self.assertEqual(self.db.session.get(self.models.VehicleChecklistResult,rid).operation_judgment_json,expected['source'])
        self.assertEqual(saved.status,'completed');self.assertIsNone(saved.next_analysis_at)
        self.login('admin')
        response=self.client.get(f'/vehicle/karte/{vid}/analysis/result')
        self.assertEqual(response.status_code,200)
        items=response.json['analysis']['recommendations']
        self.assertEqual(len(items),int(prior_candidate))
        if prior_candidate:
            self.assertTrue(bundle['analysis']['recommendations'][0]['priority_candidate_carryover'])
            self.assertIsNone(items[0]['priority_assessment']['effective_score'])
        # Only the normal existing source-change queue schedules regeneration.
        fresh,_=self.load();analysis.queue_vehicle_karte_analysis(self.vehicle,fresh);self.db.session.commit()
        class DueClock(datetime):
            @classmethod
            def now(cls,tz=None):return datetime.now(tz)+timedelta(minutes=3)
        with patch.object(common,'datetime',DueClock), \
                patch.object(common,'analyze_vehicle_karte',return_value={'overview':'next generation','recommendations':[]}) as next_ai:
            self.assertTrue(analysis.run_vehicle_karte_analysis_job(sid))
        next_ai.assert_called_once()
        self.db.session.expire_all()
        second=json.loads(self.db.session.get(self.models.VehicleKarteAnalysis,sid).result_json)
        self.assertEqual(len(second['analysis']['recommendations']),int(prior_candidate))

    def test_repair_before_final_gate_cannot_invent_first_saved_held_history(self):
        self.run_repair_before_gate(False)

    def test_legitimate_previous_candidate_remains_held_history(self):
        self.run_repair_before_gate(True)


class FinalSourceScopeTests(unittest.TestCase):
    setUpClass = classmethod(fixture.QueuedGenerationFenceTests.setUpClass.__func__)
    tearDownClass = classmethod(fixture.QueuedGenerationFenceTests.tearDownClass.__func__)
    setUp = fixture.QueuedGenerationFenceTests.setUp
    tearDown = fixture.QueuedGenerationFenceTests.tearDown
    state = fixture.QueuedGenerationFenceTests.state
    run_job = fixture.QueuedGenerationFenceTests.run_job

    def test_deleted_or_foreign_target_after_model_never_saves_generated_bundle(self):
        for fields in ({'deleted':True},{'company_code':'OTHER'}):
            with self.subTest(fields=fields):
                self.m.Vehicle.query.filter_by(id=self.vehicle.id).update({'deleted':False,'company_code':'TEST'})
                self.m.VehicleKarteAnalysis.query.filter_by(id=self.state_id).update({
                    'status':'pending','lease_token':None,'lease_expires_at':None,
                    'next_analysis_at':service_fixture.NOW-timedelta(seconds=1),'result_json':self.previous})
                self.m.db.session.commit()
                def model(payload,on_progress):
                    self.m.Vehicle.query.filter_by(id=self.vehicle.id).update(fields)
                    self.m.db.session.commit()
                    return {'overview':'must not save','recommendations':[]}
                self.assertTrue(self.run_job(model)[0])
                self.assertEqual(self.state().status,'skipped')
                self.assertEqual(self.state().result_json,self.previous)
                self.assertIsNone(self.state().lease_token)
