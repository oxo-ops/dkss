"""Standard daily inspection flows using production templates and real routes.

Only companies, users and vehicles are seeded. The HTTP routes create templates,
answers, results, defects, judgments, maintenance, rechecks and notifications.
Disposable SQLite; external delivery disabled. No browser or PostgreSQL proof.
"""
from identity_fixture import identity_for
import io
import html
import re
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class Q02DailyInspectionFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='dkss-q02-daily-flow-')
        from dkss_app import create_app, models
        from dkss_app.extensions import db, limiter
        cls.db, cls.models = db, models
        env = {'SECRET_KEY': 'q02-daily-flow-test-only', 'RENDER': '',
               'DATABASE_URL': 'sqlite:///' + str(Path(cls.temp.name) / 'test.db'),
               'OPENAI_API_KEY': '', 'SMTP_HOST': '', 'S3_BUCKET_NAME': '',
               'VAPID_PRIVATE_KEY': '', 'VAPID_PUBLIC_KEY': '',
               'AWS_EC2_METADATA_DISABLED': 'true'}
        with patch.dict(os.environ, env):
            cls.app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False})
        limiter.enabled = False

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            cls.db.session.remove()
            cls.db.engine.dispose()
        cls.temp.cleanup()

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.db.drop_all()
        self.db.create_all()
        m = self.models
        for company in ('A', 'B'):
            self.db.session.add(m.Company(company_code=company, company_name=company, active=True))
            for username, role in [('admin', 'admin'), ('checker', 'user'),
                                   ('reviewer', 'user'), ('outsider', 'user'), ('support', 'itc')]:
                self.db.session.add(m.User(company_code=company, username=username, role=role,
                    password='unused', last_name='Test', first_name=username,
                    password_changed_at='2026-10-27 10:00:00'))
        for company in ('A', 'B'):
            self.db.session.add(m.Vehicle(company_code=company, chassis_number=company+'-TEST', deleted=False, office='test'))
        self.db.session.commit()
        self.client = self.app.test_client()
        self.login('admin')

    def tearDown(self):
        self.db.session.remove()
        self.ctx.pop()

    def login(self, username, company='A'):
        user = self.models.User.query.filter_by(company_code=company, username=username).one()
        with self.client.session_transaction() as session:
            session.clear()
            session.update(account_identity=identity_for(company, username, app=(self.client).application), company_code=company, username=username, role=user.role,
                name='Test ' + username, password_changed_at=user.password_changed_at)

    def request(self, method, url, **kwargs):
        response = self.client.open(url, method=method, **kwargs)
        self.addCleanup(response.close)
        return response

    def begin(self, defect=False):
        self.login('checker')
        response=self.request('GET','/vehicle/checklists')
        self.assertIn(response.status_code,(200,302))
        self.checklist=self.models.Checklist.query.filter_by(company_code='A').one()
        items=json.loads(self.checklist.items_json)
        self.assertEqual(items[0]['fixed_template_code'],'daily_inspection_truck_trailer')
        self.check_count=sum(item['item_type']=='check' for item in items)
        self.assertGreater(self.check_count,27)
        vehicle=self.models.Vehicle.query.filter_by(company_code='A').one()
        self.form={'vehicle_record_id':vehicle.id,'year':'2026','month':'10','day':'23'}
        for no in range(self.check_count):
            self.save(no,'×' if defect and no==0 else '✓')
        self.row=self.models.VehicleChecklistResult.query.one()
        self.assertEqual(self.row.status,'入力中')
        self.complete()
        self.db.session.refresh(self.row)
        self.assertEqual(self.row.status,'承認待ち')
        self.assertEqual(self.state()['requested_usernames'],['admin'])
        return self.row

    def save(self,no,value):
        response=self.request('POST',f'/vehicle/checklists/{self.checklist.id}/save-one',
            data={**self.form,'item_no':str(no),'value':value})
        self.assertEqual(response.status_code,302)

    def selection_proof(self):
        response=self.request('GET',f'/vehicle/checklists/{self.checklist.id}',
            query_string={**self.form, 'active_day':self.form['day']})
        self.assertEqual(response.status_code,200)
        match=re.search(r'name="person_selection_token"\s+value="([^"]+)"',response.get_data(as_text=True))
        self.assertIsNotNone(match, 'The real GET must issue person-generation evidence')
        return {'person_selection_token':html.unescape(match[1])}

    def complete(self):
        proof=Q02DailyInspectionFlowTests.selection_proof(self)
        response=self.request('POST',f'/vehicle/checklists/{self.checklist.id}/complete',
            data={**self.form,'approval_notify_users_0':'admin',**proof})
        self.assertEqual(response.status_code,302)

    def state(self):
        self.db.session.refresh(self.row)
        return json.loads(self.row.operation_judgment_json)

    def decision_data(self,decision='運行可'):
        from dkss_app.checklists import get_vehicle_operation_basis
        state=self.state()
        return {'decision':decision,'reason':'合成試験の確認結果','authority_role':'整備管理者',
                'authority_confirmed':'1','judgment_version':str(state.get('version',0)),
                'expected_answers':self.row.answers_json,'expected_snapshot':self.row.checklist_snapshot_json,
                'checks_confirmed':'1','vehicle_operation_basis':get_vehicle_operation_basis('A',self.row.vehicle_record_id)}

    def decide(self,decision='運行可'):
        self.login('admin')
        response=self.request('POST',f'/vehicle/checklist-results/{self.row.id}/operation-judgment',
            data=self.decision_data(decision))
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.state()['status'],decision)
        return response

    def repair(self,recheck=None):
        self.login('checker' if recheck else 'reviewer')
        state=self.state()
        data={'judgment_version':str(state['version']),'repair_status':'再確認待ち',
              'repair_note':'合成試験の整備と確認','repair_performed_date':'2026-10-23'}
        if recheck:data['recheck_result']=recheck
        response=self.request('POST',f'/vehicle/checklist-results/{self.row.id}/defects/1/repair',data=data)
        self.assertEqual(response.status_code,302)
        return data

    def snapshot(self):
        self.db.session.expire_all()
        return tuple(tuple(tuple(getattr(row,c.name) for c in model.__table__.columns)
                           for row in model.query.order_by(model.id).all())
                     for model in (self.models.VehicleChecklistResult,self.models.ChecklistEvent,
                                   self.models.Notification,self.models.VehicleMaintenanceRecord,
                                   self.models.VehicleMaintenanceRecordEvent))

    def assert_integrity(self):
        self.assertEqual(self.models.VehicleChecklistResult.query.count(),1)
        self.assertTrue(all(n.company_code=='A' for n in self.models.Notification.query.all()))
        self.assertTrue(all(e.company_code=='A' for e in self.models.ChecklistEvent.query.all()))
        self.assertTrue(all(r.company_code=='A' and r.vehicle_record_id==self.row.vehicle_record_id
                            for r in self.models.VehicleMaintenanceRecord.query.all()))

    def test_normal_inspection_completes_and_can_be_cleared_once(self):
        self.begin()
        self.assertEqual(len(json.loads(self.row.answers_json)),self.check_count)
        self.assertEqual(self.state()['defects'],[])
        self.login('admin')
        stale=self.decision_data()
        self.decide()
        self.assertEqual(self.row.status,'承認済み')
        before=self.snapshot()
        response=self.request('POST',f'/vehicle/checklist-results/{self.row.id}/operation-judgment',data=stale)
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.snapshot(),before)
        self.assert_integrity()

    def test_defect_repair_recheck_and_clearance_preserve_the_inspection_answer(self):
        self.begin(defect=True)
        self.assertEqual(self.state()['defects'][0]['status'],'対応待ち')
        self.decide('運行不可')
        self.repair()
        self.assertEqual(self.state()['status'],'未判定')
        self.assertEqual(self.state()['defects'][0]['status'],'再確認待ち')
        self.repair('異常なし')
        self.assertEqual(self.state()['defects'][0]['status'],'解消')
        self.decide()
        answers=json.loads(self.row.answers_json)
        self.assertEqual(next(a for a in answers if a['item_no']==0)['value'],'×')
        self.assertEqual(self.models.VehicleMaintenanceRecord.query.count(),1)
        events=self.models.ChecklistEvent.query.filter_by(result_id=self.row.id).order_by(self.models.ChecklistEvent.id).all()
        types=[e.event_type for e in events]
        self.assertEqual(types.count('運行判断'),2)
        self.assertIn('再確認待ち',types)
        self.assertIn('解消',types)
        self.assert_integrity()

    def test_failed_recheck_can_be_repaired_and_rechecked_again(self):
        self.begin(defect=True)
        self.decide('運行不可')
        self.repair()
        self.repair('異常あり')
        self.assertEqual(self.state()['defects'][0]['status'],'対応待ち')
        self.repair()
        self.repair('異常なし')
        self.assertEqual(self.state()['defects'][0]['status'],'解消')
        self.decide()
        self.assert_integrity()

    def test_completed_inspection_answer_cannot_be_rewritten_after_clearance(self):
        self.begin()
        self.decide()
        self.login('checker')
        before=self.snapshot()
        response=self.request('POST',f'/vehicle/checklists/{self.checklist.id}/save-one',
            data={**self.form,'item_no':'0','value':'×'})
        self.assertEqual(response.status_code,403)
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.state()['status'],'運行可')
        self.assert_integrity()

    def test_repair_replay_cannot_duplicate_records_in_real_flow(self):
        self.begin(defect=True)
        self.decide('運行不可')
        stale=self.repair()
        before=self.snapshot()
        response=self.request('POST',f'/vehicle/checklist-results/{self.row.id}/defects/1/repair',data=stale)
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.snapshot(),before)
        self.assert_integrity()

    def test_real_flow_excel_remains_readable_after_recheck(self):
        self.begin(defect=True)
        self.decide('運行不可')
        self.repair()
        self.repair('異常なし')
        self.decide()
        response=self.request('GET',f'/vehicle/checklist-results/{self.row.id}/excel')
        self.assertEqual(response.status_code,200)
        from openpyxl import load_workbook
        book=load_workbook(io.BytesIO(response.data),read_only=True)
        try:
            values=[str(v) for sh in book for row in sh.values for v in row]
            self.assertTrue(any('日常点検' in value for value in values))
            self.assertIn('×',values)
        finally:book.close()
        self.assert_integrity()


if __name__=='__main__':
    unittest.main(verbosity=2)
