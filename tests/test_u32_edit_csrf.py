"""CSRF contract of the real maintenance correction route, temporary SQLite only."""
import unittest

import test_u32_part_sync as sync
from test_q02_auth_csrf import TokenParser


class MaintenanceEditCSRFTests(unittest.TestCase):
    setUpClass = classmethod(sync.PartSyncTests.setUpClass.__func__)
    tearDownClass = classmethod(sync.PartSyncTests.tearDownClass.__func__)
    tearDown = sync.PartSyncTests.tearDown
    invoice = sync.PartSyncTests.invoice
    imported = sync.PartSyncTests.imported
    edit_form = sync.PartSyncTests.edit_form

    def setUp(self):
        # Reuse only synthetic invoice arrangement, not its CSRF-disabled assertions.
        self.m.app.config['WTF_CSRF_ENABLED'] = False
        sync.PartSyncTests.setUp(self)
        row, part, _, _ = self.imported()
        self.row_id, self.part_id = row.id, part.id
        self.url = f'/vehicle/karte/{self.vehicle.id}/maintenance/{row.id}/edit'
        self.form = self.edit_form(row, mileage='12000', completion_date='2026-10-23')
        self.m.app.config['WTF_CSRF_ENABLED'] = True
        self.addCleanup(self.m.app.config.update, WTF_CSRF_ENABLED=False)

    def request(self, client, method, **kwargs):
        self.assertTrue(self.m.app.config['WTF_CSRF_ENABLED'])
        # Flask-WTF's g.csrf_valid/token cache must not leak across HTTP requests.
        self.m.db.session.remove()
        self.ctx.pop()
        try:
            response = client.open(self.url, method=method, **kwargs)
        finally:
            self.ctx = self.m.app.app_context()
            self.ctx.push()
        self.addCleanup(response.close)
        return response

    def token(self, client):
        response = self.request(client, 'GET')
        self.assertEqual(response.status_code, 200)
        parser = TokenParser()
        parser.feed(response.get_data(as_text=True))
        self.assertTrue(bool(parser.token), 'Rendered edit form must contain CSRF token')
        return parser.token

    def snapshot(self):
        self.m.db.session.expire_all()
        models = (self.m.VehicleMaintenanceRecord, self.m.VehiclePartReplacement,
                  self.m.VehiclePartReplacementSource, self.m.VehicleMaintenanceRecordEvent,
                  self.m.VehicleDocumentImportDraft)
        return tuple(tuple(tuple(getattr(row, col.name) for col in model.__table__.columns)
                           for row in model.query.order_by(model.id).all()) for model in models)

    def assert_rejected(self, form):
        before = self.snapshot()
        response = self.request(self.client, 'POST', data=form)
        self.assertEqual(response.status_code, 400)
        # Avoid rendering any persisted payload in failure logs.
        self.assertTrue(self.snapshot() == before, 'Rejected POST changed persisted state')

    def test_valid_edit_form_token_saves_parent_part_and_history(self):
        token = self.token(self.client)
        events_before = self.m.VehicleMaintenanceRecordEvent.query.count()
        response = self.request(self.client, 'POST', data=dict(self.form, csrf_token=token))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/maintenance', response.location)
        row = self.m.db.session.get(self.m.VehicleMaintenanceRecord, self.row_id)
        part = self.m.db.session.get(self.m.VehiclePartReplacement, self.part_id)
        self.assertEqual((row.mileage, row.completion_date), (12000, '2026-10-23'))
        self.assertEqual((part.mileage, part.replacement_date), (12000, '2026-10-23'))
        self.assertEqual(self.m.VehicleMaintenanceRecordEvent.query.count(), events_before + 1)

    def test_missing_token_rejects_without_persisted_changes(self):
        self.token(self.client)
        self.assert_rejected(self.form)

    def test_tampered_token_rejects_without_persisted_changes(self):
        token = self.token(self.client)
        self.assert_rejected(dict(self.form, csrf_token='invalid.' + token))

    def test_other_authenticated_session_token_rejects_without_persisted_changes(self):
        self.token(self.client)
        other = self.m.app.test_client()
        with self.client.session_transaction() as session:
            identity = {key: value for key, value in session.items()
                        if key in ('account_identity', 'company_code', 'username', 'role',
                                   'password_changed_at')}
        with other.session_transaction() as session:
            session.update(identity)
        foreign_token = self.token(other)
        self.assert_rejected(dict(self.form, csrf_token=foreign_token))


if __name__ == '__main__':
    unittest.main()
