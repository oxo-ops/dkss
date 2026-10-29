"""Receipt UUID boundaries, including all mutations and normal account continuity."""
import json
import unittest
from unittest.mock import patch
from uuid import uuid4
from sqlalchemy import create_engine, text
import test_workflow_regressions as workflow
import test_document_import_queue as jobs
from test_inspection_document_ai import extraction
from dkss_app import document_import_queue as queue, vehicle_imports, import_owner


class ImportOwnerGenerationTests(unittest.TestCase):
    setUpClass=classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass=classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    setUp=workflow.WorkflowRegressionTests.setUp
    tearDown=workflow.WorkflowRegressionTests.tearDown
    send=jobs.DocumentImportQueueTests.send
    worker=jobs.DocumentImportQueueTests.worker

    def test_admission_rejects_missing_or_unprivileged_company_owner(self):
        from io import BytesIO
        from werkzeug.datastructures import FileStorage
        def denied():
            with self.assertRaises(queue.ImportQueueError) as result:
                queue.enqueue([FileStorage(stream=BytesIO(jobs.pdf_bytes()),filename='fake.pdf')],
                    'inspection','OTHER','admin')
            self.assertEqual(result.exception.status,403)
            self.assertEqual(self.m.VehicleDocumentImportDraft.query.count(),0)
        denied()
        self.m.db.session.add(self.m.Company(company_code='OTHER',company_name='Synthetic',active=True))
        user=self.m.User(company_code='OTHER',username='admin',role='user',password='unused',last_name='Synthetic')
        self.m.db.session.add(user);self.m.db.session.commit()
        denied()
        user.role='admin';user.login_locked=True;self.m.db.session.commit()
        denied()

    def replace_person(self):
        with self.m.app.app_context():
            old=self.m.User.query.filter_by(company_code='TEST',username='admin').one()
            identity=old.account_identity
            self.m.db.session.delete(old)
            self.m.db.session.flush()
            new=self.m.User(company_code='TEST',username='admin',role='admin',password='unused',
                last_name='Different person',password_changed_at='stamp')
            self.m.db.session.add(new);self.m.db.session.commit()
            new_identity=new.account_identity
        self.assertNotEqual(identity,new_identity)
        with self.client.session_transaction() as state:
            state.update(company_code='TEST',username='admin',role='admin',account_identity=new_identity,password_changed_at='stamp')
        self.m.db.session.expire_all()
        return identity,new_identity

    def test_replacement_cannot_read_mutate_cancel_or_reclassify_old_receipt(self):
        receipt=self.send().json
        self.assertTrue(self.worker())
        draft=self.m.VehicleDocumentImportDraft.query.one()
        ident,batch=draft.id,draft.batch_id
        before=(draft.status,draft.preview_json,draft.result_json,bytes(draft.source_file))
        old,new=self.replace_person()
        paths=[('GET',receipt['status_url']),('GET',receipt['page_url']),
            ('GET',f'/vehicle/data-import/{batch}/preview'),('GET',f'/vehicle/data-import/files/{ident}'),
            ('GET',f'/vehicle/data-import/{ident}/kind'),('POST',f'/vehicle/data-import/{ident}/kind'),
            ('POST',receipt['page_url']+'/retry'),('POST',receipt['page_url']+'/delete'),
            ('POST',f'/vehicle/data-import/{batch}/confirm')]
        for method,path in paths:
            with self.subTest(method=method,path=path):
                self.assertEqual(self.client.open(path,method=method).status_code,404)
        self.m.db.session.expire_all()
        row=self.m.VehicleDocumentImportDraft.query.one()
        self.assertEqual(row.owner_identity,old)
        self.assertEqual((row.status,row.preview_json,row.result_json,bytes(row.source_file)),before)

    def test_upload_key_replay_is_scoped_to_uuid_not_reused_username(self):
        key=str(uuid4())
        first=self.send(key=key).json
        old_row=self.m.VehicleDocumentImportDraft.query.one()
        old_id,old_identity=old_row.id,old_row.owner_identity
        _,identity=self.replace_person()
        response=self.send(key=key)
        self.assertEqual(response.status_code,202)
        self.assertEqual(len(response.json['files']),1)
        self.assertNotEqual(response.json['files'][0]['id'],old_id)
        rows=self.m.VehicleDocumentImportDraft.query.order_by(self.m.VehicleDocumentImportDraft.id).all()
        self.assertEqual(len(rows),2)
        self.assertEqual({r.owner_identity for r in rows},{old_identity,identity})
        self.assertEqual([f['id'] for f in self.client.get(first['status_url']).json['files']],
            [response.json['files'][0]['id']])

    def test_same_uuid_rename_during_ocr_keeps_receipt_and_original_access(self):
        receipt=self.send().json
        row=self.m.VehicleDocumentImportDraft.query.one()
        identity,source=row.owner_identity,bytes(row.source_file)
        def read(source,**kwargs):
            with self.m.app.app_context():
                user=self.m.User.query.filter_by(account_identity=identity).one()
                user.username='renamed';self.m.db.session.commit()
            return extraction(source)
        with patch.object(queue,'detect_document_types',return_value={'types':['inspection'],'certainty':'clear','supported':True}), patch.object(
                vehicle_imports,'vehicle_document_extractor',return_value=read):
            self.assertTrue(queue.process_one(self.m.app))
        with self.client.session_transaction() as state:
            state['username']='renamed'
        self.m.db.session.expire_all()
        row=self.m.VehicleDocumentImportDraft.query.one()
        self.assertEqual((row.owner_identity,row.created_by_username,row.status),(identity,'admin','preview'))
        self.assertEqual(self.client.get(receipt['status_url']).status_code,200)
        self.assertEqual(self.client.get('/vehicle/data-import/files/'+row.id).data,source)
        self.assertEqual(self.client.get(f'/vehicle/data-import/{row.batch_id}/preview').status_code,200)
        self.assertIn('no-store',self.client.get(f'/vehicle/data-import/{row.batch_id}/preview').headers['Cache-Control'])
        self.assertEqual(self.send(key=receipt['batch_id']).status_code,202)
        self.assertEqual(self.m.VehicleDocumentImportDraft.query.count(),1)

    def test_same_uuid_unlock_can_retry_after_revocation(self):
        receipt=self.send().json
        user=self.m.User.query.filter_by(company_code='TEST',username='admin').one()
        identity=user.account_identity
        user.login_locked=True;self.m.db.session.commit()
        self.assertTrue(self.worker())
        row=self.m.VehicleDocumentImportDraft.query.one()
        self.assertEqual(row.status,'read_error')
        user.login_locked=False;self.m.db.session.commit()
        self.assertEqual(self.client.post(receipt['page_url']+'/retry').status_code,303)
        self.assertTrue(self.worker())
        self.m.db.session.expire_all()
        self.assertEqual((row.owner_identity,row.status),(identity,'preview'))

    def test_mixed_document_children_keep_parent_uuid_after_account_recreation(self):
        self.send()
        identity=self.m.VehicleDocumentImportDraft.query.one().owner_identity
        with patch.object(queue,'detect_document_types',return_value={'types':['inspection','maintenance'],'certainty':'clear','supported':True}), patch.object(
                vehicle_imports,'vehicle_document_extractor',return_value=lambda source,**kw:extraction(source)):
            self.assertTrue(queue.process_one(self.m.app))
        rows=self.m.VehicleDocumentImportDraft.query.all()
        self.assertEqual(len(rows),2)
        self.assertEqual({r.owner_identity for r in rows},{identity})
        self.replace_person()
        with patch.object(vehicle_imports,'vehicle_document_extractor') as factory:
            self.assertTrue(queue.process_one(self.m.app))
            factory.assert_not_called()
        self.m.db.session.expire_all()
        self.assertEqual(self.m.VehicleDocumentImportDraft.query.filter_by(document_type='maintenance').one().status,'read_error')

    def test_recreation_after_preview_build_cannot_publish_result(self):
        self.send()
        original=vehicle_imports.build_vehicle_document_preview
        def build(*args,**kwargs):
            preview=original(*args,**kwargs)
            self.replace_person()
            return preview
        with patch.object(vehicle_imports,'build_vehicle_document_preview',side_effect=build):
            self.assertTrue(self.worker())
        row=self.m.VehicleDocumentImportDraft.query.one()
        self.assertEqual((row.status,json.loads(row.preview_json)),('read_error',{}))

    def test_legacy_unbound_receipt_is_not_backfilled_on_update(self):
        self.send();self.worker()
        row=self.m.VehicleDocumentImportDraft.query.one()
        with self.m.db.engine.begin() as c:
            c.execute(text('UPDATE vehicle_document_import_draft SET owner_identity=NULL'))
        self.m.db.session.expire_all()
        row.result_json='{}';self.m.db.session.commit()
        self.assertIsNone(row.owner_identity)
        self.assertEqual(self.client.get('/vehicle/data-import/files/'+row.id).status_code,404)

    def test_receipt_owner_cannot_be_reassigned(self):
        self.send()
        row=self.m.VehicleDocumentImportDraft.query.one()
        identity=row.owner_identity
        row.owner_identity=str(uuid4())
        with self.assertRaises(ValueError):self.m.db.session.flush()
        self.m.db.session.rollback()
        self.assertEqual(self.m.VehicleDocumentImportDraft.query.one().owner_identity,identity)


