"""Human-readable original quantities use the actual paired denominator."""
import csv
import io
import unittest
from decimal import Decimal
from unittest.mock import patch
from driving_report_insights import summarize
from driving_report_reflection import build_evidence
import test_driving_report_insights as insight_tests
import test_driving_workspace as workspace_tests


class MetricBasisTests(unittest.TestCase):
    setUpClass=classmethod(workspace_tests.WorkspaceTests.setUpClass.__func__)
    tearDownClass=classmethod(workspace_tests.WorkspaceTests.tearDownClass.__func__)
    setUp=workspace_tests.WorkspaceTests.setUp
    tearDown=workspace_tests.WorkspaceTests.tearDown
    save=workspace_tests.WorkspaceTests.save
    render=workspace_tests.WorkspaceTests.render

    def summary(self,rows,method):
        _,facts,_=insight_tests.board(rows)
        metric=next(m for f in facts for m in f['metrics'] if m['method']==method)
        return summarize(facts,metric['id'])

    def test_counts_show_total_and_only_the_matching_record_distance(self):
        rows=[insight_tests.row(1,distance='20',count='1'),insight_tests.row(2,distance='80',count='3'),insight_tests.row(3,distance=None)]
        result=self.summary(rows,'rate')
        self.assertEqual(result['display'],'4');self.assertEqual(result['basis_display'],'4回 ／ 対象距離 100 km')
        self.assertEqual(result['metric_count'],2);self.assertEqual(result['denominator_unit'],'km')
        self.assertEqual(result['paired_distance'],100)

    def test_explicit_distance_time_and_percent_units_do_not_use_whole_trip_distance(self):
        item=dict(item_name='速度超過',raw_result='2回/100km',value='2',unit='回/100km',numerator='3',denominator='150',denominator_unit='km',definition='検知回数',threshold='基準値',status='confirmed')
        result=self.summary([insight_tests.row(1,distance='1000',report_items=[item])],'rate')
        self.assertEqual(result['basis_display'],'3回 ／ 対象距離 150 km');self.assertEqual(result['paired_distance'],150)
        item.update(unit='件/h',numerator='2',denominator='0.5',denominator_unit='h')
        result=self.summary([insight_tests.row(2,distance='1000',report_items=[item])],'rate')
        self.assertEqual(result['basis_display'],'2件 ／ 対象時間 0.5 h');self.assertIsNone(result['paired_distance'])
        item.update(unit='%',numerator='2',denominator='10',denominator_unit='分')
        result=self.summary([insight_tests.row(3,distance='1000',report_items=[item])],'ratio')
        self.assertEqual(result['display'],'20');self.assertEqual(result['basis_display'],'原数値 2 ／ 対象 10 分')
        self.assertEqual(result['numerator_unit'],'');self.assertIsNone(result['paired_distance'])

    def test_weighted_fuel_and_zero_counts_keep_units_but_raw_scores_are_not_summed(self):
        rows=[insight_tests.row(1,distance='100',fuel_consumption='20',fuel_unit='L'),insight_tests.row(2,distance='200',fuel_consumption='20',fuel_unit='L')]
        result=self.summary(rows,'fuel')
        self.assertEqual(result['display'],'7.5');self.assertEqual(result['basis_display'],'300 km ／ 消費燃料 40 L')
        result=self.summary([insight_tests.row(3,distance='20',count='0')],'rate')
        self.assertEqual(result['basis_display'],'0回 ／ 対象距離 20 km')
        result=self.summary([insight_tests.row(4,definition_version=None)],'raw')
        self.assertEqual(result['basis_display'],'');self.assertIsNone(result['numerator'])

    def test_page_csv_and_pdf_show_the_same_source_quantities(self):
        response,_=self.render(self.base)
        self.assertIn('1回 ／ 対象距離 20 km',response.get_data(as_text=True))
        for view in ['comparison','breakdown']:
            exported=self.client.get('/safety/driving-reports/export.csv?period=all&breakdown=people&view='+view)
            rows=list(csv.DictReader(io.StringIO(exported.data.decode('utf-8-sig'))))
            self.assertTrue(all(None not in r for r in rows))
            row=next(r for r in rows if r['運行数']=='1')
            self.assertEqual(row['算出の元値'],'1回 ／ 対象距離 20 km')
            self.assertEqual((row['分子単位'],row['分母単位']),('回','km'))
        with patch('driving_report_management.export_pdf',return_value=b'pdf') as pdf:
            self.assertEqual(self.client.get('/safety/driving-reports/export.pdf?period=all&breakdown=people').status_code,200)
            self.assertIn('1回 ／ 対象距離 20 km',str(pdf.call_args))

    def test_ai_basis_is_program_generated_and_stays_in_authorized_office(self):
        _,context=self.render(self.base)
        from driving_report_insights import collect,driver_keys
        keys,_=driver_keys([self.a]);facts,_=collect([self.a],{},keys)
        evidence=build_evidence(context['insights'],facts,[])
        self.assertIn('1回 ／ 対象距離 20 km',evidence[0]['context'])
        self.assertNotIn('小山の人',str(evidence));self.assertNotIn(self.secret.id,evidence[0]['reports'])


if __name__=='__main__':unittest.main()
