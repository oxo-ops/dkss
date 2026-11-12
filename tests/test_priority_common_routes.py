"""Scoped ORM -> ordinary GET/dashboard priority integration, disposable SQLite."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import shutil
import subprocess
import unittest
from unittest.mock import patch

from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
import test_workflow_regressions as workflow
from test_priority_common_projection import fixture
from dkss_app.analysis_feedback import vehicle_analysis_proposal_ids
from dkss_app.priority_projection import project_registered_priorities, registered_inspection_provenance


class CommonPriorityRouteTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    base_setup = workflow.WorkflowRegressionTests.setUp
    tearDown = workflow.WorkflowRegressionTests.tearDown

    def setUp(self):
        self.base_setup()
        self.day = datetime.now(ZoneInfo('Asia/Tokyo')).date()
        self.url = f'/vehicle/karte/{self.vehicle.id}/analysis/result'

    def seed_analysis(self, decision=None, label='低', code='daily_02'):
        """Reusable synthetic browser fixture. Returns (state,bundle,inspection)."""
        m = self.m
        analysis, sources, snap = fixture(code, day=self.day, label=label, decision=decision)
        item = analysis['recommendations'][0]
        for key in ('proposal_id', 'proposal_revision', 'feedback'):
            item.pop(key)
        checklist=m.Checklist(company_code='TEST', name='合成日常点検', target='車両管理',
            active=True, items_json=json.dumps(json.loads(snap.checklist_json)['items']))
        m.db.session.add(checklist);m.db.session.flush()
        row=m.VehicleChecklistResult(company_code='TEST',vehicle_record_id=self.vehicle.id,
            checklist_id=checklist.id,year=str(self.day.year),month=str(self.day.month),day=str(self.day.day),
            status=snap.status,checklist_snapshot_json=snap.checklist_json,
            answers_json=snap.answers_json,operation_judgment_json=snap.judgment_json)
        m.db.session.add(row);m.db.session.flush()
        sid=f'inspection:{row.id}';item['source_ids']=[sid]
        sources={sid:{'label':'合成日常点検', 'url':f'/vehicle/checklists/{checklist.id}/results',
                      'priority_provenance':registered_inspection_provenance(self.vehicle,row)}}
        fingerprints={'policy_version':'synthetic', 'important_hash':'synthetic-important', 'routine_hash':'synthetic-routine'}
        bundle=dict(analysis=analysis,sources=sources,fingerprints=fingerprints,coverage={},
            generated_at=self.day.isoformat(),analysis_method='synthetic')
        state=m.VehicleKarteAnalysis(company_code='TEST',vehicle_record_id=self.vehicle.id,
            status='completed',result_json=json.dumps(bundle,ensure_ascii=False))
        m.db.session.add(state);m.db.session.commit()
        return state,bundle,row

    @contextmanager
    def frozen_projection(self,bundle,current=True):
        fingerprints=deepcopy(bundle['fingerprints'])
        if not current:fingerprints['routine_hash']='changed'
        with patch('dkss_app.analysis.get_vehicle_analysis_read_projection',return_value=(
                {'fingerprints':fingerprints,'input_summary':{},'comparison':None},True)):
            yield

    @contextmanager
    def readonly_queries(self):
        statements=[]
        def capture(conn,cursor,statement,parameters,context,executemany):
            if statement.lstrip().split(None,1)[0].upper() in {'INSERT','UPDATE','DELETE','REPLACE','CREATE','ALTER','DROP'}:
                statements.append(statement.split(None,1)[0])
        event.listen(self.m.db.engine,'before_cursor_execute',capture)
        try:yield statements
        finally:event.remove(self.m.db.engine,'before_cursor_execute',capture)

    def original_snapshot(self):
        result={}
        for name in ('VehicleKarteAnalysis','VehicleChecklistResult','VehicleAnalysisFeedback',
                     'VehicleAnalysisEvaluation','Notification','VehicleMaintenanceRecord'):
            model=getattr(self.m,name)
            result[name]=[tuple(getattr(row,c.name) for c in model.__table__.columns)
                          for row in model.query.order_by(model.id).all()]
        return result

    def test_normal_get_computes_without_preview_flags_ai_or_saved_writes(self):
        state,bundle,row=self.seed_analysis()
        before=self.original_snapshot()
        with self.frozen_projection(bundle),self.readonly_queries() as writes, \
                patch('dkss_app.analysis.get_vehicle_karte_analysis_job_data',side_effect=AssertionError('No AI input rebuild')):
            response=self.client.get(self.url)
        self.assertEqual(response.status_code,200)
        value=response.json['analysis']['recommendations'][0]['priority_assessment']
        self.assertEqual((value['label'],value['effective_score']),('中',50))
        self.assertIn('no-store',response.headers['Cache-Control'])
        self.assertEqual(writes,[]);self.assertEqual(self.original_snapshot(),before)
        self.assertEqual(json.loads(state.result_json)['analysis']['recommendations'][0]['priority'],'低')

    def test_normal_input_builder_emits_server_provenance_for_the_get_projection(self):
        state,bundle,row=self.seed_analysis()
        with self.m.app.test_request_context('/'),self.readonly_queries() as writes:
            payload,sources=self.m.get_vehicle_karte_analysis_job_data(self.vehicle)
        sid=f'inspection:{row.id}'
        self.assertEqual(sources[sid]['priority_provenance'],registered_inspection_provenance(self.vehicle,row))
        record=next(v for v in payload['records'] if v['source_id']==sid)
        self.assertEqual(record['findings'][0]['content'],bundle['analysis']['recommendations'][0]['target'])
        self.assertNotIn('priority_provenance',record)  # Source proof is not AI output.
        self.assertEqual(writes,[])
        bundle.update(sources=sources,fingerprints=payload['_fingerprints'])
        state.result_json=json.dumps(bundle,ensure_ascii=False);self.m.db.session.commit()
        before=self.original_snapshot()
        with self.frozen_projection(bundle),self.readonly_queries() as writes:
            value=self.client.get(self.url).json['analysis']['recommendations'][0]['priority_assessment']
        self.assertEqual((value['label'],value['effective_score']),('中',50))
        self.assertEqual(writes,[]);self.assertEqual(self.original_snapshot(),before)

    def test_old_source_and_replaced_event_do_not_receive_a_new_score(self):
        state,bundle,row=self.seed_analysis(label='高')
        sid=f'inspection:{row.id}'
        proof=bundle['sources'][sid].pop('priority_provenance')
        state.result_json=json.dumps(bundle,ensure_ascii=False);self.m.db.session.commit()
        with self.frozen_projection(bundle):value=self.client.get(self.url).json['analysis']['recommendations'][0]['priority_assessment']
        self.assertEqual(value['label'],'高');self.assertIsNone(value['effective_score'])
        bundle['sources'][sid]['priority_provenance']=proof
        state.result_json=json.dumps(bundle,ensure_ascii=False)
        changed=json.loads(row.operation_judgment_json);changed['defects'][0]['defect_no']=2
        row.operation_judgment_json=json.dumps(changed);self.m.db.session.commit()
        with self.frozen_projection(bundle):value=self.client.get(self.url).json['analysis']['recommendations'][0]['priority_assessment']
        self.assertEqual(value['label'],'高');self.assertIsNone(value['effective_score'])

    @unittest.skipUnless(shutil.which('node'),'Node required for the UI contract')
    def test_real_api_envelopes_pass_the_strict_javascript_contract(self):
        state,bundle,row=self.seed_analysis()
        original=bundle['analysis']['recommendations'][0]
        bundle['analysis']['recommendations'] += [dict(original,target='Legacy',priority='高'),
                                                dict(original,target='Invalid',priority='未評価')]
        state.result_json=json.dumps(bundle,ensure_ascii=False);self.m.db.session.commit()
        with self.frozen_projection(bundle):data=self.client.get(self.url).json
        script="""const p=require('./static/js/vehicle_priority_presentation.js');
        const d=JSON.parse(require('fs').readFileSync(0,'utf8')); const a=d.analysis;
        const values=a.recommendations.map(x=>p.read(x));
        if (!values[0].valid || values[0].score!==50 || values[0].label!=='中') process.exit(1);
        if (!values[1].valid || !values[1].legacy || values[1].score!==null) process.exit(2);
        if (values[2].valid || values[2].label!==null) process.exit(3);
        if (JSON.stringify(p.ordered(a.recommendations,a).map(x=>x.proposal_id))!==JSON.stringify(a.priority_order)) process.exit(4);
        """
        subprocess.run([shutil.which('node'),'-e',script],input=json.dumps(data),text=True,check=True)

    def test_original_feedback_revision_and_evaluation_remain_attached_after_projection(self):
        state,bundle,row=self.seed_analysis()
        original=bundle['analysis']['recommendations'][0]
        key,revision=vehicle_analysis_proposal_ids(original)
        m=self.m
        feedback=m.VehicleAnalysisFeedback(company_code='TEST',vehicle_record_id=self.vehicle.id,
            proposal_key=key,proposal_revision=revision,status='accepted',comment='合成確認',
            snapshot_json=json.dumps({'proposal':original}),created_by='admin',created_at=self.day.isoformat())
        evaluation=m.VehicleAnalysisEvaluation(company_code='TEST',vehicle_record_id=self.vehicle.id,
            proposal_key=key,proposal_revision=revision,verdict='appropriate',comment='合成',
            snapshot_json=json.dumps({'proposal':original}),created_by='admin',created_at=self.day.isoformat())
        m.db.session.add_all([feedback,evaluation]);m.db.session.commit()
        before=self.original_snapshot()
        with self.frozen_projection(bundle):data=self.client.get(self.url).json
        item=data['analysis']['recommendations'][0]
        self.assertEqual((item['proposal_id'],item['proposal_revision']),(key,revision))
        self.assertEqual(item['feedback']['revision'],revision)
        self.assertEqual(item['evaluation']['verdict'],'appropriate')
        self.assertEqual(item['priority_assessment']['effective_score'],50)
        self.assertEqual(self.original_snapshot(),before)

    def test_dashboard_and_api_share_assessment_order_and_identity(self):
        state,bundle,row=self.seed_analysis()
        original=bundle['analysis']['recommendations'][0]
        bundle['analysis']['recommendations'] += [dict(original,target='Legacy',title='保存高',priority='高'),
                                                dict(original,target='Other',title='保存中',priority='中')]
        state.result_json=json.dumps(bundle,ensure_ascii=False);self.m.db.session.commit()
        with self.frozen_projection(bundle):data=self.client.get(self.url).json
        with self.m.app.test_request_context('/'),self.readonly_queries() as writes:
            from dkss_app.dashboard import get_dashboard_vehicle_attention
            group=get_dashboard_vehicle_attention('TEST',None,[self.vehicle.id])['mine']
        self.assertEqual([v['proposal_id'] for v in group['items']],data['analysis']['priority_order'])
        values={v['proposal_id']:v for v in data['analysis']['recommendations']}
        for item in group['items']:
            self.assertEqual(item['priority_assessment']['label'],values[item['proposal_id']]['priority_assessment']['label'])
            self.assertEqual(item['priority_assessment']['effective_score'],values[item['proposal_id']]['priority_assessment']['effective_score'])
        self.assertEqual(writes,[])

    def test_foreign_company_vehicle_or_missing_citation_never_scores(self):
        state,bundle,row=self.seed_analysis(label='高')
        row.company_code='OTHER';self.m.db.session.commit()
        with self.frozen_projection(bundle):item=self.client.get(self.url).json['analysis']['recommendations'][0]
        self.assertEqual(item['priority'],'高')
        self.assertIsNone(item['priority_assessment']['effective_score'])
        other=self.m.Vehicle(company_code='OTHER',chassis_number='OTHER');self.m.db.session.add(other);self.m.db.session.commit()
        self.assertEqual(self.client.get(f'/vehicle/karte/{other.id}/analysis/result').status_code,404)

    def test_dirty_session_is_not_flushed_or_used_to_reclassify(self):
        state,bundle,row=self.seed_analysis(label='高')
        decorated=self.m.analysis_with_vehicle_feedback(bundle['analysis'],self.vehicle)
        row.status='pending'
        with self.readonly_queries() as writes:
            result=project_registered_priorities(decorated,self.vehicle,bundle['sources'],as_of=self.day)
        self.assertEqual(result['recommendations'][0]['priority'],'高')
        self.assertIsNone(result['recommendations'][0]['priority_assessment']['effective_score'])
        self.assertEqual(writes,[])
        self.m.db.session.rollback()

    def test_external_committed_change_is_read_instead_of_stale_orm_object(self):
        state,bundle,row=self.seed_analysis()
        decorated=self.m.analysis_with_vehicle_feedback(bundle['analysis'],self.vehicle)
        judgment=json.loads(row.operation_judgment_json);judgment['defects'][0]['status']='解消'
        with self.m.db.engine.begin() as conn:
            conn.execute(text('UPDATE vehicle_checklist_result SET operation_judgment_json=:j WHERE id=:i'),
                         {'j':json.dumps(judgment),'i':row.id})
        self.assertEqual(json.loads(row.operation_judgment_json)['defects'][0]['status'],'対応待ち')
        result=project_registered_priorities(decorated,self.vehicle,bundle['sources'],as_of=self.day)
        self.assertIsNone(result['recommendations'][0]['priority_assessment']['effective_score'])

    def test_stale_saved_analysis_preserves_state_and_does_not_erase_current_safety_floor(self):
        state,bundle,row=self.seed_analysis()
        for status in ('pending','running','error'):
            state.status=status;self.m.db.session.commit()
            with self.frozen_projection(bundle,current=False):data=self.client.get(self.url).json
            self.assertEqual(data['status'],status);self.assertFalse(data['is_current'])
            value=data['analysis']['recommendations'][0]['priority_assessment']
            self.assertEqual(value['label'],'中');self.assertEqual(value['effective_score'],50)
            self.assertTrue(any('最新性' in x for x in value['missing_conditions']))

    def test_query_failure_keeps_saved_high_without_exception_text(self):
        state,bundle,row=self.seed_analysis(label='高')
        decorated=self.m.analysis_with_vehicle_feedback(bundle['analysis'],self.vehicle)
        with patch.object(self.m.db.session,'query',side_effect=OperationalError('SECRET_SQL',{},Exception('secret'))):
            result=project_registered_priorities(decorated,self.vehicle,bundle['sources'],as_of=self.day)
        value=result['recommendations'][0]['priority_assessment']
        self.assertEqual(value['label'],'高');self.assertIsNone(value['effective_score'])
        self.assertNotIn('SECRET',json.dumps(value))

    def test_bad_numeric_source_ids_never_reach_integer_db_binding(self):
        state,bundle,row=self.seed_analysis(label='高')
        for suffix in ('²','9223372036854775808','9'*4400,'0','-1','2147483648'):
            sid='inspection:'+suffix
            changed=deepcopy(bundle);changed['analysis']['recommendations'][0]['source_ids']=[sid]
            changed['sources']={sid:{'label':'invalid','url':'/source'}}
            decorated=self.m.analysis_with_vehicle_feedback(changed['analysis'],self.vehicle)
            with self.readonly_queries() as writes:
                result=project_registered_priorities(decorated,self.vehicle,changed['sources'],as_of=self.day)
            value=result['recommendations'][0]['priority_assessment']
            self.assertEqual(value['label'],'高');self.assertIsNone(value['effective_score']);self.assertEqual(writes,[])

    def test_recorded_past_stop_and_malformed_history_withhold_new_score(self):
        state,bundle,row=self.seed_analysis(label='高')
        m=self.m
        history=m.ChecklistEvent(company_code='TEST',result_type='vehicle',result_id=row.id,
            event_type='運行判断',created_at=self.day.isoformat(),
            detail_json=json.dumps({'previous_judgment':{'status':'運行不可'},'judgment':{'status':'運行可'}}))
        m.db.session.add(history);m.db.session.commit()
        for detail in (history.detail_json,'not-json',json.dumps({'judgment':[]})):
            history.detail_json=detail;m.db.session.commit()
            with self.frozen_projection(bundle):value=self.client.get(self.url).json['analysis']['recommendations'][0]['priority_assessment']
            self.assertEqual(value['label'],'高');self.assertIsNone(value['effective_score'])

    def test_foreign_or_other_result_history_cannot_contaminate_bound_event(self):
        state,bundle,row=self.seed_analysis()
        m=self.m
        for company,kind,result in [('OTHER','vehicle',row.id),('TEST','worker',row.id),('TEST','vehicle',row.id+100)]:
            m.db.session.add(m.ChecklistEvent(company_code=company,result_type=kind,result_id=result,
                event_type='運行判断',created_at=self.day.isoformat(),
                detail_json=json.dumps({'judgment':{'status':'運行不可'}})))
        m.db.session.commit()
        with self.frozen_projection(bundle):value=self.client.get(self.url).json['analysis']['recommendations'][0]['priority_assessment']
        self.assertEqual(value['effective_score'],50)

    def test_default_off_synthetic_preview_guard_stays_intact(self):
        self.seed_analysis()
        self.assertEqual(self.client.get(self.url+'?priority_preview=1').status_code,404)

if __name__=='__main__':unittest.main()
