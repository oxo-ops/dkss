"""Distance absence, measured zero and partial totals remain distinct."""
import csv
import io
import json
import unittest
from decimal import Decimal
from unittest.mock import patch
from driving_report_data import payload
from driving_report_insights import summarize,collect,driver_keys
from driving_report_reflection import build_evidence
import test_driving_workspace as workspace_tests


class DistanceCompletenessTests(unittest.TestCase):
    setUpClass=classmethod(workspace_tests.WorkspaceTests.setUpClass.__func__)
    tearDownClass=classmethod(workspace_tests.WorkspaceTests.tearDownClass.__func__)
    setUp=workspace_tests.WorkspaceTests.setUp
    tearDown=workspace_tests.WorkspaceTests.tearDown
    save=workspace_tests.WorkspaceTests.save
    render=workspace_tests.WorkspaceTests.render

    def set_distance(self,row,value):
        data=payload(row);data['distance']=value;row.details_json=json.dumps(data);self.m.db.session.commit()

    def test_summary_distinguishes_empty_unknown_zero_and_partial(self):
        self.set_distance(self.a,None)
        keys,_=driver_keys([self.a]);facts,_=collect([self.a],{},keys)
        absent=summarize([]);unknown=summarize(facts)
        self.assertEqual((absent['distance_state'],absent['distance_display']),('記録なし','記録なし'))
        self.assertIsNone(unknown['distance']);self.assertEqual(unknown['distance_display'],'距離未取得')
        self.set_distance(self.a,'0');facts,_=collect([self.a],{},keys)
        zero=summarize(facts)
        self.assertEqual(zero['distance'],Decimal(0));self.assertEqual(zero['distance_display'],'0 km')
        self.assertEqual(zero['distance_count'],1)
        self.assertEqual(summarize(facts+[dict(facts[0],distance=None)])['distance_display'],'0 km（距離取得 1／2運行）')

    def test_page_distinguishes_no_reports_and_no_distance_without_other_office(self):
        self.set_distance(self.a,None)
        response,context=self.render(self.base)
        self.assertEqual(context['insights']['summary']['distance_display'],'距離未取得')
        self.assertIn('距離未取得',response.get_data(as_text=True))
        self.assertNotIn('小山の人',response.get_data(as_text=True))
        _,context=self.render('/safety/driving-reports?period=custom&start=2030-01-01&end=2030-01-02')
        self.assertEqual(context['insights']['summary']['distance_display'],'記録なし')
        _,context=self.render(self.base+'&scope=company')
        self.assertEqual(context['insights']['summary']['distance_display'],'100 km（距離取得 1／2運行）')

    def test_partial_day_and_vehicle_totals_exclude_cancellations_and_duplicate_copies(self):
        self.set_distance(self.a,None)
        self.save(8,distance='80');self.save(10,report_number='R8',distance='80')
        cancelled=self.save(9,distance='999')
        data=payload(cancelled);data['lifecycle']='cancelled';cancelled.details_json=json.dumps(data);self.m.db.session.commit()
        key=driver_keys([self.a])[0][self.a.id]
        response,context=self.render(self.base+'&focus='+key)
        summary=context['insights']['summary']
        self.assertEqual((summary['count'],summary['distance_count'],summary['distance']),(2,1,Decimal(80)))
        self.assertEqual(context['insights']['trend'][0]['distance_display'],'80 km（距離取得 1／2運行）')
        self.assertEqual(context['vehicle_history'][0]['summary']['distance_display'],summary['distance_display'])
        self.assertIn(summary['distance_display'],response.get_data(as_text=True))

    def test_csv_keeps_missing_numeric_distance_empty_and_previous_zero_numeric(self):
        self.set_distance(self.a,None);self.save(8,day='2026-09-10',distance='0')
        query='period=custom&start=2026-10-01&end=2026-10-26&breakdown=people'
        for view in ['comparison','breakdown']:
            response=self.client.get('/safety/driving-reports/export.csv?'+query+'&view='+view)
            self.assertEqual(response.status_code,200)
            rows=list(csv.DictReader(io.StringIO(response.data.decode('utf-8-sig'))))
            self.assertTrue(all(None not in row for row in rows),'CSV headings must align with values')
            row=next(row for row in rows if row['運行数']=='1')
            self.assertEqual(row['走行距離km'],'');self.assertEqual(row['距離取得運行数'],'0')
            self.assertEqual(row['距離取得状態'],'未取得')
            self.assertEqual(row['前期間走行距離km'],'0');self.assertEqual(row['前期間距離取得状態'],'取得済み')
        with patch('driving_report_management.export_pdf',return_value=b'pdf') as pdf:
            self.assertEqual(self.client.get('/safety/driving-reports/export.pdf?'+query).status_code,200)
            self.assertIn('距離未取得',str(pdf.call_args));self.assertIn('前期間 0 km',str(pdf.call_args))

    def test_ai_record_only_fallback_describes_missing_or_partial_distance(self):
        self.set_distance(self.a,None)
        keys,_=driver_keys([self.a]);facts,_=collect([self.a],{},keys)
        for fact in facts:fact['metrics']=[]
        evidence=build_evidence({'drivers':[],'highlights':[]},facts,[])
        self.assertIn('距離未取得',evidence[0]['finding']);self.assertNotIn('0 km',evidence[0]['finding'])
        evidence=build_evidence({'drivers':[],'highlights':[]},facts+[dict(facts[0],distance=Decimal(80))],[])
        self.assertIn('80 km（距離取得 1／2運行）',evidence[0]['finding'])


if __name__=='__main__':unittest.main()