class ImportOwnerMigrationTests(unittest.TestCase):
    def test_incompatible_existing_owner_type_is_not_overwritten(self):
        engine=create_engine('sqlite:///:memory:');self.addCleanup(engine.dispose)
        with engine.begin() as c:
            c.execute(text('CREATE TABLE vehicle_document_import_draft (id TEXT PRIMARY KEY, owner_identity INTEGER)'))
            c.execute(text("INSERT INTO vehicle_document_import_draft VALUES ('old',42)"))
        with self.assertRaises(RuntimeError):import_owner.upgrade_import_owners(engine)
        with engine.connect() as c:
            self.assertEqual(c.scalar(text('SELECT owner_identity FROM vehicle_document_import_draft')),42)

    def test_legacy_sqlite_sources_and_json_remain_unbound_and_unchanged(self):
        engine=create_engine('sqlite:///:memory:');self.addCleanup(engine.dispose)
        with engine.begin() as c:
            c.execute(text('CREATE TABLE vehicle_document_import_draft (id TEXT PRIMARY KEY, company_code TEXT, created_by_username TEXT, source_file BLOB, result_json TEXT)'))
            c.execute(text("INSERT INTO vehicle_document_import_draft VALUES ('old','TEST','admin',X'010203','{\"status\":\"old\"}')"))
        import_owner.upgrade_import_owners(engine)
        import_owner.upgrade_import_owners(engine)
        with engine.connect() as c:
            self.assertEqual(tuple(c.execute(text('SELECT * FROM vehicle_document_import_draft')).one()),
                ('old','TEST','admin',b'\x01\x02\x03','{"status":"old"}',None))
