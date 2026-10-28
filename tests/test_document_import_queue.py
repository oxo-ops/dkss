"""Durable OCR queue contracts; external AI is mocked, all writes are isolated."""
from identity_fixture import identity_for
from io import BytesIO
import hashlib
import json
import threading
from datetime import timedelta
from uuid import uuid4
from unittest.mock import patch
import unittest
from sqlalchemy import event
from sqlalchemy.orm import load_only
import test_workflow_regressions as workflow
from test_inspection_document_ai import extraction, pdf_bytes
from dkss_app import document_import_queue as queue
from dkss_app import vehicle_imports
from dkss_app.extensions import db
from dkss_app.models import VehicleDocumentImportDraft as Draft


class DocumentImportQueueTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = workflow.WorkflowRegressionTests.setUp
    tearDown = workflow.WorkflowRegressionTests.tearDown
    inspection_form = workflow.WorkflowRegressionTests.inspection_form

    def send(self, count=1, key=None, kind='inspection', source=None):
        source = source or pdf_bytes()
        return self.client.post('/vehicle/data-import/jobs', data={
            'document_type':kind, 'upload_key':key or str(uuid4()),
            'document_files':[(BytesIO(source),f'document-{i}.pdf') for i in range(count)]},
            headers={'Accept':'application/json'})

    def worker(self, failure=None):
        def extract(source, filename=None, progress_callback=None):
            if progress_callback:progress_callback({'phase':'ai_accepted'})
            if failure:raise failure
            return extraction(source)
        with patch.object(vehicle_imports, 'vehicle_document_extractor',return_value=extract), patch.object(
            queue, 'detect_document_types', return_value={'types':['inspection'],'certainty':'clear','supported':True}):
            return queue.process_one(self.m.app)

    def status(self, receipt):
        return self.client.get(receipt['status_url']).json

    def test_receipt_is_saved_before_ai_runs_and_survives_new_client(self):
        with patch.object(vehicle_imports,'vehicle_document_extractor',side_effect=AssertionError('AI in HTTP request')):
            response=self.send(3)
        self.assertEqual(response.status_code,202)
        receipt=response.json
        self.assertEqual(Draft.query.count(),3)
        self.assertEqual(self.status(receipt)['completed'],0)
        page=self.client.get(receipt['page_url'])
        self.assertEqual(page.status_code,200)
        self.assertIn('画面を閉じても',page.get_data(as_text=True))
        self.assertTrue(self.worker())
        self.assertEqual(self.status(receipt)['succeeded'],1)
        self.assertIn(receipt['batch_id'],self.client.get('/vehicle/data-import').get_data(as_text=True))

    def test_fifty_files_run_serially_and_reach_review(self):
        receipt=self.send(50).json
        for i in range(50):self.assertTrue(self.worker())
        status=self.status(receipt)
        self.assertTrue(status['finished'])
        self.assertEqual(status['succeeded'],50)
        self.assertTrue(status['preview_ready'])
        self.assertEqual(self.client.get(status['preview_url']).status_code,200)
        self.assertFalse(self.worker())

    def test_successful_files_are_kept_when_another_file_fails(self):
        receipt=self.send(2).json
        self.worker(failure=RuntimeError('OPENAI_NETWORK_OR_TIMEOUT: secret-detail'))
        self.worker()
        status=self.status(receipt)
        self.assertEqual((status['succeeded'],status['failed']),(1,1))
        self.assertNotIn('secret-detail',json.dumps(status))
        self.assertTrue(status['preview_ready'])
        self.assertIn('一部の資料',self.client.get(status['preview_url']).get_data(as_text=True))

    def test_retry_only_failed_rows_preserves_finished_preview(self):
        receipt=self.send(2).json
        self.worker(failure=ValueError('NO_INSPECTION_FOUND'))
        self.worker()
        ready=Draft.query.filter_by(status='preview').one()
        before=ready.preview_json
        response=self.client.post(receipt['page_url']+'/retry')
        self.assertEqual(response.status_code,303)
        self.assertEqual(self.status(receipt)['succeeded'],1)
        self.worker()
        db.session.expire_all()
        self.assertEqual(Draft.query.filter_by(id=ready.id).one().preview_json,before)
        self.assertEqual(self.status(receipt)['succeeded'],2)

    def test_duplicate_receipt_does_not_enqueue_or_extract_twice(self):
        key=str(uuid4())
        first=self.send(2,key).json
        second=self.send(2,key).json
        self.assertEqual(first['batch_id'],second['batch_id'])
        self.assertEqual(Draft.query.count(),2)
        self.worker();self.worker()
        self.assertFalse(self.worker())

    def test_lease_claim_and_stale_owner_cannot_overwrite_new_result(self):
        self.send()
        first=queue.claim_next()
        self.assertIsNone(queue.claim_next())
        row=Draft.query.filter_by(id=first[0]).one()
        job=queue.metadata(row.result_json)
        job['lease_until']=(queue.now()-timedelta(seconds=10)).isoformat()
        row.result_json=queue.result(job);db.session.commit()
        second=queue.claim_next()
        self.assertNotEqual(first[1],second[1])
        self.assertFalse(queue.renew(*first))
        self.assertFalse(queue.finish(*first,error=ValueError('NO_INSPECTION_FOUND')))
        self.assertTrue(queue.renew(*second))

    def test_repeated_crashes_stop_automatic_retries(self):
        receipt=self.send().json
        for attempt in range(queue.MAX_ATTEMPTS):
            ident,token=queue.claim_next()
            row=Draft.query.filter_by(id=ident).one()
            job=queue.metadata(row.result_json);job['lease_until']='2000-01-01'
            row.result_json=queue.result(job);db.session.commit()
        self.assertIsNone(queue.claim_next())
        self.assertEqual(self.status(receipt)['failed'],1)

    def test_company_creator_and_role_boundaries(self):
        stamp=self.m.User.query.filter_by(company_code='TEST',username='admin').one().password_changed_at
        self.m.db.session.add(self.m.Company(company_code='OTHER',company_name='Other',active=True))
        for company,name,role in [('TEST','another-admin','admin'),('TEST','reader','user'),('OTHER','admin','admin')]:
            self.m.db.session.add(self.m.User(company_code=company,username=name,role=role,password='unused',last_name='検証',password_changed_at=stamp))
        self.m.db.session.commit()
        receipt=self.send().json
        with self.client.session_transaction() as s:s['username']='another-admin'; s['account_identity'] = identity_for(s.get('company_code'), s.get('username'))
        for suffix in ['', '/status']:
            self.assertEqual(self.client.get(receipt['page_url']+suffix).status_code,404)
        with self.client.session_transaction() as s:s.update(account_identity=identity_for('OTHER', 'admin', app=(self.client).application), username='admin',company_code='OTHER')
        self.assertEqual(self.client.get(receipt['status_url']).status_code,404)
        with self.client.session_transaction() as s:s.update(account_identity=identity_for('TEST', 'reader', app=(self.client).application), company_code='TEST',username='reader',role='user')
        self.assertIn(self.client.get(receipt['status_url']).status_code,[403,404])
        self.assertEqual(self.send().status_code,403)

    def test_source_digest_and_revoked_role_are_checked_before_external_call(self):
        receipt=self.send().json
        row=Draft.query.one();row.source_sha256='0'*64;db.session.commit()
        with patch.object(vehicle_imports,'vehicle_document_extractor',side_effect=AssertionError('unverified source')):
            self.assertTrue(queue.process_one(self.m.app))
        self.assertEqual(self.status(receipt)['failed'],1)
        self.send()
        self.m.User.query.filter_by(company_code='TEST',username='admin').one().role='user'
        db.session.commit()
        with patch.object(vehicle_imports,'vehicle_document_extractor',side_effect=AssertionError('revoked user')):
            self.assertTrue(queue.process_one(self.m.app))

    def test_invalid_file_rolls_back_the_whole_receipt(self):
        response=self.client.post('/vehicle/data-import/jobs',data={
            'document_type':'inspection','document_files':[(BytesIO(pdf_bytes()),'good.pdf'),(BytesIO(b'bad'),'bad.pdf')]},
            headers={'Accept':'application/json'})
        self.assertEqual(response.status_code,400)
        self.assertEqual(Draft.query.count(),0)
        self.assertEqual(self.send(51).status_code,400)

    def test_byte_limits_reject_without_leaving_partial_jobs(self):
        with patch.object(queue,'MAX_FILE_BYTES',100):
            self.assertEqual(self.send().status_code,400)
        self.assertEqual(Draft.query.count(),0)
        source=pdf_bytes()
        with patch.object(queue,'MAX_BATCH_BYTES',len(source)+10):
            # Fake a small multipart envelope so this exercises cumulative file bounds.
            from werkzeug.datastructures import FileStorage
            with self.assertRaises(queue.ImportQueueError):
                queue.enqueue([FileStorage(stream=BytesIO(source),filename='one.pdf'),
                    FileStorage(stream=BytesIO(source),filename='two.pdf')], 'inspection','TEST','admin')
        self.assertEqual(Draft.query.count(),0)

    def test_status_poll_does_not_load_source_blobs(self):
        receipt=self.send(3).json
        statements=[]
        def capture(conn,cursor,statement,parameters,context,many):statements.append(statement)
        event.listen(db.engine,'before_cursor_execute',capture)
        try:self.status(receipt)
        finally:event.remove(db.engine,'before_cursor_execute',capture)
        status_selects=[s for s in statements if 'FROM vehicle_document_import_draft' in s]
        self.assertTrue(status_selects)
        import re
        self.assertTrue(all(not re.search(r'\.source_file(?:\s|,)',s) for s in status_selects))

    def test_preview_and_confirm_wait_for_all_files(self):
        receipt=self.send(2).json
        self.worker()
        preview=self.client.get('/vehicle/data-import/'+receipt['batch_id']+'/preview')
        self.assertEqual(preview.status_code,302)
        self.assertEqual(preview.location,receipt['page_url'])
        response=self.client.post('/vehicle/data-import/'+receipt['batch_id']+'/confirm',data={})
        self.assertEqual(response.status_code,409)

    def test_retry_after_successful_registration_only_registers_newly_ready_file(self):
        receipt=self.send(2).json
        self.worker(failure=ValueError('NO_INSPECTION_FOUND'));self.worker()
        ready=Draft.query.filter_by(status='preview').one()
        response=self.client.post('/vehicle/data-import/'+receipt['batch_id']+'/confirm',data=self.inspection_form(ready))
        self.assertEqual(response.status_code,302,response.get_data(as_text=True))
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(),1)
        self.client.post(receipt['page_url']+'/retry');self.worker()
        # The destination-type duplicate is now excluded before spending another OCR call.
        self.assertEqual(Draft.query.filter_by(status='skipped').count(),1)
        self.assertEqual(Draft.query.filter_by(status='preview').count(),0)
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(),1)

    def test_delete_cancels_queued_and_claimed_jobs_and_fences_worker(self):
        receipt = self.send(2).json
        draft_id, token = queue.claim_next()
        response = self.client.post(receipt['page_url'] + '/delete')
        self.assertEqual(response.status_code, 303)
        db.session.expire_all()
        for row in Draft.query.all():
            self.assertEqual(row.status, 'deleted')
            self.assertEqual(row.source_file, b'')
        self.assertFalse(queue.renew(draft_id, token))
        self.assertFalse(queue.finish(draft_id, token, error=ValueError('NO_INSPECTION_FOUND')))
        self.assertIsNone(queue.claim_next())
        self.assertEqual(self.client.get(receipt['status_url']).status_code, 404)
        self.assertNotIn(receipt['batch_id'], self.client.get('/vehicle/data-import').get_data(as_text=True))

    def test_delete_registered_receipt_preserves_record_source_and_deduplication(self):
        receipt = self.send().json
        self.worker()
        row = Draft.query.one()
        response = self.client.post('/vehicle/data-import/' + receipt['batch_id'] + '/confirm',
            data=self.inspection_form(row))
        self.assertEqual(response.status_code, 302)
        db.session.expire_all()
        row = Draft.query.one()
        original_source, original_result = row.source_file, json.loads(row.result_json)
        source_keys = vehicle_imports.registered_inspection_import_keys('TEST')
        response = self.client.post(receipt['page_url'] + '/delete')
        self.assertEqual(response.status_code, 303)
        db.session.expire_all()
        row = Draft.query.one()
        self.assertEqual(row.status, 'completed')
        self.assertEqual(row.source_file, original_source)
        self.assertEqual(json.loads(row.result_json)['records'], original_result['records'])
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(), 1)
        self.assertEqual(vehicle_imports.registered_inspection_import_keys('TEST'), source_keys)
        self.assertNotIn(receipt['batch_id'], self.client.get('/vehicle/data-import').get_data(as_text=True))

    def test_delete_requires_owner_post_and_csrf(self):
        receipt = self.send().json
        self.assertEqual(self.client.get(receipt['page_url'] + '/delete').status_code, 405)
        stamp = self.m.User.query.filter_by(company_code='TEST', username='admin').one().password_changed_at
        self.m.db.session.add(self.m.User(company_code='TEST', username='other-admin', role='admin', password='unused', last_name='検証', password_changed_at=stamp))
        self.m.db.session.commit()
        with self.client.session_transaction() as session:
            session['username'] = 'other-admin'; session['account_identity'] = identity_for(session.get('company_code'), session.get('username'))
        self.assertIn(self.client.post(receipt['page_url'] + '/delete').status_code, (403, 404))
        self.assertEqual(Draft.query.one().status, 'queued')
        with self.client.session_transaction() as session:
            session['username'] = 'admin'; session['account_identity'] = identity_for(session.get('company_code'), session.get('username'))
        self.m.app.config['WTF_CSRF_ENABLED'] = True
        try:
            self.assertEqual(self.client.post(receipt['page_url'] + '/delete').status_code, 400)
        finally:
            self.m.app.config['WTF_CSRF_ENABLED'] = False
        self.assertEqual(Draft.query.one().status, 'queued')

    def test_retry_csrf_is_required(self):
        receipt=self.send().json
        self.m.app.config['WTF_CSRF_ENABLED']=True
        try:self.assertEqual(self.client.post(receipt['page_url']+'/retry').status_code,400)
        finally:self.m.app.config['WTF_CSRF_ENABLED']=False


class DocumentImportTransportTests(unittest.TestCase):
    def test_long_ai_reads_have_a_configurable_idle_timeout(self):
        import os
        import inspection_document_ai as ai
        from test_inspection_document_ai import Response
        payload={"status":"completed","output":[{"content":[{"type":"output_text","text":json.dumps(extraction())}]}]}
        for seconds in (600,900):
            with patch.dict(os.environ,{"OPENAI_API_KEY":"isolated-test-key","DOCUMENT_AI_TIMEOUT_SECONDS":str(seconds)}), patch(
                "maintenance_invoice_ai.urllib.request.urlopen",return_value=Response(payload)) as call:
                ai.extract_inspection_documents(pdf_bytes(),"inspection.pdf")
                self.assertEqual(call.call_args.kwargs["timeout"],seconds)
