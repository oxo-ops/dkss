"""Driver comparisons, rates, scope and review routes against real Flask/SQLite."""
import copy
import csv
import io
import json
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import urlencode
from unittest.mock import patch
from driving_report_insights import periods, collect, dashboard, driver_keys, number, review_notes
from driving_report_data import payload, version
import test_workflow_regressions as workflow


def row(i,day='2026-10-10',distance='100',count='2',code='A',name='乗務員A',**fields):
    values=dict(source_system='DTG',definition_version='v1',driver_name=name,driver_code=code,
        office_name='安城',report_number='R'+str(i),operation_date=day,operation_start_time='08:00:00',operation_end_time='09:00:00',
        report_scope='trip',distance=distance,report_items=[dict(item_name='急加速',category='安全',raw_result=str(count)+'回',value=count,
            unit='回',definition='急加速の回数',threshold='0.3G',road_type='一般道',status='confirmed')])
    values.update(fields)
    return SimpleNamespace(id=i,company_code='TEST',vehicle_record_id=1,operation_date=day,
        report_number=values.get('report_number'),operation_record_id=None,details_json=json.dumps(values),created_at=None,created_by_username='admin')


def board(rows,previous=None):
    keys,_=driver_keys(rows+(previous or []));facts,issues=collect(rows,{},keys)
    old,_=collect(previous or [],{},keys)
    return dashboard(facts,old,{1:'テスト車両'}),facts,issues


class DrivingInsightDataTests(unittest.TestCase):
    def test_periods_use_explicit_scope_and_equal_preceding_length(self):
        m=periods({},date(2026,10,26))
        self.assertEqual((m['start'],m['end'],m['previous_start'],m['previous_end']),('2026-10-01','2026-10-26','2026-09-05','2026-09-30'))
        self.assertEqual(periods({'period':'30d'},date(2026,3,1))['start'],'2026-01-31')
        self.assertEqual(periods({'period':'prev_month'},date(2028,3,1))['end'],'2028-02-29')
        self.assertEqual(periods({'period':'all'},date(2026,10,26))['start'],'')
        for args in ({'start':'bad'},{'period':'unknown'},{'start':'2026-10-20','end':'2026-10-01'}):
            with self.assertRaises(ValueError):periods(args,date(2026,10,26))

    def test_count_is_normalized_by_paired_distance_not_count_ranking(self):
        b,_,_=board([row(1,distance='20',count='1'),row(2,code='B',name='乗務員B',count='2')])
        self.assertEqual(b['metric']['unit'],'回/100km')
        self.assertEqual([p['current']['value'] for p in b['drivers']],[Decimal(5),Decimal(2)])
        self.assertEqual(b['summary']['value'],Decimal('2.5'))
        self.assertEqual(b['summary']['numerator'],Decimal(3))
        self.assertEqual(b['summary']['denominator'],Decimal(120))

    def test_fuel_uses_total_distance_over_paired_consumption(self):
        a=row(1,distance='100',fuel_consumption='10',fuel_unit='L',report_items=[])
        b=row(2,distance='300',fuel_consumption='20',fuel_unit='L',report_items=[])
        c=row(3,distance='999',fuel_unit='L',report_items=[])
        result,_,_=board([a,b,c])
        self.assertEqual(result['summary']['display'],'13.33')
        self.assertEqual(result['summary']['metric_count'],2)
        self.assertEqual(result['summary']['paired_distance'],Decimal(400))
        self.assertNotEqual(result['summary']['value'],Decimal('12.5'))
        zero=row(4,distance='100',fuel_consumption='0',fuel_unit='L',report_items=[])
        self.assertEqual(board([zero])[0]['groups'],[])

    def test_missing_distance_and_zero_are_not_synthetic_measurements(self):
        result,_,_=board([row(1,distance=None),row(2,distance='0')])
        self.assertIsNone(result['summary']['value']);self.assertEqual(result['summary']['display'],'2回')
        self.assertEqual(result['summary']['distance_count'],1)
        self.assertEqual(number(Decimal('0')),'0')
        zero=row(3,count='0');self.assertEqual(board([zero])[0]['summary']['value'],0)

    def test_incompatible_definitions_stay_separate_and_no_score_average(self):
        a=row(1);b=row(2,definition_version='v2')
        result,_,_=board([a,b]);self.assertEqual(len(result['groups']),2)
        values=copy.deepcopy(payload(a));values['report_items'][0].update(unit='点',value='60',score='60',raw_result='60点')
        a.details_json=json.dumps(values)
        values['report_items'][0].update(value='100',score='100',raw_result='100点');b.details_json=json.dumps(dict(values,report_number='R2'))
        result,_,_=board([a,b]);self.assertIsNone(result['summary']['value'])
        self.assertNotEqual(result['summary']['display'],'80')
        self.assertEqual(result['summary']['raw_count'],2)

    def test_duplicate_copies_day_month_and_cancellations_do_not_add_twice(self):
        a=row(1);copy_row=row(2,report_number='R1')
        day=row(3,report_scope='daily',report_number='day',distance='500')
        month=row(4,report_scope='monthly',distance='3000')
        cancelled=row(5,lifecycle='cancelled')
        result,facts,_=board([a,copy_row,day,month,cancelled])
        self.assertEqual(result['summary']['count'],1);self.assertEqual(result['summary']['distance'],100)
        self.assertEqual(result['summary']['metric_count'],1)
        conflict=row(6,report_number='R1',distance='102')
        result,_,issues=board([a,conflict]);self.assertIsNone(result['summary']['value']);self.assertTrue(issues)

    def test_same_name_and_reused_code_do_not_merge_people(self):
        a=row(1,code=None);b=row(2,code=None)
        self.assertEqual(len(board([a,b])[0]['drivers']),2)
        c=row(3,name='別の人')
        self.assertEqual(len(board([row(4),c])[0]['drivers']),2)
        other=row(5);other.company_code='OTHER'
        self.assertEqual(len(board([row(6),other])[0]['drivers']),2)

    def test_period_comparison_uses_same_person_and_definition(self):
        now=[row(1,count='2')];before=[row(2,'2026-09-10',count='5')]
        result,_,_=board(now,before)
        self.assertEqual(result['drivers'][0]['change'],'-3')
        before[0].details_json=json.dumps(dict(payload(before[0]),definition_version='v2'))
        self.assertIsNone(board(now,before)[0]['drivers'][0]['change'])

    def test_review_notes_explain_holds_without_flagging_copies_or_cancellations(self):
        a=row(1,distance=None,code=None,definition_version=None)
        duplicate=row(2,distance=None,code=None,definition_version=None,report_number='R1')
        cancelled=row(3,distance=None,lifecycle='cancelled')
        rows=[a,duplicate,cancelled]
        keys,conflicts=driver_keys(rows);facts,issues=collect(rows,{},keys)
        notes=review_notes(rows,facts,issues,conflicts)
        self.assertEqual(len(notes),1);self.assertEqual(notes[0]['id'],1)
        self.assertEqual(len(notes[0]['reasons']),3)
        self.assertIn('乗務員コード',notes[0]['reasons'][0])
        self.assertIn('原本値',notes[0]['reasons'][-1])
        rows=[row(4,name='A'),row(5,name='B')]
        keys,conflicts=driver_keys(rows);facts,issues=collect(rows,{},keys)
        self.assertTrue(all('異なる氏名' in n['reasons'][0] for n in review_notes(rows,facts,issues,conflicts)))
        self.assertEqual(review_notes([row(6)],[],[{'id':999,'reason':'範囲外'}],set()),[])

    def test_unknown_raw_metrics_remain_visible_without_chart_or_rank(self):
        a=row(1,definition_version=None)
        result,facts,_=board([a]);selected=dashboard(facts,[],{1:'車両'},selected_driver=result['drivers'][0]['key'])
        self.assertEqual(selected['summary']['display'],'2回')
        self.assertEqual(selected['chart'],[]);self.assertEqual(selected['trend'][0]['report_ids'],[1])


