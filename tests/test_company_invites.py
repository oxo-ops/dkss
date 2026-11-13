"""Isolated acceptance tests for reusable company invitations and customer approval.

All accounts/data are synthetic. No mail, production database or cloud calls.
"""
import unittest
import re
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import check_password_hash
from dkss_app import create_app
from dkss_app.extensions import db
from dkss_app.models import Company, User, Driver, AuditLog, CompanyRegistrationInvite, CompanyRegistrationApplication
from dkss_app import company_invites as invites


class CompanyInviteAcceptance(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'SECRET_KEY': 'synthetic-invites-only', 'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:', 'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False, 'MFA_ENABLED': False, 'S3_BUCKET_NAME': ''})
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        db.session.add_all([Company(company_code=code, company_name=code, active=True,
            vehicle_limit=3) for code in ('ITC', 'FICTION', 'OTHER')])
        self.actor = self.make_user('ITC', 'itc', 'itc')
        self.company = Company.query.filter_by(company_code='FICTION').one()
        self.url = f'/itc/companies/{self.company.id}/registration'
        self.client = self.app.test_client()
        self.sign_in(self.actor)
        self.public = self.app.test_client()
        self.form = dict(employee_id='manager', last_name='朝日', first_name='太郎',
                         email_address='', password='Synthetic9!Only', office='')

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def make_user(self, code, username, role):
        user = User(company_code=code, username=username, last_name='架空', role=role,
            password='unused', password_changed_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        db.session.add(user)
        db.session.commit()
        return user

    def sign_in(self, actor, client=None, **overrides):
        client = client or self.client
        with client.session_transaction() as session:
            session.clear()
            session.update(company_code=actor.company_code, username=actor.username,
                role=actor.role, account_identity=actor.account_identity,
                password_changed_at=actor.password_changed_at)
            session.update(overrides)

    def issue(self, code='FICTION'):
        with self.app.test_request_context():
            return invites.issue_invite(code, self.actor)

    def submit(self, token, username='manager', **values):
        with self.app.test_request_context():
            return invites.submit_application(token, self.form | {'employee_id': username} | values)

    def approve(self, application, role='admin', reason='導入契約の責任者に既知の連絡先で確認済み'):
        return self.client.post(self.url, data=dict(action='approve', application_id=application.id,
                                                  role=role, verification_reason=reason))

    def test_one_link_accepts_multiple_people_without_granting_access(self):
        invitation, token = self.issue()
        for username in ('manager', 'driver1', 'driver2'):
            response = self.public.post('/register?invite=' + token,
                                        data=self.form | {'employee_id': username})
            self.assertLess(response.status_code, 400)
        self.assertEqual(User.query.filter_by(company_code='FICTION').count(), 0)
        self.assertEqual(Driver.query.filter_by(company_code='FICTION').count(), 0)
        self.assertEqual(invites.validate_invite(token)[0].id, invitation.id)
        self.public.post('/login', data=dict(company_code='FICTION', username='manager',
                                            password=self.form['password']))
        with self.public.session_transaction() as session:
            self.assertNotIn('username', session)
        self.assertEqual(self.public.get('/master/registration').status_code, 302)

    def test_verified_first_admin_then_customer_approves_multiple_roles(self):
        _, token = self.issue()
        first = self.submit(token)
        second = self.submit(token, 'second')
        driver = self.submit(token, 'driver')
        self.assertLess(self.approve(first).status_code, 400)
        admin = User.query.filter_by(company_code='FICTION', username='manager').one()
        self.assertEqual(admin.role, 'admin')
        self.assertTrue(check_password_hash(admin.password, self.form['password']))
        self.assertTrue(admin.account_identity)
        self.sign_in(admin)
        for application, role in ((second, 'admin'), (driver, 'user')):
            response = self.client.post('/master/registration', data=dict(
                action='approve', application_id=application.id, role=role))
            self.assertLess(response.status_code, 400)
        self.assertEqual(sorted(u.role for u in User.query.filter_by(company_code='FICTION')), ['admin', 'admin', 'user'])
        self.assertEqual(Driver.query.filter_by(company_code='FICTION').count(), 3)
        self.assertEqual(invites.validate_invite(token)[1].company_code, 'FICTION')

    def test_initial_admin_requires_verification_not_first_come(self):
        _, token = self.issue()
        application = self.submit(token)
        self.assertGreaterEqual(self.approve(application, reason='').status_code, 400)
        self.assertGreaterEqual(self.approve(application, reason='ok').status_code, 400)
        self.assertEqual(User.query.filter_by(company_code='FICTION').count(), 0)

    def test_itc_cannot_manage_every_later_account(self):
        _, token = self.issue()
        first = self.submit(token)
        self.approve(first)
        later = self.submit(token, 'later')
        self.assertGreaterEqual(self.approve(later).status_code, 400)
        self.assertIsNone(User.query.filter_by(company_code='FICTION', username='later').first())

    def test_expiry_revoke_reissue_all_close_admission(self):
        invitation, token = self.issue()
        invitation.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()
        self.assertGreaterEqual(self.public.post('/register?invite=' + token, data=self.form).status_code, 400)
        invitation, token = self.issue()
        with self.app.test_request_context():
            invites.revoke_invite(invitation.id, self.actor)
        self.assertGreaterEqual(self.public.get('/register?invite=' + token).status_code, 400)
        _, old_token = self.issue()
        _, new_token = self.issue()
        self.assertNotEqual(old_token, new_token)
        self.assertGreaterEqual(self.public.post('/register?invite=' + old_token, data=self.form).status_code, 400)
        self.assertLess(self.public.post('/register?invite=' + new_token, data=self.form).status_code, 400)

    def test_invalid_or_legacy_company_code_links_fail_closed(self):
        for url in ('/register', '/register?company_code=FICTION', '/register?invite=unknown'):
            self.assertGreaterEqual(self.public.post(url, data=self.form).status_code, 400)
        self.assertEqual(User.query.filter_by(company_code='FICTION').count(), 0)

    def test_company_role_and_office_tampering_never_creates_account(self):
        _, token = self.issue()
        for fields in ({'role': 'itc'}, {'company_code': 'OTHER'}, {'company_id': '1'}, {'office': 'unknown'}):
            response = self.public.post('/register?invite=' + token, data=self.form | fields)
            self.assertGreaterEqual(response.status_code, 400)
            self.assertNotIn(self.form['password'], response.get_data(as_text=True))
        self.assertEqual(User.query.filter(User.company_code != 'ITC').count(), 0)

    def test_company_admin_cannot_approve_or_revoke_other_tenant(self):
        invitation, token = self.issue()
        application = self.submit(token)
        other = self.make_user('OTHER', 'admin', 'admin')
        self.sign_in(other)
        for action, fields in (('approve', dict(application_id=application.id, role='admin')),
                               ('reject', dict(application_id=application.id)),
                               ('revoke', dict(invite_id=invitation.id))):
            response = self.client.post('/master/registration', data={'action': action} | fields)
            self.assertGreaterEqual(response.status_code, 400)
        self.assertEqual(User.query.filter_by(company_code='FICTION').count(), 0)
        self.assertEqual(invites.validate_invite(token)[0].id, invitation.id)

    def test_regular_user_forged_role_and_stale_identity_denied(self):
        user = self.make_user('FICTION', 'ordinary', 'user')
        self.sign_in(user, role='admin')
        self.assertIn(self.client.post('/master/registration', data={'action': 'issue'}).status_code, (302, 403))
        self.sign_in(self.actor, account_identity='stale')
        self.assertEqual(self.client.post(self.url, data={'action': 'issue'}).status_code, 302)

    def test_disabled_company_cannot_register_or_approve(self):
        _, token = self.issue()
        application = self.submit(token)
        self.company.active = False
        db.session.commit()
        self.assertGreaterEqual(self.public.post('/register?invite=' + token, data=self.form | {'employee_id':'other'}).status_code, 400)
        self.assertGreaterEqual(self.approve(application).status_code, 400)
        self.assertEqual(User.query.filter_by(company_code='FICTION').count(), 0)

    def test_duplicate_and_replayed_approval_do_not_duplicate_accounts(self):
        _, token = self.issue()
        application = self.submit(token)
        self.assertGreaterEqual(self.public.post('/register?invite=' + token, data=self.form).status_code, 400)
        self.approve(application)
        self.assertGreaterEqual(self.approve(application).status_code, 400)
        self.assertEqual(User.query.filter_by(company_code='FICTION').count(), 1)
        self.assertEqual(Driver.query.filter_by(company_code='FICTION').count(), 1)

    def test_rejected_application_cannot_be_approved(self):
        _, token = self.issue()
        application = self.submit(token)
        response = self.client.post(self.url, data={'action': 'reject', 'application_id': application.id})
        self.assertLess(response.status_code, 400)
        self.assertGreaterEqual(self.approve(application).status_code, 400)
        self.assertEqual(User.query.filter_by(company_code='FICTION').count(), 0)

    def test_approval_failure_rolls_back_and_never_echoes_database_exception(self):
        _, token = self.issue()
        application = self.submit(token)
        with patch('dkss_app.company_invites.add_audit_log', side_effect=SQLAlchemyError('private-bound-secret')):
            response = self.approve(application)
        self.assertGreaterEqual(response.status_code, 400)
        self.assertNotIn('private-bound-secret', response.get_data(as_text=True))
        self.assertEqual(User.query.filter_by(company_code='FICTION').count(), 0)
        self.assertEqual(Driver.query.filter_by(company_code='FICTION').count(), 0)

    def test_email_optional_without_bypassing_enabled_mfa(self):
        _, token = self.issue()
        self.submit(token, 'noemail')
        self.app.config['MFA_ENABLED'] = True
        response = self.public.post('/register?invite=' + token, data=self.form | {'employee_id':'requiresmail'})
        self.assertGreaterEqual(response.status_code, 400)
        with patch('dkss_app.auth.send_mfa_code_email') as send:
            response = self.public.post('/register?invite=' + token, data=self.form | {'employee_id':'hasmail', 'email_address':'manager@example.invalid'})
            self.assertLess(response.status_code, 400)
            send.assert_not_called()

    def test_csrf_required_for_registration_issue_and_approval(self):
        _, token = self.issue()
        application = self.submit(token)
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.assertEqual(self.client.post(self.url, data={'action':'issue'}).status_code, 400)
        self.assertEqual(self.approve(application).status_code, 400)
        response = self.public.post('/register?invite=' + token, data=self.form | {'employee_id':'blocked'},
                                    headers={'Accept':'text/html'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('/register?invite=' + token, response.get_data(as_text=True))
        self.assertIn('no-store', response.headers.get('Cache-Control', ''))
        self.assertEqual(response.headers.get('Referrer-Policy'), 'same-origin')
        self.assertIsNone(CompanyRegistrationApplication.query.filter_by(username='blocked').first())
        self.assertEqual(User.query.filter_by(company_code='FICTION').count(), 0)

    def test_public_response_does_not_cache_or_leak_referrer(self):
        _, token = self.issue()
        response = self.public.get('/register?invite=' + token)
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response.headers.get('Cache-Control', ''))
        self.assertEqual(response.headers.get('Referrer-Policy'), 'same-origin')

    def test_http_issue_returns_link_once_not_stored_raw(self):
        response = self.client.post(self.url, data={'action':'issue'})
        self.assertLess(response.status_code, 400)
        self.assertIn('/register?invite=', response.get_data(as_text=True))
        self.assertNotIn(self.form['password'], response.get_data(as_text=True))

    def test_token_and_password_stored_only_as_hashes_and_erased_on_rejection(self):
        invitation, token = self.issue()
        application = self.submit(token)
        self.assertNotEqual(invitation.token_hash, token)
        self.assertTrue(check_password_hash(application.password_hash, self.form['password']))
        for row in (invitation, application):
            for column in row.__table__.columns:
                value = getattr(row, column.name)
                self.assertNotEqual(value, token)
                self.assertNotEqual(value, self.form['password'])
        self.client.post(self.url, data={'action':'reject', 'application_id':application.id})
        db.session.refresh(application)
        self.assertIsNone(application.password_hash)
        for audit in AuditLog.query.all():
            self.assertNotIn(token, audit.detail or '')
            self.assertNotIn(self.form['password'], audit.detail or '')

    def test_invite_revocation_cancels_pending_without_changing_existing_users(self):
        invitation, token = self.issue()
        application = self.submit(token)
        existing = self.make_user('FICTION', 'existing', 'user')
        identity = existing.account_identity
        response = self.client.post(self.url, data={'action':'revoke', 'invite_id':invitation.id})
        self.assertLess(response.status_code, 400)
        db.session.refresh(application)
        self.assertNotEqual(application.status, 'pending')
        self.assertIsNone(application.password_hash)
        self.assertEqual(User.query.filter_by(company_code='FICTION',username='existing').one().account_identity, identity)
        self.assertGreaterEqual(self.approve(application).status_code, 400)

    def test_expired_pending_application_cannot_be_approved(self):
        invitation, token = self.issue()
        application = self.submit(token)
        invitation.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()
        self.assertGreaterEqual(self.approve(application).status_code, 400)
        self.assertEqual(User.query.filter_by(company_code='FICTION').count(), 0)

    def test_approval_role_itc_is_never_available(self):
        _, token = self.issue()
        application = self.submit(token)
        self.assertGreaterEqual(self.approve(application, role='itc').status_code, 400)
        self.assertEqual(User.query.filter_by(company_code='FICTION').count(), 0)

    def test_old_itc_password_creation_route_is_removed(self):
        response = self.client.post(f'/itc/companies/{self.company.id}/initial-admin', data=self.form)
        self.assertIn(response.status_code, (404, 405))
        self.assertEqual(User.query.filter_by(company_code='FICTION').count(), 0)

    def test_expired_password_hashes_are_purged_by_maintenance(self):
        invitation, token = self.issue()
        application = self.submit(token)
        invitation.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()
        self.assertEqual(invites.expire_pending_applications(), 1)
        db.session.refresh(application)
        self.assertEqual(application.status, 'expired')
        self.assertIsNone(application.password_hash)
        self.assertEqual(invites.expire_pending_applications(), 0)

    def test_reissue_retires_pending_and_requires_new_application(self):
        _, old_token = self.issue()
        application = self.submit(old_token)
        _, new_token = self.issue()
        db.session.refresh(application)
        self.assertEqual(application.status, 'revoked')
        self.assertIsNone(application.password_hash)
        self.assertGreaterEqual(self.approve(application).status_code, 400)
        replacement = self.submit(new_token)
        self.assertNotEqual(replacement.id, application.id)
        self.assertLess(self.approve(replacement).status_code, 400)

    def test_browser_html_validation_keeps_invite_and_private_headers(self):
        _, token = self.issue()
        response = self.public.post('/register?invite=' + token,
            data=self.form | {'password': 'short'}, headers={'Accept':'text/html'})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('Location', response.headers)
        html = response.get_data(as_text=True)
        self.assertIn('/register?invite=' + token, html)
        self.assertIn('name="password"', html)
        self.assertNotIn('value="short"', html)
        self.assertIn('no-store', response.headers.get('Cache-Control', ''))
        self.assertEqual(response.headers.get('Referrer-Policy'), 'same-origin')
        self.assertEqual(CompanyRegistrationApplication.query.count(), 0)
        corrected = self.public.post('/register?invite=' + token, data=self.form,
                                     headers={'Accept':'text/html'})
        self.assertEqual(corrected.status_code, 200)
        self.assertEqual(CompanyRegistrationApplication.query.count(), 1)
        self.assertEqual(User.query.filter_by(company_code='FICTION').count(), 0)

    def test_all_201_applications_reachable_through_pagination_pending_first(self):
        invitation, _ = self.issue()
        # Seed synthetic states without expensive password hashing: this test
        # exercises list navigation, not admission or approval.
        for index in range(201):
            db.session.add(CompanyRegistrationApplication(company_code='FICTION',
                invite_id=invitation.id, username=f'pageperson{index:03d}',
                last_name='架空', status='pending' if index >= 150 else 'rejected',
                password_hash='synthetic-not-used' if index >= 150 else None))
        db.session.commit()
        seen = set()
        for page in range(1, 6):
            response = self.client.get(self.url + f'?page={page}', headers={'Accept':'text/html'})
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            users = set(re.findall(r'pageperson[0-9]{3}', html))
            self.assertFalse(seen & users)
            seen.update(users)
            self.assertEqual(len(users), 50 if page < 5 else 1)
            if page < 5:
                self.assertIn(f'href="?page={page+1}"', html)
            if page > 1:
                self.assertIn(f'href="?page={page-1}"', html)
            if page == 1:
                self.assertIn('pageperson150', users)
                self.assertNotIn('pageperson000', users)
            if page == 2:
                self.assertIn('pageperson200', users)
        self.assertEqual(len(seen), 201)
