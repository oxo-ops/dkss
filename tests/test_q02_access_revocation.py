"""QP-20261027 Q02: request-level revocation and attachment boundaries.

Synthetic data and temporary SQLite/files only. No production DB, network,
AI calls or shared application edits. MFA/login and PostgreSQL are out of scope.
"""
from identity_fixture import identity_for
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class Q02AccessRevocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='dkss-q02-')
        cls.files = Path(cls.temp.name) / 'static'
        env = {'SECRET_KEY': 'q02-isolated-test-key', 'RENDER': '',
               'DATABASE_URL': 'sqlite:///' + str(Path(cls.temp.name) / 'q02.db'),
               'OPENAI_API_KEY': '', 'SMTP_HOST': '', 'S3_BUCKET_NAME': '',
               'VAPID_PRIVATE_KEY': '', 'VAPID_PUBLIC_KEY': '',
               'AWS_EC2_METADATA_DISABLED': 'true'}
        from dkss_app import create_app
        from dkss_app.extensions import db, limiter
        from dkss_app import models
        cls.db, cls.models = db, models
        with patch.dict(os.environ, env):
            cls.app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False})
        cls.app.static_folder = str(cls.files)
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
        self.db.session.add_all([
            m.Company(company_code='A', company_name='A', active=True),
            m.Company(company_code='B', company_name='B', active=True),
            m.User(company_code='A', username='same', role='admin', password='unused', last_name='Test', first_name='User',
                   office='east', password_changed_at='2026-10-27 10:00:00'),
            m.User(company_code='B', username='same', role='admin', password='unused', last_name='Test', first_name='User',
                   office='west', password_changed_at='2026-10-27 10:00:00'),
            m.Manual(company_code='A', title='own', filename='own.pdf'),
            m.Manual(company_code='B', title='secret', filename='secret.pdf'),
        ])
        self.db.session.commit()
        for folder in ('manuals', 'uploads'):
            for company in ('A', 'B'):
                directory = self.files / folder / company
                directory.mkdir(parents=True, exist_ok=True)
                for filename in ('own.pdf', 'secret.pdf', 'evidence.pdf'):
                    (directory / filename).write_bytes((company + ':' + filename).encode())
        self.client = self.app.test_client()
        self.login()

    def tearDown(self):
        self.db.session.remove()
        self.ctx.pop()

    def get(self, url):
        response = self.client.get(url)
        self.addCleanup(response.close)
        return response

    def login(self):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(account_identity=identity_for('A', 'same', app=(self.client).application), company_code='A', username='same', role='admin', office='east',
                           password_changed_at='2026-10-27 10:00:00')

    def user(self):
        return self.models.User.query.filter_by(company_code='A', username='same').one()

    def assert_session_revoked(self):
        with self.client.session_transaction() as session:
            self.assertNotIn('username', session)

    def test_anonymous_api_returns_401(self):
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.get('/api/notifications/unread-count').status_code, 401)

    def test_anonymous_manual_cannot_read_bytes(self):
        with self.client.session_transaction() as session:
            session.clear()
        response = self.get('/static/manuals/A/own.pdf')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/login')
        self.assertNotIn(b'A:own.pdf', response.data)

    def test_same_company_manual_is_available_and_not_cached(self):
        response = self.get('/static/manuals/A/own.pdf')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'A:own.pdf')
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_other_company_manual_is_denied_despite_same_username(self):
        self.assertEqual(self.get('/static/manuals/B/secret.pdf').status_code, 404)

    def test_changed_company_segment_never_serves_other_company_bytes(self):
        response = self.get('/static/manuals/B/own.pdf')
        # Storage resolves the path from the authenticated company, ignoring
        # the supplied directory. It may serve A or reject, but must not serve B.
        self.assertIn(response.status_code, (200, 404))
        self.assertNotIn(b'B:own.pdf', response.data)
        if response.status_code == 200:
            self.assertEqual(response.data, b'A:own.pdf')

    def test_files_endpoint_denies_other_company_reference(self):
        self.assertEqual(self.get('/files/manuals/secret.pdf').status_code, 404)

    def test_locked_user_loses_existing_manual_session(self):
        self.user().login_locked = True
        self.db.session.commit()
        self.assertEqual(self.get('/static/manuals/A/own.pdf').location, '/login')
        self.assert_session_revoked()

    def test_deleted_user_cannot_reuse_same_username_from_other_company(self):
        self.db.session.delete(self.user())
        self.db.session.commit()
        self.assertEqual(self.get('/api/notifications/unread-count').status_code, 401)
        self.assert_session_revoked()

    def test_password_change_revokes_existing_session(self):
        self.user().password_changed_at = '2026-10-27 11:00:00'
        self.db.session.commit()
        self.assertEqual(self.get('/api/notifications/unread-count').status_code, 401)
        self.assert_session_revoked()

    def test_inactive_company_revokes_manual_session(self):
        self.models.Company.query.filter_by(company_code='A').one().active = False
        self.db.session.commit()
        self.assertEqual(self.get('/static/manuals/A/own.pdf').location, '/login')
        self.assert_session_revoked()

    def test_inactive_company_api_returns_403(self):
        self.models.Company.query.filter_by(company_code='A').one().active = False
        self.db.session.commit()
        self.assertEqual(self.get('/api/notifications/unread-count').status_code, 403)
        self.assert_session_revoked()

    def test_revoked_admin_cannot_use_stale_cookie_for_master(self):
        self.user().role = 'user'
        self.db.session.commit()
        response = self.get('/master')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/')
        with self.client.session_transaction() as session:
            self.assertEqual(session['role'], 'user')

    def news(self, target_type, target_value='', company='A'):
        self.db.session.add(self.models.News(company_code=company, title='test',
            target_type=target_type, target_value=target_value,
            files_json=json.dumps(['evidence.pdf'])))
        self.db.session.commit()

    def test_current_admin_can_read_admin_news_attachment(self):
        self.news('admins')
        response = self.get('/static/uploads/A/evidence.pdf')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'A:evidence.pdf')

    def test_revoked_admin_cannot_read_admin_news_attachment(self):
        self.news('admins')
        self.user().role = 'user'
        self.db.session.commit()
        self.assertEqual(self.get('/static/uploads/A/evidence.pdf').status_code, 404)

    def test_moved_office_cannot_read_previous_office_attachment(self):
        self.news('office', 'east')
        self.user().office = 'west'
        self.db.session.commit()
        self.assertEqual(self.get('/static/uploads/A/evidence.pdf').status_code, 404)

    def test_matching_office_can_read_attachment(self):
        self.news('office', 'east')
        self.assertEqual(self.get('/static/uploads/A/evidence.pdf').status_code, 200)

    def test_other_recipient_attachment_is_denied(self):
        self.news('user', 'someone-else')
        self.assertEqual(self.get('/static/uploads/A/evidence.pdf').status_code, 404)

    def test_own_recipient_attachment_is_available(self):
        self.news('user', 'same')
        self.assertEqual(self.get('/static/uploads/A/evidence.pdf').status_code, 200)

    def test_other_company_news_attachment_is_denied(self):
        self.news('all', company='B')
        self.assertEqual(self.get('/static/uploads/B/evidence.pdf').status_code, 404)

    def test_company_news_attachment_is_available(self):
        self.news('company')
        self.assertEqual(self.get('/static/uploads/A/evidence.pdf').status_code, 200)


if __name__ == '__main__':
    unittest.main()
