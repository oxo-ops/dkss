"""AI proposal boundary: no entry workflow, evidence-grounded priority, preserved actual facts."""
import json
import unittest
from datetime import timedelta
from unittest.mock import patch
import vehicle_periodic_followups as proposals
from test_inspection_plans import InspectionPlanTests as _Base


def answer(priority='高', refs=None, title='制動装置の状態確認'):
    return {'priority':priority,'category':'整備・点検','target':'制動装置','current_state':'原本の記載を確認',
        'timing':'次の整備時に確認','title':title,'reason':'原本の記載と整備状況を照合するため',
        'action':'整備後の状態を確認','confirmation_steps':['原本と実車を照合'],
        'confirmation_branch':'異常が残れば担当者が判断','uncertainty':'現在の実車状態は未確認',
        'basis_type':'AIの一般知識','knowledge_ids':[],'source_ids':refs or ['periodic:1']}


class PeriodicFollowupTests(unittest.TestCase):
    setUpClass = classmethod(_Base.setUpClass.__func__)
    tearDownClass = classmethod(_Base.tearDownClass.__func__)
    tearDown = _Base.tearDown
    upload_inspection = _Base.upload_inspection
    inspection_form = _Base.inspection_form
    import_record = _Base.import_record

    def setUp(self):
        _base_setup(self)
        self.record = self.import_record()
        self.url = f'/vehicle/karte/{self.vehicle.id}/periodic/{self.record.id}/followup'
        self.api = self.url.replace('/followup','/suggestions')
        self.service = self.m.periodic_followups
        self.Proposal = self.service.Proposal
        self.executor = self.m.app.extensions['periodic_proposal_executor']

    def input(self):
        with self.m.app.test_request_context('/'):
            return self.service.proposal_input(self.vehicle,self.record)

    def cached(self, result=None, status='completed'):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        payload, _, digest = self.input()
        row=self.Proposal(company_code='TEST',inspection_record_id=self.record.id,input_hash=digest,run_token='test-token',status=status,
            result_json=json.dumps(result or {'overview':'点検簿を確認しました。','recommendations':[answer()]}),updated_at=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(timespec='seconds'))
        self.m.db.session.add(row);self.m.db.session.commit()
        return row

    def test_page_has_no_checkboxes_textareas_or_actual_registration_form(self):
        html=self.client.get(self.url).get_data(as_text=True)
        # Existing header dialogs are outside the proposal workspace.
        workspace=html.split('<div class="pf-workspace"',1)[1].split('</div>\n<script',1)[0]
        self.assertNotIn('<textarea',workspace);self.assertNotIn('type="checkbox"',workspace)
        self.assertNotIn('<form',workspace);self.assertIn('優先度：高 → 中 → 低',workspace)
        self.assertNotIn('手入力は不要',workspace)
        self.assertNotIn('data-proposal-overview',workspace)
        self.assertNotIn('提案は未解消件数や整備記録へ自動登録しません',workspace)
        self.assertIn('data-proposal-order style="display:none"',workspace)

    def test_legacy_mutation_endpoints_are_rejected_without_writes(self):
        for action in ['register','repair','recheck','cancel']:
            response=self.client.post(self.url,data={'action':action,'item_key':'0','description_0':'入力しない'})
            self.assertEqual(response.status_code,410)
        self.assertEqual(self.service.Issue.query.count(),0)
        self.assertEqual(self.m.VehicleMaintenanceRecord.query.count(),0)
        self.assertEqual(self.m.Notification.query.count(),0)

    def test_proposal_input_preserves_raw_items_legend_and_unknowns(self):
        payload,evidence,_=self.input()
        row=next(r for r in payload['records'] if r['source_id']=='periodic:1')
        self.assertIn('×：交換',row['symbol_legend'])
        self.assertEqual(row['inspection_items'][0]['raw_result'],'○')
        self.assertEqual(row['inspection_items'][0]['source_page'],1)
        self.assertIn('空欄は未実施・不良ではない',payload['analysis_focus'])
        self.assertIn('periodic:1',evidence)

    def test_priority_is_sorted_high_medium_low_without_changing_actuals(self):
        payload,_,_=self.input()
        with patch('vehicle_karte_analysis_ai.analyze_vehicle_karte',return_value={'overview':'候補', 'recommendations':[answer('低'),answer('高'),answer('中')]}):
            result=proposals.generate_periodic_proposals(payload)
        self.assertEqual([x['priority'] for x in result['recommendations']],['高','中','低'])
        self.assertEqual(self.service.Issue.query.count(),0)
        self.assertEqual(self.m.Notification.query.count(),0)

    def test_vehicle_wide_proposals_are_retained_and_foreign_evidence_rejected(self):
        payload,_,_=self.input()
        payload['records'].append({'source_id':'maintenance:2'})
        with patch('vehicle_karte_analysis_ai.analyze_vehicle_karte',return_value={'overview':'候補','recommendations':[answer(refs=['maintenance:2'])]}):
            self.assertEqual(len(proposals.generate_periodic_proposals(payload)['recommendations']),1)
        with patch('vehicle_karte_analysis_ai.analyze_vehicle_karte',return_value={'overview':'候補','recommendations':[answer(refs=['periodic:999'])]}):
            with self.assertRaises(ValueError):proposals.generate_periodic_proposals(payload)

    def test_later_repairs_and_inspections_are_available_for_resolution_check(self):
        row=self.m.VehicleMaintenanceRecord(company_code='TEST',vehicle_record_id=self.vehicle.id,content='整備を実施',repair_content='調整済み',status='完了',completion_date='2026-10-21')
        self.m.db.session.add(row);self.m.db.session.commit()
        self.import_record('2026-10-12','2027-01')
        payload,_,_=self.input()
        self.assertEqual(len(payload['records']),3)
        self.assertTrue(any(r.get('repair_content')=='調整済み' for r in payload['records']))
        self.assertEqual(payload['focus_source_ids'],['periodic:1'])

    def daily(self, vehicle=None):
        m = self.m
        checklist = m.Checklist(company_code='TEST', name='日常点検', target='車両管理', active=True, items_json='[]')
        m.db.session.add(checklist); m.db.session.flush()
        row = m.VehicleChecklistResult(company_code='TEST', checklist_id=checklist.id,
            vehicle_record_id=(vehicle or self.vehicle).id, year='2026', month='10', day='01', status='承認済み',
            answers_json=json.dumps([{'item_no':'0','content':'ブレーキ','value':'×','comment':'異音'}]),
            checklist_snapshot_json=json.dumps({'name':'日常点検','items':[]}),
            operation_judgment_json=json.dumps({'status':'判定保留','defects':[{'defect_no':1,'item_no':'0','status':'再確認待ち',
                'repair':{'note':'調整実施','performed_at':'2026-10-02'},'recheck':{'result':'未解消','note':'異音継続'}}]}))
        m.db.session.add(row); m.db.session.commit()
        return row

    def test_daily_findings_repair_and_recheck_are_used_and_daily_only_proposal_is_kept(self):
        daily = self.daily()
        payload, evidence, _ = self.input()
        source = 'inspection:' + str(daily.id)
        row = next(row for row in payload['records'] if row['source_id'] == source)
        self.assertEqual(row['findings'][0]['comment'], '異音')
        self.assertEqual(row['treatments'][0]['repair_note'], '調整実施')
        self.assertEqual(row['treatments'][0]['recheck_result'], '未解消')
        self.assertIn(source, evidence)
        with patch('vehicle_karte_analysis_ai.analyze_vehicle_karte', return_value={'overview':'内部注記','recommendations':[answer(refs=[source])]}):
            self.assertEqual(len(proposals.generate_periodic_proposals(payload)['recommendations']), 1)

    def test_daily_change_invalidates_cache_and_other_vehicles_are_excluded(self):
        daily = self.daily(); self.cached()
        daily.operation_judgment_json = json.dumps({'status':'運行可能','defects':[{'defect_no':1,'status':'解消','recheck':{'result':'解消'}}]})
        self.m.db.session.commit()
        self.assertEqual(self.client.get(self.api).json['status'], 'missing')
        other = self.m.Vehicle(company_code='TEST', chassis_number='OTHER-DAILY')
        self.m.db.session.add(other); self.m.db.session.commit()
        foreign_daily = self.daily(other)
        payload, evidence, _ = self.input()
        source = 'inspection:' + str(foreign_daily.id)
        self.assertNotIn(source, evidence)
        self.assertNotIn(source, [row['source_id'] for row in payload['records']])

    def test_shared_analysis_keeps_mileage_preventive_facts_and_knowledge_context(self):
        with self.m.app.test_request_context('/'):
            shared, sources = self.m.get_vehicle_karte_analysis_job_data(self.vehicle)
        payload, _, _ = self.input()
        for key in ['vehicle','summary','comparison','preventive_facts','maintenance_knowledge','feedback_context']:
            self.assertEqual(payload[key], shared[key], key)
        payload['maintenance_knowledge'] = [{'source_id':'knowledge:7'}]
        payload['preventive_facts'] = {'part_replacements':[{'source_ids':['part:8']}]}
        with patch('vehicle_karte_analysis_ai.analyze_vehicle_karte', return_value={'recommendations':[answer(refs=['knowledge:7','part:8'])]}):
            self.assertEqual(len(proposals.generate_periodic_proposals(payload)['recommendations']),1)

    def test_opening_page_or_getting_status_does_not_start_paid_generation(self):
        with patch.object(self.executor,'submit') as submit:
            self.client.get(self.url)
            result=self.client.get(self.api)
            self.assertEqual(result.json['status'],'missing');submit.assert_not_called()
        self.assertEqual(self.Proposal.query.count(),0)

    def test_automatic_start_and_repeated_requests_create_one_job(self):
        with patch.object(self.executor,'submit') as submit:
            self.assertEqual(self.client.post(self.api,json={}).status_code,202)
            self.assertEqual(self.client.post(self.api,json={}).json['status'],'running')
            self.assertEqual(submit.call_count,1)
        self.assertEqual(self.Proposal.query.count(),1)

    def test_cache_is_reused_without_new_ai_call(self):
        self.cached()
        with patch.object(self.executor,'submit') as submit:
            response=self.client.post(self.api,json={})
            self.assertEqual(response.json['status'],'completed');submit.assert_not_called()
        self.assertEqual(self.client.get(self.api).json['result']['recommendations'][0]['priority'],'高')

    def test_source_or_later_maintenance_change_invalidates_cache(self):
        self.cached()
        self.record.content='原本の確認内容を修正';self.m.db.session.commit()
        self.assertEqual(self.client.get(self.api).json['status'],'missing')
        with patch.object(self.executor,'submit') as submit:
            self.assertEqual(self.client.post(self.api,json={}).status_code,202)
            self.assertEqual(submit.call_count,1)

    def test_worker_saves_only_proposal_and_no_issue_cost_or_notice(self):
        job=self.cached(status='running');payload,_,_=self.input()
        with patch.object(proposals,'generate_periodic_proposals',return_value={'overview':'候補','recommendations':[answer()]}):
            self.service.worker('TEST',self.record.id,job.run_token,payload)
        self.m.db.session.expire_all()
        self.assertEqual(job.status,'completed')
        self.assertEqual(self.m.VehicleMaintenanceRecord.query.count(),0)
        self.assertEqual(self.m.VehiclePartReplacement.query.count(),0)
        self.assertEqual(self.service.Issue.query.count(),0)
        self.assertEqual(self.m.Notification.query.count(),0)

    def test_missing_api_key_does_not_fabricate_proposals(self):
        job=self.cached(status='running');payload,_,_=self.input()
        with patch.object(proposals,'generate_periodic_proposals',side_effect=ValueError('API_KEY_NOT_SET')):
            self.service.worker('TEST',self.record.id,job.run_token,payload)
        self.m.db.session.expire_all()
        self.assertEqual((job.status,job.error),('error','not_configured'))
        self.assertEqual(json.loads(job.result_json),{})

    def test_old_worker_cannot_overwrite_new_run(self):
        job=self.cached(status='running');payload,_,_=self.input()
        with patch.object(proposals,'generate_periodic_proposals',return_value={'overview':'古い候補','recommendations':[]}):
            self.service.worker('TEST',self.record.id,'old-token',payload)
        self.m.db.session.expire_all();self.assertEqual(job.status,'running')

    def test_error_reopens_do_not_repeat_paid_requests_unless_explicitly_retried(self):
        job=self.cached(status='error');job.error='generation_failed';self.m.db.session.commit()
        with patch.object(self.executor,'submit') as submit:
            self.assertEqual(self.client.post(self.api,json={}).json['status'],'error');submit.assert_not_called()
            self.assertEqual(self.client.post(self.api,json={'retry':True}).status_code,202)
            self.assertEqual(submit.call_count,1)

    def test_company_vehicle_scope_and_role_protect_generation(self):
        other=self.m.Vehicle(company_code='TEST',chassis_number='SECOND');self.m.db.session.add(other);self.m.db.session.commit()
        self.assertEqual(self.client.get(self.api.replace(f'/karte/{self.vehicle.id}/',f'/karte/{other.id}/')).status_code,404)
        self.m.User.query.filter_by(username='admin').one().role='user';self.m.db.session.commit()
        self.assertEqual(self.client.post(self.api,json={}).status_code,403)
        self.assertEqual(self.client.get(self.url).status_code,200)
        self.assertEqual(self.Proposal.query.count(),0)

    def test_other_company_cannot_read_cached_evidence(self):
        self.cached()
        with self.client.session_transaction() as session:session['company_code']='FOREIGN'
        response=self.client.get(self.api)
        self.assertNotEqual(response.status_code,200)
        self.assertNotIn('制動装置',response.get_data(as_text=True))

    def test_existing_human_registered_fact_is_readonly_and_keeps_header_count(self):
        issue=self.service.Issue(company_code='TEST',vehicle_record_id=self.vehicle.id,inspection_record_id=self.record.id,item_key='0',evidence_json='{}',description='保存済みの指摘',status='再確認待ち',version=1,created_by='admin',created_at='2026-10-21T10:00:00+09:00')
        self.m.db.session.add(issue);self.m.db.session.commit()
        html=self.client.get(self.url).get_data(as_text=True)
        self.assertIn('登録済みの対応履歴 1件',html)
        self.assertIn('保存済みの指摘',html)
        self.assertNotIn('再確認結果を保存',html)
        self.assertEqual(self.service.summary('TEST',self.vehicle.id)['open_count'],1)

    def test_completed_empty_analysis_is_distinct_from_not_generated(self):
        self.cached({'overview':'追加候補なし','recommendations':[]})
        result=self.client.get(self.api).json
        self.assertEqual(result['status'],'completed');self.assertEqual(result['result']['recommendations'],[])

    def test_inspection_list_link_is_labeled_ai_proposals(self):
        response=self.client.get(f'/vehicle/karte/{self.vehicle.id}/inspections?inspection_view=periodic')
        self.assertIn('>AI提案</a>',response.get_data(as_text=True))


_base_setup=_Base.setUp
del _Base
