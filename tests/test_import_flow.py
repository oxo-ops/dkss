"""End-to-end recovery, ownership, and duplicate contracts for every import family."""
from io import BytesIO
import hashlib
import json
from unittest.mock import patch
import unittest
import test_workflow_regressions as workflow
import test_document_import_queue as queue_tests
from test_inspection_document_ai import pdf_bytes
from dkss_app import document_import_queue as queue
from dkss_app.extensions import db
from dkss_app.models import VehicleDocumentImportDraft as Draft, VehicleOperationImportDraft as OperationDraft


class ImportFlowTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = workflow.WorkflowRegressionTests.setUp
    tearDown = workflow.WorkflowRegressionTests.tearDown
    send = queue_tests.DocumentImportQueueTests.send
    worker = queue_tests.DocumentImportQueueTests.worker
    inspection_form = workflow.WorkflowRegressionTests.inspection_form

    def completed_source(self, kind='inspection', company='TEST', creator='other-admin', source=None, records=1, imported=1):
        source = source or pdf_bytes()
        draft = Draft(id='completed-'+kind+'-'+company, batch_id='old-'+kind, company_code=company,
            created_by_username=creator, document_type=kind, source_filename='original.pdf',
            source_file=source, source_sha256=hashlib.sha256(source).hexdigest(), status='completed',
            preview_json=json.dumps({'records':[{}]*records}), result_json=json.dumps({'records':[{'record_id':i} for i in range(imported)]}))
        db.session.add(draft);db.session.commit()
        return draft

    def test_other_users_completed_source_is_rejected_before_ai_for_all_document_types(self):
        for kind in ('inspection', 'driving_report', 'maintenance'):
            self.completed_source(kind)
            with patch('dkss_app.vehicle_imports.vehicle_document_extractor', side_effect=AssertionError('must not call AI')):
                response = self.send(kind=kind)
            self.assertEqual(response.status_code, 409)
            self.assertIn('他の利用者', response.json['errors'][0]['message'])
        self.assertEqual(Draft.query.filter_by(status='queued').count(), 0)

    def test_other_company_and_partially_imported_sources_do_not_block_new_reading(self):
        self.completed_source(company='OTHER')
        self.completed_source(records=2, imported=1)
        self.assertEqual(self.send().status_code, 202)

    def test_mixed_batch_skips_completed_source_and_preserves_unregistered_file(self):
        original = pdf_bytes()
        self.completed_source(source=original)
        response = self.client.post('/vehicle/data-import/jobs', data={'document_type':'inspection',
            'document_files':[(BytesIO(original),'registered.pdf'),(BytesIO(original+b'\n%second'),'new.pdf')]},
            headers={'Accept':'application/json'})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json['total'], 1)
        self.assertEqual(response.json['files'][0]['ignored_files'], ['registered.pdf'])
        self.assertIn('登録済みの資料', self.client.get(response.json['page_url']).get_data(as_text=True))

    def test_document_cancel_fences_worker_and_returns_to_data_entry(self):
        receipt = self.send().json
        claimed = queue.claim_next()
        response = self.client.post('/vehicle/import-flow/cancel?kind=document&key='+receipt['batch_id'])
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.location, '/vehicle/data-import')
        self.assertFalse(queue.renew(*claimed))
        self.assertFalse(queue.finish(*claimed, error=ValueError('NO_INSPECTION_FOUND')))
        self.assertEqual(Draft.query.filter_by(batch_id=receipt['batch_id']).one().source_file, b'')

    def test_cancel_preserves_already_registered_record_and_original(self):
        receipt = self.send().json;self.worker();row=Draft.query.one()
        source=row.source_file
        self.assertEqual(self.client.post('/vehicle/data-import/'+receipt['batch_id']+'/confirm',data=self.inspection_form(row)).status_code,302)
        self.assertEqual(self.client.post('/vehicle/import-flow/cancel?kind=document&key='+receipt['batch_id']).status_code,303)
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(),1)
        self.assertEqual(Draft.query.one().source_file,source)

    def test_operation_cancel_is_scoped_and_clears_only_preview(self):
        for ident, user, status in [('mine','admin','preview'),('other','someone','preview'),('done','admin','completed')]:
            db.session.add(OperationDraft(id=ident,company_code='TEST',created_by_username=user,source_filename='test.csv',source_file=b'original',status=status))
        db.session.commit()
        self.assertEqual(self.client.post('/vehicle/import-flow/cancel?kind=operation&key=other').status_code,404)
        self.assertEqual(OperationDraft.query.filter_by(id='other').one().source_file,b'original')
        self.assertEqual(self.client.post('/vehicle/import-flow/cancel?kind=operation&key=mine').status_code,303)
        self.assertEqual(OperationDraft.query.filter_by(id='mine').one().status,'cancelled')
        self.assertEqual(self.client.post('/vehicle/import-flow/cancel?kind=operation&key=done').status_code,303)
        self.assertEqual(OperationDraft.query.filter_by(id='done').one().source_file,b'original')

    def test_browser_errors_have_shared_back_and_cancel_instead_of_blank_page(self):
        for path in ['/master/vehicles/import','/vehicle/operation-import','/vehicle/data-import/jobs']:
            response=self.client.post(path,data={},headers={'Accept':'text/html','Sec-Fetch-Mode':'navigate'})
            self.assertGreaterEqual(response.status_code,400)
            html=response.get_data(as_text=True)
            self.assertIn('importFlowError',html)
            self.assertIn('キャンセルして取込画面へ戻る',html)
            self.assertIn('元の取込画面へ戻る',html)

    def test_registration_cancel_and_csrf_are_not_a_get_mutation(self):
        self.assertEqual(self.client.get('/vehicle/import-flow/cancel?kind=registration').status_code,405)
        response=self.client.post('/vehicle/import-flow/cancel?kind=registration')
        self.assertEqual(response.location,'/master/vehicles/register')
        self.m.app.config['WTF_CSRF_ENABLED']=True
        try:
            response=self.client.post('/vehicle/import-flow/cancel?kind=registration')
            self.assertEqual(response.status_code,400)
            self.assertIn('取込画面へ戻る',response.get_data(as_text=True))
        finally:self.m.app.config['WTF_CSRF_ENABLED']=False

    def test_duplicate_preview_disables_registered_record_but_keeps_new_file_selected(self):
        receipt=self.send().json;self.worker();row=Draft.query.one()
        self.client.post('/vehicle/data-import/'+receipt['batch_id']+'/confirm',data=self.inspection_form(row))
        # The second receipt was accepted before another user completed the first one.
        other=Draft(id='later',batch_id='later-batch',company_code='TEST',created_by_username='admin',
            document_type='inspection',source_filename='later.pdf',source_file=row.source_file,
            source_sha256=row.source_sha256,status='preview',preview_json=row.preview_json,result_json='{}')
        db.session.add(other);db.session.commit()
        html=self.client.get('/vehicle/data-import/later-batch/preview').get_data(as_text=True)
        self.assertIn('すべての記録が同じ会社ですでに登録済み',html)
        self.assertIn('disabled aria-label="登録済みのため取り込み対象外"',html)
        self.assertIn('import-flow/cancel?kind=document',html)

    def workbook_bytes(self):
        from openpyxl import Workbook
        book=Workbook();sheet=book.active
        headers=['ID','車両番号','車体番号','車番','車種コード','車番・地域名','車番・分類','車番・ひらがな',
            '車両総重量','車体型式','初年度車検','車検期間終了日','車両メーカー','車両形状','最大積載量']
        values={'ID':'1','車両番号':'1','車体番号':'EXCEL-NEW','車番':'7001','車種コード':'1',
            '車番・地域名':'品川','車番・分類':'100','車番・ひらがな':'す','車両総重量':7995,
            '車体型式':'2KG-X','初年度車検':'2024-04','車検期間終了日':'2027-04-15','車両メーカー':'日野','車両形状':'キャブオーバ','最大積載量':3000}
        sheet.append(headers);sheet.append([values.get(name,'') for name in headers])
        stream=BytesIO();book.save(stream);return stream.getvalue()

    def test_excel_review_has_safe_get_resume_and_owner_scoped_cancellation(self):
        response=self.client.post('/master/vehicles/import',data={'excel_file':(BytesIO(self.workbook_bytes()),'vehicles.xlsx')},
            headers={'X-DKSS-Final-Submit':'1'})
        self.assertEqual(response.status_code,200,response.get_data(as_text=True))
        destination=response.json['preview_url']
        self.assertTrue(destination.startswith('/master/vehicles/import/review/'))
        self.assertEqual(self.client.get(destination).status_code,200)
        html=self.client.get(destination).get_data(as_text=True)
        self.assertIn('vehicle_excel_import_draft',html)
        row=Draft.query.filter_by(document_type='vehicle_excel').one()
        self.assertNotIn(row.id,self.client.get('/vehicle/data-import').get_data(as_text=True))
        response=self.client.post('/vehicle/import-flow/cancel?kind=registration&key='+row.id)
        self.assertEqual(response.status_code,303)
        self.assertEqual(self.client.get(destination).status_code,302)
        self.assertEqual(Draft.query.filter_by(id=row.id).one().source_file,b'')
        self.assertEqual(self.m.Vehicle.query.count(),1)

    def test_certificate_preflight_validates_without_registering_a_vehicle(self):
        data={'chassis_number':'CERT-NEW','plate_area':'品川','plate_class':'100','plate_kana':'す','plate_number':'7002',
            'gross_vehicle_weight':'7995','max_payload':'3000','first_registration_date':'2024-04','inspection_expiry':'2027-04-15'}
        response=self.client.post('/master/vehicles/new',data=data,headers={'X-DKSS-Validation-Only':'1'})
        self.assertEqual(response.status_code,200,response.get_data(as_text=True))
        self.assertEqual(response.json,{'ok':True})
        self.assertEqual(self.m.Vehicle.query.count(),1)
        data['chassis_number']=self.vehicle.chassis_number
        response=self.client.post('/master/vehicles/new',data=data,headers={'X-DKSS-Validation-Only':'1'})
        self.assertEqual(response.status_code,409)
        self.assertIn('登録',response.json['errors'][0]['message'])

    def test_excel_save_closes_review_and_replay_cannot_register_twice(self):
        self.m.db.session.add(self.m.VehicleType(company_code='TEST',name='トラック'))
        self.m.db.session.add(self.m.Office(company_code='TEST',name='本社'))
        self.m.db.session.commit()
        response=self.client.post('/master/vehicles/import',data={'excel_file':(BytesIO(self.workbook_bytes()),'vehicles.xlsx')},headers={'X-DKSS-Final-Submit':'1'})
        row=Draft.query.filter_by(document_type='vehicle_excel').one()
        data={'vehicle_excel_import_draft':row.id,'vehicle_type_code':'1','vehicle_type':'トラック',
            'plate_area':'品川','plate_class':'100','plate_kana':'す','plate_number':'7001','gross_vehicle_weight':'7995',
            'chassis_number':'EXCEL-NEW','model_code':'2KG-X','first_registration_date':'2024-04',
            'inspection_expiry':'2027-04-15','vehicle_name':'日野','body_type':'キャブオーバ',
            'max_payload':'3000','office':'本社','active_status':'有効'}
        first=self.client.post('/master/vehicles/import/confirm',data=data,headers={'X-DKSS-Final-Submit':'1'})
        self.assertEqual(first.status_code,200,first.get_data(as_text=True))
        self.assertEqual(self.m.Vehicle.query.count(),2)
        db.session.expire_all()
        self.assertEqual(Draft.query.filter_by(id=row.id).one().status,'completed')
        self.assertEqual(Draft.query.filter_by(id=row.id).one().source_file,b'')
        again=self.client.post('/master/vehicles/import/confirm',data=data,headers={'X-DKSS-Final-Submit':'1'})
        self.assertEqual(again.status_code,409)
        self.assertEqual(self.m.Vehicle.query.count(),2)
