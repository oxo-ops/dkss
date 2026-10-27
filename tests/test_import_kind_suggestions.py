"""Type recovery on the existing stream, plus visible registration selectors."""
from io import BytesIO
from html.parser import HTMLParser
import json
import unittest
from unittest.mock import patch
from flask import render_template
import test_workflow_regressions as fixtures
from test_inspection_document_ai import pdf_bytes, extraction


class SelectLocation(HTMLParser):
    def __init__(self):
        super().__init__(); self.stack = []; self.selects = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'select' and attrs.get('name', '').startswith('vehicle_'):
            self.selects.append([dict(a) for _, a in self.stack])
        if tag not in {'input', 'br', 'hr', 'img', 'meta', 'link'}:
            self.stack.append((tag, attrs))
    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]; break


class ImportKindSuggestionTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = fixtures.WorkflowRegressionTests.setUp
    tearDown = fixtures.WorkflowRegressionTests.tearDown

    def stream(self, count=1):
        response = self.client.post('/vehicle/data-import/progress', data={
            'document_type': 'inspection',
            'document_files': [(BytesIO(pdf_bytes() + b'\n%' + str(i).encode()), 'file'+str(i)+'.pdf') for i in range(count)],
        })
        self.assertEqual(response.status_code, 200)
        return [json.loads(line) for line in response.get_data(as_text=True).splitlines()]

    def assert_no_import(self):
        self.assertEqual(self.m.VehicleDocumentImportDraft.query.count(), 0)
        self.assertEqual(self.m.VehicleMaintenanceRecord.query.count(), 0)
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(), 0)

    def test_wrong_card_suggests_correct_kind_before_extracting_or_saving(self):
        with patch('document_type_detection.text_detection', return_value={
            'types':['maintenance'], 'certainty':'clear', 'supported':True}), patch(
            'dkss_app.vehicle_imports.vehicle_document_extractor') as factory:
            events = self.stream()
        factory.assert_not_called()
        self.assertEqual(events[-1]['phase'], 'type_mismatch')
        self.assertEqual((events[-1]['document_type'], events[-1]['file_index'], events[-1]['filename']),
                         ('maintenance', 0, 'file0.pdf'))
        self.assert_no_import()

    def test_wrong_later_file_leaves_entire_batch_unimported(self):
        detect = lambda kind: {'types':[kind], 'certainty':'clear', 'supported':True}
        with patch('document_type_detection.text_detection', side_effect=[detect('inspection'), detect('maintenance')]), patch(
            'dkss_app.vehicle_imports.vehicle_document_extractor') as factory:
            events = self.stream(2)
        factory.assert_not_called()
        self.assertEqual(events[-1]['file_index'], 1)
        self.assert_no_import()

    def test_unreadable_text_can_suggest_kind_after_no_matching_document(self):
        with patch('document_type_detection.text_detection', return_value=None), patch(
            'document_type_detection.detect_document_types', return_value={
                'types':['maintenance'], 'certainty':'clear', 'supported':True}), patch(
            'dkss_app.vehicle_imports.vehicle_document_extractor', return_value=lambda *a,**k: (_ for _ in ()).throw(ValueError('NO_INSPECTION_FOUND'))):
            events = self.stream()
        self.assertEqual(events[-1]['phase'], 'type_mismatch')
        self.assertEqual(events[-1]['document_type'], 'maintenance')
        self.assert_no_import()

    def test_uncertain_classification_never_redirects_to_guessed_kind(self):
        with patch('document_type_detection.text_detection', return_value={
            'types':['maintenance','inspection'], 'certainty':'uncertain', 'supported':True}), patch(
            'dkss_app.vehicle_imports.vehicle_document_extractor', return_value=lambda source,**k: extraction(source)):
            events = self.stream()
        self.assertEqual(events[-1]['phase'], 'complete')
        self.assertEqual(self.m.VehicleDocumentImportDraft.query.one().document_type, 'inspection')

    def test_vehicle_selector_is_unique_and_above_collapsible_editors_for_all_kinds(self):
        for name in ('maintenance_invoice_fields.html', 'inspection_document_fields.html', 'driving_report_fields.html'):
            with self.subTest(template=name), self.m.app.test_request_context('/'):
                html = render_template(name, record={}, row_key='test_0',
                    document={'id':'test', 'preview':{}}, batch_id='test-batch', vehicle_choices=[], cost_offices=[])
                parser = SelectLocation(); parser.feed(html)
                self.assertEqual(len(parser.selects), 1)
                self.assertTrue(any('invoice-registration-target' in a.get('class','') for a in parser.selects[0]))
                self.assertFalse(any('invoice-info-editor' in a.get('class','') for a in parser.selects[0]))
                self.assertLess(html.index('invoice-registration-target'), html.index('invoice-overview-details'))
                self.assertIn('登録先の車両', html)
