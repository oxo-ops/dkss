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

    def test_browser_failure_keeps_503_without_redirect_loop(self):
        from dkss_app.auth_session_registry import AuthSession
        AuthSession.__table__.drop(self.db.engine)
        with self.app.app_context():
            response = self.client.post('/login', data={'company_code':'SYNTH',
                'username':'operator', 'password':self.password}, headers={
                'Accept':'text/html', 'Sec-Fetch-Mode':'navigate', 'Sec-Fetch-Dest':'document'})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('Location', response.headers)
        self.assertNotIn('Set-Cookie', response.headers)
        self.assertTrue(response.cache_control.no_store)
        body = response.get_data(as_text=True)
        self.assertIn('完了したとは限りません', body)
        self.assertNotIn('operator', body)

    def test_unprepared_and_version_zero_read_failure_is_visible_before_activation(self):
        """Deployment itself adds availability dependence; not an activation-only gate."""
        from dkss_app import auth_session_registry as registry
        from sqlalchemy.exc import OperationalError
        registry.RegistryBase.metadata.drop_all(self.db.engine)
        self.login()
        for prepared in (False, True):
            with self.subTest(prepared=prepared):
                if prepared:
                    registry.prepare_schema()
                for path, headers in (
                    ('/api/notifications/unread-count', {}),
                    ('/static/js/base.js', {}),
                    ('/login', {'Accept':'text/html', 'Sec-Fetch-Mode':'navigate',
                                'Sec-Fetch-Dest':'document'}),
                ):
                    with self.subTest(path=path):
                        with patch.object(registry, 'inspect', side_effect=OperationalError(
                            'synthetic', {}, Exception('synthetic'))):
                            with self.app.app_context():
                                response = self.client.get(path, headers=headers)
                        self.assertEqual(response.status_code, 503)
                        self.assertNotIn('Set-Cookie', response.headers)
                        self.assertNotIn('Location', response.headers)
                with self.app.app_context():
                    recovered = self.client.get('/api/notifications/unread-count')
                self.assertEqual(recovered.status_code, 200)

    def test_unprepared_static_and_polling_each_consult_registry(self):
        """Count real guard entry without pretending SQLite timing is a PG budget."""
        from dkss_app import auth_session_registry as registry
        registry.RegistryBase.metadata.drop_all(self.db.engine)
        self.login()
        for path in ('/static/js/base.js', '/api/notifications/unread-count'):
            with self.subTest(path=path):
                with patch.object(registry, 'inspect', wraps=registry.inspect) as lookups:
                    for _ in range(3):
                        with self.app.app_context():
                            response = self.client.get(path)
                        self.assertEqual(response.status_code, 200)
                        response.close()
                self.assertEqual(lookups.call_count, 3)
