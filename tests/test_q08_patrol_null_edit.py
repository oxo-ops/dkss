"""New focused acceptance; none of the previous 20/26 audit cases are loaded."""
import json
import os
from pathlib import Path
import re
import subprocess
import unittest
from unittest.mock import patch

from sqlalchemy import event, text
import test_q02_vehicle_workflow_boundaries as fixture
from test_q08_postgres_identity import DisposablePostgres


class PatrolFixture(unittest.TestCase):
    setUpClass=classmethod(fixture.Q02VehicleWorkflowBoundaryTests.setUpClass.__func__)
    tearDownClass=classmethod(fixture.Q02VehicleWorkflowBoundaryTests.tearDownClass.__func__)
    tearDown=fixture.Q02VehicleWorkflowBoundaryTests.tearDown
    login=fixture.Q02VehicleWorkflowBoundaryTests.login

    def setUp(self):
        fixture.Q02VehicleWorkflowBoundaryTests.setUp(self)
        self.app.config['WTF_CSRF_ENABLED']=True
        from dkss_app import notifications_delivery
        self.enterContext(patch.object(notifications_delivery,'dispatch_external_notification'))
        if self.db.engine.dialect.name=='sqlite':
            self.db.session.remove();self.db.engine.dispose()
            engine=self.db.engine
            def fk(connection, record):connection.execute('PRAGMA foreign_keys=ON')
            event.listen(engine,'connect',fk)
            self.addCleanup(event.remove,engine,'connect',fk)
            self.assertEqual(self.db.session.scalar(text('PRAGMA foreign_keys')),1)
        self.ids={}
        for company in ('A','B'):
            vehicle=self.models.Vehicle.query.filter_by(company_code=company).one()
            row=self.models.VehiclePatrol(company_code=company,vehicle_record_id=vehicle.id,
                category='不具合',priority='高',content='Q08 original '+company,status='未対応',
                occurred_date='',cause='',temporary_action='',repair_content='',repair_date='',
                repair_person='',repair_time='',parts='',cost='')
            self.db.session.add(row);self.db.session.commit()
            self.ids[company]=row.id
        row=self.row()
        self.db.session.execute(row.__table__.update().where(row.__table__.c.id==row.id).values(status=None))
        self.db.session.commit()

    def tearDown(self):
        self.app.config['WTF_CSRF_ENABLED']=False
        fixture.Q02VehicleWorkflowBoundaryTests.tearDown(self)

    def row(self, company='A'):
        return self.db.session.get(self.models.VehiclePatrol,self.ids[company])

    def request(self,method,path,**kw):
        self.db.session.remove();self.ctx.pop()
        try:r=self.client.open(path,method=method,**kw)
        finally:self.ctx=self.app.app_context();self.ctx.push()
        self.addCleanup(r.close)
        return r

    def path(self):return f'/vehicle-patrols/{self.ids["A"]}/edit'

    def get_form(self,path=None):
        response=self.request('GET',path or self.path())
        self.assertEqual(response.status_code,200)
        return response.get_data(as_text=True)

    def data(self,html=None):
        html=html or self.get_form()
        token=re.search(r'name="csrf_token"\s+value="([^"]+)"',html).group(1)
        vehicle=self.models.Vehicle.query.filter_by(company_code='A').one()
        return dict(csrf_token=token,vehicle_record_id=vehicle.id,category='不具合',priority='高',
            content='Q08 body-only edit',occurred_date='',cause='',temporary_action='',repair_content='',
            repair_date='',repair_person='',repair_time='',parts='',cost='')

    def snapshot(self):
        self.db.session.expire_all()
        return tuple(tuple(tuple(getattr(r,c.name) for c in m.__table__.columns)
            for r in m.query.order_by(m.id)) for m in (self.models.VehiclePatrol,
                self.models.Notification,self.models.AuditLog))