class DrivingInsightRouteTests(unittest.TestCase):
    setUpClass=classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass=classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    setUp=workflow.WorkflowRegressionTests.setUp
    tearDown=workflow.WorkflowRegressionTests.tearDown
    def save(self,i=1,**kw):
        fixture=row(i,**kw)
        r=self.m.VehicleDrivingReportRecord(company_code='TEST',vehicle_record_id=self.vehicle.id,
            operation_date=fixture.operation_date,details_json=fixture.details_json,content='日報',created_by_username='admin',source_draft_id='fixture-'+str(i),source_record_index=0)
        self.m.db.session.add(r);self.m.db.session.commit();return r
    def test_month_default_and_resolved_export_scope(self):
        self.save();self.save(2,day='2025-10-10',name='過去の人',code='OLD')
        with patch('driving_report_management.datetime') as clock:
            from datetime import datetime
            clock.now.return_value=datetime(2026,10,26)
            response=self.client.get('/safety/driving-reports')
        self.assertEqual(response.status_code,200,response.get_data(as_text=True))
        html=response.get_data(as_text=True)
        self.assertIn('2026-10-01',html);self.assertNotIn('過去の人',html)
        self.assertIn('period=month',html);self.assertIn('比較CSV',html)
        self.assertIn('乗務員ごとの運転傾向',html)
        self.assertEqual(self.client.get('/safety/driving-reports?period=custom&start=bad&end=bad').status_code,400)

    def test_focus_trend_and_company_scoped_maintenance_links(self):
        a=self.save();self.save(2,day='2026-10-11')
        self.m.db.session.add(self.m.VehicleMaintenanceRecord(company_code='TEST',vehicle_record_id=self.vehicle.id,entry_date='2026-09-01',completion_date='2026-09-02',status='完了',content='クラッチ交換',total_cost=1100))
        self.m.db.session.add(self.m.VehicleMaintenanceRecord(company_code='OTHER',vehicle_record_id=self.vehicle.id,entry_date='2026-09-01',completion_date='2026-09-02',status='完了',content='他社秘密整備'))
        self.m.db.session.commit()
        key=driver_keys([a])[0][a.id]
        response=self.client.get('/safety/driving-reports?'+urlencode({'period':'all','focus':key}))
        self.assertEqual(response.status_code,200,response.get_data(as_text=True));html=response.get_data(as_text=True)
        self.assertIn('さんの推移',html);self.assertIn('クラッチ交換',html);self.assertNotIn('他社秘密整備',html)
        self.assertIn('data-driving-chart',html);self.assertIn('return_to=',html)

    def test_comparison_csv_matches_rates_and_includes_provenance(self):
        self.save(distance='20',count='1',name='=名前');self.save(2,name='二人目',code='B',count='2')
        response=self.client.get('/safety/driving-reports/export.csv?period=all&view=comparison')
        self.assertEqual(response.status_code,200)
        rows=list(csv.DictReader(io.StringIO(response.data.decode('utf-8-sig'))))
        self.assertEqual(len(rows),2)
        by={r['コード']:r for r in rows}
        self.assertEqual(by['A']['表示値'],'5');self.assertEqual(by['B']['表示値'],'2')
        self.assertEqual(by['A']['乗務員'],"'=名前");self.assertEqual(by['A']['閾値'],'0.3G')
        self.assertEqual(by['A']['単位'],'回/100km');self.assertTrue(by['A']['日報ID'])

    def test_review_retains_action_explanation_rejects_stale_and_guards_return(self):
        r=self.save();url=f'/safety/driving-reports/{r.id}/review'
        data=dict(version=version(r),state='followup',action='急な加速を減らす',driver_explanation='合流のため',return_to='/safety/driving-reports?period=all#driver-trend')
        response=self.client.post(url,data=data)
        self.assertEqual(response.status_code,302);self.assertIn('return_to=',response.location)
        self.assertEqual(payload(r)['review']['action'],data['action']);self.assertEqual(payload(r)['review']['driver_explanation'],'合流のため')
        self.assertEqual(self.client.post(url,data=data).status_code,409)
        data.update(version=version(r),return_to='https://example.invalid/')
        response=self.client.post(url,data=data)
        self.assertNotIn('example.invalid',response.location)
        r.company_code='OTHER';self.m.db.session.commit()
        self.assertEqual(self.client.get(f'/safety/driving-reports/{r.id}').status_code,404)

    def test_get_and_exports_do_not_change_source_or_call_ai(self):
        r=self.save();original=r.details_json
        with patch('maintenance_invoice_ai.urllib.request.urlopen',side_effect=AssertionError('no network')):
            self.assertEqual(self.client.get('/safety/driving-reports?period=all').status_code,200)
            self.assertEqual(self.client.get('/safety/driving-reports/export.pdf?period=all').status_code,200)
        self.assertEqual(r.details_json,original)

    def test_partial_export_scope_and_reserved_query_parameters(self):
        self.save(day='2026-10-10',name='範囲内',code='IN')
        self.save(2,day='2026-09-01',name='範囲外',code='OUT')
        response=self.client.get('/safety/driving-reports/export.csv?view=comparison&start=2026-10-01')
        text=response.data.decode('utf-8-sig')
        self.assertEqual(response.status_code,200);self.assertIn('範囲内',text);self.assertNotIn('範囲外',text)
        response=self.client.get('/safety/driving-reports?period=all&format=csv&record_id=99')
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.get('/safety/driving-reports?period=all&focus=bad').status_code,400)
        report=self.m.VehicleDrivingReportRecord.query.first()
        self.assertEqual(self.client.get(f'/safety/driving-reports/{report.id}?return_to=http://[').status_code,200)

    def test_review_guidance_links_preserve_scope_and_escape_original_names(self):
        import re
        from html import unescape
        self.save(distance=None,code=None,name='<script>名前</script>',definition_version=None)
        self.save(2,lifecycle='cancelled',distance=None)
        self.save(3,day='2025-01-01',distance=None,name='範囲外')
        response=self.client.get('/safety/driving-reports?period=custom&start=2026-10-01&end=2026-10-26&office=安城')
        self.assertEqual(response.status_code,200)
        notes=response.get_data(as_text=True).split('id="comparison-review"',1)[1].split('</details>',1)[0]
        self.assertEqual(notes.count('class="driving-review-note"'),1);self.assertIn('原本値',notes)
        self.assertNotIn('<script>',notes)
        link=unescape(re.search(r'href="([^"]+)"',notes).group(1))
        response=self.client.get(link)
        self.assertEqual(response.status_code,200)
        back=unescape(re.search(r'page-breadcrumb[^>]*><a href="([^"]+)"',response.get_data(as_text=True)).group(1))
        self.assertIn('office=',back);self.assertIn('start=2026-10-01',back);self.assertTrue(back.endswith('#comparison-review'))
        self.assertEqual(self.client.get(back).status_code,200)
