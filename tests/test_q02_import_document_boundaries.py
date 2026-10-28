"""Document state and company/creator access, using real routes and isolated DB."""
import hashlib
import re
import unittest
import test_workflow_regressions as workflow
from test_inspection_document_ai import extraction, pdf_bytes


class Q02ImportDocumentBoundaryTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    upload_inspection = workflow.WorkflowRegressionTests.upload_inspection
    inspection_form = workflow.WorkflowRegressionTests.inspection_form
    tearDown = workflow.WorkflowRegressionTests.tearDown

    def setUp(self):
        workflow.WorkflowRegressionTests.setUp(self)
        stamp = self.m.User.query.filter_by(company_code='TEST', username='admin').one().password_changed_at
        self.m.db.session.add(self.m.Company(company_code='OTHER', company_name='Other', active=True))
        for company, name, role in [('TEST','other-admin','admin'), ('TEST','reader','user'), ('OTHER','admin','admin')]:
            self.m.db.session.add(self.m.User(company_code=company, username=name, role=role,
                password='unused', last_name='Synthetic', password_changed_at=stamp))
        self.m.db.session.commit()
        self.stamp = stamp

    def request(self, method, path, **kwargs):
        response = self.client.open(path, method=method, **kwargs)
        self.addCleanup(response.close)
        return response

    def actor(self, company='TEST', name='admin', role='admin'):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(company_code=company, username=name, role=role, password_changed_at=self.stamp)

    def preview(self, width=595):
        source = pdf_bytes(width)
        data = extraction(source)
        data['records'][0].update(inspection_type='other', next_inspection_date=None, next_inspection_month=None)
        response = self.upload_inspection(data=data, source=source)
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 302)
        return self.m.VehicleDocumentImportDraft.query.order_by(self.m.VehicleDocumentImportDraft.created_at.desc()).filter_by(
            source_sha256=hashlib.sha256(source).hexdigest()).one(), source

    def completed(self):
        row, source = self.preview()
        form = self.inspection_form(row)
        form['inspection_type_' + row.id + '_0'] = 'other'
        response = self.request('POST', '/vehicle/data-import/' + row.batch_id + '/confirm', data=form)
        self.assertEqual(response.status_code, 302)
        self.m.db.session.expire_all()
        self.assertEqual(row.status, 'completed')
        return row, source

    def snapshot(self):
        self.m.db.session.expire_all()
        m = self.m
        return ([(r.id, r.company_code, r.created_by_username, r.document_type, r.status,
                  hashlib.sha256(r.source_file).hexdigest(), r.preview_json, r.result_json)
                 for r in m.VehicleDocumentImportDraft.query.order_by(m.VehicleDocumentImportDraft.id).all()],
                m.VehiclePeriodicInspectionRecord.query.count(), m.VehicleMaintenanceRecord.query.count(),
                m.AuditLog.query.count())

    def token(self, row):
        page = self.request('GET', '/vehicle/data-import/' + row.id + '/kind')
        self.assertEqual(page.status_code, 200)
        match = re.search(r'name="kind_token" value="([^"]+)"', page.get_data(as_text=True))
        self.assertIsNotNone(match)
        return match.group(1)

    def assert_preview_denied_without_writes(self, row, token):
        before = self.snapshot()
        urls = [('GET','/vehicle/data-import/files/' + row.id, {}),
            ('GET','/vehicle/data-import/' + row.batch_id + '/preview', {}),
            ('POST','/vehicle/data-import/' + row.batch_id + '/confirm', self.inspection_form(row)),
            ('GET','/vehicle/data-import/' + row.id + '/kind', {}),
            ('POST','/vehicle/data-import/' + row.id + '/kind', {'kind_token': token, 'document_type': 'maintenance'}),
            ('POST','/vehicle/data-import/' + row.id + '/kind', {'action': 'cancel'})]
        for method, path, data in urls:
            with self.subTest(method=method, path=path):
                response = self.request(method, path, data=data)
                self.assertIn(response.status_code, (302, 403, 404))
                self.assertNotEqual(response.headers.get('Content-Type'), 'application/pdf')
                self.assertEqual(self.snapshot(), before)

    def test_owner_can_read_preview_and_source_and_confirm(self):
        row, source = self.preview()
        response = self.request('GET', '/vehicle/data-import/files/' + row.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, source)
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertEqual(self.request('GET', '/vehicle/data-import/' + row.batch_id + '/preview').status_code, 200)
        self.token(row)
        self.assertEqual(self.request('POST', '/vehicle/data-import/' + row.batch_id + '/confirm',
                                     data=self.inspection_form(row)).status_code, 302)
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(), 1)

    def test_same_company_other_admin_cannot_use_unregistered_source_or_owner_token(self):
        row, _ = self.preview()
        token = self.token(row)
        self.actor(name='other-admin')
        self.assert_preview_denied_without_writes(row, token)

    def test_other_company_same_username_cannot_use_unregistered_source_or_owner_token(self):
        row, _ = self.preview()
        token = self.token(row)
        self.actor(company='OTHER')
        self.assert_preview_denied_without_writes(row, token)

    def test_role_revoked_after_preview_cannot_submit_or_cancel(self):
        row, _ = self.preview()
        token = self.token(row)
        self.m.User.query.filter_by(company_code='TEST', username='admin').one().role = 'user'
        self.m.db.session.commit()
        self.assert_preview_denied_without_writes(row, token)

    def test_account_locked_after_preview_cannot_submit_or_cancel(self):
        row, _ = self.preview()
        token = self.token(row)
        self.m.User.query.filter_by(company_code='TEST', username='admin').one().login_locked = True
        self.m.db.session.commit()
        self.assert_preview_denied_without_writes(row, token)

    def test_registered_source_is_shared_with_same_company_admin_and_correction_keeps_original(self):
        row, source = self.completed()
        original = (row.id, row.source_file, row.preview_json, row.result_json)
        self.actor(name='other-admin')
        url = f'/vehicle/karte/{self.vehicle.id}/documents/{row.id}/source'
        response = self.request('GET', url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, source)
        token = self.token(row)
        response = self.request('POST', '/vehicle/data-import/' + row.id + '/kind', data={
            'document_type': 'maintenance', 'kind_token': token})
        self.assertEqual(response.status_code, 303)
        self.m.db.session.expire_all()
        self.assertEqual((row.id, row.source_file, row.preview_json, row.result_json), original)
        replacement = self.m.VehicleDocumentImportDraft.query.filter(self.m.VehicleDocumentImportDraft.id != row.id).one()
        self.assertEqual((replacement.company_code, replacement.created_by_username, replacement.status),
                         ('TEST', 'other-admin', 'queued'))
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(), 1)

    def test_general_user_can_read_registered_source_but_cannot_correct_kind(self):
        row, source = self.completed()
        token = self.token(row)
        self.actor(name='reader', role='user')
        before = self.snapshot()
        response = self.request('GET', f'/vehicle/karte/{self.vehicle.id}/documents/{row.id}/source')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, source)
        self.assertEqual(self.request('POST', '/vehicle/data-import/' + row.id + '/kind', data={
            'document_type': 'maintenance', 'kind_token': token}).status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def test_foreign_same_username_cannot_read_or_correct_registered_source(self):
        row, _ = self.completed()
        token = self.token(row)
        self.actor(company='OTHER')
        before = self.snapshot()
        for method, path, data in [
            ('GET', f'/vehicle/karte/{self.vehicle.id}/documents/{row.id}/source', {}),
            ('GET', '/vehicle/data-import/files/' + row.id, {}),
            ('GET', '/vehicle/data-import/' + row.id + '/kind', {}),
            ('POST', '/vehicle/data-import/' + row.id + '/kind', {'document_type':'maintenance','kind_token':token})]:
            with self.subTest(method=method, path=path):
                self.assertEqual(self.request(method, path, data=data).status_code, 404)
                self.assertEqual(self.snapshot(), before)

    def test_registered_source_rejects_unrelated_same_company_vehicle(self):
        row, _ = self.completed()
        other = self.m.Vehicle(company_code='TEST', chassis_number='UNRELATED-SYNTHETIC')
        self.m.db.session.add(other)
        self.m.db.session.commit()
        before = self.snapshot()
        self.assertEqual(self.request('GET', f'/vehicle/karte/{other.id}/documents/{row.id}/source').status_code, 404)
        self.assertEqual(self.snapshot(), before)

    def test_confirm_and_kind_cancel_require_csrf_and_preserve_the_source(self):
        row, _ = self.preview()
        before = self.snapshot()
        self.m.app.config['WTF_CSRF_ENABLED'] = True
        try:
            self.assertEqual(self.request('POST', '/vehicle/data-import/' + row.batch_id + '/confirm',
                data=self.inspection_form(row)).status_code, 400)
            self.assertEqual(self.request('POST', '/vehicle/data-import/' + row.id + '/kind',
                data={'action':'cancel'}).status_code, 400)
        finally:
            self.m.app.config['WTF_CSRF_ENABLED'] = False
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
