"""Reader is display-only; existing original bytes and company gate are retained."""
import unittest
import os
from unittest.mock import patch
from pathlib import Path
from test_inspection_plans import InspectionPlanTests as Base
class PeriodicReaderTests(unittest.TestCase):
    setUpClass=classmethod(Base.setUpClass.__func__)
    tearDownClass=classmethod(Base.tearDownClass.__func__)
    setUp=Base.setUp
    tearDown=Base.tearDown
    import_record=Base.import_record
    upload_inspection=Base.upload_inspection
    inspection_form=Base.inspection_form
    def test_reader_and_original_preserve_records(self):
        if os.environ.get('READER_QA_DIR'):
            from io import BytesIO
            from reportlab.pdfgen import canvas
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.cidfonts import UnicodeCIDFont
            pdfmetrics.registerFont(UnicodeCIDFont('HeiseiKakuGo-W5'))
            buf=BytesIO();c=canvas.Canvas(buf,pagesize=(595,842));c.setFont('HeiseiKakuGo-W5',18)
            c.drawString(45,760,'日本語表示の技術検証');c.drawString(45,720,'新規架空の試験文章 12 ABC');c.save()
            with patch('test_inspection_document_ai.pdf_bytes',return_value=buf.getvalue()):
                record=self.import_record()
        else:
            record=self.import_record()
        draft=self.m.VehicleDocumentImportDraft.query.get(record.source_draft_id)
        before=(draft.source_file,draft.result_json,record.details_json,self.m.VehicleInspectionPlan.query.count(),self.m.Notification.query.count())
        url=f'/vehicle/periodic-inspections/{record.id}/source'
        original=self.client.get(url)
        response=self.client.get(url+'?view=reader')
        self.assertEqual(response.status_code,200)
        self.assertIn('text/html',response.content_type)
        html=response.get_data(as_text=True)
        self.assertIn('maintenance_invoice_pdf_viewer.mjs',html)
        self.assertIn('data-source-base="'+url+'"',html)
        self.assertIn('原本を別タブで開く',html)
        self.assertIn('no-store',response.headers['Cache-Control'])
        if os.environ.get('READER_QA_DIR'):
            out=Path(os.environ['READER_QA_DIR']);out.mkdir(parents=True,exist_ok=True)
            (out/'reader.html').write_text(html)
            (out/'source.pdf').write_bytes(original.data)
        self.assertEqual(original.data,draft.source_file)
        self.assertEqual(self.client.get(url).data,original.data)
        self.assertEqual(before,(draft.source_file,draft.result_json,record.details_json,self.m.VehicleInspectionPlan.query.count(),self.m.Notification.query.count()))
        record.company_code='OTHER'
        self.m.db.session.commit()
        self.assertEqual(self.client.get(url+'?view=reader').status_code,404)
        self.assertEqual(self.client.get(url).status_code,404)
del Base
if __name__=='__main__':unittest.main()
