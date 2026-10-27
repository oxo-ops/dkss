"""Real navigation, provenance and role isolation in the redesigned workspace."""
import json
import unittest
from urllib.parse import urlencode
from driving_report_presentation import enrich, finding
from driving_report_insights import driver_keys
import test_driving_workspace as workspace_tests


class WorkspaceUITests(unittest.TestCase):
    setUpClass=classmethod(workspace_tests.WorkspaceTests.setUpClass.__func__)
    tearDownClass=classmethod(workspace_tests.WorkspaceTests.tearDownClass.__func__)
    setUp=workspace_tests.WorkspaceTests.setUp
    tearDown=workspace_tests.WorkspaceTests.tearDown
    save=workspace_tests.WorkspaceTests.save
    render=workspace_tests.WorkspaceTests.render

    def test_metric_category_navigation_keeps_office_and_original_quantities(self):
        data=json.loads(self.a.details_json)
        data.update(fuel_consumption='5',fuel_unit='L')
        data['report_items'].append(dict(item_name='休憩',raw_result='1時間00分',unit='',status='confirmed'))
        self.a.details_json=json.dumps(data);self.m.db.session.commit()
        _,context=self.render(self.base)
        board=context['insights']
        categories={c['key']:c['metric_id'] for c in board['metric_categories']}
        self.assertEqual(set(categories),{'safety','economy','other'})
        for category,metric in categories.items():
            response,selected=self.render(self.base+'&'+urlencode({'metric':metric}))
            self.assertEqual(selected['insights']['metric_category'],category)
            self.assertEqual(selected['insights']['summary']['distance'],20)
            self.assertEqual(selected['filters']['office'],context['filters']['office'])
            self.assertNotIn('小山の人',response.get_data(as_text=True))
            self.assertIn('記録量・条件・出典',response.get_data(as_text=True))
        _,raw=self.render(self.base+'&metric='+categories['other'])
        self.assertEqual(raw['insights']['display_metrics'][0]['current']['display'],'1時間00分')

    def test_general_user_sees_own_layout_and_no_management_controls(self):
        from dkss_app import driving_access
        from flask import session
        self.m.db.session.add(self.m.User(company_code='TEST',username='one',role='user',password='unused',last_name='本人',password_changed_at='stamp'))
        self.m.db.session.commit()
        with self.m.app.test_request_context():
            session.update(company_code='TEST',username='admin',role='admin')
            driving_access.assign([self.a],'one','admin');self.m.db.session.commit()
        with self.client.session_transaction() as state:state.update(username='one',role='user',password_changed_at='stamp')
        response,context=self.render(self.base+'&scope=company&office=小山')
        html=response.get_data(as_text=True)
        self.assertEqual(context['filters']['scope'],'self');self.assertEqual(context['total'],1)
        for label in ['自分の運転実績','前期間と比べる','日ごとの記録','次の振り返り']:self.assertIn(label,html)
        for label in ['data-office-select','本人アカウントを設定','車両全体の整備実費','乗務員一覧へ戻る','小山の人','他社の秘密']:self.assertNotIn(label,html)
        self.assertEqual(self.client.post('/safety/driving-reports/readers',data={}).status_code,403)

    def test_admin_person_links_to_real_reader_and_daily_record_forms(self):
        key=driver_keys([self.a])[0][self.a.id]
        response,context=self.render(self.base+'&focus='+key)
        html=response.get_data(as_text=True)
        self.assertIn('id="reader-setting"',html)
        self.assertIn('name="reader_version" value="'+context['insights']['reader_version']+'"',html)
        self.assertIn('name="csrf_token"',html)
        self.assertIn('日別の数値',html)
        self.assertIn('日報から確認・指導を記録',html)
        self.assertIn('id="report-list"',html)

    def test_next_followup_uses_real_earliest_unfinished_date(self):
        base={'groups':[],'available_highlights':[],'metric_id':'','followups':[
            {'id':1,'review':{'state':'completed','next_date':'2020-01-01'}},
            {'id':2,'review':{'state':'followup','next_date':'2026-11-02'}},
            {'id':3,'review':{'state':'reviewed','next_date':'2026-10-28'}},
            {'id':4,'review':{'state':'followup','next_date':'bad'}}]}
        enrich(base,[],[])
        self.assertEqual(base['next_followup']['id'],3)
        self.assertEqual(base['followups'][0]['review']['state'],'completed')

    def test_scope_daily_chart_uses_scoped_numerators_and_retains_report_links(self):
        self.save(4,day='2026-10-11',distance='80',count='0')
        _,office=self.render(self.base)
        board=office['insights']
        self.assertEqual(board['vehicle_count'],1)
        self.assertEqual([p['date'] for p in board['trend']],['2026-10-10','2026-10-11'])
        self.assertEqual([p['display'] for p in board['trend']],['5','0'])
        self.assertEqual(board['trend'][0]['report_ids'],[self.a.id])
        _,company=self.render(self.base+'&scope=company')
        first=company['insights']['trend'][0]
        self.assertEqual(first['display'],'2.5')
        self.assertEqual(set(first['report_ids']),{self.a.id,self.b.id})
        self.assertNotIn(self.secret.id,first['report_ids'])

    def test_change_presentation_keeps_observation_separate_from_improvement(self):
        item={'kind':'scope','title':'急減速の傾向','finding':'元の根拠。条件を確認。','action':'周囲の状況を確認'}
        metric={'name':'急減速','method':'rate','unit':'回/100km'}
        entry={'metric':metric,'change':'0.8','current':{'display':'2.4'},'previous':{'display':'1.6'}}
        shown=finding(item,{'available_highlights':[entry]})
        self.assertEqual(shown['display_tone'],'attention')
        self.assertEqual(shown['display_title'],'急減速の記録が増加')
        self.assertEqual(shown['finding'],item['finding'])
        self.assertNotIn('悪化',shown['display_headline'])
        entry['change']='-0.8'
        self.assertEqual(finding(item,{'available_highlights':[entry]})['display_label'],'減少した記録')
        # Same metric names can have distinct definitions/settings. Never select by name alone.
        ambiguous=finding(item,{'available_highlights':[entry,dict(entry,change='1')]})
        self.assertEqual(ambiguous['display_headline'],item['finding'].split('。',1)[0])

    def test_empty_and_raw_reports_keep_the_primary_screen_structure(self):
        from driving_report_data import payload
        self.a.details_json=json.dumps(dict(payload(self.a),source_system=None,definition_version=None,
            report_items=[dict(item_name='休憩',raw_result='1時間00分',status='confirmed')]))
        self.m.db.session.commit()
        response,context=self.render(self.base)
        html=response.get_data(as_text=True)
        for marker in ['id="reflection-title"','id="driving-metrics"','id="driver-trend"','id="driving-next-title"','id="driving-roster"']:
            self.assertIn(marker,html)
        self.assertEqual(context['insights']['display_metrics'],[])
        self.assertEqual(context['insights']['empty_metric_names'],['急加速','急減速','速度超過'])
        self.assertNotIn('data-driving-chart',html)
        self.assertIn('1時間00分',html)
        self.assertLess(html.index('id="driving-next-title"'),html.index('id="driving-roster"'))
        _,economy=self.render(self.base+'&category=economy')
        self.assertEqual(economy['insights']['empty_metric_names'],['燃費','アイドリング','回転超過'])
        self.assertEqual(economy['insights']['summary']['distance'],20)
        self.assertEqual(self.client.get(self.base+'&category=invalid').status_code,400)

    def test_compact_ai_cards_keep_full_authorized_evidence(self):
        source={'kind':'change','finding':'検知回数は前期間から変わりました。取得距離も確認してください。',
                'context':'原数値 3回 ／ 対象距離 100 km','reports':[1],'action':'原本を確認'}
        shown=finding(source)
        self.assertEqual(shown['display_headline'],'検知回数は前期間から変わりました')
        self.assertEqual(shown['finding'],source['finding']);self.assertEqual(shown['reports'],[1])
        self.assertEqual(shown['context'],source['context']);self.assertEqual(shown['action'],source['action'])
        self.assertNotIn('改善',shown['display_label'])


if __name__=='__main__':unittest.main()
