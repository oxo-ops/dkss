"""HTTPS CSRF acceptance with the Referer policy returned by the actual page.

Synthetic local test clients only. This models the browser's same-origin POST
header decision; it does not weaken Flask-WTF's HTTPS strict origin check.
"""
import re
import unittest
import test_company_invites as acceptance
from dkss_app.models import CompanyRegistrationApplication, CompanyRegistrationInvite, User


class CompanyInviteHTTPSCSRF(unittest.TestCase):
    setUp = acceptance.CompanyInviteAcceptance.setUp
    tearDown = acceptance.CompanyInviteAcceptance.tearDown
    make_user = acceptance.CompanyInviteAcceptance.make_user
    sign_in = acceptance.CompanyInviteAcceptance.sign_in
    issue = acceptance.CompanyInviteAcceptance.issue
    submit = acceptance.CompanyInviteAcceptance.submit
    origin = 'https://localhost'

    def fresh_form(self, client, path):
        self.app.config.update(WTF_CSRF_ENABLED=True, WTF_CSRF_SSL_STRICT=True)
        response = client.get(path, base_url=self.origin)
        self.assertEqual(response.status_code, 200)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True))
        self.assertIsNotNone(csrf)
        # Simulate the browser policy rather than always adding Referer: the old
        # no-referrer implementation must fail these fresh HTTPS form posts.
        headers = {} if response.headers.get('Referrer-Policy') == 'no-referrer' else {'Referer': self.origin + path}
        return csrf.group(1), headers, response

    def post_form(self, client, path, data):
        token, headers, _ = self.fresh_form(client, path)
        return client.post(path, base_url=self.origin, data=data | {'csrf_token': token}, headers=headers)

    def test_fresh_https_itc_issue_then_approve_and_revoke(self):
        issued = self.post_form(self.client, self.url, {'action': 'issue'})
        self.assertEqual(issued.status_code, 200)
        self.assertEqual(CompanyRegistrationInvite.query.count(), 1)
        # A second fresh GET/POST must also work, including approval and revoke.
        _, token = self.issue()
        application = self.submit(token)
        accepted = self.post_form(self.client, self.url, {'action': 'approve',
            'application_id': application.id, 'role': 'admin',
            'verification_reason': '導入契約の責任者へ既知の電話で本人確認済み'})
        self.assertEqual(accepted.status_code, 303)
        self.assertEqual(User.query.filter_by(company_code='FICTION', role='admin').count(), 1)
        invite = CompanyRegistrationInvite.query.order_by(CompanyRegistrationInvite.id.desc()).first()
        self.assertEqual(self.post_form(self.client, self.url,
            {'action': 'revoke', 'invite_id': invite.id}).status_code, 303)

    def test_fresh_https_public_registration(self):
        _, token = self.issue()
        response = self.post_form(self.public, '/register?invite=' + token, self.form)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(CompanyRegistrationApplication.query.filter_by(status='pending').count(), 1)
        self.assertEqual(User.query.filter_by(company_code='FICTION').count(), 0)

    def test_fresh_https_company_admin_issue(self):
        actor = self.make_user('FICTION', 'customeradmin', 'admin')
        self.sign_in(actor)
        response = self.post_form(self.client, '/master/registration', {'action': 'issue'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(CompanyRegistrationInvite.query.count(), 1)

    def test_https_strict_referrer_and_token_checks_remain_enforced(self):
        _, invite_token = self.issue()
        actor = self.make_user('FICTION', 'customeradmin', 'admin')
        customer = self.app.test_client()
        self.sign_in(actor, client=customer)
        cases = [(self.client, self.url, {'action': 'issue'}),
                 (customer, '/master/registration', {'action': 'issue'}),
                 (self.public, '/register?invite=' + invite_token, self.form)]
        for client, path, data in cases:
            token, _, response = self.fresh_form(client, path)
            self.assertEqual(response.headers['Referrer-Policy'], 'same-origin')
            self.assertIn('no-store', response.headers['Cache-Control'])
            for headers in ({}, {'Referer': 'https://external.example.invalid/'}, {'Referer': 'http://localhost/'}):
                with self.subTest(path=path, headers=headers):
                    denied = client.post(path, base_url=self.origin,
                        data=data | {'csrf_token': token}, headers=headers)
                    self.assertEqual(denied.status_code, 400)
                    self.assertEqual(denied.headers['Referrer-Policy'], 'same-origin')
            self.assertEqual(client.post(path, base_url=self.origin,
                data=data, headers={'Referer': self.origin + path}).status_code, 400)
        self.assertEqual(CompanyRegistrationInvite.query.count(), 1)
        self.assertEqual(CompanyRegistrationApplication.query.count(), 0)
