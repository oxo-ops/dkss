"""Q02 boundaries of #251 invoice projections, with populated companies.

Real import -> plan API -> every original link; disposable SQLite and synthetic
PDFs only. No browser, external services, PostgreSQL or production verification.
"""
import hashlib
import json
import unittest

import test_q05_document_dates as fixtures
from test_inspection_document_ai import pdf_bytes


class Q02InvoicePlanBoundaryTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.DocumentCompletionDateTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.DocumentCompletionDateTests.tearDownClass.__func__)
    tearDown = fixtures.DocumentCompletionDateTests.tearDown
    form = fixtures.DocumentCompletionDateTests.form

    def setUp(self):
        fixtures.DocumentCompletionDateTests.setUp(self)
        m = self.m
        self.stamp = self.user().password_changed_at
        m.db.session.add(m.Company(company_code='OTHER', company_name='Other', active=True))
        m.db.session.add(m.User(company_code='OTHER', username='admin', role='admin',
            password='unused', last_name='Synthetic', password_changed_at=self.stamp))
        self.foreign_vehicle = m.Vehicle(company_code='OTHER', chassis_number='FOREIGN-SECRET')
        m.db.session.add(self.foreign_vehicle)
        m.db.session.commit()
        self.own_record, self.own_draft = self.import_invoice('TEST', self.vehicle, 'own', 595)
        self.foreign_record, self.foreign_draft = self.import_invoice(
            'OTHER', self.foreign_vehicle, 'FOREIGN-SECRET', 612)
        self.actor()

    def user(self):
        return self.m.User.query.filter_by(company_code='TEST', username='admin').one()

    def actor(self, company='TEST'):
        # Restore the original authenticated cookie's claims before EACH request.
        # A denial on an earlier URL must not make later checks merely anonymous.
        with self.client.session_transaction() as session:
            session.clear()
            session.update(company_code=company, username='admin', role='admin',
                           password_changed_at=self.stamp)

    def request(self, path, **kwargs):
        response = self.client.get(path, **kwargs)
        self.addCleanup(response.close)
        return response

    def import_invoice(self, company, vehicle, ident, width):
        self.actor(company)
        source = pdf_bytes(width)
        row = {'record_date': '2026-10-28', 'completion_date': '2026-10-28',
               'content': ident + '-work', 'source_pages': [1], 'line_items': [], 'fees': []}
        draft = self.m.VehicleDocumentImportDraft(
            id=ident, batch_id=ident + '-batch', company_code=company,
            created_by_username='admin', document_type='maintenance',
            source_filename=ident + '.pdf', source_file=source,
            source_sha256=hashlib.sha256(source).hexdigest(),
            preview_json=json.dumps({'records': [row]}), status='preview')
        self.m.db.session.add(draft)
        self.m.db.session.commit()
        original_vehicle = self.vehicle
        self.vehicle = vehicle
        try:
            data = self.form(ident=ident, start='2026-10-28', end='2026-10-28')
        finally:
            self.vehicle = original_vehicle
        data.update({'content_' + ident + '_0': ident + '-work',
                     'maintenance_category_' + ident + '_0': '整備',
                     'total_cost_' + ident + '_0': '3300'})
        response = self.client.post('/vehicle/data-import/' + draft.batch_id + '/confirm', data=data)
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))
        self.m.db.session.refresh(draft)
        self.assertEqual(draft.status, 'completed')
        record = self.m.VehicleMaintenanceRecord.query.filter_by(company_code=company).one()
        return record, draft

    def snapshot(self):
        m = self.m
        m.db.session.expire_all()
        models = (m.VehicleMaintenanceRecord, m.VehicleMaintenanceRecordEvent,
                  m.VehicleMaintenanceDocument, m.VehicleDocumentImportDraft,
                  m.VehicleInspectionPlan, m.VehicleInspectionPlanEvent,
                  m.inspection_plans.Execution, m.inspection_plans.Evidence,
                  m.VehiclePartReplacement, m.Vehicle)
        return [tuple(tuple(getattr(row, col.name) for col in model.__table__.columns)
                      for row in model.query.order_by(*model.__table__.primary_key.columns).all())
                for model in models]

    def projection(self, **args):
        response = self.request('/api/vehicle/inspection-plans', query_string={
            'scope': 'company', 'year': 2026, 'month': '2026-10', **args})
        self.assertEqual(response.status_code, 200)
        return response.json

    def originals(self, projection, expected_draft):
        rows = projection['invoice_actuals']
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['sources'])
        self.assertEqual(rows[0]['source_url'], rows[0]['sources'][0]['url'])
        for source in rows[0]['sources']:
            response = self.request(source['url'])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, expected_draft.source_file)
            self.assertIn('no-store', response.headers['Cache-Control'])
        return [source['url'] for source in rows[0]['sources']]

    def test_demoted_admin_retains_own_invoice_and_all_originals_without_foreign_data(self):
        # Include a later confirmed attachment, exercising the new sources list.
        m = self.m
        second = m.VehicleDocumentImportDraft(
            id='own-second', batch_id='own-second-batch', company_code='TEST',
            created_by_username='admin', document_type='maintenance',
            source_filename='own-second.pdf', source_file=self.own_draft.source_file,
            source_sha256=self.own_draft.source_sha256,
            result_json=self.own_draft.result_json, status='completed')
        m.db.session.add(second)
        m.db.session.flush()
        m.db.session.add(m.VehicleMaintenanceDocument(
            company_code='TEST', vehicle_record_id=self.vehicle.id,
            maintenance_record_id=self.own_record.id, source_draft_id=second.id,
            source_record_index=0, created_by_username='admin',
            financial_status='confirmed', parts_status='not_applicable'))
        self.user().role = 'user'
        m.db.session.commit()
        before = self.snapshot()
        self.actor()  # Stale cookie still claims admin.
        projection = self.projection(company_code='OTHER')
        self.assertFalse(projection['can_edit'])
        self.assertNotIn('FOREIGN-SECRET', json.dumps(projection))
        self.assertEqual(projection['invoice_actuals'][0]['maintenance_record_id'], self.own_record.id)
        self.assertEqual(len(self.originals(projection, self.own_draft)), 2)
        with self.client.session_transaction() as session:
            self.assertEqual(session['role'], 'user')
        self.assertEqual(self.snapshot(), before)

    def test_foreign_same_username_reads_only_own_invoice_and_cannot_retarget_original(self):
        own_projection = self.projection()
        own_url = self.originals(own_projection, self.own_draft)[0]
        self.actor('OTHER')
        before = self.snapshot()
        projection = self.projection(company_code='TEST')
        self.assertEqual(projection['invoice_actuals'][0]['maintenance_record_id'], self.foreign_record.id)
        self.assertNotIn('own-work', json.dumps(projection))
        self.originals(projection, self.foreign_draft)
        paths = [own_url,
                 f'/vehicle/karte/{self.foreign_vehicle.id}/documents/{self.own_draft.id}/source',
                 f'/vehicle/karte/{self.vehicle.id}/documents/{self.foreign_draft.id}/source',
                 '/api/vehicle/inspection-plans?scope=vehicle&year=2026&vehicle_id=' + str(self.vehicle.id)]
        for path in paths:
            with self.subTest(path=path):
                response = self.request(path)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(self.own_draft.source_file, response.data)
                self.assertNotIn('Content-Disposition', response.headers)
                self.assertEqual(self.snapshot(), before)

    def check_revocation(self, kind, api_status):
        projection = self.projection()
        urls = self.originals(projection, self.own_draft)
        user = self.user()
        if kind == 'locked':
            user.login_locked = True
        elif kind == 'deleted':
            self.m.db.session.delete(user)
        elif kind == 'password':
            user.password_changed_at = '2099-01-01 00:00:00'
        else:
            self.m.Company.query.filter_by(company_code='TEST').one().active = False
        self.m.db.session.commit()
        before = self.snapshot()
        for path in ['/api/vehicle/inspection-plans?scope=company&year=2026'] + urls:
            with self.subTest(path=path):
                self.actor()
                response = self.request(path)
                self.assertEqual(response.status_code, api_status if path.startswith('/api/') else 302)
                self.assertNotIn(self.own_draft.source_file, response.data)
                self.assertNotIn('own-work', response.get_data(as_text=True))
                self.assertNotIn('Content-Disposition', response.headers)
                with self.client.session_transaction() as session:
                    self.assertNotIn('username', session)
                self.assertEqual(self.snapshot(), before)

    def test_lock_after_invoice_view_revokes_projection_and_original(self):
        self.check_revocation('locked', 401)

    def test_deletion_after_invoice_view_does_not_use_foreign_same_username(self):
        self.check_revocation('deleted', 401)

    def test_password_change_after_invoice_view_revokes_projection_and_original(self):
        self.check_revocation('password', 401)

    def test_company_stop_after_invoice_view_revokes_projection_and_original(self):
        self.check_revocation('company', 403)


if __name__ == '__main__':
    unittest.main()
