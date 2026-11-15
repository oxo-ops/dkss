"""Handover UI checks, synthetic accounts and no external delivery."""
import unittest
import test_session_authority_candidate as candidate_tests


class HandoverUX(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        from dkss_app import create_app
        def preview_app(config):
            return create_app(dict(config, USER_HANDOVER_PREVIEW=True))
        with patch('dkss_app.create_app', side_effect=preview_app):
            candidate_tests.SessionAuthorityIntegration.setUp(self)
    login = candidate_tests.SessionAuthorityIntegration.login

    def test_anonymous_cannot_open_or_post_handover(self):
        for method in (self.client.get, self.client.post):
            self.assertEqual(method('/switch-user').location, '/login')

    def test_cancel_is_read_only_and_confirm_ends_session(self):
        self.login()
        response = self.client.get('/switch-user')
        self.assertIn('作業を終了して次の方へ', response.get_data(as_text=True))
        self.assertTrue(response.cache_control.no_store)
        with self.client.session_transaction() as state:
            nonce = state['handover_nonce']
            authority = state['authority_token']
        self.client.get('/switch-user')
        with self.client.session_transaction() as state:
            self.assertEqual(state['authority_token'], authority)
            self.assertEqual(state['handover_nonce'], nonce)
        response = self.client.post('/switch-user', data={'handover_nonce': nonce})
        self.assertEqual(response.location, '/login')
        with self.client.session_transaction() as state:
            self.assertNotIn('username', state)

    def test_previous_login_form_cannot_end_new_login(self):
        self.login(); self.client.get('/switch-user')
        with self.client.session_transaction() as state:
            old_nonce = state['handover_nonce']
        self.client.post('/logout'); self.login()
        with self.client.session_transaction() as state:
            authority = state['authority_token']
        response = self.client.post('/switch-user', data={'handover_nonce': old_nonce})
        self.assertIn('この操作では終了していません', response.get_data(as_text=True))
        with self.client.session_transaction() as state:
            self.assertEqual(state['authority_token'], authority)
            self.assertEqual(state['username'], 'operator')

    def test_csrf_is_not_bypassed(self):
        from flask.sessions import SecureCookieSessionInterface
        self.app.config['SESSION_AUTHORITY_CANDIDATE'] = False
        self.app.session_interface = SecureCookieSessionInterface()
        self.login(); self.client.get('/switch-user')
        with self.client.session_transaction() as state:
            nonce = state['handover_nonce']
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.client.post('/switch-user', data={'handover_nonce': nonce})
        with self.client.session_transaction() as state:
            self.assertEqual(state['username'], 'operator')

    def test_normal_mode_handover_uses_existing_mfa(self):
        from flask.sessions import SecureCookieSessionInterface
        from unittest.mock import patch
        self.app.config['SESSION_AUTHORITY_CANDIDATE'] = False
        self.app.session_interface = SecureCookieSessionInterface()
        self.login(); self.client.get('/switch-user')
        with self.client.session_transaction() as state:
            nonce = state['handover_nonce']
            self.assertNotIn('authority_token', state)
        self.client.post('/switch-user', data={'handover_nonce': nonce})
        self.app.config['MFA_ENABLED'] = True
        with patch.object(self.auth, 'send_mfa_code_email', return_value=True):
            response = self.login()
        self.assertEqual(response.location, '/mfa')
        with self.client.session_transaction() as state:
            self.assertNotIn('username', state)

    def test_non_ascii_nonce_is_rejected_without_logout(self):
        self.login(); self.client.get('/switch-user')
        response = self.client.post('/switch-user', data={'handover_nonce': 'あ' * 64})
        self.assertIn('この操作では終了していません', response.get_data(as_text=True))
        with self.client.session_transaction() as state:
            self.assertEqual(state['username'], 'operator')

    def test_normal_mode_valid_csrf_confirmation(self):
        import re
        from flask.sessions import SecureCookieSessionInterface
        self.app.config['SESSION_AUTHORITY_CANDIDATE'] = False
        self.app.session_interface = SecureCookieSessionInterface()
        self.login()
        self.app.config['WTF_CSRF_ENABLED'] = True
        with self.app.app_context():
            page = self.client.get('/switch-user').get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
        nonce = re.search(r'name="handover_nonce" value="([^"]+)"', page).group(1)
        with self.app.app_context():
            response = self.client.post('/switch-user', data={'csrf_token': token, 'handover_nonce': nonce})
        self.assertEqual(response.location, '/login')
        with self.client.session_transaction() as state:
            self.assertNotIn('username', state)

    def test_route_is_absent_without_explicit_test_preview(self):
        from dkss_app import create_app
        from unittest.mock import patch
        import os
        with patch.dict(os.environ, {'RENDER': '', 'DATABASE_URL': '', 'S3_BUCKET_NAME': '', 'OPENAI_API_KEY': '', 'VAPID_PRIVATE_KEY': '', 'SMTP_HOST': ''}):
            for testing, preview in ((True, False), (False, True)):
                app = create_app(dict(self.app.config, TESTING=testing,
                    SESSION_AUTHORITY_CANDIDATE=False, USER_HANDOVER_PREVIEW=preview))
                self.assertNotIn('/switch-user', {rule.rule for rule in app.url_map.iter_rules()})
                with app.app_context():
                    self.db.engine.dispose()
