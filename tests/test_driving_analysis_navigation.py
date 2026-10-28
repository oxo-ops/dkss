"""The office analysis and driver directory are primary content, not disclosures."""
from html.parser import HTMLParser
import unittest
from urllib.parse import parse_qs, urlsplit
import test_driving_workspace_ui as ui
from driving_report_insights import driver_keys


class Tree(HTMLParser):
    def __init__(self,html):
        super().__init__();self.stack=[];self.nodes=[];self.feed(html)
    def handle_starttag(self,tag,attrs):
        node={'tag':tag,'attrs':dict(attrs),'parents':list(self.stack)};self.nodes.append(node)
        if tag not in {'input','img','br','hr','meta','link','source','area','wbr'}:self.stack.append(node)
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i]['tag']==tag:self.stack=self.stack[:i];break
    def by_id(self,value):return next(n for n in self.nodes if n['attrs'].get('id')==value)


class AnalysisNavigationTests(unittest.TestCase):
    setUpClass=classmethod(ui.WorkspaceUITests.setUpClass.__func__)
    tearDownClass=classmethod(ui.WorkspaceUITests.tearDownClass.__func__)
    setUp=ui.WorkspaceUITests.setUp
    tearDown=ui.WorkspaceUITests.tearDown
    render=ui.WorkspaceUITests.render
    save=ui.WorkspaceUITests.save

    def test_office_analysis_and_driver_directory_are_visible_without_expansion(self):
        response,_=self.render(self.base);html=response.get_data(as_text=True);tree=Tree(html)
        for key in ['driving-metrics','driver-comparison','driving-roster']:
            node=tree.by_id(key)
            self.assertNotEqual(node['tag'],'details')
            self.assertFalse(any(p['tag']=='details' or 'hidden' in p['attrs'] for p in node['parents']))
        self.assertLess(html.index('id="driving-metrics"'),html.index('id="driver-comparison"'))
        self.assertIn('所属ドライバー',html);self.assertIn('分析を見る →',html)
        self.assertNotIn('driving-metric-select" href=',html)

    def test_company_offices_have_named_analysis_actions_and_keep_scope(self):
        response,ctx=self.render(self.base+'&scope=company')
        html=response.get_data(as_text=True);tree=Tree(html)
        self.assertFalse(any(p['tag']=='details' for p in tree.by_id('office-comparison')['parents']))
        actions=[n for n in tree.nodes if n['tag']=='a' and n['attrs'].get('aria-label','').endswith('の分析を見る')]
        self.assertGreater(len(actions),0)
        for action in actions:
            self.assertIn('scope=office',action['attrs']['href']);self.assertIn('period=all',action['attrs']['href'])
        self.assertIn('全ドライバーを見る',html)

    def test_panels_do_not_change_scope_or_invalidate_the_same_ai_input(self):
        keys=set()
        for panel in ['analysis','reports','comparison','data']:
            response,ctx=self.render(self.base+'&panel='+panel)
            self.assertEqual(ctx['workspace_panel'],panel)
            self.assertNotIn('panel',ctx['filters'])
            self.assertEqual(ctx['insights']['summary']['distance'],20)
            keys.add(ctx['reflection']['key'])
            tree=Tree(response.get_data(as_text=True))
            containers=[n for n in tree.nodes if 'data-workspace-panel' in n['attrs']]
            self.assertEqual([n['attrs']['data-workspace-panel'] for n in containers if 'hidden' not in n['attrs']],[panel])
        self.assertEqual(len(keys),1)
        self.assertEqual(self.client.get(self.base+'&panel=invalid').status_code,400)

    def test_person_has_visible_trend_control_and_back_action_near_top(self):
        key=driver_keys([self.a])[0][self.a.id]
        response,_=self.render(self.base+'&focus='+key);html=response.get_data(as_text=True);tree=Tree(html)
        selector=next(n for n in tree.nodes if n['tag']=='form' and 'driving-detail-metric' in n['attrs'].get('class',''))
        self.assertFalse(any(p['tag']=='details' for p in selector['parents']))
        self.assertIn('表示する指標',html);self.assertIn('表示を更新',html)
        back=next(n for n in tree.nodes if n['tag']=='a' and 'driving-back-link' in n['attrs'].get('class',''))
        self.assertIn('btn',back['attrs']['class'])
        self.assertLess(html.index('driving-back-link'),html.index('id="driving-filter-form"'))

    def test_no_records_are_not_presented_as_zero_scores_or_an_active_analysis(self):
        response,_=self.render(self.base);html=response.get_data(as_text=True);tree=Tree(html)
        row=next(n for n in tree.nodes if n['tag']=='a' and n['attrs'].get('aria-label')=='乗務員Aさんの分析を見る')
        self.assertIn('focus=',row['attrs']['href'])
        self.assertNotIn('#driver-trend',row['attrs']['href'])
        self.assertIn('日報の取込後に表示',html)
        self.assertIn('振り返り未記入',html)

    def test_empty_custom_comparison_can_open_all_records_without_expanding_scope(self):
        query='?period=custom&start=2030-10-01&end=2030-10-26&compare=custom&compare_start=2026-06-01&compare_end=2026-06-07'
        for scope in ['office','company','self']:
            response,context=self.render('/safety/driving-reports'+query+'&scope='+scope+'&panel=reports')
            self.assertEqual(context['total'],0)
            tree=Tree(response.get_data(as_text=True))
            link=next(n['attrs']['href'] for n in tree.nodes if n['tag']=='a' and
                      parse_qs(urlsplit(n['attrs'].get('href','')).query).get('period')==['all'])
            response,all_records=self.render(link)
            self.assertEqual(all_records['filters']['scope'],scope)
            self.assertEqual(all_records['workspace_panel'],'reports')
            self.assertEqual(all_records['insights']['period']['mode'],'all')
            self.assertEqual(all_records['insights']['period']['previous_start'],'')
            self.assertEqual(all_records['total'],{'office':1,'company':2,'self':0}[scope])
            self.assertNotIn('他社の秘密',response.get_data(as_text=True))
