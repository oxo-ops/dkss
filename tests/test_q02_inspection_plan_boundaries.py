"""Q02: inspection plan stale sessions, confirmation tokens and evidence downloads.

Real Flask routes, synthetic temporary SQLite only. No PostgreSQL concurrency,
production database, browser, mail, OCR or external storage verification.
"""
from io import BytesIO
import json
import unittest

from openpyxl import load_workbook
import test_inspection_plans as planning


class Q02InspectionPlanBoundaryTests(unittest.TestCase):
    setUpClass = classmethod(planning.InspectionPlanTests.setUpClass.__func__)
    tearDownClass = classmethod(planning.InspectionPlanTests.tearDownClass.__func__)
    tearDown = planning.InspectionPlanTests.tearDown
    change = planning.InspectionPlanTests.change
    certificate_payload = planning.InspectionPlanTests.certificate_payload
    certificate_save = planning.InspectionPlanTests.certificate_save
    certificate_document = planning.InspectionPlanTests.certificate_document

    def setUp(self):
        planning.InspectionPlanTests.setUp(self)
        m = self.m
        self.stamp = self.user().password_changed_at
        m.db.session.add(m.Company(company_code='OTHER', company_name='Other', active=True))
        m.db.session.add(m.User(company_code='OTHER', username='admin', role='admin',
            password='unused', last_name='Synthetic', password_changed_at=self.stamp))
        self.foreign = m.Vehicle(company_code='OTHER', chassis_number='FOREIGN-PLAN-SECRET')
        self.second = m.Vehicle(company_code='TEST', chassis_number='SECOND-VEHICLE')
        m.db.session.add_all([self.foreign, self.second])
        m.db.session.commit()

    def user(self):
        return self.m.User.query.filter_by(company_code='TEST', username='admin').one()

    def request(self, method, path, **kwargs):
        response = self.client.open(path, method=method, **kwargs)
        self.addCleanup(response.close)
        return response

    def actor(self, company):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(company_code=company, username='admin', role='admin',
                           password_changed_at=self.stamp)

    def snapshot(self):
        m = self.m
        m.db.session.expire_all()
        models = (m.VehicleInspectionPlan, m.VehicleInspectionPlanEvent,
                  m.inspection_plans.Execution, m.inspection_plans.Evidence,
                  m.VehicleDocumentImportDraft, m.Vehicle)
        return [tuple(tuple(getattr(row, col.name) for col in model.__table__.columns)
                      for row in model.query.order_by(*model.__table__.primary_key.columns).all())
                for model in models]

    def pending(self):
        result = []
        for path, payload in (
            ('/api/vehicle/inspection-plans', {'changes': [self.change()]}),
            ('/api/vehicle/inspection-plans/execution', self.certificate_payload()),
        ):
            response = self.request('POST', path + '/preview', json=payload)
            self.assertEqual(response.status_code, 200)
            result.append((path, dict(payload, token=response.json['token'])))
        return result

    def assert_writes_denied(self, pending, status, company='TEST'):
        before = self.snapshot()
        for path, payload in pending:
            for suffix in ('/preview', '/save'):
                with self.subTest(path=path + suffix):
                    self.actor(company)
                    response = self.request('POST', path + suffix, json=payload)
                    self.assertEqual(response.status_code, status)
                    self.assertEqual(self.snapshot(), before)

    def reads(self, source=None):
        urls = ['/api/vehicle/inspection-plans?scope=company&year=2026',
                '/vehicle/inspection-plans/export.xlsx?scope=company&year=2026']
        if source:
            urls.append(source)
        return urls

    def evidence(self):
        document = self.certificate_document()
        self.certificate_save(self.certificate_payload(document_id=document.id))
        execution = self.m.inspection_plans.Execution.query.one()
        return document, execution, f'/vehicle/inspection-plans/executions/{execution.id}/source'

    def test_revoked_admin_stale_session_and_preview_tokens_cannot_write(self):
        pending = self.pending()
        self.user().role = 'user'
        self.m.db.session.commit()
        # Keep the old cookie claiming admin; the request must refresh from DB.
        with self.client.session_transaction() as session:
            self.assertEqual(session['role'], 'admin')
        self.assert_writes_denied(pending, 403)
        with self.client.session_transaction() as session:
            self.assertEqual(session['role'], 'user')

    def test_locked_user_cannot_submit_previously_previewed_changes(self):
        pending = self.pending()
        self.user().login_locked = True
        self.m.db.session.commit()
        self.assert_writes_denied(pending, 401)

    def test_deleted_user_cannot_reuse_foreign_same_username_for_preview_or_save(self):
        pending = self.pending()
        self.m.db.session.delete(self.user())
        self.m.db.session.commit()
        self.assert_writes_denied(pending, 401)

    def test_password_change_invalidates_pending_plan_and_execution_tokens(self):
        pending = self.pending()
        self.user().password_changed_at = '2099-01-01 00:00:00'
        self.m.db.session.commit()
        self.assert_writes_denied(pending, 401)

    def test_inactive_company_cannot_save_pending_plan_or_execution(self):
        pending = self.pending()
        self.m.Company.query.filter_by(company_code='TEST').one().active = False
        self.m.db.session.commit()
        # First request revokes the session; restore the stale cookie for each path.
        before = self.snapshot()
        for path, payload in pending:
            for suffix in ('/preview', '/save'):
                self.actor('TEST')
                response = self.request('POST', path + suffix, json=payload)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(self.snapshot(), before)

    def test_foreign_same_username_cannot_reuse_plan_or_execution_token(self):
        pending = self.pending()
        self.actor('OTHER')
        self.assert_writes_denied(pending, 404, company='OTHER')

    def test_general_user_can_read_export_and_evidence_without_foreign_data(self):
        document, _, source = self.evidence()
        self.actor('OTHER')
        payload = {'changes': [dict(self.change(vehicle=self.foreign), note='FOREIGN-NOTE-SECRET')]}
        preview = self.request('POST', '/api/vehicle/inspection-plans/preview', json=payload)
        self.assertEqual(preview.status_code, 200)
        response = self.request('POST', '/api/vehicle/inspection-plans/save',
                                json=dict(payload, token=preview.json['token']))
        self.assertEqual(response.status_code, 200)
        self.actor('TEST')
        self.user().role = 'user'
        self.m.db.session.commit()
        before = self.snapshot()
        api = self.request('GET', self.reads()[0] + '&company_code=OTHER')
        self.assertEqual(api.status_code, 200)
        self.assertFalse(api.json['can_edit'])
        self.assertNotIn('FOREIGN-', json.dumps(api.json))
        response = self.request('GET', self.reads()[1] + '&company_code=OTHER')
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertIn('attachment', response.headers['Content-Disposition'])
        with BytesIO(response.data) as data:
            workbook = load_workbook(data)
            try:
                cells = str([cell.value for sheet in workbook for row in sheet for cell in row])
                self.assertNotIn('FOREIGN-', cells)
                self.assertIn('TEST-001', cells)
            finally:
                workbook.close()
        response = self.request('GET', source)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, document.source_file)
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertEqual(self.snapshot(), before)

    def test_locked_user_cannot_read_api_excel_or_evidence(self):
        document, _, source = self.evidence()
        self.user().login_locked = True
        self.m.db.session.commit()
        for url in self.reads(source):
            self.actor('TEST')
            response = self.request('GET', url)
            self.assertEqual(response.status_code, 401 if url.startswith('/api/') else 302)
            self.assertNotIn(document.source_file, response.data)
            self.assertNotIn('Content-Disposition', response.headers)

    def test_inactive_company_cannot_read_api_excel_or_evidence(self):
        document, _, source = self.evidence()
        self.m.Company.query.filter_by(company_code='TEST').one().active = False
        self.m.db.session.commit()
        for url in self.reads(source):
            self.actor('TEST')
            response = self.request('GET', url)
            self.assertEqual(response.status_code, 403 if url.startswith('/api/') else 302)
            self.assertNotIn(document.source_file, response.data)
            self.assertNotIn('Content-Disposition', response.headers)

    def test_foreign_authenticated_same_username_cannot_download_execution_evidence(self):
        document, _, source = self.evidence()
        self.actor('OTHER')
        response = self.request('GET', source)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(document.source_file, response.data)
        self.assertNotIn('Content-Disposition', response.headers)

    def test_evidence_download_rechecks_document_vehicle_binding(self):
        document, _, source = self.evidence()
        document.result_json = json.dumps({'vehicle_record_id': self.second.id})
        self.m.db.session.commit()
        before = self.snapshot()
        response = self.request('GET', source)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(document.source_file, response.data)
        self.assertEqual(self.snapshot(), before)

    def test_evidence_download_rechecks_document_company_status_and_hash(self):
        document, _, source = self.evidence()
        for field, invalid in (('company_code', 'OTHER'), ('status', 'preview'),
                               ('source_sha256', '0' * 64)):
            with self.subTest(field=field):
                original = getattr(document, field)
                setattr(document, field, invalid)
                self.m.db.session.commit()
                before = self.snapshot()
                response = self.request('GET', source)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(document.source_file, response.data)
                self.assertEqual(self.snapshot(), before)
                setattr(document, field, original)
                self.m.db.session.commit()


if __name__ == '__main__':
    unittest.main()
