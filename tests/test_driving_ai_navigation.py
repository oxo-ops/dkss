"""Grounded office findings and local action targets obey the active filters."""
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs
from driving_report_reflection import build_evidence,validate_result
from driving_report_data import payload
from dkss_app.models import DrivingReportReflection
import test_driving_workspace as workspace_tests


class AiNavigationTests(unittest.TestCase):
    setUpClass=classmethod(workspace_tests.WorkspaceTests.setUpClass.__func__)
    tearDownClass=classmethod(workspace_tests.WorkspaceTests.tearDownClass.__func__)
    setUp=workspace_tests.WorkspaceTests.setUp
    tearDown=workspace_tests.WorkspaceTests.tearDown
    save=workspace_tests.WorkspaceTests.save
    render=workspace_tests.WorkspaceTests.render

    def generate_for(self,url,kind):
        _,context=self.render(url)
        executor=self.m.app.extensions['driving_reflection_executor']
        with patch.dict('os.environ',{'OPENAI_API_KEY':'test-only'}),patch.object(executor,'submit') as submit:
            response=self.client.post('/safety/driving-reports/reflection',data=dict(context['filters'],input_key=context['reflection']['key']))
            self.assertEqual(response.status_code,202)
            work,*args=submit.call_args.args;document=args[-1]
        item=next(e for e in document['evidence'] if e['kind']==kind)
        with patch('driving_report_reflection.generate',return_value={'items':[{'evidence_id':item['id'],'action':item['allowed_actions'][0],'url':'https://invalid.example/','finding':'架空の数値'}]}):
            with ThreadPoolExecutor(max_workers=1) as worker:worker.submit(work,*args).result(timeout=10)
        self.m.db.session.expire_all()
        response,context=self.render(url)
        self.assertEqual(context['reflection']['status'],'completed')
        from test_driving_analysis_navigation import Tree
        tree=Tree(response.get_data(as_text=True))
        actions=[n for n in tree.nodes if n['tag']=='a' and 'data-analysis-destination' in n['attrs']]
        self.assertTrue(actions)
        for action in actions:
            self.assertFalse(any(p['tag']=='details' for p in action['parents']))
            self.assertIn('btn',action['attrs'].get('class','').split())
        return response,context,document

    def test_company_office_finding_links_to_scoped_office_then_person(self):
        self.vehicle.manufacturer='日野';self.m.db.session.commit()
        from driving_report_insights import digest
        query='period=custom&start=2026-10-01&end=2026-10-26&compare=custom&compare_start=2026-06-01&compare_end=2026-06-07&scope=company&vehicle_make='+digest(['vehicle_make','日野'])
        response,context,document=self.generate_for('/safety/driving-reports?'+query,'office')
        item=context['reflection']['items'][0]
        self.assertEqual(item['kind'],'office');self.assertIn('指標取得',item['finding'])
        link=item['links'][0];target=urlsplit(link['url']);args=parse_qs(target.query)
        self.assertEqual(args['scope'],['office']);self.assertEqual(args['compare_start'],['2026-06-01'])
        self.assertEqual(args['vehicle_make'],[digest(['vehicle_make','日野'])])
        self.assertEqual(target.fragment,'')
        self.assertEqual(args['panel'],['analysis'])
        page,next_context=self.render(link['url'])
        self.assertEqual(next_context['total'],1)
        for evidence in document['evidence']:
            self.assertNotIn(self.secret.id,evidence['reports'])
        html=response.get_data(as_text=True)
        self.assertIn('この営業所を確認',html);self.assertNotIn('invalid.example',html);self.assertNotIn('架空の数値',html)

    def test_office_and_person_scope_never_add_other_office_candidates(self):
        _,context=self.render(self.base)
        self.assertNotIn('office',[e['kind'] for e in build_evidence(context['insights'],[],[])])
        response,context,_=self.generate_for(self.base,'record')
        item=context['reflection']['items'][0];link=item['links'][0]
        _,focused=self.render(link['url'])
        self.assertEqual(focused['total'],1)
        self.assertEqual(urlsplit(link['url']).fragment,'')
        self.assertEqual(parse_qs(urlsplit(link['url']).query)['panel'],['analysis'])
        self.assertEqual(focused['insights']['selected_driver']['name'],'乗務員A')
        self.assertNotIn('小山の人',str(context['reflection']))

    def test_next_actions_are_visible_without_opening_evidence(self):
        from test_driving_analysis_navigation import Tree
        from dkss_app import driving_access
        from flask import session
        with self.m.app.test_request_context():
            session.update(company_code='TEST',username='admin',role='admin')
            driving_access.assign([self.a],'admin','admin');self.m.db.session.commit()
        for scope,kind in [('company','office'),('office','scope'),('self','record')]:
            with self.subTest(scope=scope):
                response,context,_=self.generate_for(self.base+'&scope='+scope,kind)
                tree=Tree(response.get_data(as_text=True))
                actions=[n for n in tree.nodes if n['tag']=='a' and any(
                    'driving-reflection-links' in p['attrs'].get('class','').split() for p in n['parents'])]
                self.assertTrue(actions)
                for action in actions:
                    self.assertFalse(any(p['tag']=='details' or 'hidden' in p['attrs'] for p in action['parents']))
                    self.assertIn('btn',action['attrs'].get('class','').split())
                self.assertIn('次の行動と確認',response.get_data(as_text=True))
                self.assertTrue(context['reflection']['items'][0]['report_links'])

    def test_cached_urls_and_targets_are_rebuilt_from_current_evidence(self):
        _,context,_=self.generate_for(self.base,'scope')
        cached=DrivingReportReflection.query.filter_by(cache_key=context['reflection']['key']).one()
        saved=json.loads(cached.result_json);saved['items'][0].update(office_key='forged',vehicle_id=999999,links=[{'url':'https://invalid.example','label':'不正リンク'}],reports=[self.secret.id])
        cached.result_json=json.dumps(saved);self.m.db.session.commit()
        response,context=self.render(self.base)
        text=response.get_data(as_text=True)
        self.assertNotIn('不正リンク',text);self.assertNotIn('invalid.example',text)
        self.assertNotIn(self.secret.id,context['reflection']['items'][0]['reports'])
        self.assertNotIn('vehicle_id',context['reflection']['items'][0])

    def test_due_finding_opens_review_and_preserves_comparison_filters(self):
        data=payload(self.a);data['review']={'state':'followup','next_date':'2020-01-01','action':'早めの減速を振り返る'}
        self.a.details_json=json.dumps(data);self.m.db.session.commit()
        _,context,_=self.generate_for(self.base+'&followup_due=due','followup_due')
        links=context['reflection']['items'][0]['links']
        self.assertEqual([link['label'] for link in links],['振り返りを記録','前後の記録を比較'])
        self.assertEqual(self.client.get(links[0]['url']).status_code,200)
        _,focused=self.render(links[1]['url']);self.assertEqual(focused['total'],1)
        self.assertEqual(focused['filters']['followup_due'],'due')
        from test_driving_analysis_navigation import Tree
        shown=Tree(self.client.get(self.base+'&followup_due=due').get_data(as_text=True))
        next_date=next(n for n in shown.nodes if 'driving-followup-date' in n['attrs'].get('class','').split())
        self.assertFalse(any(p['tag']=='details' for p in next_date['parents']))

    def test_user_actions_and_sources_remain_within_confirmed_own_reports(self):
        self.m.db.session.add(self.m.User(company_code='TEST',username='one',role='user',password='unused',last_name='本人',password_changed_at='stamp'))
        self.m.db.session.commit()
        from dkss_app import driving_access
        from flask import session
        with self.m.app.test_request_context():
            session.update(company_code='TEST',username='admin',role='admin')
            driving_access.assign([self.a],'one','admin');self.m.db.session.commit()
        with self.client.session_transaction() as state:state.update(username='one',role='user',password_changed_at='stamp')
        response,context,document=self.generate_for(self.base+'&scope=company','record')
        self.assertFalse(any(e['kind']=='office' or e.get('vehicle_id') for e in document['evidence']))
        item=context['reflection']['items'][0];self.assertEqual(item['links'][0]['label'],'自分の記録を確認')
        self.assertEqual(self.client.get(item['links'][0]['url']).status_code,200)
        self.assertEqual(len(item['report_links']),1)
        self.assertEqual(item['report_links'][0]['label'],'2026-10-10の日報')
        self.assertEqual(self.client.get(item['report_links'][0]['url']).status_code,200)
        self.assertNotIn('小山の人',response.get_data(as_text=True))

    def test_person_finding_opens_its_source_instead_of_reopening_same_person(self):
        from driving_report_insights import driver_keys
        key=driver_keys([self.a])[0][self.a.id]
        _,context,_=self.generate_for(self.base+'&focus='+key,'record')
        item=context['reflection']['items'][0]
        self.assertEqual([link['label'] for link in item['links']],['対象日報を確認'])
        self.assertEqual(item['links'][0]['url'],item['report_links'][0]['url'])
        self.assertEqual(self.client.get(item['links'][0]['url']).status_code,200)

    def test_finding_without_a_specialized_action_offers_its_authorized_source(self):
        from flask import render_template
        from test_driving_analysis_navigation import Tree
        _,context,_=self.generate_for(self.base,'record')
        item=dict(context['reflection']['items'][0],links=[])
        reflection=dict(context['reflection'],items=[item])
        with self.m.app.test_request_context():
            html=render_template('driving_workspace_reflection.html',reflection=reflection,
                insights=context['insights'],filter_query=context['filter_query'],driving_is_admin=True)
        actions=[n for n in Tree(html).nodes if n['tag']=='a' and 'data-analysis-destination' in n['attrs']]
        self.assertEqual(len(actions),1)
        self.assertEqual(actions[0]['attrs']['href'],item['report_links'][0]['url'])
        self.assertFalse(any(p['tag']=='details' for p in actions[0]['parents']))

    def test_maintenance_and_cost_findings_use_different_vehicle_destinations(self):
        self.m.db.session.add(self.m.VehicleMaintenanceRecord(company_code='TEST',vehicle_record_id=self.vehicle.id,
            entry_date='2026-10-01',completion_date='2026-10-02',status='完了',content='クラッチ交換',mileage=1000,total_cost=50000))
        self.m.db.session.commit()
        from driving_report_insights import driver_keys
        key=driver_keys([self.a])[0][self.a.id]
        url=self.base+'&focus='+key
        _,context,_=self.generate_for(url,'maintenance')
        item=context['reflection']['items'][0]
        self.assertEqual(item['vehicle_id'],self.vehicle.id)
        self.assertEqual([link['label'] for link in item['links']],['車両の分析を確認','部品・交換履歴を確認'])
        _,context,document=self.generate_for(url+'&breakdown=vehicles','maintenance_cost')
        item=context['reflection']['items'][0]
        self.assertEqual([link['label'] for link in item['links']],['車両の費用を確認'])


if __name__=='__main__':unittest.main()
