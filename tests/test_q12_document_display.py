"""Document preview dependencies; synthetic DB and source bytes only."""
import hashlib
from io import BytesIO
import json
import unittest
from datetime import datetime
from PIL import Image
from pypdf import PdfWriter
import test_workflow_regressions as workflow

class DocumentDisplayTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = workflow.WorkflowRegressionTests.setUp
    tearDown = workflow.WorkflowRegressionTests.tearDown

    def seed(self, extension):
        out = BytesIO()
        if extension == 'pdf':
            writer = PdfWriter()
            writer.add_blank_page(width=595, height=842)
            writer.write(out)
        else:
            Image.new('RGB', (160,100), 'blue').save(out, format='JPEG')
        source = out.getvalue()
        draft = self.m.VehicleDocumentImportDraft(id='q12-doc', batch_id='q12-batch',
            company_code='TEST', created_by_username='admin', document_type='maintenance',
            source_filename='q12-doc.'+extension, source_file=source,
            source_sha256=hashlib.sha256(source).hexdigest(), status='completed',
            completed_at=datetime.now(), result_json=json.dumps({'records':[{'vehicle_record_id':self.vehicle.id}]}))
        self.m.db.session.add(draft)
        self.m.db.session.commit()
        return source

    def page(self, selection):
        response = self.client.get(f'/vehicle/karte/{self.vehicle.id}/documents?document={selection}')
        self.assertEqual(response.status_code,200)
        return response.get_data(as_text=True)

    def test_image_keeps_original_without_pdf_dependency(self):
        source = self.seed('jpg')
        html = self.page('document:q12-doc')
        self.assertIn('kd-image-preview',html)
        self.assertIn('vehicle_karte_documents.js',html)
        self.assertNotIn('maintenance_invoice_pdf_viewer.mjs',html)
        response = self.client.get(f'/vehicle/karte/{self.vehicle.id}/documents/q12-doc/source?download=1')
        self.assertEqual(response.data,source)
        self.assertIn('no-store',response.headers['Cache-Control'])

    def test_pdf_keeps_viewer_and_original(self):
        source = self.seed('pdf')
        html = self.page('document:q12-doc')
        self.assertIn('maintenance_invoice_pdf_viewer.mjs',html)
        self.assertIn('data-pdf-next',html)
        self.assertIn('data-pdf-zoom',html)
        response = self.client.get(f'/vehicle/karte/{self.vehicle.id}/documents/q12-doc/source?download=1')
        self.assertEqual(response.data,source)

    def test_closed_and_empty_preview_do_not_fetch_pdf_dependencies(self):
        self.assertNotIn('maintenance_invoice_pdf_viewer.mjs',self.page('closed'))
        self.seed('pdf')
        html = self.page('closed')
        self.assertNotIn('maintenance_invoice_pdf_viewer.mjs',html)
        self.assertIn('kd-download',html)

    def test_vehicle_switcher_and_header_share_truck_derivatives(self):
        from html.parser import HTMLParser
        from unittest.mock import patch
        class Images(HTMLParser):
            def __init__(self):
                super().__init__()
                self.images = []
            def handle_starttag(self, tag, attrs):
                if tag == 'img':
                    self.images.append(dict(attrs))
        self.vehicle.type = 'トラック'
        car = self.m.Vehicle(company_code='TEST', chassis_number='Q12-CAR', type='乗用車')
        self.m.db.session.add(car)
        self.m.db.session.commit()
        with patch('dkss_app.vehicle_karte.get_vehicle_karte_usage_vehicles', return_value=[self.vehicle, car]):
            html = self.page('closed')
        parsed = Images()
        parsed.feed(html)
        trucks = [i for i in parsed.images if 'truck-display' in i.get('src', '')]
        self.assertEqual(len(trucks), 2)
        self.assertEqual(trucks[0]['src'], trucks[1]['src'])
        self.assertEqual(trucks[0]['srcset'], trucks[1]['srcset'])
        self.assertIn('4x', trucks[0]['srcset'])
        self.assertNotIn('/static/icons/truck.png', html)
        cars = [i for i in parsed.images if '/static/icons/car.png' in i.get('src', '')]
        self.assertEqual(len(cars), 1)
        self.assertNotIn('srcset', cars[0])
