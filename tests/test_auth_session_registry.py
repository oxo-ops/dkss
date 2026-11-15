"""Normal-auth durable revocation on synthetic databases; no live activation."""
import unittest
from unittest.mock import patch
import test_session_authority_candidate as fixtures


class RegistryIntegration(unittest.TestCase):
    login = fixtures.SessionAuthorityIntegration.login

    def setUp(self):
        from dkss_app import create_app
        from sqlalchemy import inspect
        def normal_app(config):
            return create_app(dict(config, SESSION_AUTHORITY_CANDIDATE=False))
        with patch('dkss_app.create_app', side_effect=normal_app):
            fixtures.SessionAuthorityIntegration.setUp(self)
        self.assertFalse(self.app.config['SESSION_AUTHORITY_CANDIDATE'])
        self.assertNotIn('auth_session', self.db.metadata.tables)
        self.assertNotIn('auth_session_policy', self.db.metadata.tables)
        self.assertFalse(inspect(self.db.engine).has_table('auth_session'))
        self.assertFalse(inspect(self.db.engine).has_table('auth_session_policy'))
        from dkss_app.auth_session_registry import prepare_schema, activate
        prepare_schema(); activate()

    def copy_client(self):
        name = self.app.config['SESSION_COOKIE_NAME']
        copied = self.app.test_client()
        copied.set_cookie(name, self.client.get_cookie(name).value)
        return copied

    def test_logout_revokes_copied_cookie(self):
        self.login(); copied = self.copy_client()
        with self.app.app_context():
            self.assertEqual(self.client.post('/logout').location, '/login')
        with self.app.app_context():
            response = copied.get('/api/notifications/unread-count')
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Set-Cookie', response.headers)

    def test_other_device_remains_logged_in(self):
        self.login(); first = self.client
        self.client = self.app.test_client(); self.login()
        with self.app.app_context(): first.post('/logout')
        with self.app.app_context(): response = self.client.get('/api/notifications/unread-count')
        self.assertEqual(response.status_code, 200)

    def test_account_and_company_are_bound(self):
        self.login()
        with self.client.session_transaction() as state:
            state['company_code'] = 'OTHER'
        with self.app.app_context(): response = self.client.get('/api/notifications/unread-count')
        self.assertEqual(response.status_code, 401)

    def test_mfa_issues_only_after_completion(self):
        from dkss_app.auth_session_registry import AuthSession
        self.app.config['MFA_ENABLED'] = True
        codes = []
        with patch.object(self.auth, 'send_mfa_code_email', side_effect=lambda user,code: codes.append(code) or True):
            self.assertEqual(self.login().location, '/mfa')
        self.assertEqual(self.db.session.query(AuthSession).count(), 0)
        with self.app.app_context(): response = self.client.post('/mfa', data={'code': codes[0]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.db.session.query(AuthSession).count(), 1)

    def test_preparation_does_not_revert_activation(self):
        from dkss_app.auth_session_registry import prepare_schema, AuthSessionPolicy
        prepare_schema()
        self.assertEqual(self.db.session.get(AuthSessionPolicy, 1).version, 1)
        self.login()
        with self.client.session_transaction() as state:
            state.pop('auth_session_token')
        self.app.config['AUTH_SESSION_REVOCATION_ENABLED'] = False  # no bypass flag exists
        with self.app.app_context(): response = self.client.get('/api/notifications/unread-count')
        self.assertEqual(response.status_code, 401)

    def test_missing_registry_fails_closed_without_cookie_write(self):
        from dkss_app.auth_session_registry import AuthSession
        self.login(); AuthSession.__table__.drop(self.db.engine)
        with self.app.app_context(): response = self.client.get('/api/notifications/unread-count')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('Set-Cookie', response.headers)

    def test_failed_issue_never_saves_authenticated_cookie(self):
        from dkss_app.auth_session_registry import AuthSession
        AuthSession.__table__.drop(self.db.engine)
        with self.app.app_context(): response = self.client.post('/login', data={
            'company_code':'SYNTH', 'username':'operator', 'password':self.password})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('Set-Cookie', response.headers)

    def test_revoked_cookie_can_explicitly_reset_then_login(self):
        self.login(); copied = self.copy_client()
        with self.app.app_context(): self.client.post('/logout')
        with self.app.app_context(): self.assertEqual(copied.get('/login').location, '/login')
        with copied.session_transaction() as state: self.assertNotIn('username', state)
        self.client = copied
        with self.app.app_context(): self.login()
        with self.app.app_context(): self.assertEqual(self.client.get('/api/notifications/unread-count').status_code, 200)

    def test_no_implicit_schema_preparation_or_activation(self):
        from dkss_app.auth_session_registry import RegistryBase, prepare_schema, AuthSessionPolicy
        from sqlalchemy import inspect
        RegistryBase.metadata.drop_all(self.db.engine)
        self.login()
        self.assertFalse(inspect(self.db.engine).has_table('auth_session'))
        with self.client.session_transaction() as state: self.assertNotIn('auth_session_token', state)
        prepare_schema()
        self.assertEqual(self.db.session.get(AuthSessionPolicy, 1).version, 0)
        with self.app.app_context(): self.assertEqual(self.client.get('/api/notifications/unread-count').status_code, 200)

    def test_logout_update_failure_is_not_success(self):
        from sqlalchemy.exc import OperationalError
        self.login()
        original = self.db.session.execute
        def fail_revoke(statement, *args, **kwargs):
            if getattr(statement, 'is_update', False):
                raise OperationalError('synthetic', {}, Exception('synthetic'))
            return original(statement, *args, **kwargs)
        with patch.object(self.db.session, 'execute', side_effect=fail_revoke):
            with self.app.app_context(): response = self.client.post('/logout')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('Set-Cookie', response.headers)

    def test_activation_requires_explicit_acknowledgement(self):
        result = self.app.test_cli_runner().invoke(args=['activate-auth-session-registry'])
        self.assertNotEqual(result.exit_code, 0)

    def test_password_generation_checks_remain_enforced(self):
        self.login()
        user = self.db.session.query(self.models.User).filter_by(username='operator').one()
        user.password_changed_at = '2099-01-01 00:00:00'; self.db.session.commit()
        with self.app.app_context(): response = self.client.get('/api/notifications/unread-count')
        self.assertEqual(response.status_code, 401)

    def test_prepare_does_not_reset_corrupt_existing_policy(self):
        from dkss_app.auth_session_registry import prepare_schema, AuthSessionPolicy
        self.db.session.execute(self.db.delete(AuthSessionPolicy)); self.db.session.commit()
        with self.assertRaises(RuntimeError): prepare_schema()
        self.assertEqual(self.db.session.query(AuthSessionPolicy).count(), 0)

    def test_postgres_two_replacements_have_one_successor(self):
        if self.db.engine.dialect.name != 'postgresql':
            self.skipTest('real isolated PostgreSQL concurrency required')
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from dkss_app import auth_session_registry as registry
        self.login()
        name = self.app.config['SESSION_COOKIE_NAME']
        old_cookie = self.client.get_cookie(name).value
        barrier = Barrier(2)
        original = registry.begin_replacement
        def gated():
            barrier.wait(timeout=15)
            return original()
        def replace():
            client = self.app.test_client(); client.set_cookie(name, old_cookie)
            with self.app.app_context():
                response = client.post('/login', data={'company_code':'SYNTH',
                    'username':'operator', 'password':self.password})
                return response.status_code, 'Set-Cookie' in response.headers
        with patch.object(registry, 'begin_replacement', side_effect=gated):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(replace) for _ in range(2)]
                results = [f.result(timeout=30) for f in futures]
        self.assertEqual(sorted(results), [(302, True), (409, False)])
        self.db.session.expire_all()
        self.assertEqual(self.db.session.query(registry.AuthSession).filter_by(revoked=False).count(), 1)
