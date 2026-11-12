"""Normal HTTP inspection entry, completion and authority review -> priority GET.

Only account/vehicle fixtures are seeded. No synthetic version-one inspection,
AI, live service or external notification is used.
"""
import json
import unittest
from unittest.mock import patch
import test_q02_daily_inspection_flow as daily_flow


class CommonPriorityWorkflowTests(unittest.TestCase):
    setUpClass=classmethod(daily_flow.Q02DailyInspectionFlowTests.setUpClass.__func__)
    tearDownClass=classmethod(daily_flow.Q02DailyInspectionFlowTests.tearDownClass.__func__)
    setUp=daily_flow.Q02DailyInspectionFlowTests.setUp
    tearDown=daily_flow.Q02DailyInspectionFlowTests.tearDown
    login=daily_flow.Q02DailyInspectionFlowTests.login
    request=daily_flow.Q02DailyInspectionFlowTests.request
    save=daily_flow.Q02DailyInspectionFlowTests.save
    selection_proof=daily_flow.Q02DailyInspectionFlowTests.selection_proof
    complete=daily_flow.Q02DailyInspectionFlowTests.complete
    state=daily_flow.Q02DailyInspectionFlowTests.state
    decision_data=daily_flow.Q02DailyInspectionFlowTests.decision_data
    decide=daily_flow.Q02DailyInspectionFlowTests.decide
    snapshot=daily_flow.Q02DailyInspectionFlowTests.snapshot

    def test_http_standard_answers_complete_and_review_drive_normal_score_50(self):
        self.login('checker')
        self.assertIn(self.request('GET','/vehicle/checklists').status_code,(200,302))
        self.checklist=self.models.Checklist.query.filter_by(company_code='A').one()
        fields=json.loads(self.checklist.items_json)
        self.check_count=sum(v['item_type']=='check' for v in fields)
        vehicle=self.models.Vehicle.query.filter_by(company_code='A').one()
        self.form={'vehicle_record_id':vehicle.id,'year':'2026','month':'10','day':'23'}
        for no in range(self.check_count):
            self.save(no,'×' if no==1 else '✓')
        self.row=self.models.VehicleChecklistResult.query.one()
        self.complete()
        self.decide('運行可')  # Existing human operation decision, never made by priority.
        self.assertGreater(self.state()['version'],27)
        self.assertEqual(self.row.status,'承認済み')
        vehicle=self.models.Vehicle.query.filter_by(company_code='A',id=self.row.vehicle_record_id).one()
        from dkss_app.analysis import get_vehicle_karte_analysis_job_data
        with self.app.test_request_context('/'):
            payload,sources=get_vehicle_karte_analysis_job_data(vehicle)
        sid=f'inspection:{self.row.id}'
        record=next(v for v in payload['records'] if v['source_id']==sid)
        target=next(v['content'] for v in record['findings'] if str(v['item_no'])=='1')
        self.assertLessEqual(len(target),24)
        proposal=dict(priority='低',category='整備・点検',target=target,title='日常点検の確認',
            current_state='登録された指摘',action='実車と記録を確認',source_ids=[sid])
        bundle=dict(analysis={'recommendations':[proposal]},sources=sources,fingerprints=payload['_fingerprints'])
        state=self.models.VehicleKarteAnalysis(company_code='A',vehicle_record_id=vehicle.id,status='completed',
            result_json=json.dumps(bundle,ensure_ascii=False))
        self.db.session.add(state);self.db.session.commit()
        before=self.snapshot();original=state.result_json
        with patch('dkss_app.analysis.get_vehicle_analysis_read_projection',return_value=(
                {'fingerprints':payload['_fingerprints'],'input_summary':{},'comparison':None},True)):
            response=self.client.get(f'/vehicle/karte/{vehicle.id}/analysis/result')
        self.assertEqual(response.status_code,200)
        item=response.json['analysis']['recommendations'][0]
        self.assertEqual((item['priority'],item['priority_assessment']['effective_score']),('中',50))
        self.assertEqual([f['points'] for f in item['priority_assessment']['factors']],[40,None,10])
        self.assertEqual(self.snapshot(),before);self.assertEqual(state.result_json,original)
        self.assertEqual(self.state()['status'],'運行可')

if __name__=='__main__':unittest.main()
