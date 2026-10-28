"""Viewer isolation and manager-confirmed identity against real Flask/SQLite."""
import json
import unittest
from datetime import date
from unittest.mock import patch
from urllib.parse import urlencode
import test_workflow_regressions as workflow
import test_driving_report_insights as insights_tests
from driving_report_data import payload, version
from driving_report_insights import periods, driver_keys
from dkss_app import driving_access as access
from dkss_app.models import DrivingReportReader


class DrivingReadershipTests(unittest.TestCase):
    setUpClass=classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass=classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    tearDown=workflow.WorkflowRegressionTests.tearDown
    save=insights_tests.DrivingInsightRouteTests.save

    def setUp(self):
        workflow.WorkflowRegressionTests.setUp(self)
        for username,company in [('one','TEST'),('two','TEST'),('outsider','OTHER')]:
            self.m.db.session.add(self.m.User(company_code=company,username=username,password='unused',role='user',last_name='同姓',first_name='同名',password_changed_at='stamp'))
        self.m.db.session.commit()

    def login(self,username='one',role='user'):
        with self.client.session_transaction() as state:
            state.update(company_code='TEST',username=username,role=role,password_changed_at='stamp' if role=='user' else self.m.User.query.filter_by(username='admin').one().password_changed_at)

    def grant(self,record,username='one'):
        return self.client.post(f'/safety/driving-reports/{record.id}/reader',data={'version':version(record),'reader_username':username})

    def test_no_name_code_or_uploader_fallback_and_sidebar_visible(self):
        self.save(name='同姓同名',code='one')
        self.login()
        response=self.client.get('/safety/driving-reports?scope=company&period=all')
        self.assertEqual(response.status_code,200)
        text=response.get_data(as_text=True)
        self.assertIn('自分の運転実績',text);self.assertIn('本人確認済みの日報はありません',text)
        self.assertNotIn('DTG',text)
        self.assertIn('no-store',response.headers['Cache-Control'])

    def test_list_details_exports_filters_cannot_read_other_people(self):
        own=self.save(name='本人だけ');other=self.save(2,name='他人秘密',code='B')
        secret=self.save(3,name='他社秘密',code='C');secret.company_code='OTHER';self.m.db.session.commit()
        self.assertEqual(self.grant(own).status_code,302)
        self.assertEqual(self.grant(other,'two').status_code,302)
        p=payload(own);p['audit'].append({'kind':'correction','detail':'変更前の他人秘密'});own.details_json=json.dumps(p);self.m.db.session.commit()
        self.login()
        for suffix in ['?period=all','?period=all&driver=他人秘密','?period=all&focus='+driver_keys([other])[0][other.id],'/export.csv?period=all','/export.csv?period=all&view=comparison']:
            response=self.client.get('/safety/driving-reports'+suffix)
            self.assertEqual(response.status_code,200)
            self.assertNotIn('他人秘密',response.get_data(as_text=True));self.assertNotIn('他社秘密',response.get_data(as_text=True))
        self.assertEqual(self.client.get(f'/safety/driving-reports/{own.id}').status_code,200)
        self.assertEqual(self.client.get(f'/safety/driving-reports/{other.id}').status_code,404)
        self.assertEqual(self.client.get(f'/safety/driving-reports/{secret.id}').status_code,404)
        from pypdf import PdfReader
        from io import BytesIO
        response=self.client.get('/safety/driving-reports/export.pdf?scope=company&period=all')
        text=''.join(p.extract_text() for p in PdfReader(BytesIO(response.data)).pages)
        self.assertIn('本人だけ',text);self.assertNotIn('他人秘密',text)

    def test_user_is_read_only_and_original_files_are_not_exposed(self):
        own=self.save();self.grant(own);self.login()
        for endpoint in ['review','reconcile','reader','edit']:
            self.assertEqual(self.client.post(f'/safety/driving-reports/{own.id}/{endpoint}',data={'version':version(own),'state':'completed','reader_username':'one'}).status_code,403)
        self.assertEqual(self.client.get(f'/safety/driving-reports/{own.id}/edit').status_code,403)
        with self.m.app.test_request_context():
            from flask import url_for
            source=url_for('vehicle_driving_report_source',record_id=own.id)
        self.assertEqual(self.client.get(source).status_code,403)
        html=self.client.get(f'/safety/driving-reports/{own.id}').get_data(as_text=True)
        self.assertNotIn('原本と照合・訂正',html);self.assertNotIn('本人の閲覧設定',html)
        self.assertNotIn('車両の履歴',html);self.assertNotIn('変更履歴',html)
        self.assertNotIn('確認内容を保存',html)

    def test_admin_cannot_bind_cross_company_or_stale_records(self):
        own=self.save();old_version=version(own)
        self.assertEqual(self.grant(own,'outsider').status_code,400)
        self.assertEqual(self.grant(own).status_code,302)
        self.assertEqual(self.client.post(f'/safety/driving-reports/{own.id}/reader',data={'version':old_version,'reader_username':'two'}).status_code,409)
        self.assertEqual(DrivingReportReader.query.one().username,'one')
        secret=self.save(3);secret.company_code='OTHER';self.m.db.session.commit()
        self.assertEqual(self.grant(secret).status_code,404)

    def test_identity_correction_reassignment_and_revocation_take_effect(self):
        own=self.save();self.grant(own)
        p=payload(own);p['driver_name']='訂正後の本人';own.details_json=json.dumps(p);self.m.db.session.commit()
        self.login();self.assertEqual(self.client.get(f'/safety/driving-reports/{own.id}').status_code,404)
        self.login('admin','admin');self.grant(own,'two')
        self.login();self.assertEqual(self.client.get(f'/safety/driving-reports/{own.id}').status_code,404)
        self.login('two');self.assertEqual(self.client.get(f'/safety/driving-reports/{own.id}').status_code,200)
        self.login('admin','admin');self.grant(own,'')
        self.login('two');self.assertEqual(self.client.get(f'/safety/driving-reports/{own.id}').status_code,404)

    def test_bulk_grant_is_scoped_and_checks_version(self):
        from flask import template_rendered
        own=self.save();second=self.save(2,day='2026-10-11');other=self.save(3,code='B',name='別の人')
        focus=driver_keys([own,second,other])[0][own.id]
        contexts=[]
        def capture(sender,template,context,**extra):contexts.append(context)
        template_rendered.connect(capture,self.m.app)
        try:self.client.get('/safety/driving-reports?'+urlencode({'scope':'company','period':'all','focus':focus}))
        finally:template_rendered.disconnect(capture,self.m.app)
        token=contexts[-1]['insights']['reader_version']
        data={'scope':'company','period':'all','focus':focus,'reader_version':token,'reader_username':'one','return_to':'/safety/driving-reports?scope=company&period=all#driver-trend'}
        self.assertEqual(self.client.post('/safety/driving-reports/readers',data=dict(data,reader_version='stale')).status_code,409)
        self.assertEqual(DrivingReportReader.query.count(),0)
        response=self.client.post('/safety/driving-reports/readers',data=data)
        self.assertEqual(response.status_code,302)
        self.assertEqual({g.report_id for g in DrivingReportReader.query.all()},{own.id,second.id})
        self.login();self.assertEqual(self.client.post('/safety/driving-reports/readers',data=data).status_code,403)
        self.assertEqual(self.client.get(f'/safety/driving-reports/{other.id}').status_code,404)
        # The confirmed source/code/name correspondence applies to later imports.
        fourth=self.save(4)
        self.assertEqual(self.client.get(f'/safety/driving-reports/{fourth.id}').status_code,200)

    def test_missing_schema_fails_closed_and_explicit_initializer_is_idempotent(self):
        with self.m.db.engine.begin() as connection:DrivingReportReader.__table__.drop(connection)
        self.m.app.extensions['dkss']['driving_readers_ready']=False
        self.login();self.assertEqual(self.client.get('/safety/driving-reports?scope=company&period=all').status_code,200)
        self.login('admin','admin');own=self.save();self.assertEqual(self.grant(own).status_code,503)
        for _ in range(2):access.initialize_driving_access(self.m.app)
        self.assertEqual(self.grant(own).status_code,302)

    def test_comparison_period_is_explicit_and_previous_month_includes_leap_day(self):
        p=periods({'period':'month','compare':'month'},date(2028,3,10))
        self.assertEqual((p['previous_start'],p['previous_end']),('2028-02-01','2028-02-29'))
        self.assertEqual(self.client.get('/safety/driving-reports?compare=bad').status_code,400)

    def test_reusing_a_login_name_does_not_inherit_a_previous_users_records(self):
        own=self.save();self.grant(own)
        original=self.m.User.query.filter_by(company_code='TEST',username='one').one()
        old_id=original.id
        # Removing an account can be blocked by the FK; changing its login name also
        # simulates a new account taking the old login without transferring the grant.
        original.username='retired';self.m.db.session.commit()
        self.m.db.session.add(self.m.User(company_code='TEST',username='one',role='user',password='unused',last_name='別人',password_changed_at='stamp'))
        self.m.db.session.commit()
        self.assertNotEqual(self.m.User.query.filter_by(username='one').one().id,old_id)
        self.login();self.assertEqual(self.client.get(f'/safety/driving-reports/{own.id}').status_code,404)
