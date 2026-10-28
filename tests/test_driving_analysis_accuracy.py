"""Reconcile stored source quantities, scoped aggregates and grounded AI evidence."""
import csv
import io
import json
import unittest
from decimal import Decimal
from flask import session
from identity_fixture import identity_for
from driving_report_data import payload
from driving_report_insights import collect, dashboard, driver_keys
from driving_report_workspace import enrich
from driving_report_comparisons import build
from driving_report_reflection import build_evidence
import test_driving_report_insights as source_tests
import test_driving_workspace as workspace_tests
import test_driving_ai_navigation as ai_tests


def evidence_board(current, previous):
    keys,_=driver_keys(current+previous)
    facts,_=collect(current,{},keys);before,_=collect(previous,{},keys)
    board=dashboard(facts,before,{1:'検証車両'})
    board['labels']={1:'検証車両'}
    enrich(board,facts,before,[],[],{},[{'key':'one','name':'安城'},{'key':'two','name':'小山'}],
           {'scope':'company'},True)
    board['scope']='company'
    return board,facts,before


class EvidenceAccuracyTests(unittest.TestCase):
    def test_both_periods_remain_reachable_when_report_links_are_limited_to_ten(self):
        now=[source_tests.row(i,count='1') for i in range(1,13)]
        old=[source_tests.row(i,day='2026-09-10',count='2') for i in range(101,113)]
        board,facts,_=evidence_board(now,old)
        for item in build_evidence(board,facts,[]):
            if '前期間 ' not in item['finding']:continue
            visible=item['reports'][:10]
            self.assertTrue(set(visible)&set(range(1,13)))
            self.assertTrue(set(visible)&set(range(101,113)))
            self.assertEqual(set(item['reports']),set(range(1,13))|set(range(101,113)))

    def test_difference_uses_original_precision_before_rounding_for_display(self):
        board,facts,_=evidence_board([source_tests.row(1,distance='300',count='1')],
            [source_tests.row(2,day='2026-09-10',distance='600',count='1')])
        entry=board['highlights'][0]
        self.assertEqual((entry['current']['display'],entry['previous']['display'],entry['change']),
                         ('0.33','0.17','0.17'))
        self.assertIn('差 0.17',build_evidence(board,facts,[])[0]['finding'])

    def test_previous_only_metrics_do_not_create_current_analysis(self):
        board,facts,_=evidence_board([],[source_tests.row(1)])
        self.assertEqual(build_evidence(board,facts,[]),[])

    def test_missing_current_metric_offers_record_facts_instead_of_a_previous_only_finding(self):
        now=source_tests.row(1,distance='50',report_items=[])
        old=source_tests.row(2,day='2026-09-10')
        board,facts,_=evidence_board([now],[old])
        evidence=build_evidence(board,facts,[])
        self.assertEqual(len(evidence),1)
        self.assertEqual(evidence[0]['title'],'運行記録の確認')
        self.assertEqual(evidence[0]['reports'],[1])
        self.assertIn('50 km',evidence[0]['finding'])
        self.assertEqual(evidence[0]['allowed_actions'],['verify_data'])

    def test_every_displayed_change_cites_both_periods_and_keeps_current_sources_first(self):
        now=[source_tests.row(1,distance='20',count='1'),
             source_tests.row(2,code='B',name='乗務員B',office_name='小山')]
        old=[source_tests.row(3,day='2026-09-10',distance='40',count='4'),
             source_tests.row(4,day='2026-09-10',code='B',name='乗務員B',office_name='小山',distance='50',count='1')]
        board,facts,before=evidence_board(now,old)
        board['comparison']=build(board,facts,before,'vehicle',True)
        board['comparison']['ready']=True
        evidence=build_evidence(board,facts,[])
        changed=[item for item in evidence if '前期間 ' in item['finding']]
        self.assertEqual({item['kind'] for item in changed},{'scope','office','change','comparison'})
        for item in changed:
            with self.subTest(kind=item['kind'],title=item['title']):
                self.assertTrue(set(item['reports'])&{1,2})
                self.assertTrue(set(item['reports'])&{3,4})
                self.assertIn(item['reports'][0],{1,2})
                self.assertEqual(len(item['reports']),len(set(item['reports'])))