class PatrolNullEditTests(PatrolFixture):
    def test_missing_status_preserves_null_and_updates_body(self):
        data=self.data()
        self.assertNotIn('status',data)
        self.assertEqual(self.request('POST',self.path(),data=data).status_code,302)
        self.assertIsNone(self.row().status)
        self.assertEqual(self.row().content,data['content'])

    def test_missing_status_preserves_each_existing_regular_state(self):
        for status in ('未対応','対応中','修理完了'):
            self.row().status=status;self.db.session.commit()
            response=self.request('POST',self.path(),data=self.data())
            self.assertEqual(response.status_code,302)
            self.assertEqual(self.row().status,status)

    def test_explicit_regular_status_changes_are_allowed(self):
        for status in ('未対応','対応中','修理完了'):
            response=self.request('POST',self.path(),data=dict(self.data(),status=status))
            self.assertEqual(response.status_code,302)
            self.assertEqual(self.row().status,status)

    def test_explicit_empty_or_unknown_status_is_rejected_without_partial_write(self):
        for status in ('','Q08_UNKNOWN','null','false'):
            before=self.snapshot()
            response=self.request('POST',self.path(),data=dict(self.data(),status=status))
            self.assertEqual(response.status_code,400)
            self.assertEqual(self.snapshot(),before)

    def test_new_patrol_omitted_status_still_defaults_to_unhandled(self):
        html=self.get_form('/vehicle-patrols/new')
        response=self.request('POST','/vehicle-patrols/new',data=self.data(html))
        self.assertEqual(response.status_code,302)
        row=self.models.VehiclePatrol.query.order_by(self.models.VehiclePatrol.id.desc()).first()
        self.assertEqual(row.status,'未対応')

    def test_new_patrol_invalid_status_is_still_rejected(self):
        html=self.get_form('/vehicle-patrols/new')
        before=self.snapshot()
        response=self.request('POST','/vehicle-patrols/new',data=dict(self.data(html),status='Q08_UNKNOWN'))
        self.assertEqual(response.status_code,400)
        self.assertEqual(self.snapshot(),before)

    def test_other_company_and_non_admin_cannot_edit(self):
        data=self.data()
        before=self.snapshot()
        self.login('admin','B')
        data['csrf_token']=self.request('GET','/login/csrf-token').json['csrf_token']
        self.assertEqual(self.request('POST',self.path(),data=data).status_code,302)
        self.assertEqual(self.snapshot(),before)
        self.login('checker','A')
        data['csrf_token']=self.request('GET','/login/csrf-token').json['csrf_token']
        self.assertEqual(self.request('POST',self.path(),data=data).status_code,302)
        self.assertEqual(self.snapshot(),before)


class PostgresPatrolNullEditTests(DisposablePostgres,PatrolNullEditTests):
    @classmethod
    def setUpClass(cls):
        DisposablePostgres.setUpClass.__func__(cls)
        from dkss_app import models
        cls.app,cls.db,cls.models=cls.m.app,cls.m.db,models


@unittest.skipUnless(os.environ.get('Q08_PATROL_BROWSER')=='1','explicit native Chromium acceptance required')
class PatrolNullBrowserTests(PatrolFixture):
    def test_real_get_native_form_data_body_edit_and_explicit_choices(self):
        html=self.get_form()
        result=subprocess.run([os.environ.get('Q08_NODE','node'),str(Path(__file__).with_name('q08_patrol_form_browser.cjs'))],
            input=html,text=True,encoding='utf8',capture_output=True,timeout=45)
        self.assertEqual(result.returncode,0,result.stderr)
        browser=json.loads(result.stdout)
        response=self.request('POST',self.path(),data=browser['bodyOnly'])
        self.assertEqual(response.status_code,302,response.get_data(as_text=True)[:300])
        self.assertIsNone(self.row().status,'The browser implicitly selected 未対応')
        self.assertEqual(self.row().content,'Q08 browser body-only edit')
        self.assertNotIn('status',browser['bodyOnly'])
        self.assertEqual(browser['before']['value'],'')
        self.assertTrue(browser['before']['disabled'])
        self.assertIn('状態未確認',browser['before']['label'])
        for status,data in browser['explicit'].items():
            self.assertEqual(data['status'],status)
            self.assertEqual(self.request('POST',self.path(),data=data).status_code,302)
            self.assertEqual(self.row().status,status)


class PostgresPatrolNullBrowserTests(DisposablePostgres,PatrolNullBrowserTests):
    setUpClass=classmethod(PostgresPatrolNullEditTests.setUpClass.__func__)
