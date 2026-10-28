"""Real queue/routes and transactions; only external classification/OCR are mocked."""
from identity_fixture import identity_for
import hashlib
import json
import re
from io import BytesIO
from uuid import uuid4
from unittest import TestCase
from unittest.mock import patch
import test_workflow_regressions as workflow
from test_inspection_document_ai import extraction, pdf_bytes
from dkss_app import document_import_queue as queue, vehicle_imports
from dkss_app.extensions import db
from dkss_app.models import VehicleDocumentImportDraft as Draft
from document_type_detection import text_detection, validate_detection


class DocumentKindRecoveryTests(TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = workflow.WorkflowRegressionTests.setUp
    tearDown = workflow.WorkflowRegressionTests.tearDown
    upload_inspection = workflow.WorkflowRegressionTests.upload_inspection
    inspection_form = workflow.WorkflowRegressionTests.inspection_form

    def send(self, kind='inspection', source=None):
        response=self.client.post('/vehicle/data-import/jobs',data={'document_type':kind,
            'document_files':(BytesIO(source or pdf_bytes()),'original.pdf')},headers={'Accept':'application/json'})
        self.assertEqual(response.status_code,202,response.get_data(as_text=True))
        return response.json

    def invoice(self, source):
        import maintenance_invoice_ai as ai
        row={key:None for key in ai.record_properties}
        row.update(source_pages=[1],line_items=[],fees=[],warnings=[],entry_date='2026-08-01',
            completion_date='2026-08-02',content='故障修理',total_cost='1100',maintenance_category='突発修理')
        return dict(records=[row],warnings=[],source_sha256=hashlib.sha256(source).hexdigest(),schema_version=1)

    def worker(self, kinds=None, certainty='clear', invoice=False, fail=False):
        def extract(source,filename=None,progress_callback=None):
            if fail:raise RuntimeError('OPENAI_NETWORK_OR_TIMEOUT')
            return self.invoice(source) if invoice else extraction(source)
        with patch.object(queue,'detect_document_types',return_value={
            'types':kinds or ['inspection'],'certainty':certainty,'supported':True}) as classify, patch.object(
            vehicle_imports,'vehicle_document_extractor',return_value=extract) as factory:
            result=queue.process_one(self.m.app)
        return result,classify,factory

    def kind_post(self,row,kind,**extra):
        page=self.client.get('/vehicle/data-import/'+row.id+'/kind')
        self.assertEqual(page.status_code,200,page.get_data(as_text=True))
        token=re.search(r'name="kind_token" value="([^"]+)"',page.get_data(as_text=True)).group(1)
        return self.client.post('/vehicle/data-import/'+row.id+'/kind',data={
            'kind_token':token,'document_type':kind,**extra})

    def test_wrong_card_is_routed_before_extraction_and_notice_survives_preview(self):
        receipt=self.send()
        result,classify,factory=self.worker(['maintenance'],invoice=True)
        self.assertTrue(result);factory.assert_called_once_with('maintenance')
        row=Draft.query.one()
        self.assertEqual((row.document_type,row.status),('maintenance','preview'))
        self.assertEqual(row.source_file,pdf_bytes())
        html=self.client.get('/vehicle/data-import/'+receipt['batch_id']+'/preview').get_data(as_text=True)
        self.assertIn('請求書・整備資料として読み取りました。',html)
        self.assertIn('資料の種類を変更',html)

    def test_ambiguous_source_waits_and_user_choice_reuses_source_without_classifier(self):
        receipt=self.send();_,_,factory=self.worker(['inspection','maintenance'],certainty='uncertain')
        factory.assert_not_called()
        row=Draft.query.one();self.assertEqual(row.status,'type_review')
        status=self.client.get(receipt['status_url']).json
        self.assertEqual(status['needs_review'],1);self.assertTrue(status['finished'])
        self.assertIn(receipt['batch_id'],self.client.get('/vehicle/data-import').get_data(as_text=True))
        source=row.source_file
        result=self.kind_post(row,'maintenance')
        self.assertEqual(result.status_code,303)
        _,classify,factory=self.worker(invoice=True)
        classify.assert_not_called();factory.assert_called_once_with('maintenance')
        db.session.expire_all();self.assertEqual(db.session.get(Draft,row.id).source_file,source)
        self.assertEqual(Draft.query.count(),1)

    def test_cancel_only_selected_source_and_stale_worker_cannot_publish(self):
        receipt=self.send();other=self.send(source=pdf_bytes(987))
        first=Draft.query.filter_by(batch_id=receipt['batch_id']).one()
        claimed=queue.claim_next()
        self.assertEqual(claimed[0],first.id)
        response=self.kind_post(first,'inspection',action='cancel')
        self.assertEqual(response.status_code,303)
        self.assertFalse(queue.finish(*claimed,extraction=extraction(pdf_bytes())))
        self.assertIsNone(queue.route_detection(*claimed,{'types':['maintenance'],'certainty':'clear','supported':True}))
        self.assertEqual(db.session.get(Draft,first.id).source_file,b'')
        self.assertEqual(Draft.query.filter_by(batch_id=other['batch_id']).one().status,'queued')

    def test_clear_mixed_file_creates_one_job_per_kind_and_no_split_on_retries(self):
        receipt=self.send()
        self.worker(['inspection','maintenance'])
        self.assertEqual(Draft.query.count(),2)
        child=Draft.query.filter_by(document_type='maintenance').one()
        self.assertEqual(child.source_file,pdf_bytes())
        self.worker(invoice=True,fail=True)
        db.session.expire_all()
        self.assertEqual(db.session.get(Draft,child.id).status,'read_error')
        queue.retry_failed(receipt['batch_id'],'TEST','admin')
        self.worker(invoice=True)
        self.assertEqual(Draft.query.count(),2)
        self.assertEqual(self.client.get(receipt['status_url']).json['succeeded'],2)

    def test_destination_duplicate_is_skipped_without_extraction(self):
        source=pdf_bytes()
        db.session.add(Draft(id=str(uuid4()),batch_id=str(uuid4()),company_code='TEST',
            created_by_username='other-admin',document_type='maintenance',source_filename='registered.pdf',
            source_file=source,source_sha256=hashlib.sha256(source).hexdigest(),status='completed',
            preview_json=json.dumps({'records':[{}]}),result_json=json.dumps({'records':[{'record_id':1}]})))
        db.session.commit()
        receipt=self.send('inspection',source)
        _,_,factory=self.worker(['maintenance'],invoice=True);factory.assert_not_called()
        row=Draft.query.filter_by(batch_id=receipt['batch_id']).one()
        self.assertEqual(row.status,'skipped')
        self.assertIn('登録済み',self.client.get(receipt['status_url']).json['files'][0]['message'])

    def test_other_creator_company_and_csrf_cannot_change_type(self):
        self.send();row=Draft.query.one()
        stamp=self.m.User.query.filter_by(company_code='TEST',username='admin').one().password_changed_at
        self.m.db.session.add(self.m.User(company_code='TEST',username='other',role='admin',password='unused',last_name='検証',password_changed_at=stamp))
        db.session.commit()
        with self.client.session_transaction() as state:state['username']='other'; state['account_identity'] = identity_for(state.get('company_code'), state.get('username'))
        self.assertEqual(self.client.get('/vehicle/data-import/'+row.id+'/kind').status_code,404)
        with self.client.session_transaction() as state:state['username']='admin'; state['account_identity'] = identity_for(state.get('company_code'), state.get('username'))
        self.m.app.config['WTF_CSRF_ENABLED']=True
        try:self.assertEqual(self.client.post('/vehicle/data-import/'+row.id+'/kind',data={'action':'cancel'}).status_code,400)
        finally:self.m.app.config['WTF_CSRF_ENABLED']=False
        self.assertEqual(row.status,'queued')

    def test_registered_correction_is_atomic_requires_confirmation_and_retains_history(self):
        source=pdf_bytes();data=extraction(source)
        data['records'][0].update(inspection_type='other',next_inspection_date=None,next_inspection_month=None)
        self.upload_inspection(data=data,source=source)
        original=Draft.query.one();form=self.inspection_form(original)
        form['inspection_type_'+original.id+'_0']='other'
        self.assertEqual(self.client.post('/vehicle/data-import/'+original.batch_id+'/confirm',data=form).status_code,302)
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(),1)
        response=self.kind_post(original,'maintenance')
        self.assertEqual(response.status_code,303,response.get_data(as_text=True))
        self.worker(invoice=True)
        replacement=Draft.query.filter(Draft.id!=original.id).one()
        key=replacement.id+'_0'
        form={'include':key,'vehicle_'+key:str(self.vehicle.id),'date_'+key:'2026-08-01','content_'+key:'故障修理'}
        url='/vehicle/data-import/'+replacement.batch_id+'/confirm'
        self.assertEqual(self.client.post(url,data=form).status_code,400)
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(),1)
        self.assertEqual(self.m.VehicleMaintenanceRecord.query.count(),0)
        form['confirm_kind_correction']='yes'
        response=self.client.post(url,data=form)
        self.assertEqual(response.status_code,302,response.get_data(as_text=True))
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(),0)
        self.assertEqual(self.m.VehicleMaintenanceRecord.query.count(),1)
        self.assertEqual(str(self.m.VehicleMaintenanceRecord.query.one().total_cost),'1100.00')
        self.assertEqual(original.status,'superseded');self.assertEqual(original.source_file,source)
        self.assertEqual(json.loads(original.result_json)['correction_history']['replacement_draft_id'],replacement.id)
        self.assertEqual(self.client.post(url,data=form).status_code,409)


class DetectionValidationTests(TestCase):
    def test_classifier_does_not_trust_empty_or_invalid_output(self):
        for data in [{'types':[],'certainty':'clear','supported':True},
                     {'types':['unknown'],'certainty':'clear','supported':True}]:
            with self.assertRaises(ValueError):validate_detection(data)
        validate_detection({'types':[],'certainty':'uncertain','supported':False})

    def test_invoice_mentioning_periodic_work_is_not_a_periodic_record(self):
        from pypdf import PdfWriter, PdfReader
        from types import SimpleNamespace
        pages=[SimpleNamespace(extract_text=lambda:'請求書\n3か月点検費用\n工賃\n合計10000円')]
        with patch('pypdf.PdfReader',return_value=SimpleNamespace(is_encrypted=False,pages=pages)):
            self.assertEqual(text_detection(b'%PDF-test')['types'],['maintenance'])
