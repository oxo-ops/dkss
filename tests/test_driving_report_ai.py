"""Report OCR schema and original-value preservation; network is mocked."""
import copy
import hashlib
import json
import os
import unittest
from unittest.mock import patch
import driving_report_ai as ai
from test_inspection_document_ai import pdf_bytes, Response


def extraction(source=None):
    row = {key: None for key in ai.TEXT_FIELDS}
    row.update(report_scope='trip', registration_number='三河100き4312', operation_date='2026-09-22',
               operation_end_date='2026-09-22', operation_start_time='05:21:34',
               operation_end_time='14:48:38', driver_name='試験乗務員', office_name='安城営業所',
               start_mileage='198141.39', mileage='198243.24', distance='101.85',
               driving_time='2:12:40', handling_time='2:34:37', notes='車間をよくとる。',
               source_pages=[1], content='安全運転日報', warnings=[],
               report_items=[{'category':'安全運転分析','item_name':'速度オーバー回数',
                   'raw_result':'0.0回/h','score':'40','result_text':'A',
                   'notes':'今後も余裕を持って運転してください','source_page':1}])
    return {'schema_version':1, 'source_sha256':hashlib.sha256(source or pdf_bytes()).hexdigest(),
            'records':[row], 'warnings':[]}


class DrivingReportAITests(unittest.TestCase):
    def test_shared_transport_schema_and_source_hash(self):
        source = pdf_bytes(); data = extraction(source)
        result = {'status':'completed', 'output':[{'content':[{'type':'output_text','text':json.dumps(data)}]}]}
        with patch.dict(os.environ, {'OPENAI_API_KEY':'test-only'}), patch('maintenance_invoice_ai.urllib.request.urlopen', return_value=Response(result)) as call:
            got = ai.extract_driving_reports(source)
        sent = json.loads(call.call_args.args[0].data)
        self.assertEqual(sent['text']['format']['name'], 'safety_driving_reports')
        self.assertFalse(sent['store'])
        self.assertEqual(got['source_sha256'], data['source_sha256'])
        self.assertEqual(got['records'][0]['report_items'][0]['raw_result'], '0.0回/h')

    def test_no_inferred_odometer_date_or_judgment(self):
        data = extraction(); data['records'][0].update(operation_date=None, mileage=None)
        got = ai.build_driving_report_preview(data, [])
        self.assertEqual(got['records'][0]['record_date'], '')
        self.assertIsNone(got['records'][0]['mileage'])
        self.assertNotIn('operation_judgment', got['records'][0])
        got['records'][0]['report_items'][0]['score'] = '0'
        self.assertEqual(got['original_records'][0]['report_items'][0]['score'], '40')

    def test_invalid_dates_numbers_and_page_references(self):
        for key, value in [('operation_date','2026-02-30'), ('operation_end_date','2026-09-21'),
                           ('mileage','NaN'), ('distance','-1'), ('source_pages',[True])]:
            data = extraction(); data['records'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): ai._validate(data)
        data = extraction(); data['records'][0]['report_items'][0]['source_page'] = 2
        with self.assertRaises(ValueError): ai._validate(data)
        with self.assertRaisesRegex(ValueError,'NO_DRIVING_REPORT_FOUND'):
            ai._validate({'records':[], 'warnings':[]})
        with self.assertRaisesRegex(ValueError,'INVALID_DRIVING_REPORT_PDF'):
            ai.extract_driving_reports(b'%PDF-broken')
        data = extraction(); data['records'][0]['source_pages'] = [1,2]
        with patch.object(ai,'extract_vehicle_document',return_value=data):
            with self.assertRaisesRegex(ValueError,'INVALID_SOURCE_PAGES'): ai.extract_driving_reports(pdf_bytes())

    def test_matching_uses_existing_vehicle_rules(self):
        data = extraction()
        choice = {'id':1,'number':'三河 100 き 4312','chassis_number':''}
        self.assertEqual(ai.build_driving_report_preview(data,[choice])['records'][0]['vehicle_record_id'],1)
        for choices in [[{**choice,'deleted':True}], [choice,{**choice,'id':2}]]:
            self.assertIsNone(ai.build_driving_report_preview(data,choices)['records'][0]['vehicle_record_id'])