class AnalysisAccuracyRouteTests(unittest.TestCase):
    setUpClass=classmethod(workspace_tests.WorkspaceTests.setUpClass.__func__)
    tearDownClass=classmethod(workspace_tests.WorkspaceTests.tearDownClass.__func__)
    setUp=workspace_tests.WorkspaceTests.setUp
    tearDown=workspace_tests.WorkspaceTests.tearDown
    render=workspace_tests.WorkspaceTests.render
    save=workspace_tests.WorkspaceTests.save
    generate_for=ai_tests.AiNavigationTests.generate_for

    def update(self,row,**fields):
        data=payload(row);data.update(fields);row.details_json=json.dumps(data);self.m.db.session.commit()

    def exported(self,url):
        response=self.client.get(url.replace('/safety/driving-reports?','/safety/driving-reports/export.csv?'))
        self.assertEqual(response.status_code,200)
        return list(csv.DictReader(io.StringIO(response.data.decode('utf-8-sig'))))

    def test_source_office_person_company_and_csv_use_paired_totals_once(self):
        second=self.save(4,distance='40',count='3')
        duplicate=self.save(5,report_number='R4',distance='40',count='3')
        original={row.id:row.details_json for row in [self.a,self.b,second,duplicate]}
        _,office=self.render(self.base)
        now=office['insights']['summary']
        self.assertEqual((office['total'],now['count'],now['distance']),(3,2,Decimal(60)))
        self.assertEqual((now['numerator'],now['denominator'],now['display']),(4,60,'6.67'))
        key=driver_keys([self.a])[0][self.a.id]
        _,person=self.render(self.base+'&focus='+key)
        for field in ['count','distance','numerator','denominator','value','display']:
            self.assertEqual(person['insights']['summary'][field],now[field])
        _,company=self.render(self.base+'&scope=company')
        total=company['insights']['summary']
        self.assertEqual((total['count'],total['distance'],total['numerator'],total['denominator'],total['display']),
                         (3,160,6,160,'3.75'))
        self.assertEqual(sum(o['summary']['distance'] or 0 for o in company['insights']['office_summaries']),160)
        csv_row=next(r for r in self.exported(self.base+'&view=comparison') if r['コード']=='A' and r['日報ID'])
        self.assertEqual((csv_row['運行数'],csv_row['計算分子'],csv_row['計算分母'],csv_row['表示値']),('2','4','60','6.67'))
        for row,distance in [(self.a,'20'),(second,'40'),(duplicate,'40')]:
            _,detail=self.render('/safety/driving-reports/'+str(row.id))
            self.assertEqual(detail['report']['data']['distance'],distance)
            self.assertEqual(row.details_json,original[row.id])

    def test_disjoint_periods_use_exact_source_windows_at_each_scope(self):
        old=self.save(4,day='2026-06-02',distance='40',count='4')
        self.save(5,day='2026-08-01',distance='999',count='999')
        query='?period=custom&start=2026-10-01&end=2026-10-26&compare=custom&compare_start=2026-06-01&compare_end=2026-06-07'
        for scope in ['office','company']:
            _,context=self.render('/safety/driving-reports'+query+'&scope='+scope)
            board=context['insights']
            self.assertEqual(board['previous']['report_ids'],[old.id])
            self.assertEqual(board['previous']['display'],'10')
            self.assertEqual(board['summary']['display'],'5' if scope=='office' else '2.5')
        invalid=query.replace('compare_end=2026-06-07','compare_end=2026-10-02')
        self.assertEqual(self.client.get('/safety/driving-reports'+invalid).status_code,400)

    def test_fuel_uses_consumption_pairs_across_offices_and_does_not_borrow_missing_fuel(self):
        self.update(self.a,distance='100',fuel_consumption='10',fuel_unit='L',report_items=[])
        self.update(self.b,distance='300',fuel_consumption='20',fuel_unit='L',report_items=[])
        self.save(4,distance='50',report_items=[])
        _,office=self.render(self.base+'&category=economy')
        self.assertEqual(office['insights']['summary']['display'],'10')
        self.assertEqual(office['insights']['summary']['distance'],150)
        _,company=self.render(self.base+'&scope=company&category=economy')
        summary=company['insights']['summary']
        self.assertEqual((summary['distance'],summary['numerator'],summary['denominator'],summary['display']),
                         (450,400,30,'13.33'))
        self.assertEqual(summary['metric_count'],2)
        self.assertEqual(summary['basis_display'],'400 km ／ 消費燃料 30 L')

    def test_conflicting_duplicate_metrics_keep_sources_without_polluting_other_drivers(self):
        conflicting=self.save(4,report_number='R1',distance='20',count='9')
        raw={r.id:r.details_json for r in [self.a,conflicting]}
        _,company=self.render(self.base+'&scope=company')
        summary=company['insights']['summary']
        self.assertEqual((summary['count'],summary['distance'],summary['display']),(2,120,'2'))
        self.assertEqual(summary['sources'],[self.b.id])
        self.assertIn('値が不一致',str(company['insights']['review_notes']))
        for row in [self.a,conflicting]:self.assertEqual(row.details_json,raw[row.id])

    def test_zero_current_reports_with_previous_data_have_empty_ai_in_every_scope(self):
        url='/safety/driving-reports?period=custom&start=2026-11-01&end=2026-11-30'
        for scope in ['office','company']:
            with self.subTest(scope=scope):
                _,context=self.render(url+'&scope='+scope)
                self.assertEqual(context['total'],0)
                self.assertGreater(context['insights']['previous']['count'],0)
                self.assertEqual(context['reflection']['status'],'empty')
                self.assertEqual(context['reflection']['candidate_count'],0)

    def test_generated_changes_link_to_authorized_current_and_previous_originals(self):
        old=self.save(4,day='2026-09-10',distance='40',count='4')
        query='/safety/driving-reports?period=custom&start=2026-10-01&end=2026-10-26'
        for personal in [False,True]:
            with self.subTest(personal=personal):
                if personal:
                    from dkss_app import driving_access
                    self.m.db.session.add(self.m.User(company_code='TEST',username='reader',role='user',password='unused',last_name='本人',password_changed_at='stamp'))
                    self.m.db.session.commit()
                    with self.m.app.test_request_context():
                        session.update(company_code='TEST',username='admin',role='admin')
                        driving_access.assign([self.a,old],'reader','admin');self.m.db.session.commit()
                    with self.client.session_transaction() as state:
                        state.update(username='reader',role='user',password_changed_at='stamp',
                                     account_identity=identity_for('TEST', 'reader', app=self.m.app))
                _,context,document=self.generate_for(query,'change')
                item=context['reflection']['items'][0]
                self.assertEqual(set(item['reports']),{self.a.id,old.id})
                self.assertIn('前期間 10',item['finding'])
                self.assertIn('差 -5',item['finding'])
                for link in item['report_links']:self.assertEqual(self.client.get(link['url']).status_code,200)
                self.assertEqual(len(item['report_links']),2)
                self.assertNotIn(self.secret.id,{rid for e in document['evidence'] for rid in e['reports']})


if __name__=='__main__':unittest.main()
