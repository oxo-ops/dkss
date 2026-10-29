"""Unconfirmed operation CSV receipts must not follow a reused login ID."""
import io
import json
import unittest
import os
import tempfile
from uuid import uuid4
from unittest.mock import patch
import test_workflow_regressions as fixture
from identity_fixture import identity_for


class CsvOwnerTests(unittest.TestCase):
    setUpClass=classmethod(fixture.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass=classmethod(fixture.WorkflowRegressionTests.tearDownClass.__func__)
    setUp=fixture.WorkflowRegressionTests.setUp
    tearDown=fixture.WorkflowRegressionTests.tearDown

    def login(self,company='TEST',username='admin'):
        u=self.m.User.query.filter_by(company_code=company,username=username).one()
        with self.client.session_transaction() as s:
            s.clear();s.update(company_code=company,username=username,role=u.role,
                account_identity=u.account_identity,password_changed_at=u.password_changed_at)

    def upload(self,number='CSV-A',source_code=None):
        source=('日報番号,運行日,車両コード,車両,入庫メータ,走行距離\n'
                +number+',2026/10/23,'+(source_code or number)+',横浜100あ1234,1000,12\n').encode('utf-8-sig')
        response=self.client.post('/vehicle/operation-import',data={'csv_file':(io.BytesIO(source),'synthetic.csv')})
        self.assertEqual(response.status_code,302)
        row=self.m.VehicleOperationImportDraft.query.order_by(self.m.VehicleOperationImportDraft.created_at.desc()).first()
        return row,source

    def replace(self):
        a=self.m.User.query.filter_by(company_code='TEST',username='admin').one()
        ident,old,stamp=a.id,a.account_identity,a.password_changed_at
        self.m.db.session.delete(a);self.m.db.session.commit()
        b=self.m.User(id=ident,company_code='TEST',username='admin',role='admin',last_name='Replacement B',password='unused',password_changed_at=stamp)
        self.m.db.session.add(b);self.m.db.session.commit()
        self.assertEqual(b.id,ident);self.assertNotEqual(b.account_identity,old)
        self.login();return old,b.account_identity

    def test_recreated_login_cannot_read_old_preview(self):
        row,source=self.upload();path=f'/vehicle/operation-import/{row.id}/preview'
        self.assertEqual(self.client.get(path).status_code,200)
        self.replace()
        response=self.client.get(path)
        self.assertEqual(response.status_code,404)
        self.assertNotIn(b'CSV-A',response.data)

    def form(self):
        return {'include':'2','vehicle_2':str(self.vehicle.id),'confirmed_vehicle_mapping':f'2:{self.vehicle.id}'}

    def snapshot(self):
        m=self.m;m.db.session.expire_all()
        return tuple(tuple(tuple(getattr(r,c.name) for c in model.__table__.columns)
            for r in model.query.order_by(model.id).all()) for model in (
                m.VehicleOperationImportDraft,m.VehicleOperationRecord,m.VehicleImportPending,
                m.VehicleImportPendingRecord,m.VehicleOperationVehicleMapping,m.Vehicle,m.AuditLog,m.Notification))

    def paths(self,row):
        return [('GET',f'/vehicle/operation-import/{row.id}/preview',{}),
                ('GET',f'/vehicle/operation-import/{row.id}/result',{}),
                ('POST',f'/vehicle/operation-import/{row.id}/confirm',self.form()),
                ('POST',f'/api/vehicle/operation-import/{row.id}/vehicles',{'chassis_number':'NEW-PRIVATE'})]

    def assert_private_denied(self,row):
        before=self.snapshot()
        for method,path,data in self.paths(row):
            with self.subTest(path=path):
                response=self.client.open(path,method=method,data=data)
                self.assertEqual(response.status_code,404)
                self.assertIn('no-store',response.headers['Cache-Control'])
                self.assertEqual(self.snapshot(),before)
        response=self.client.post(f'/vehicle/operation-import/{row.id}/confirm',data=self.form(),
            headers={'X-DKSS-Validation-Only':'1'})
        self.assertEqual(response.status_code,404);self.assertEqual(self.snapshot(),before)

    def test_recreated_login_cannot_operate_old_receipt(self):
        row,_=self.upload();old,new=self.replace()
        self.assertEqual(row.owner_identity,old);self.assert_private_denied(row)

    def test_legacy_receipt_is_retained_but_not_inferred(self):
        row,source=self.upload()
        self.m.db.session.execute(type(row).__table__.update().where(type(row).id==row.id).values(owner_identity=None))
        self.m.db.session.commit();self.m.db.session.refresh(row)
        self.assert_private_denied(row)
        self.assertEqual(row.source_file,source);self.assertIsNone(row.owner_identity)
        # Same bytes are a new explicit upload, never a claim to the old legacy row.
        fresh,_=self.upload();self.assertNotEqual(fresh.id,row.id)
        self.assertEqual(fresh.owner_identity,self.m.User.query.filter_by(company_code='TEST',username='admin').one().account_identity)

    def test_normal_confirm_and_replay_register_once(self):
        row,_=self.upload();url=f'/vehicle/operation-import/{row.id}/confirm'
        self.assertEqual(self.client.get(url.replace('/confirm','/preview')).status_code,200)
        self.assertEqual(self.client.post(url,data=self.form(),headers={'X-DKSS-Validation-Only':'1'}).status_code,200)
        self.assertEqual(self.m.VehicleOperationRecord.query.count(),0)
        self.assertEqual(self.client.post(url,data=self.form()).status_code,302)
        self.assertEqual(self.client.get(url.replace('/confirm','/result')).status_code,200)
        self.assertEqual(self.client.post(url,data=self.form()).status_code,302)
        self.assertEqual(self.m.VehicleOperationRecord.query.count(),1)
        self.m.db.session.refresh(row);self.assertEqual(row.status,'completed')

    def test_normal_api_vehicle_creation_is_still_allowed(self):
        row,_=self.upload()
        response=self.client.post(f'/api/vehicle/operation-import/{row.id}/vehicles',data={'chassis_number':'CSV-NEW-CAR'})
        self.assertEqual(response.status_code,201)
        self.assertEqual(self.m.Vehicle.query.filter_by(chassis_number='CSV-NEW-CAR').count(),1)

    def test_same_generation_rename_unlock_and_login_change(self):
        row,_=self.upload();owner=row.owner_identity
        user=self.m.User.query.filter_by(company_code='TEST',username='admin').one()
        user.last_name='Renamed A';user.login_locked=True;self.m.db.session.commit()
        self.login();self.assertEqual(self.client.get(f'/vehicle/operation-import/{row.id}/preview').status_code,302)
        user.login_locked=False;user.username='renamed-login';self.m.db.session.commit();self.login(username='renamed-login')
        self.assertEqual(self.client.get(f'/vehicle/operation-import/{row.id}/preview').status_code,200)
        self.m.db.session.refresh(row);self.assertEqual(row.owner_identity,owner);self.assertEqual(row.created_by_username,'admin')

    def test_other_company_same_login_cannot_access_receipt(self):
        row,_=self.upload();m=self.m
        m.db.session.add(m.Company(company_code='OTHER',company_name='Other',active=True))
        m.db.session.add(m.User(company_code='OTHER',username='admin',role='admin',last_name='Other admin',password='unused',password_changed_at='same'))
        m.db.session.commit();self.login('OTHER');self.assert_private_denied(row)

    def test_explicit_reupload_by_B_creates_own_receipt(self):
        row,source=self.upload();old,new=self.replace();fresh,_=self.upload()
        self.assertNotEqual(fresh.id,row.id);self.assertEqual(fresh.owner_identity,new)
        self.m.db.session.refresh(row);self.assertEqual(row.owner_identity,old);self.assertEqual(row.source_file,source)
        self.assertEqual(self.client.get(f'/vehicle/operation-import/{fresh.id}/preview').status_code,200)

    def test_same_owner_upload_replay_reuses_only_own_receipt(self):
        row,_=self.upload();again,_=self.upload()
        self.assertEqual(row.id,again.id);self.assertEqual(self.m.VehicleOperationImportDraft.query.count(),1)

    def test_owner_uuid_cannot_be_rebound_by_unrelated_ORM_edit(self):
        row,_=self.upload();original=row.owner_identity;row.owner_identity='not-the-owner'
        with self.assertRaisesRegex(ValueError,'immutable'):self.m.db.session.commit()
        self.m.db.session.rollback();self.m.db.session.refresh(row);self.assertEqual(row.owner_identity,original)

    def test_back_link_has_no_server_cancellation_or_receipt_deletion(self):
        row,source=self.upload();before=self.snapshot()
        self.assertEqual(self.client.get('/vehicle/operation-import').status_code,200)
        self.assertEqual(self.client.post(f'/vehicle/operation-import/{row.id}/cancel').status_code,404)
        self.assertEqual(self.client.delete(f'/vehicle/operation-import/{row.id}/preview').status_code,405)
        self.assertEqual(self.snapshot(),before)

    def test_invalid_form_selection_save_still_requires_owner(self):
        row,_=self.upload();url=f'/vehicle/operation-import/{row.id}/confirm'
        self.assertEqual(self.client.post(url,data={}).status_code,400)
        self.m.db.session.refresh(row);self.assertEqual(row.status,'preview')
        self.assertIn('form_errors',row.result_json)
        self.replace();before=self.snapshot()
        self.assertEqual(self.client.post(url,data={}).status_code,404);self.assertEqual(self.snapshot(),before)

    def test_owner_recreated_after_auth_before_confirm_rolls_back(self):
        from flask import request
        row,_=self.upload();url=f'/vehicle/operation-import/{row.id}/confirm';before=self.snapshot();changed=[]
        def replace():
            if request.path==url and not changed:changed.append(self.replace())
        hooks=self.m.app.before_request_funcs[None];hooks.append(replace)
        try:response=self.client.post(url,data=self.form())
        finally:hooks.remove(replace)
        self.assertEqual(response.status_code,404);self.assertEqual(self.snapshot(),before)

    def test_owner_disappears_during_parsing_before_claim(self):
        from dkss_app import vehicle_operations
        row,_=self.upload();before=self.snapshot();real=vehicle_operations.get_vehicle_operation_import_submission
        def parse_then_delete(*args,**kwargs):
            result=real(*args,**kwargs)
            user=self.m.User.query.filter_by(company_code='TEST',username='admin').one()
            self.m.db.session.delete(user);self.m.db.session.commit()
            return result
        with patch.object(vehicle_operations,'get_vehicle_operation_import_submission',side_effect=parse_then_delete):
            response=self.client.post(f'/vehicle/operation-import/{row.id}/confirm',data=self.form())
        self.assertEqual(response.status_code,404);self.assertEqual(self.snapshot(),before)

    def test_confirm_rollback_keeps_receipt_source_and_all_related_rows(self):
        from sqlalchemy import event
        row,source=self.upload();before=self.snapshot();hits=[]
        def fail(conn,cursor,statement,parameters,context,many):
            if statement.lower().startswith('insert into vehicle_operation_record '):hits.append(True);raise RuntimeError('Q03_CSV_AFTER_INSERT')
        event.listen(self.m.db.engine,'after_cursor_execute',fail)
        try:response=self.client.post(f'/vehicle/operation-import/{row.id}/confirm',data=self.form())
        finally:event.remove(self.m.db.engine,'after_cursor_execute',fail)
        self.assertEqual(response.status_code,500);self.assertEqual(hits,[True]);self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.client.post(f'/vehicle/operation-import/{row.id}/confirm',data=self.form()).status_code,302)
        self.m.db.session.refresh(row);self.assertEqual(row.source_file,source)

    def test_owner_and_vehicle_are_held_after_check(self):
        from dkss_app import operation_csv_owner
        from sqlalchemy import text
        from sqlalchemy.exc import OperationalError
        row,_=self.upload();real=operation_csv_owner.hold_owner;checked=[]
        def verify_then_delete(*args,**kwargs):
            answer=real(*args,**kwargs)
            for sql in ('DELETE FROM "user" WHERE company_code=\'TEST\' AND username=\'admin\'',
                        'UPDATE vehicle SET office=\'concurrent\' WHERE id='+str(self.vehicle.id)):
                with self.m.db.engine.connect() as writer:
                    if writer.dialect.name=='sqlite':writer.exec_driver_sql('PRAGMA busy_timeout=100');writer.commit()
                    with self.assertRaises(OperationalError) as caught:
                        with writer.begin():
                            if writer.dialect.name=='postgresql':writer.execute(text("SET LOCAL lock_timeout='100ms'"))
                            writer.execute(text(sql))
                    if writer.dialect.name=='postgresql':self.assertEqual(caught.exception.orig.pgcode,'55P03')
                    else:self.assertIn('database is locked',str(caught.exception))
            checked.append(True);return answer
        with patch.object(operation_csv_owner,'hold_owner',side_effect=verify_then_delete):
            self.assertEqual(self.client.post(f'/vehicle/operation-import/{row.id}/confirm',data=self.form()).status_code,302)
        self.assertEqual(checked,[True])

    def test_completed_company_source_is_not_private_receipt_ownership(self):
        row,source=self.upload();self.assertEqual(self.client.post(f'/vehicle/operation-import/{row.id}/confirm',data=self.form()).status_code,302)
        self.replace()
        self.assertEqual(self.client.get(f'/vehicle/operation-import/{row.id}/result').status_code,404)
        response=self.client.get(f'/vehicle/karte/{self.vehicle.id}/operation-files/{row.id}')
        self.assertEqual(response.status_code,200);self.assertEqual(response.data,source)

    def test_unconfirmed_source_with_old_published_metadata_requires_owner(self):
        row,_=self.upload();row.result_json=json.dumps({'imported_vehicle_ids':[self.vehicle.id]});self.m.db.session.commit()
        self.assertEqual(self.client.get(f'/vehicle/karte/{self.vehicle.id}/operation-files/{row.id}').status_code,200)
        self.replace()
        self.assertEqual(self.client.get(f'/vehicle/karte/{self.vehicle.id}/operation-files/{row.id}').status_code,404)

    def test_pending_source_keeps_completed_company_sharing_and_holds_private_legacy(self):
        row,source=self.upload();m=self.m
        pending=m.VehicleImportPending(id='csv-pending',company_code='TEST',match_key='synthetic',created_by_username='admin')
        item=m.VehicleImportPendingRecord(id='csv-item',pending_id='csv-pending',company_code='TEST',
            source_kind='operation',record_key='synthetic',operation_draft_id=row.id,source_record_index=2,
            payload_json='{}',created_by_username='admin')
        m.db.session.add_all([pending,item]);m.db.session.commit()
        path=f'/master/vehicles/pending/{pending.id}/sources/{row.id}'
        self.assertEqual(self.client.get(path).status_code,200)
        self.replace();self.assertEqual(self.client.get(path).status_code,404)
        # A completed parent is an already shared company asset, independent of old creator identity.
        row.status='completed';m.db.session.commit()
        response=self.client.get(path);self.assertEqual(response.status_code,200);self.assertEqual(response.data,source)

    def test_role_revoked_after_auth_does_not_save_selections_or_results(self):
        from dkss_app import vehicle_operations
        row,_=self.upload();before=self.snapshot();real=vehicle_operations.get_vehicle_operation_import_submission
        def parse_then_demote(*args,**kwargs):
            result=real(*args,**kwargs)
            self.m.User.query.filter_by(company_code='TEST',username='admin').one().role='user'
            self.m.db.session.commit();return result
        with patch.object(vehicle_operations,'get_vehicle_operation_import_submission',side_effect=parse_then_demote):
            response=self.client.post(f'/vehicle/operation-import/{row.id}/confirm',data=self.form())
        self.assertEqual(response.status_code,404);self.assertEqual(self.snapshot(),before)


