"""Cross-process new -> recovery -> new compatibility on one synthetic SQLite file."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import socket
import sys
import unittest
from datetime import date
from unittest.mock import patch

root = Path(os.environ["M06_SWITCH_EVIDENCE_DIR"]).resolve()
stage = sys.argv[1]
database = root/'m06-switch-fixture.db'
metadata = root/'M06-switch-fixture.json'
os.environ.update(AWS_EC2_METADATA_DISABLED='true', DOCUMENT_IMPORT_WORKER_ENABLED='0',
                  OPENAI_API_KEY='', SMTP_HOST='', S3_BUCKET_NAME='', VAPID_PRIVATE_KEY='', VAPID_PUBLIC_KEY='')
from test_m06_confirmed_periodic_notice import ConfirmedPeriodicNoticeTests as Confirmed
from test_m06_new_kinds import NewKindTests as Kinds
from test_q05_document_dates import DocumentCompletionDateTests as Document
from application_fixture import ApplicationFixture

class Driver(unittest.TestCase):
    setUpClass = classmethod(Confirmed.setUpClass.__func__)
    tearDownClass = classmethod(Confirmed.tearDownClass.__func__)
    setUp = Confirmed.setUp
    tearDown = Confirmed.tearDown
    upload_inspection = Confirmed.upload_inspection
    inspection_form = Confirmed.inspection_form
    confirmed_plan = Confirmed.confirmed_plan
    run_alerts = Confirmed.run_alerts
    change = Kinds.change
    save_plan = Kinds.save_plan
    draft = Document.draft
    form = Document.form

def snapshot(m):
    models = (m.Vehicle, m.VehicleInspectionPlan, m.VehicleInspectionPlanEvent,
              m.inspection_plans.Execution, m.inspection_plans.Evidence,
              m.VehiclePeriodicInspectionRecord, m.VehicleDocumentImportDraft,
              m.VehicleMaintenanceRecord, m.VehicleMaintenanceDocument,
              m.Notification, m.inspection_alerts.Delivery, m.inspection_alerts.ExpiryDelivery)
    def value(v):
        return {'sha256':hashlib.sha256(v).hexdigest()} if isinstance(v,bytes) else str(v)
    return {model.__tablename__: sorted([[value(getattr(row,c.name)) for c in model.__table__.columns]
            for row in model.query.all()],key=str) for model in models}

def complete(d, kind, day, original):
    payload = dict(vehicle_record_id=d.vehicle.id, kind=kind, performed_date=day,
                   kind_contract='independent-v1', confirmed=True,
                   confirmation='Synthetic original verifies this independent kind and actual day', document_id=original)
    preview=d.client.post('/api/vehicle/inspection-plans/execution/preview',json=payload)
    d.assertEqual(preview.status_code,200,preview.get_data(as_text=True))
    payload['token']=preview.json['token']
    saved=d.client.post('/api/vehicle/inspection-plans/execution/save',json=payload)
    d.assertEqual(saved.status_code,200,saved.get_data(as_text=True))

def no_external(sock,address):
    raise AssertionError('No network is allowed in switch acceptance')

with patch.object(socket.socket,'connect',no_external), patch('vehicle_inspection_alerts.local_today',return_value=date(2026,10,22)):
    d=Driver()
    if stage=='seed':
        assert not database.exists(), 'Do not overwrite an existing switch fixture'
        Driver.setUpClass(); d.setUp(); m=d.m
        legacy, record, inspection_draft=d.confirmed_plan()
        for kind in ('12month','vehicle_inspection'):
            d.save_plan(kind,mon='2026-12')
        d.save_plan('12month',mon='2026-08')
        d.save_plan('12month',mon='2026-05')
        d.save_plan('vehicle_inspection',mon='2026-11')
        d.run_alerts()
        held=m.VehicleInspectionPlan.query.filter_by(kind='periodic_12month',planned_month='2026-08').one()
        ended=m.VehicleInspectionPlan.query.filter_by(kind='periodic_12month',planned_month='2026-05').one()
        held_receipt=m.inspection_alerts.Delivery.query.filter_by(plan_id=held.id).one()
        ended_receipt=m.inspection_alerts.Delivery.query.filter_by(plan_id=ended.id).one()
        held.kind='12month'
        ended_receipt.ended_status='closed'
        m.db.session.get(m.Notification,ended_receipt.notification_id).read=True
        m.db.session.commit()
        original=d.draft('maintenance')
        form=d.form(start='2026-09-14',end='2026-09-14')
        response=d.client.post('/vehicle/data-import/q05-batch/confirm',data=form)
        d.assertEqual(response.status_code,302,response.get_data(as_text=True))
        case=m.VehicleMaintenanceRecord.query.one()
        m.db.session.add(m.VehicleMaintenanceDocument(company_code='TEST',vehicle_record_id=d.vehicle.id,
            maintenance_record_id=case.id,source_draft_id=original.id,source_record_index=0,
            created_by_username='admin',financial_status='confirmed',parts_status='not_applicable'))
        m.db.session.commit()
        for kind in ('12month','vehicle_inspection'):
            complete(d,kind,'2026-09-14',original.id)
        d.run_alerts()
        info={'vehicle_id':d.vehicle.id,'legacy_plan':legacy.id,'legacy_record':record.id,
              'held_plan':held.id,'held_receipt':held_receipt.id,'ended_receipt':ended_receipt.id,
              'original_id':original.id,'source_sha256':original.source_sha256,
              'snapshot':snapshot(m)}
        m.db.session.commit(); m.db.session.remove(); m.db.engine.dispose()
        shutil.copyfile(Path(Driver.temp.name)/'test.db',database)
        metadata.write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
        d.tearDown(); d.doCleanups(); Driver.tearDownClass()
        result={'stage':stage,'passed':True,'dataset':'new car/periodic plans and same-day actuals; confirmed legacy original; unknown old plan; held/ended/normal notices; shared original'}
    else:
        info=json.loads(metadata.read_text(encoding='utf-8'))
        if stage=='candidate':
            runpy.run_path(str(Path.cwd()/'gunicorn.conf.py'))
            assert os.environ['DOCUMENT_IMPORT_WORKER_ENABLED']=='0'
        os.environ.update(SECRET_KEY='isolated-switch-key',ITC_INITIAL_PASSWORD='Synthetic-Only-742!',
            DATABASE_URL='sqlite:///'+str(database),MFA_ENABLED='false',RENDER='')
        from dkss_app import create_app
        m=ApplicationFixture(create_app(initialize_database=False)); d.m=m
        m.app.config.update(TESTING=True,WTF_CSRF_ENABLED=False); m.limiter.enabled=False
        context=m.app.app_context(); context.push()
        d.vehicle=m.db.session.get(m.Vehicle,info['vehicle_id']); d.client=m.app.test_client()
        user=m.User.query.filter_by(company_code='TEST',username='admin').one()
        with d.client.session_transaction() as session:
            session.update(company_code='TEST',username='admin',role='admin',account_identity=user.account_identity,password_changed_at=user.password_changed_at)
        expected=info['snapshot'] if stage=='candidate' else info['candidate_snapshot']
        d.assertEqual(snapshot(m),expected,'Switch/startup altered stored facts')
        d.assertEqual(m.inspection_plans.plan_kind(m.db.session.get(m.VehicleInspectionPlan,info['legacy_plan'])),'12month')
        d.assertEqual(m.inspection_plans.plan_kind(m.db.session.get(m.VehicleInspectionPlan,info['held_plan'])),'annual_unconfirmed')
        for kind in ('12month','vehicle_inspection','annual_unconfirmed'):
            page=d.client.get('/api/vehicle/inspection-plans?scope=company&year=2026')
            d.assertEqual(page.status_code,200)
            d.assertTrue(any(row['kind']==kind for row in page.json['plans']))
            export=d.client.get('/vehicle/inspection-plans/export.xlsx',query_string={'scope':'company','year':2026,'kind':kind})
            d.assertEqual(export.status_code,200)
            karte=d.client.get(f'/vehicle/karte/{d.vehicle.id}/inspections?inspection_view={kind}')
            d.assertEqual(karte.status_code,200)
        for execution in m.inspection_plans.Execution.query.all():
            original=d.client.get(f'/vehicle/inspection-plans/executions/{execution.id}/source')
            d.assertEqual(original.status_code,200)
            d.assertEqual(hashlib.sha256(original.data).hexdigest(),info['source_sha256'])
        d.run_alerts()
        d.assertEqual(snapshot(m),expected,'Read/normal tick altered saved facts or protected receipt history')
        for kind in ('12month','vehicle_inspection'):
            duplicate=d.client.post('/api/vehicle/inspection-plans/execution/preview',json=dict(
                vehicle_record_id=d.vehicle.id,kind=kind,performed_date='2026-09-14',kind_contract='independent-v1'))
            d.assertEqual(duplicate.status_code,409)
            duplicate=d.client.post('/api/vehicle/inspection-plans/preview',json=dict(
                changes=[d.change(kind=kind,mon='2026-12')],kind_contract='independent-v1'))
            d.assertEqual(duplicate.status_code,409)
        d.assertEqual(snapshot(m),expected,'Rejected duplicates changed state')
        if stage=='candidate':
            for kind in ('12month','vehicle_inspection'):
                d.save_plan(kind,mon='2027-02')
                complete(d,kind,'2026-07-14',info['original_id'])
            d.run_alerts()
            # Newly allowed registrations must not modify any pre-existing fact/receipt.
            after=snapshot(m)
            for table, rows in expected.items():
                for row in rows:
                    d.assertIn(row,after[table],table)
            info['candidate_snapshot']=after
            metadata.write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
        else:
            for kind in ('12month','vehicle_inspection'):
                duplicate=d.client.post('/api/vehicle/inspection-plans/execution/preview',json=dict(
                    vehicle_record_id=d.vehicle.id,kind=kind,performed_date='2026-07-14',kind_contract='independent-v1'))
                d.assertEqual(duplicate.status_code,409)
            d.assertEqual(snapshot(m),expected)
        result={'stage':stage,'passed':True,'checks':['API/karte/Excel identities','shared original bytes',
            'semantic duplicate rejection','held/ended/normal receipt and read history unchanged',
            'same SQLite preserved across code switch','candidate new writes retained' if stage=='candidate' else 'candidate writes readable after switch back']}
        m.db.session.remove();m.db.engine.dispose();context.pop()
    (root/f'M06-switch-{stage}-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))

