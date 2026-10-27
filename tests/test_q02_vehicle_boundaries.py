"""QP-20261027 Q02-VEHICLE-03: tenant/parent boundaries and write roles.

Real Flask endpoints and model queries, synthetic temporary SQLite only.
No production DB or AI/OCR/mail/S3 services. PostgreSQL concurrency is excluded.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch


class Q02VehicleBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='dkss-q02-vehicle-')
        from dkss_app import create_app, models
        from dkss_app.extensions import db, limiter
        cls.db,cls.models=db,models
        env={'SECRET_KEY':'q02-isolated-vehicle-tests','RENDER':'',
             'DATABASE_URL':'sqlite:///'+str(Path(cls.temp.name)/'test.db'),
             'OPENAI_API_KEY':'','SMTP_HOST':'','S3_BUCKET_NAME':'',
             'VAPID_PRIVATE_KEY':'','VAPID_PUBLIC_KEY':'','AWS_EC2_METADATA_DISABLED':'true'}
        with patch.dict(os.environ,env):
            cls.app=create_app({'TESTING':True,'WTF_CSRF_ENABLED':False})
        limiter.enabled=False

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            cls.db.session.remove();cls.db.engine.dispose()
        cls.temp.cleanup()

    def setUp(self):
        self.ctx=self.app.app_context();self.ctx.push()
        self.db.drop_all();self.db.create_all()
        m=self.models
        for company in ('A','B'):
            self.db.session.add(m.Company(company_code=company,company_name=company,active=True))
            self.db.session.add(m.User(company_code=company,username='same',password='unused',
                role='admin',last_name='Test',first_name='User',password_changed_at='2026-10-27 10:00:00'))
        self.vehicles=[m.Vehicle(company_code=c,chassis_number=ch,office='test') for c,ch in
                       [('A','OWN-1'),('A','OWN-2'),('B','FOREIGN-CHASSIS-SECRET')]]
        self.db.session.add_all(self.vehicles);self.db.session.flush()
        self.a,self.a2,self.b=self.vehicles
        self.records=[]
        for vehicle,content in zip(self.vehicles,['OWN-MAINTENANCE','SECOND-VEHICLE-SECRET','FOREIGN-MAINTENANCE-SECRET']):
            row=m.VehicleMaintenanceRecord(company_code=vehicle.company_code,
                vehicle_record_id=vehicle.id,content=content,entry_date='2026-10-01',
                completion_date='2026-10-02',status='完了',total_cost={'A':11111,'B':99999}[vehicle.company_code])
            self.db.session.add(row);self.records.append(row)
        self.db.session.commit()
        self.ra,self.ra2,self.rb=self.records
        self.client=self.app.test_client()
        with self.client.session_transaction() as session:
            session.update(company_code='A',username='same',role='admin',
                           password_changed_at='2026-10-27 10:00:00')

    def tearDown(self):
        self.db.session.remove();self.ctx.pop()

    def request(self,method,url,**kwargs):
        r=self.client.open(url,method=method,**kwargs)
        self.addCleanup(r.close)
        return r

    def snapshot(self):
        self.db.session.expire_all()
        m=self.models
        return ([tuple(getattr(row,col.name) for col in m.VehicleMaintenanceRecord.__table__.columns)
                 for row in m.VehicleMaintenanceRecord.query.order_by(m.VehicleMaintenanceRecord.id).all()],
                m.VehicleKarteNote.query.count(),m.VehicleMaintenanceRecordEvent.query.count(),m.AuditLog.query.count())

    def payload(self,**extra):
        return {'content':'CHANGED','entry_date':'2026-10-01','completion_date':'2026-10-02',
                'total_cost':'100','maintenance_action':'save',**extra}

    def edit_url(self,vehicle=None,record=None):
        return f'/vehicle/karte/{(vehicle or self.a).id}/maintenance/{(record or self.ra).id}/edit'

    def version(self):
        r=self.request('GET',self.edit_url())
        self.assertEqual(r.status_code,200)
        match=re.search(r'name="record_version" value="([a-f0-9]{64})"',r.get_data(as_text=True))
        self.assertIsNotNone(match)
        return match.group(1)

    def set_role(self,role):
        self.models.User.query.filter_by(company_code='A',username='same').one().role=role
        self.db.session.commit()

    def test_foreign_vehicle_all_read_tabs_are_404(self):
        for suffix in ('','/history','/documents','/inspections','/parts','/costs','/maintenance'):
            with self.subTest(suffix=suffix):
                r=self.request('GET',f'/vehicle/karte/{self.b.id}{suffix}')
                self.assertEqual(r.status_code,404)
                self.assertNotIn('FOREIGN-MAINTENANCE-SECRET',r.get_data(as_text=True))

    def test_own_vehicle_read_tabs_remain_available(self):
        for suffix in ('','/history','/documents','/inspections','/parts','/costs','/maintenance'):
            with self.subTest(suffix=suffix):
                r=self.request('GET',f'/vehicle/karte/{self.a.id}{suffix}')
                self.assertEqual(r.status_code,200)
                self.assertNotIn('FOREIGN-MAINTENANCE-SECRET',r.get_data(as_text=True))

    def test_record_id_cannot_cross_vehicle_or_company_on_read(self):
        for record in (self.ra2,self.rb):
            with self.subTest(id=record.id):
                self.assertEqual(self.request('GET',f'/vehicle/karte/{self.a.id}/maintenance/{record.id}').status_code,404)

    def test_record_id_cannot_cross_vehicle_or_company_on_edit(self):
        before=self.snapshot()
        for vehicle,record in ((self.a,self.ra2),(self.a,self.rb),(self.b,self.ra),(self.b,self.rb)):
            for method in ('GET','POST'):
                with self.subTest(vehicle=vehicle.id,record=record.id,method=method):
                    r=self.request(method,self.edit_url(vehicle,record),data=self.payload())
                    self.assertEqual(r.status_code,404)
                    self.assertEqual(self.snapshot(),before)

    def test_foreign_new_record_and_note_are_rejected_without_writes(self):
        before=self.snapshot()
        for url,data in [(f'/vehicle/karte/{self.b.id}/maintenance/new',self.payload()),
                         (f'/vehicle/karte/{self.b.id}/note',{'version':'0','content':'bad'})]:
            with self.subTest(url=url):
                self.assertEqual(self.request('POST',url,data=data).status_code,404)
                self.assertEqual(self.snapshot(),before)

    def test_general_user_cannot_write_maintenance_or_note(self):
        self.set_role('user')
        before=self.snapshot()
        for url,data in [(f'/vehicle/karte/{self.a.id}/maintenance/new',self.payload()),
                         (self.edit_url(),self.payload()),
                         (f'/vehicle/karte/{self.a.id}/note',{'version':'0','content':'bad'})]:
            with self.subTest(url=url):
                self.assertEqual(self.request('POST',url,data=data).status_code,403)
                self.assertEqual(self.snapshot(),before)

    def test_role_revoked_after_form_open_cannot_submit_stale_form(self):
        token=self.version()
        self.set_role('user')
        before=self.snapshot()
        self.assertEqual(self.request('POST',self.edit_url(),data=self.payload(record_version=token)).status_code,403)
        self.assertEqual(self.snapshot(),before)

    def test_new_record_ignores_forged_company_vehicle_and_creator_fields(self):
        r=self.request('POST',f'/vehicle/karte/{self.a.id}/maintenance/new',data=self.payload(
            company_code='B',vehicle_record_id=str(self.b.id),created_by_username='forged'))
        self.assertEqual(r.status_code,302)
        row=self.models.VehicleMaintenanceRecord.query.filter_by(content='CHANGED').one()
        self.assertEqual((row.company_code,row.vehicle_record_id,row.created_by_username),('A',self.a.id,'same'))
        event=self.models.VehicleMaintenanceRecordEvent.query.filter_by(maintenance_record_id=row.id).one()
        self.assertEqual((event.company_code,event.vehicle_record_id,event.created_by_username),('A',self.a.id,'same'))

    def test_edit_ignores_forged_parent_company_and_creator(self):
        token=self.version()
        foreign_before=self.snapshot()[0][1:]
        r=self.request('POST',self.edit_url(),data=self.payload(record_version=token,
            company_code='B',vehicle_record_id=str(self.b.id),created_by_username='forged'))
        self.assertEqual(r.status_code,302)
        states=self.snapshot()
        self.assertEqual(states[0][1:],foreign_before)
        self.assertEqual((self.ra.company_code,self.ra.vehicle_record_id,self.ra.updated_by_username),('A',self.a.id,'same'))
        self.assertEqual(self.ra.content,'CHANGED')

    def test_stale_edit_token_rejects_second_update_without_events(self):
        token=self.version()
        self.assertEqual(self.request('POST',self.edit_url(),data=self.payload(record_version=token)).status_code,302)
        before=self.snapshot()
        r=self.request('POST',self.edit_url(),data=self.payload(record_version=token,content='STALE'))
        self.assertEqual(r.status_code,409)
        self.assertEqual(self.snapshot(),before)

    def test_unknown_inspection_link_cannot_be_attached(self):
        token=self.version()
        before=self.snapshot()
        r=self.request('POST',self.edit_url(),data=self.payload(record_version=token,inspection_defect='999999:1:1'))
        self.assertEqual(r.status_code,400)
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.models.VehicleMaintenanceInspectionLink.query.count(),0)

    def document(self,vehicle,company=None,status='completed'):
        content=b'%PDF-Q02-'+vehicle.chassis_number.encode()
        row=self.models.VehicleDocumentImportDraft(id='doc-'+str(vehicle.id),batch_id='batch',
            company_code=company or vehicle.company_code,created_by_username='same',
            document_type='maintenance_invoice',source_filename='test.pdf',source_file=content,
            source_sha256=hashlib.sha256(content).hexdigest(),status=status,
            result_json=json.dumps({'records':[{'vehicle_record_id':vehicle.id}]}))
        self.db.session.add(row);self.db.session.commit()
        return row,content

    def test_document_source_requires_both_company_and_vehicle_match(self):
        doc,data=self.document(self.a)
        doc2,_=self.document(self.a2)
        foreign,_=self.document(self.b)
        r=self.request('GET',f'/vehicle/karte/{self.a.id}/documents/{doc.id}/source')
        self.assertEqual(r.status_code,200);self.assertEqual(r.data,data)
        self.assertIn('no-store',r.headers['Cache-Control'])
        for vehicle,draft in ((self.a,doc2),(self.a,foreign),(self.b,doc),(self.b,foreign)):
            with self.subTest(vehicle=vehicle.id,draft=draft.id):
                self.assertEqual(self.request('GET',f'/vehicle/karte/{vehicle.id}/documents/{draft.id}/source').status_code,404)

    def test_preview_document_is_not_published_as_vehicle_source(self):
        doc,_=self.document(self.a,status='preview')
        self.assertEqual(self.request('GET',f'/vehicle/karte/{self.a.id}/documents/{doc.id}/source').status_code,404)

    def operation(self,vehicle):
        row=self.models.VehicleOperationImportDraft(id='op-'+str(vehicle.id),
            company_code=vehicle.company_code,created_by_username='same',
            source_filename='test.csv',source_file=b'Q02-operation-'+str(vehicle.id).encode(),
            status='completed',result_json=json.dumps({'imported_vehicle_ids':[vehicle.id]}))
        self.db.session.add(row);self.db.session.commit()
        return row

    def test_operation_source_requires_both_company_and_vehicle_match(self):
        own=self.operation(self.a);other=self.operation(self.a2);foreign=self.operation(self.b)
        r=self.request('GET',f'/vehicle/karte/{self.a.id}/operation-files/{own.id}')
        self.assertEqual(r.status_code,200);self.assertEqual(r.data,own.source_file)
        self.assertIn('no-store',r.headers['Cache-Control'])
        for vehicle,draft in ((self.a,other),(self.a,foreign),(self.b,own),(self.b,foreign)):
            with self.subTest(vehicle=vehicle.id,draft=draft.id):
                self.assertEqual(self.request('GET',f'/vehicle/karte/{vehicle.id}/operation-files/{draft.id}').status_code,404)

    def test_foreign_cost_query_parameters_cannot_change_vehicle_scope(self):
        from flask import template_rendered
        captured=[]
        def capture(sender, template, context, **extra):
            captured.append(context)
        with template_rendered.connected_to(capture,self.app):
            r=self.request('GET',f'/vehicle/karte/{self.a.id}/costs?year=2026&company_code=B&vehicle_record_id={self.b.id}')
        details=captured[-1]['cost_details']
        self.assertEqual(details['selected_summary']['total_cost'],11111)
        self.assertEqual(details['all_time_summary']['total_cost'],11111)
        self.assertEqual(details['selected_record_count'],1)
        self.assertEqual([row.id for row in details['high_cost_records']],[self.ra.id])
        self.assertEqual(r.status_code,200)
        self.assertNotIn('FOREIGN-MAINTENANCE-SECRET',r.get_data(as_text=True))
        self.assertNotIn('FOREIGN-CHASSIS-SECRET',r.get_data(as_text=True))


    def test_inconsistent_company_parent_record_is_excluded_from_costs(self):
        # Intentional legacy inconsistency: a B record points at A's vehicle.
        # This verifies application filtering, not DB constraint enforcement.
        row=self.models.VehicleMaintenanceRecord(company_code='B',vehicle_record_id=self.a.id,
            content='INCONSISTENT-COMPANY-SECRET',entry_date='2026-10-01',total_cost=888888)
        self.db.session.add(row);self.db.session.commit()
        from flask import template_rendered
        captured=[]
        def capture(sender,template,context,**extra):
            captured.append(context)
        with template_rendered.connected_to(capture,self.app):
            r=self.request('GET',f'/vehicle/karte/{self.a.id}/costs?year=2026')
        self.assertEqual(r.status_code,200)
        self.assertNotIn('INCONSISTENT-COMPANY-SECRET',r.get_data(as_text=True))
        self.assertEqual(captured[-1]['cost_details']['selected_summary']['total_cost'],11111)
        self.assertEqual(captured[-1]['cost_details']['selected_record_count'],1)

if __name__=='__main__':
    unittest.main()
