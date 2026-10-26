"""OCR candidates remain reviewable; invalid facts never become zero or invented pages."""
import copy,json,os,unittest
from unittest.mock import patch
import driving_report_ai as ai
from driving_report_validation import prepare_candidates,DrivingReportValidationError
from test_driving_report_ai import extraction
from test_inspection_document_ai import pdf_bytes,Response

class CandidateValidationTests(unittest.TestCase):
    def prepare(self,data,pages=5):
        prepare_candidates(data,pages,ai.TEXT_FIELDS,ai.ITEM_FIELDS,ai.COLLECTIONS);ai._validate(data);return data['records'][0]
    def test_explicit_date_km_format_and_long_timestamp_reach_review(self):
        data=extraction();r=data['records'][0]
        r.update(operation_date='２０２６年９月２２日',operation_end_date='2026/9/22',mileage='198,243.24 km',operation_start_time='2026-09-22T05:21:34+09:00')
        original=copy.deepcopy(r);r=self.prepare(data)
        self.assertEqual(r['operation_date'],'2026-09-22');self.assertEqual(r['mileage'],'198243.24')
        self.assertEqual(r['operation_start_time'],'2026-09-22T05:21:34+09:00')
        self.assertEqual(r['_ocr_raw_candidate'],original)
        preview=ai.build_driving_report_preview(data,[])
        self.assertEqual(preview['records'][0]['_ocr_issues'],r['_ocr_issues'])
    def test_uncertain_values_are_not_zero_and_miles_are_not_converted(self):
        data=extraction();r=data['records'][0]
        r.update(operation_date='2026-09',distance='12.0 mi',mileage='未記入',report_scope='日別')
        r['report_items'][0].update(value='0.0回/h',numerator='不明',denominator='NaN',status='invented')
        r=self.prepare(data)
        for key in ['operation_date','distance','mileage']:self.assertIsNone(r[key])
        self.assertEqual(r['report_scope'],'daily');self.assertEqual(r['report_items'][0]['status'],'unknown')
        self.assertEqual(r['report_items'][0]['raw_result'],'0.0回/h')
        self.assertIn('12.0 mi',json.dumps(r['_ocr_issues'],ensure_ascii=False))
    def test_explicit_zero_unknown_scope_and_no_unearned_confirmation(self):
        data=extraction();r=data['records'][0];r['report_scope']='custom';r['distance']='0';r['report_items'][0].update(value='0',status='confirmed')
        r=self.prepare(data)
        self.assertEqual(r['distance'],'0');self.assertEqual(r['report_scope'],'unknown')
        self.assertEqual(r['report_items'][0]['value'],'0');self.assertEqual(r['report_items'][0]['status'],'candidate')
    def test_cross_page_detail_preserved_and_invalid_page_quarantined(self):
        data=extraction();r=data['records'][0];r['events']=[{**r['report_items'][0],'item_name':'明細2頁','source_page':2},{**r['report_items'][0],'item_name':'範囲外','source_page':99}]
        r=self.prepare(data)
        self.assertEqual(r['source_pages'],[1,2]);self.assertEqual(len(r['events']),1)
        self.assertIn('範囲外',json.dumps(r['_ocr_issues'],ensure_ascii=False))
        data=extraction();data['records'][0]['source_pages']=[99]
        with self.assertRaisesRegex(DrivingReportValidationError,r'records\[0\].source_pages'):self.prepare(data)
    def test_strict_validation_reports_field_without_raw_value(self):
        data=extraction();data['records'][0]['distance']='private-value'
        with self.assertRaises(DrivingReportValidationError) as got:ai._validate(data)
        self.assertIn('distance',str(got.exception));self.assertNotIn('private-value',str(got.exception))
        self.assertIn('確認箇所',got.exception.user_message)
    def test_full_transport_one_request_preserves_candidates_no_retry(self):
        source=pdf_bytes();data=extraction(source);r=data['records'][0]
        r.update(mileage='198,243.24',operation_start_time='2026-09-22T05:21:34+09:00')
        result={'status':'completed','output':[{'content':[{'type':'output_text','text':json.dumps(data)}]}]}
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test-only'}),patch('maintenance_invoice_ai.urllib.request.urlopen',return_value=Response(result)) as call:
            got=ai.extract_driving_reports(source)
        self.assertEqual(call.call_count,1);self.assertEqual(got['records'][0]['mileage'],'198243.24')
        self.assertTrue(got['records'][0]['_ocr_issues'])
    def test_long_text_and_unknown_item_name_are_retained(self):
        data=extraction();r=data['records'][0];r['report_items'][0].update(item_name=None,notes='あ'*1200)
        r=self.prepare(data)
        self.assertEqual(r['report_items'][0]['item_name'],'項目名不明（要確認）')
        self.assertEqual(r['_ocr_raw_candidate']['report_items'][0]['notes'],'あ'*1200)

class CandidateRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_workflow_regressions as workflow
        workflow.WorkflowRegressionTests.setUpClass();cls.m=workflow.WorkflowRegressionTests.m
    @classmethod
    def tearDownClass(cls):
        import test_workflow_regressions as workflow
        workflow.WorkflowRegressionTests.tearDownClass()
    def setUp(self):
        import test_workflow_regressions as workflow
        workflow.WorkflowRegressionTests.setUp(self)
    def tearDown(self):
        import test_workflow_regressions as workflow
        workflow.WorkflowRegressionTests.tearDown(self)
    def test_reviewable_issues_survive_confirmation(self):
        from io import BytesIO
        import test_workflow_regressions as workflow
        source=pdf_bytes();data=extraction(source);r=data['records'][0]
        r.update(operation_date='2026年9月22日',distance='12.0 mi',operation_start_time='2026-09-22T05:21:34+09:00')
        prepare_candidates(data,1,ai.TEXT_FIELDS,ai.ITEM_FIELDS,ai.COLLECTIONS)
        with patch.object(self.m,'extract_driving_reports',return_value=data):
            response=self.client.post('/vehicle/data-import',data={'document_type':'driving_report','document_files':(BytesIO(source),'review.pdf')})
        self.assertEqual(response.status_code,302)
        draft=self.m.VehicleDocumentImportDraft.query.one();page=self.client.get(response.location)
        self.assertEqual(page.status_code,200);self.assertIn('12.0 mi',page.get_data(as_text=True));self.assertIn('読取時に要確認',page.get_data(as_text=True))
        form=workflow.WorkflowRegressionTests.inspection_form(self,draft)
        response=self.client.post(f'/vehicle/data-import/{draft.batch_id}/confirm',data=form)
        self.assertEqual(response.status_code,302)
        row=self.m.VehicleDrivingReportRecord.query.one();p=json.loads(row.details_json)
        self.assertIsNone(p['distance']);self.assertEqual(p['_ocr_raw_candidate']['distance'],'12.0 mi')
        self.assertEqual(p['operation_start_time'],'2026-09-22T05:21:34+09:00')
    def test_both_upload_paths_show_specific_failure_without_candidate_value(self):
        from io import BytesIO
        for suffix in ['', '/progress']:
            with self.subTest(suffix=suffix),patch.object(self.m,'extract_driving_reports',side_effect=DrivingReportValidationError('records[2].source_pages','PDFに存在しないページ番号')):
                response=self.client.post('/vehicle/data-import'+suffix,data={'document_type':'driving_report','document_files':(BytesIO(pdf_bytes()),'bad.pdf')},headers={'X-DKSS-Final-Submit':'1'})
                if suffix:text=response.get_data(as_text=True)
                else:text=json.dumps(response.get_json(),ensure_ascii=False)
                self.assertIn('確認箇所',text);self.assertIn('記録3',text);self.assertIn('原本ページ',text)
                self.assertNotIn('records[2]',text)
