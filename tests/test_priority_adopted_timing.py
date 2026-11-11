"""Ordinary adopted timing bridge against actual registered SQLite records.

Stored original/review fixtures are synthetic. No timing/adoption/current-read
function is mocked, and no external AI, fetch, peer, cache or production DB runs.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta
import hashlib
import json
import unittest
from unittest.mock import patch

from sqlalchemy import event
import test_workflow_regressions as workflow
from test_inspection_document_ai import pdf_bytes
from dkss_app.priority_timing import (attach_timing_priority_inputs,
    project_registered_timing_priorities, PROOF_KEY)

DAY = date(2026, 11, 11)


class AdoptedTimingPriorityTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    tearDown = workflow.WorkflowRegressionTests.tearDown

    def setUp(self):
        workflow.WorkflowRegressionTests.setUp(self)
        from dkss_app.maintenance_knowledge_import_models import get_models
        from dkss_app.public_maintenance_knowledge_models import get_models as public_models
        self.Document, _ = get_models(self.m.db)
        _, self.PublicFile = public_models(self.m.db)
        self.vehicle.manufacturer = '日野'
        self.vehicle.model_code = 'TEST-TIMING'
        self.m.db.session.commit()
        self.number = 0

    def setup_rule(self, *, criteria=None, relation='single', action='replace', origin='2026-01-31'):
        m = self.m
        self.criteria = criteria or [{'metric': 'period_days', 'value': 284}]
        self.rule = dict(action=action, cycle='repeat', relation=relation, criteria=self.criteria,
            model_codes=[], engine_codes=[], conditions='合成試験の適用条件', source_page=1,
            source_quote='合成部品の定期交換・点検基準',
            numeric_evidence={'status': 'tokens_present'})
        raw = pdf_bytes(1)
        self.checksum = hashlib.sha256(raw).hexdigest()
        self.document_id = '11111111-1111-4111-8111-111111111111'
        self.rule['source_verification'] = {'status': 'quote_matched', 'document_checksum': self.checksum}
        self.rule['semantic_review'] = {'status': 'supported', 'document_checksum': self.checksum,
            'evidence': [{'source_verification': deepcopy(self.rule['source_verification'])}],
            'applicability': {'scope': 'unrestricted', 'coverage': 'complete',
                'requirements': [], 'unresolved_conditions': []}}
        self.knowledge = m.VehicleMaintenanceKnowledge(company_code='TEST', title='合成試験基準',
            part_name='合成試験部品', manufacturer='日野', model_code='', conditions='合成試験条件',
            guidance='合成試験専用', source_kind='メーカー公式資料',
            source_reference='https://example.test/timing.pdf / [knowledge-document:' + self.document_id + ']',
            provider='合成メーカー', valid_from='2026-01-01', status='draft',
            created_by='test', created_at='2026/11/11 00:00')
        m.db.session.add(self.knowledge); m.db.session.flush()
        self.extracted = {key: getattr(self.knowledge, key) for key in
            ('title', 'part_name', 'model_code', 'conditions', 'guidance', 'provider')}
        self.extracted.update(maintenance_rules=[self.rule],
            vehicle_scope={'mode':'unrestricted', 'categories':[], 'quote':'合成試験のみ'})
        self.doc = self.Document(id=self.document_id, company_code='TEST', checksum=self.checksum,
            filename='synthetic-priority.pdf', original_data=raw, mimetype='application/pdf',
            knowledge_ids_json=json.dumps([self.knowledge.id]), extraction_json=json.dumps([self.extracted]),
            created_by='test', created_at='2026/11/11 00:00')
        m.db.session.add(self.doc)
        now = datetime.now()
        self.public = self.PublicFile(company_code='TEST', url='https://example.test/timing.pdf',
            title='合成試験資料', available=True, next_check=now+timedelta(days=2),
            last_checked=now-timedelta(days=1), checksum=self.checksum,
            document_id=self.document_id, status='unchanged')
        m.db.session.add(self.public)
        self.parent = m.VehicleMaintenanceRecord(company_code='TEST', vehicle_record_id=self.vehicle.id,
            entry_date=origin, completion_date=origin, status='完了', mileage=10000, content='合成交換記録')
        m.db.session.add(self.parent); m.db.session.flush()
        self.part = m.VehiclePartReplacement(company_code='TEST', vehicle_record_id=self.vehicle.id,
            maintenance_record_id=self.parent.id, part_name='合成試験部品', replacement_date=origin,
            mileage=10000, quantity=1, created_at='2026/11/11 00:00')
        m.db.session.add(self.part); m.db.session.commit()
        self.operation(19000)

    def operation(self, mileage, day=DAY.isoformat()):
        self.number += 1
        row = self.m.VehicleOperationRecord(company_code='TEST', vehicle_record_id=self.vehicle.id,
            report_number=f'TIMING-{self.number}', operation_date=day, arrival_meter=mileage,
            arrival_at=day+' 12:00:00')
        self.m.db.session.add(row); self.m.db.session.commit()
        return row

    def save_rule(self):
        self.extracted['maintenance_rules'] = [self.rule]
        self.doc.extraction_json = json.dumps([self.extracted])
        self.m.db.session.commit()

    def generate(self):
        from dkss_app.analysis import build_vehicle_karte_analysis_payload, build_vehicle_karte_analysis_summary
        from vehicle_analysis_repository import VehicleAnalysisInputRepository
        from dkss_app import models as m
        from dkss_app.vehicle_operations import get_vehicle_canonical_operations
        repo = VehicleAnalysisInputRepository(maintenance=m.VehicleMaintenanceRecord,
            operations=m.VehicleOperationRecord, parts=m.VehiclePartReplacement, defects=m.VehiclePatrol,
            periodic=m.VehiclePeriodicInspectionRecord, canonical_operations=get_vehicle_canonical_operations)
        records = repo.load(self.vehicle, DAY)
        summary = build_vehicle_karte_analysis_summary(records.maintenance, records.operations,
            records.parts, records.defects, DAY.isoformat(), DAY.isoformat(), periodic_records=records.periodic)
        with self.m.app.test_request_context('/'):
            payload, sources = build_vehicle_karte_analysis_payload(self.vehicle, summary, {},
                records.maintenance, records.parts, records.defects)
            attach_timing_priority_inputs(self.vehicle, payload, sources)
        return payload, sources

    def proposal(self):
        payload, sources = self.generate()
        offers = [o for k in payload['maintenance_knowledge'] for o in k.get('priority_inputs', [])]
        self.assertEqual(len(offers), 1, payload['maintenance_knowledge'])
        offer = offers[0]
        item = dict(proposal_id='stable-original-id', proposal_revision='stable-original-revision',
            priority_input_ref=offer['ref'], target=offer['display_target'], source_ids=offer['source_ids'],
            priority='高', feedback={'status':'accepted'}, risk_status='unassessed')
        return {'recommendations':[item]}, sources

    def assess(self, analysis, sources, day=DAY):
        with self.m.app.test_request_context('/'):
            return project_registered_timing_priorities(analysis, self.vehicle, sources,
                as_of=day, is_current=True)[0]

    def test_normal_generation_and_current_read_use_stored_adoption(self):
        self.setup_rule()
        analysis, sources = self.proposal(); before = deepcopy((analysis, sources))
        statements = []
        def capture(_c, _cursor, statement, _p, _ctx, _many): statements.append(statement)
        event.listen(self.m.db.engine, 'before_cursor_execute', capture)
        try:
            with patch('dkss_app.analysis.get_vehicle_karte_peer_comparison', side_effect=AssertionError('peer forbidden')):
                result, reason = self.assess(analysis, sources)
        finally:
            event.remove(self.m.db.engine, 'before_cursor_execute', capture)
        self.assertIsNone(reason)
        self.assertEqual((result['label'], result['effective_score']), ('中', 35))
        self.assertEqual([v['points'] for v in result['factors']], [None,35,None])
        self.assertEqual(result['applied_floors'], [])
        self.assertEqual(result['operation_decision'], 'human_only')
        self.assertEqual((analysis,sources), before)
        self.assertFalse(any(s.lstrip().upper().startswith(('INSERT','UPDATE','DELETE')) for s in statements))

    def test_day_and_distance_boundaries_are_real_timing_inputs(self):
        self.setup_rule(criteria=[{'metric':'distance_km','value':10000}])
        a,s=self.proposal(); value,reason=self.assess(a,s)
        self.assertIsNone(reason); self.assertEqual(value['effective_score'],25)
        self.assertTrue(any(sid.startswith('operation:') for sid in value['source_ids']))
        # New, later verified reading is allowed for the same baseline event.
        operation=self.m.VehicleOperationRecord.query.one()
        operation.arrival_meter=20000; self.m.db.session.commit()
        value,_=self.assess(a,s); self.assertEqual(value['effective_score'],35)
        operation.arrival_meter=18999; self.m.db.session.commit()
        value,_=self.assess(a,s); self.assertEqual(value['effective_score'],10)

    def test_calendar_30_days_and_actual_90_percent_duration(self):
        self.setup_rule(criteria=[{'metric':'period_days','value':400}], origin='2026-01-01')
        a,s=self.proposal()
        for days,expected in [(359,10),(360,25),(369,25),(370,25),(400,35)]:
            # Explicit past dates only; change stored origin and regenerate to
            # keep the system date independent from this deterministic boundary.
            self.parent.entry_date=self.parent.completion_date=(DAY-timedelta(days=days)).isoformat()
            self.part.replacement_date=self.parent.entry_date
            self.m.db.session.commit(); a,s=self.proposal()
            value,reason=self.assess(a,s)
            self.assertIsNone(reason); self.assertEqual(value['effective_score'],expected)

    def test_missing_mileage_never_becomes_zero_or_low(self):
        self.setup_rule(criteria=[{'metric':'distance_km','value':10000}])
        a,s=self.proposal(); self.m.VehicleOperationRecord.query.delete(); self.m.db.session.commit()
        value,reason=self.assess(a,s)
        self.assertIsNone(value); self.assertTrue(reason)

    def test_new_conflicting_reading_is_seen_beyond_saved_citations(self):
        self.setup_rule(criteria=[{'metric':'distance_km','value':10000}])
        a,s=self.proposal(); self.operation(19500)
        value,reason=self.assess(a,s)
        self.assertIsNone(value); self.assertTrue(reason)

    def test_new_latest_replacement_is_not_rebound_to_old_proposal(self):
        self.setup_rule(); a,s=self.proposal()
        row=self.m.VehiclePartReplacement(company_code='TEST',vehicle_record_id=self.vehicle.id,
            maintenance_record_id=self.parent.id,part_name=self.part.part_name,replacement_date='2026-11-10',
            mileage=18000,quantity=1,created_at='2026/11/11 00:00')
        self.m.db.session.add(row);self.m.db.session.commit()
        value,reason=self.assess(a,s);self.assertIsNone(value);self.assertTrue(reason)

    def test_public_version_or_semantic_review_withdrawal_is_held(self):
        self.setup_rule();a,s=self.proposal()
        self.rule['semantic_review']['status']='not_reviewed';self.save_rule()
        value,reason=self.assess(a,s);self.assertIsNone(value);self.assertTrue(reason)
        self.rule['semantic_review']['status']='supported';self.save_rule()
        self.public.available=False;self.m.db.session.commit()
        value,reason=self.assess(a,s);self.assertIsNone(value);self.assertTrue(reason)

    def test_inspection_rule_cannot_reuse_replacement_baseline(self):
        self.setup_rule(action='inspect')
        payload,sources=self.generate()
        self.assertEqual([o for k in payload['maintenance_knowledge'] for o in k.get('priority_inputs',[])],[])

    def test_or_and_are_not_flattened_to_max(self):
        self.setup_rule(criteria=[{'metric':'period_days','value':1},{'metric':'distance_km','value':10000}],relation='all')
        a,s=self.proposal();value,reason=self.assess(a,s)
        self.assertIsNone(value);self.assertIn('AND',reason)
        operation=self.m.VehicleOperationRecord.query.one()
        operation.arrival_meter=20000;self.m.db.session.commit()
        value,reason=self.assess(a,s)
        self.assertIsNone(reason);self.assertEqual(value['effective_score'],35)
        self.assertIsNone(value['earliest_due_on'])
        self.rule['relation']='any';self.save_rule();a,s=self.proposal()
        value,reason=self.assess(a,s);self.assertIsNone(reason);self.assertEqual(value['effective_score'],35)

    def test_or_reached_can_survive_missing_limb_and_far_cannot(self):
        self.setup_rule(criteria=[{'metric':'period_days','value':1},{'metric':'engine_hours','value':1000}],relation='any')
        a,s=self.proposal();value,reason=self.assess(a,s)
        self.assertIsNone(reason);self.assertEqual(value['effective_score'],35)
        self.assertTrue(any('engine_hours' in row for row in value['missing_conditions']))
        self.rule['criteria'][0]['value']=900;self.save_rule();a,s=self.proposal()
        value,reason=self.assess(a,s);self.assertIsNone(value);self.assertIn('engine_hours',reason)

    def test_target_scope_original_snapshot_and_dirty_session_fail_closed(self):
        self.setup_rule();a,s=self.proposal()
        b=deepcopy(a);b['recommendations'][0]['target']='エアコン'
        self.assertIsNone(self.assess(b,s)[0])
        copied=deepcopy(s);copied[f'part:{self.part.id}']['snapshot']['mileage']=0
        self.assertIsNone(self.assess(a,copied)[0])
        copied=deepcopy(s)
        copied[f'knowledge:{self.knowledge.id}']['snapshot']['maintenance_rule_evidence']['rules'][0]['source_quote']='別の原文'
        self.assertIsNone(self.assess(a,copied)[0])
        self.vehicle.model_code='unsaved'
        self.assertIsNone(self.assess(a,s)[0]);self.m.db.session.rollback()

    def test_verified_inspection_keeps_own_baseline_and_original_scope(self):
        self.setup_rule(action='inspect')
        self.rule['source_quote']='合成試験部品の排出水量と状態確認'
        self.save_rule()
        raw=pdf_bytes(1)
        details={'inspection_date':'2026-01-31','mileage':10000,'source_pages':[1],
            'symbol_legend':'○:点検済み', 'inspection_items':[{'item_name':self.rule['source_quote'],
                'raw_result':'○','source_page':1,'result_text':'','notes':''}]}
        draft=self.m.VehicleDocumentImportDraft(id='22222222-2222-4222-8222-222222222222',
            batch_id='33333333-3333-4333-8333-333333333333',company_code='TEST',
            created_by_username='test',document_type='inspection',source_filename='synthetic-periodic.pdf',
            source_file=raw,source_sha256=hashlib.sha256(raw).hexdigest(),
            preview_json=json.dumps({'records':[details]}),status='confirmed')
        self.m.db.session.add(draft);self.m.db.session.flush()
        row=self.m.VehiclePeriodicInspectionRecord(company_code='TEST',vehicle_record_id=self.vehicle.id,
            inspection_type='合成点検',inspection_date='2026-01-31',mileage=10000,
            details_json=json.dumps(details),source_draft_id=draft.id,source_record_index=0,
            created_by_username='test')
        self.m.db.session.add(row);self.m.db.session.commit()
        a,s=self.proposal();value,reason=self.assess(a,s)
        self.assertIsNone(reason);self.assertEqual(value['effective_score'],35)
        self.assertTrue(any(sid.startswith('periodic:') for sid in value['source_ids']))
        self.assertFalse(any(sid.startswith('part:') for sid in value['source_ids']))
        self.assertEqual(value['timing_criteria'][0]['baseline_kind'],'inspection')
        details['inspection_items'][0]['raw_result']=''
        row.details_json=json.dumps(details);self.m.db.session.commit()
        self.assertIsNone(self.assess(a,s)[0])

    def test_fresh_session_reads_committed_changes_not_loaded_identity(self):
        self.setup_rule();a,s=self.proposal()
        original=self.part.replacement_date
        with self.m.db.engine.begin() as connection:
            connection.execute(self.part.__table__.update().where(self.part.__table__.c.id==self.part.id)
                .values(replacement_date='2026-11-10'))
        self.assertEqual(self.part.replacement_date,original)
        self.assertIsNone(self.assess(a,s)[0])
        self.assertEqual(self.part.replacement_date,original)

    def test_other_vehicle_history_never_affects_same_event(self):
        self.setup_rule();a,s=self.proposal()
        other=self.m.Vehicle(company_code='OTHER',chassis_number='OTHER-TIMING')
        self.m.db.session.add(other);self.m.db.session.flush()
        record=self.m.VehicleMaintenanceRecord(company_code='OTHER',vehicle_record_id=other.id,
            entry_date='2026-11-11',completion_date='2026-11-11',status='完了',mileage=99999)
        self.m.db.session.add(record);self.m.db.session.flush()
        self.m.db.session.add(self.m.VehiclePartReplacement(company_code='OTHER',vehicle_record_id=other.id,
            maintenance_record_id=record.id,part_name=self.part.part_name,replacement_date='2026-11-11',
            mileage=99999,quantity=1,created_at='2026/11/11 00:00'))
        self.m.db.session.commit()
        value,reason=self.assess(a,s);self.assertIsNone(reason);self.assertEqual(value['effective_score'],35)
        b=deepcopy(a);source=deepcopy(s)
        proof=source[f'knowledge:{self.knowledge.id}'][PROOF_KEY][0]
        proof['company_code']='OTHER'
        self.assertIsNone(self.assess(b,source)[0])

    def test_rule_version_change_does_not_reuse_old_offer(self):
        self.setup_rule();a,s=self.proposal()
        self.rule['criteria'][0]['value']=285;self.save_rule()
        self.assertIsNone(self.assess(a,s)[0])

    def test_day_30_boundary_without_90_percent_already_reached(self):
        self.setup_rule(criteria=[{'metric':'period_days','value':100}])
        for remaining,expected in [(31,10),(30,25),(1,25),(0,35)]:
            origin=(DAY-timedelta(days=100-remaining)).isoformat()
            self.parent.entry_date=self.parent.completion_date=origin
            self.part.replacement_date=origin;self.m.db.session.commit()
            a,s=self.proposal();value,reason=self.assess(a,s)
            self.assertIsNone(reason);self.assertEqual(value['effective_score'],expected)

    def test_month_end_uses_calendar_due_date_without_30_day_months(self):
        self.setup_rule(criteria=[{'metric':'period_months','value':10}],origin='2026-01-31')
        a,s=self.proposal();value,reason=self.assess(a,s)
        self.assertIsNone(reason);self.assertEqual(value['earliest_due_on'],'2026-11-30')
        self.assertEqual(value['effective_score'],25)
        self.assertEqual(value['timing_criteria'][0]['due_date'],'2026-11-30')

    def test_projection_leaves_callers_transaction_and_identity_map_untouched(self):
        self.setup_rule();a,s=self.proposal()
        session=self.m.db.session()
        transaction=session.get_transaction()
        with patch.object(session,'commit',side_effect=AssertionError('caller commit forbidden')), \
             patch.object(session,'rollback',side_effect=AssertionError('caller rollback forbidden')):
            value,reason=self.assess(a,s)
        self.assertIsNone(reason);self.assertEqual(value['effective_score'],35)
        self.assertIs(session.get_transaction(),transaction)
        self.assertIs(self.m.db.session(),session)
        self.assertIs(self.m.db.session.get(self.m.Vehicle,self.vehicle.id),self.vehicle)

    def test_current_read_budget_never_scores_partial_history(self):
        self.setup_rule();a,s=self.proposal()
        with patch('dkss_app.priority_timing.MAX_HISTORY_ROWS',2):
            value,reason=self.assess(a,s)
        self.assertIsNone(value);self.assertIn('読取上限',reason)

    def test_queries_are_batched_per_vehicle_not_per_proposal(self):
        self.setup_rule();a,s=self.proposal()
        counts=[]
        for count in (1,4):
            analysis=deepcopy(a)
            analysis['recommendations']=[dict(a['recommendations'][0],proposal_id=f'original-{i}') for i in range(count)]
            statements=[]
            def capture(_c,_cursor,statement,_p,_ctx,_many):statements.append(statement)
            event.listen(self.m.db.engine,'before_cursor_execute',capture)
            try:
                with self.m.app.test_request_context('/'):
                    result=project_registered_timing_priorities(analysis,self.vehicle,s,as_of=DAY,is_current=True)
            finally:event.remove(self.m.db.engine,'before_cursor_execute',capture)
            self.assertEqual(len(result),count)
            self.assertTrue(all(value[0]['effective_score']==35 for value in result.values()))
            counts.append(len(statements))
        self.assertEqual(counts[0],counts[1])
        self.assertLessEqual(counts[0],25)

    def test_long_original_target_uses_only_server_display_name(self):
        self.setup_rule()
        full='合成試験の非常に長い部品名と個別装備の名称を保持した交換対象'
        self.knowledge.part_name=full;self.part.part_name=full
        self.extracted['part_name']=full;self.save_rule()
        a,s=self.proposal()
        self.assertEqual(a['recommendations'][0]['target'],full[:24])
        before=deepcopy((a,s))
        value,reason=self.assess(a,s)
        self.assertIsNone(reason);self.assertEqual(value['effective_score'],35)
        self.assertEqual(value['scope']['target'],full)
        from vehicle_priority_projection import project_priority
        projected=project_priority(a,s,[],company_code=self.vehicle.company_code,
            vehicle_id=self.vehicle.id,as_of=DAY,timing_results={0:(value,None)})
        item=projected['recommendations'][0]
        self.assertEqual(item['priority_assessment']['subject_label'],full)
        self.assertEqual(item['priority_assessment']['effective_score'],35)
        self.assertEqual(item['target'],full[:24])
        self.assertEqual(item['proposal_id'],a['recommendations'][0]['proposal_id'])
        self.assertEqual(item['proposal_revision'],a['recommendations'][0]['proposal_revision'])
        self.assertEqual(item['source_ids'],a['recommendations'][0]['source_ids'])
        self.assertEqual((a,s),before)
        a['recommendations'][0]['target']='エアコン'
        self.assertIsNone(self.assess(a,s)[0])

    def test_monthly_fraction_is_not_defined_by_dividing_actual_days(self):
        self.setup_rule(criteria=[{'metric':'period_months','value':12}],origin='2025-12-17')
        a,s=self.proposal();value,reason=self.assess(a,s)
        self.assertIsNone(value);self.assertIn('暦月90%',reason)
        self.assertGreaterEqual((DAY-date(2025,12,17)).days/365,0.9)
        self.assertEqual((date(2026,12,17)-DAY).days,36)

    def test_no_explicit_reference_means_no_current_reader(self):
        with patch('dkss_app.priority_timing._current_inputs',side_effect=AssertionError('should not read')):
            result=project_registered_timing_priorities({'recommendations':[{'priority':'高'}]},
                self.vehicle,{},as_of=DAY)
        self.assertEqual(result,{})


if __name__ == '__main__':
    unittest.main()