@unittest.skipUnless(os.environ.get('Q03_CSV_POSTGRES_TEST_URL'),'explicit disposable CSV PostgreSQL required')
class PostgresCsvOwnerTests(CsvOwnerTests):
    @classmethod
    def setUpClass(cls):
        from sqlalchemy import create_engine,text
        from sqlalchemy.engine import make_url
        raw=os.environ['Q03_CSV_POSTGRES_TEST_URL'];url=make_url(raw)
        if url.get_backend_name()!='postgresql' or url.host not in {'127.0.0.1','localhost'} or url.database!='dkss_q03_csv_ci':
            raise RuntimeError('Only loopback dkss_q03_csv_ci is allowed')
        cls.schema='q03_csv_'+uuid4().hex
        cls.admin=create_engine(raw,isolation_level='AUTOCOMMIT');cls.addClassCleanup(cls.admin.dispose)
        with cls.admin.connect() as c:c.execute(text('CREATE SCHEMA "'+cls.schema+'"'))
        def cleanup():
            with cls.admin.connect() as c:c.execute(text('DROP SCHEMA "'+cls.schema+'" CASCADE'))
        cls.addClassCleanup(cleanup)
        from dkss_app import create_app
        from application_fixture import ApplicationFixture
        cls.temp=tempfile.TemporaryDirectory(prefix='q03-csv-pg-');cls.addClassCleanup(cls.temp.cleanup)
        env={'DATABASE_URL':raw,'SECRET_KEY':'q03-csv-synthetic','RENDER':'','MFA_ENABLED':'false',
             'AWS_EC2_METADATA_DISABLED':'true','OPENAI_API_KEY':'','SMTP_HOST':'','S3_BUCKET_NAME':'',
             'VAPID_PRIVATE_KEY':'','VAPID_PUBLIC_KEY':'','DOCUMENT_IMPORT_WORKER_ENABLED':'0'}
        with patch.dict(os.environ,env):
            app=create_app({'TESTING':True,'WTF_CSRF_ENABLED':False,'SQLALCHEMY_ENGINE_OPTIONS':{
                'connect_args':{'options':'-csearch_path='+cls.schema+' -cstatement_timeout=15000 -clock_timeout=10000'}}})
        cls.m=ApplicationFixture(app);cls.m.limiter.enabled=False
        with app.app_context():
            cls.engine=cls.m.db.engine;cls.addClassCleanup(cls.engine.dispose)
            with cls.engine.connect() as c:assert c.scalar(text('SELECT current_schema()'))==cls.schema

    @classmethod
    def tearDownClass(cls):pass


    def parallel_confirm(self, same=False, shared_mapping=False, pending=False):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from sqlalchemy import event
        code='SHARED' if shared_mapping else None
        first,_=self.upload('CSV-ONE',source_code=code)
        second=first if same else self.upload('CSV-TWO',source_code=code)[0]
        paths=[f'/vehicle/operation-import/{row.id}/confirm' for row in (first,second)]
        payload={'include':'2'} if pending else self.form()
        with self.client.session_transaction() as s:claims=dict(s)
        local=threading.local();gate=threading.Barrier(2,timeout=10);pids={}
        def pause(conn,cursor,sql,parameters,context,many):
            worker=getattr(local,'worker',None)
            if worker is not None and worker not in pids:
                pids[worker]=cursor.connection.get_backend_pid();gate.wait()
        def confirm(item):
            no,path=item;local.worker=no
            try:
                client=self.m.app.test_client()
                with client.session_transaction() as s:s.update(claims)
                response=client.post(path,data=dict(payload))
                try:return response.status_code
                finally:response.close()
            finally:local.worker=None
        event.listen(self.m.db.engine,'after_cursor_execute',pause)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(confirm,enumerate(paths)))
        finally:event.remove(self.m.db.engine,'after_cursor_execute',pause)
        self.assertEqual(sorted(statuses),[302,409] if shared_mapping else [302,302])
        self.assertEqual(len(set(pids.values())),2)
        if shared_mapping:
            # The existing unique mapping constraint rejects one concurrent
            # creation; its whole receipt rolls back and a fresh retry succeeds.
            retry=paths[statuses.index(409)]
            self.assertEqual(self.client.post(retry,data=payload).status_code,302)
        self.m.db.session.expire_all()
        self.assertEqual(self.m.VehicleOperationRecord.query.count(),0 if pending else 1 if same else 2)
        if pending:self.assertEqual(self.m.VehicleImportPendingRecord.query.count(),2)

    def test_parallel_distinct_receipts_same_company_commit(self):self.parallel_confirm()
    def test_parallel_same_receipt_registers_once(self):self.parallel_confirm(True)
    def test_parallel_same_mapping_conflict_rolls_back_and_retries(self):self.parallel_confirm(shared_mapping=True)
    def test_parallel_pending_receipts_do_not_promote_company_share_locks(self):self.parallel_confirm(pending=True)
