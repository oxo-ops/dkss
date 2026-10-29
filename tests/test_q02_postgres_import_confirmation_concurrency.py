"""Real parallel confirmations must not upgrade competing company share locks."""
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from sqlalchemy import event, text
import test_document_import_queue as jobs
import test_workflow_regressions as workflow
from test_inspection_document_ai import pdf_bytes
from test_q08_postgres_identity import DisposablePostgres
from dkss_app import import_owner


class PostgresImportConfirmationConcurrencyTests(DisposablePostgres,unittest.TestCase):
    setUp=workflow.WorkflowRegressionTests.setUp
    tearDown=workflow.WorkflowRegressionTests.tearDown
    send=jobs.DocumentImportQueueTests.send
    worker=jobs.DocumentImportQueueTests.worker
    inspection_form=workflow.WorkflowRegressionTests.inspection_form

    def confirm_pair(self,same_document=False):
        receipts=[self.send(source=pdf_bytes(pages=n)).json for n in ([1] if same_document else [1,2])]
        for _ in receipts:self.worker()
        user=self.m.User.query.filter_by(company_code='TEST',username='admin').one()
        state=dict(company_code='TEST',username='admin',role='admin',account_identity=user.account_identity,
            password_changed_at=user.password_changed_at)
        requests=[]
        for receipt in receipts:
            row=self.m.VehicleDocumentImportDraft.query.filter_by(batch_id=receipt['batch_id']).one()
            self.assertEqual(row.status,'preview')
            form=self.inspection_form(row)
            form['inspection_type_'+row.id+'_0']='other'
            requests.append((f'/vehicle/data-import/{row.batch_id}/confirm',form))
        if same_document:requests*=2
        self.m.db.session.remove()
        barrier=threading.Barrier(2)
        original=import_owner.active_owner_username
        def synchronized(row,**kwargs):
            answer=original(row,**kwargs)
            if kwargs.get('lock'):barrier.wait(10)
            return answer
        def confirm(item):
            client=self.m.app.test_client()
            with client.session_transaction() as session:session.update(state)
            response=client.post(item[0],data=item[1])
            result=response.status_code
            response.close()
            return result
        with patch.object(import_owner,'active_owner_username',side_effect=synchronized):
            with ThreadPoolExecutor(max_workers=2) as pool:
                return sorted(pool.map(confirm,requests))

    def test_two_distinct_documents_same_company_both_commit(self):
        self.assertEqual(self.confirm_pair(),[302,302])
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(),2)
        self.assertEqual(self.m.VehicleDocumentImportDraft.query.filter_by(status='completed').count(),2)

    def test_same_document_parallel_replay_registers_once(self):
        self.assertEqual(self.confirm_pair(same_document=True),[302,409])
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(),1)
        self.assertEqual(self.m.VehicleDocumentImportDraft.query.filter_by(status='completed').count(),1)

    def test_company_revoked_after_claim_is_refreshed_before_registering(self):
        receipt=self.send().json
        self.worker()
        row=self.m.VehicleDocumentImportDraft.query.one()
        form=self.inspection_form(row)
        form['inspection_type_'+row.id+'_0']='other'
        engine=self.m.db.engine
        held=[]
        def revoke(conn,cursor,statement,parameters,context,many):
            if (statement.startswith('UPDATE vehicle_document_import_draft SET status=')
                    and isinstance(parameters,dict) and 'processing' in parameters.values() and not held):
                held.append(self.m.Company.query.filter_by(company_code='TEST').one())
                self.assertTrue(held[0].active)
                with engine.begin() as other:
                    other.execute(text("SET LOCAL lock_timeout = '1s'"))
                    other.execute(text("UPDATE company SET active=false WHERE company_code='TEST'"))
        event.listen(engine,'after_cursor_execute',revoke)
        try:
            response=self.client.post(f'/vehicle/data-import/{row.batch_id}/confirm',data=form)
            self.assertEqual(response.status_code,404)
            response.close()
        finally:
            event.remove(engine,'after_cursor_execute',revoke)
            self.m.db.session.remove()
        self.assertEqual(len(held),1)
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(),0)
        self.assertEqual(self.m.VehicleDocumentImportDraft.query.one().status,'preview')
