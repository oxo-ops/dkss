"""Real login and MFA forms with CSRF enabled; email delivery alone is mocked."""
import os
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from werkzeug.security import generate_password_hash


class TokenParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.token = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input' and attrs.get('name') == 'csrf_token':
            self.token = attrs.get('value')


class Q02AuthCSRFTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from dkss_app import create_app, models, auth
        from dkss_app.extensions import db, limiter
        cls.temp = tempfile.TemporaryDirectory(prefix='q02-auth-csrf-')
        cls.db, cls.models, cls.auth = db, models, auth
        cls.password = 'Q02-CSRF-Only-742!'
        cls.password_hash = generate_password_hash(cls.password)
        with patch.dict(os.environ, {'SECRET_KEY': 'q02-csrf-test-only', 'RENDER': '',
            'DATABASE_URL': 'sqlite:///' + str(Path(cls.temp.name) / 'test.db'),
            'OPENAI_API_KEY': '', 'SMTP_HOST': '', 'S3_BUCKET_NAME': '',
            'VAPID_PRIVATE_KEY': '', 'VAPID_PUBLIC_KEY': '', 'RATELIMIT_STORAGE_URI': 'memory://'}):
            cls.app = create_app({'TESTING': True, 'MFA_ENABLED': True, 'WTF_CSRF_ENABLED': True})
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
        self.db.session.add(self.models.Company(company_code='A', company_name='Synthetic', active=True))
        self.db.session.add(self.models.User(company_code='A', username='same',
            password=self.password_hash, last_name='Synthetic', first_name='User', role='user',
            password_changed_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            email_address='q02@example.invalid'))
        self.db.session.commit()
        self.client = self.app.test_client()
        self.codes = []
        def deliver(user, code):
            self.codes.append(code)
            return True
        mocked = patch.object(self.auth, 'send_mfa_code_email', side_effect=deliver)
        mocked.start()
        self.addCleanup(mocked.stop)

    def tearDown(self):
        self.db.session.remove()
        self.ctx.pop()

    def request(self, client, method, path, **kwargs):
        # Each HTTP request must own its app context, including Flask-WTF's g cache.
        self.db.session.remove()
        self.ctx.pop()
        try:
            response = client.open(path, method=method, **kwargs)
        finally:
            self.ctx = self.app.app_context()
            self.ctx.push()
        self.addCleanup(response.close)
        return response

    def token(self, client, path):
        response = self.request(client, 'GET', path)
        self.assertEqual(response.status_code, 200)
        parser = TokenParser()
        parser.feed(response.get_data(as_text=True))
        self.assertTrue(parser.token, 'The actual rendered form must contain its CSRF token')
        return parser.token

    def login(self):
        token = self.token(self.client, '/login')
        response = self.request(self.client, 'POST', '/login', data={
            'company_code': 'A', 'username': 'same', 'password': self.password, 'csrf_token': token})
        self.assertEqual((response.status_code, response.location), (302, '/mfa'))
        return self.codes[-1]

    def snapshot(self):
        self.db.session.expire_all()
        user = self.models.User.query.filter_by(company_code='A', username='same').one()
        return (user.mfa_code_hash, user.mfa_code_expires_at, user.failed_login_count,
                self.models.AuditLog.query.count())

    def assert_rejected(self, response, before):
        self.assertEqual((response.status_code, response.location), (302, '/login'))
        self.assertEqual(self.snapshot(), before)
        with self.client.session_transaction() as session:
            self.assertNotIn('username', session)

    def test_real_login_and_mfa_forms_authenticate_with_valid_csrf(self):
        code = self.login()
        token = self.token(self.client, '/mfa')
        response = self.request(self.client, 'POST', '/mfa', data={'code': code, 'csrf_token': token})
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertEqual((session.get('company_code'), session.get('username')), ('A', 'same'))
        self.assertEqual(self.request(self.client, 'GET', '/api/notifications/unread-count').status_code, 200)

    def test_login_without_csrf_cannot_send_code_or_change_database(self):
        self.token(self.client, '/login')
        before = self.snapshot()
        response = self.request(self.client, 'POST', '/login', data={
            'company_code': 'A', 'username': 'same', 'password': self.password})
        self.assert_rejected(response, before)
        self.assertEqual(self.codes, [])

    def test_login_rejects_csrf_from_another_browser_session(self):
        self.token(self.client, '/login')
        foreign_token = self.token(self.app.test_client(), '/login')
        before = self.snapshot()
        response = self.request(self.client, 'POST', '/login', data={
            'company_code': 'A', 'username': 'same', 'password': self.password, 'csrf_token': foreign_token})
        self.assert_rejected(response, before)
        self.assertEqual(self.codes, [])

    def test_mfa_without_csrf_cannot_consume_a_valid_code(self):
        code = self.login()
        before = self.snapshot()
        response = self.request(self.client, 'POST', '/mfa', data={'code': code})
        self.assert_rejected(response, before)
        token = self.token(self.client, '/mfa')
        self.assertEqual(self.request(self.client, 'POST', '/mfa', data={
            'code': code, 'csrf_token': token}).status_code, 302)
        with self.client.session_transaction() as session:
            self.assertEqual(session.get('username'), 'same')

    def test_mfa_rejects_foreign_csrf_without_recording_a_failed_attempt(self):
        self.login()
        foreign_token = self.token(self.app.test_client(), '/login')
        before = self.snapshot()
        response = self.request(self.client, 'POST', '/mfa', data={
            'code': 'not-a-valid-code', 'csrf_token': foreign_token})
        self.assert_rejected(response, before)
        self.assertEqual(self.models.AuditLog.query.filter_by(action='mfa_failed').count(), 0)

    def test_csrf_token_endpoint_does_not_authenticate_and_is_not_cached(self):
        response = self.request(self.client, 'GET', '/login/csrf-token')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['csrf_token'])
        self.assertIn('no-store', response.headers.get('Cache-Control', ''))
        with self.client.session_transaction() as session:
            self.assertNotIn('username', session)
        self.assertEqual(self.request(self.client, 'GET', '/api/notifications/unread-count').status_code, 401)


if __name__ == '__main__':
    unittest.main(verbosity=2)
