"""Real HTTP regressions for reused numeric IDs and durable reader evidence."""
import csv
import io
import unittest

import test_driving_report_readership as existing
from dkss_app import driving_access
from driving_report_data import payload
from driving_identity_resolution import resolver


class DrivingGenerationTests(unittest.TestCase):
    setUpClass = classmethod(existing.DrivingReadershipTests.setUpClass.__func__)
    tearDownClass = classmethod(existing.DrivingReadershipTests.tearDownClass.__func__)
    setUp = existing.DrivingReadershipTests.setUp
    tearDown = existing.DrivingReadershipTests.tearDown
    save = existing.DrivingReadershipTests.save
    grant = existing.DrivingReadershipTests.grant
    login = existing.DrivingReadershipTests.login

    def assigned(self):
        user = self.m.User(company_code='TEST', username='reused', role='user',
            password='unused', last_name='旧利用者', password_changed_at='stamp')
        self.m.db.session.add(user)
        self.m.db.session.commit()
        row = self.save(name='旧利用者')
        self.assertEqual(self.grant(row, user.username).status_code, 302)
        return row, user

    def replacement(self, original):
        old_id, identity = original.id, original.account_identity
        self.m.db.session.delete(original)
        self.m.db.session.commit()
        replacement = self.m.User(company_code='TEST', username='reused', role='user',
            password='unused', last_name='旧利用者', password_changed_at='stamp')
        self.m.db.session.add(replacement)
        self.m.db.session.commit()
        # SQLite's production-compatible INTEGER PK can reuse the highest rowid.
        self.assertEqual(replacement.id, old_id)
        self.assertNotEqual(replacement.account_identity, identity)
        self.login('reused')
        return replacement

    def test_reused_numeric_id_cannot_read_detail_list_or_csv(self):
        row, original = self.assigned()
        self.replacement(original)
        self.assertEqual(self.client.get(f'/safety/driving-reports/{row.id}').status_code, 404)
        response = self.client.get('/safety/driving-reports?period=all')
        self.assertEqual(response.status_code, 200)
        self.assertIn('0件中 0件', response.get_data(as_text=True))
        response = self.client.get('/safety/driving-reports/export.csv?period=all')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(list(csv.reader(io.StringIO(response.data.decode('utf-8-sig'))))), 1)

    def test_cascaded_grant_deletion_cannot_fall_back_to_same_name(self):
        row, original = self.assigned()
        # Simulate PostgreSQL's ON DELETE CASCADE without changing SQLite FK mode.
        self.m.db.session.delete(driving_access.reader(row))
        self.m.db.session.commit()
        self.replacement(original)
        self.assertEqual(self.client.get(f'/safety/driving-reports/{row.id}').status_code, 404)

    def test_legacy_grant_is_not_backfilled_from_current_username(self):
        row, original = self.assigned()
        driving_access.DrivingReaderAccount.query.delete()
        self.m.db.session.commit()
        self.login('reused')
        self.assertEqual(self.client.get(f'/safety/driving-reports/{row.id}').status_code, 404)
        self.assertEqual(driving_access.DrivingReaderAccount.query.count(), 0)
        self.assertEqual(driving_access.reader(row).user_id, original.id)

    def test_legacy_cascaded_grant_with_recorded_assignment_stays_held(self):
        row, original = self.assigned()
        driving_access.DrivingReaderAccount.query.delete()
        self.m.db.session.delete(driving_access.reader(row))
        self.m.db.session.commit()
        self.replacement(original)
        self.assertEqual(self.client.get(f'/safety/driving-reports/{row.id}').status_code, 404)

    def test_same_account_rename_and_lock_unlock_preserve_manual_history(self):
        row, original = self.assigned()
        identity = original.account_identity
        original.last_name = '改姓後'
        self.m.db.session.commit()
        self.login('reused')
        self.assertEqual(self.client.get(f'/safety/driving-reports/{row.id}').status_code, 200)
        original.login_locked = True
        self.m.db.session.commit()
        self.assertEqual(self.client.get(f'/safety/driving-reports/{row.id}').status_code, 302)
        original.login_locked = False
        self.m.db.session.commit()
        self.login('reused')
        self.assertEqual(self.client.get(f'/safety/driving-reports/{row.id}').status_code, 200)
        self.assertEqual(original.account_identity, identity)

    def test_explicit_reassignment_keeps_old_evidence_and_grants_only_new_account(self):
        row, original = self.assigned()
        old_identity = original.account_identity
        replacement = self.replacement(original)
        self.login('admin', 'admin')
        self.assertEqual(self.grant(row, 'reused').status_code, 302)
        self.login('reused')
        self.assertEqual(self.client.get(f'/safety/driving-reports/{row.id}').status_code, 200)
        evidence = driving_access.DrivingReaderAccount.query.order_by(driving_access.DrivingReaderAccount.id).all()
        self.assertEqual([item.account_identity for item in evidence], [old_identity, replacement.account_identity])
        self.assertTrue(all(item.actor_identity and item.actor_name for item in evidence))

    def test_account_evidence_does_not_authorize_other_company(self):
        row, original = self.assigned()
        with self.m.app.test_request_context():
            from flask import session
            session.update(company_code='OTHER', username=original.username, role='user')
            self.assertIsNone(resolver().resolve(row)[0])

    def test_explicit_import_selection_also_records_generation(self):
        row = self.save(name='自動照合用')
        user = self.m.User(company_code='TEST', username='automatic', role='user',
            password='unused', last_name='自動照合用', password_changed_at='stamp')
        self.m.db.session.add(user)
        self.m.db.session.commit()
        with self.m.app.test_request_context():
            from flask import session
            admin = self.m.User.query.filter_by(company_code='TEST', username='admin').one()
            session.update(company_code='TEST', username='admin', role='admin', account_identity=admin.account_identity)
            driving_access.resolve_import(row, user.username)
            self.m.db.session.commit()
        evidence = driving_access.DrivingReaderAccount.query.one()
        self.assertEqual(evidence.account_identity, user.account_identity)
        self.assertEqual(payload(row)['identity_resolution']['user_id'], user.id)

    def test_missing_evidence_table_fails_closed_and_initializer_is_idempotent(self):
        row, original = self.assigned()
        self.m.db.session.remove()
        with self.m.db.engine.begin() as connection:
            driving_access.DrivingReaderAccount.__table__.drop(connection)
        self.m.app.extensions['dkss']['driving_readers_ready'] = False
        self.login('reused')
        self.assertEqual(self.client.get(f'/safety/driving-reports/{row.id}').status_code, 404)
        for _ in range(2):
            driving_access.initialize_driving_access(self.m.app)
        self.assertEqual(driving_access.DrivingReaderAccount.query.count(), 0)
        self.assertEqual(self.client.get(f'/safety/driving-reports/{row.id}').status_code, 404)


if __name__ == '__main__':
    unittest.main()
