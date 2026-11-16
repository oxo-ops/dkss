"""Real email-change verification with synthetic users and no delivery."""
from datetime import datetime, timedelta
import unittest
from unittest.mock import patch
import test_q02_mfa_boundaries as fixtures

class EmailChangeAttemptTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.Q02MFABoundaryTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.Q02MFABoundaryTests.tearDownClass.__func__)
    setUp = fixtures.Q02MFABoundaryTests.setUp
    tearDown = fixtures.Q02MFABoundaryTests.tearDown
    request = fixtures.Q02MFABoundaryTests.request
    user = fixtures.Q02MFABoundaryTests.user
    login = fixtures.Q02MFABoundaryTests.login
    copy_pending_client = fixtures.Q02MFABoundaryTests.copy_pending_client

    def prepare(self, company='A'):
        code = self.login(company)
        self.request('POST', '/mfa', data={'code': code})
        user = self.user(company)
        code = self.auth.create_email_change_code(user, 'next@example.invalid')
        self.db.session.commit()
        return code

    def verify(self, code, client=None):
        return self.request('POST','/settings/email/verify',client=client,data={'code':code})

    def test_copied_cookie_fifth_failure_invalidates_server_code(self):
        code = self.prepare()
        clients = [self.copy_pending_client() for _ in range(6)]
        for c in clients[:5]: self.verify('wrong',c)
        self.db.session.expire_all()
        self.assertIsNone(self.user().email_change_code_hash)
        self.verify(code,clients[5])
        self.assertEqual(self.user().email_address,'test@example.invalid')

    def test_regeneration_resets_only_that_challenge(self):
        old = self.prepare()
        for _ in range(4): self.verify('bad')
        new = self.auth.create_email_change_code(self.user(),'second@example.invalid')
        self.db.session.commit()
        self.verify('bad')
        self.assertIsNotNone(self.user().email_change_code_hash)
        self.verify(new)
        self.assertEqual(self.user().email_address,'second@example.invalid')

    def test_success_before_limit_consumes_once(self):
        code = self.prepare()
        for _ in range(4): self.verify('bad')
        self.verify(code)
        self.assertEqual(self.user().email_address,'next@example.invalid')
        self.verify(code)
        self.assertEqual(self.models.AuditLog.query.filter_by(action='email_changed').count(),1)

    def test_expired_code_cannot_change_email(self):
        code = self.prepare()
        self.user().email_change_code_expires_at=(datetime.now()-timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S')
        self.db.session.commit()
        self.verify(code)
        self.assertIsNone(self.user().email_change_code_hash)
        self.assertEqual(self.user().email_address,'test@example.invalid')

    def test_failures_do_not_affect_same_named_other_company(self):
        self.prepare()
        other = self.user('B')
        othercode = self.auth.create_email_change_code(other,'other@example.invalid')
        self.db.session.commit()
        for _ in range(5): self.verify('bad')
        self.assertIsNotNone(self.user('B').email_change_code_hash)
        self.assertEqual(self.user('B').email_address,'test@example.invalid')

    def test_audit_never_contains_code_hash_or_email(self):
        code=self.prepare()
        hashed=self.user().email_change_code_hash
        self.verify('bad')
        logs=self.models.AuditLog.query.filter_by(action='email_change_failed').all()
        self.assertEqual(len(logs),1)
        for entry in logs:
            for secret in (hashed,'next@example.invalid'):
                self.assertNotIn(secret,entry.detail)

    def test_settings_reissue_and_failed_delivery_rollback(self):
        old = self.prepare()
        for _ in range(4): self.verify('bad')
        delivered=[]
        def send(address, code):
            delivered.append(code)
            return True
        with patch.object(self.auth,'send_email_change_code_email',side_effect=send):
            response=self.request('POST','/settings',data={
                'action':'notifications','email_address':'again@example.invalid',
                'notification_current_password':self.password,'timezone':'Asia/Tokyo'})
        self.assertEqual(response.location,'/settings/email/verify')
        new_hash=self.user().email_change_code_hash
        with patch.object(self.auth,'send_email_change_code_email',return_value=False):
            self.request('POST','/settings',data={
                'action':'notifications','email_address':'failed@example.invalid',
                'notification_current_password':self.password,'timezone':'Asia/Tokyo'})
        self.db.session.expire_all()
        self.assertEqual(self.user().email_change_code_hash,new_hash)
        self.assertEqual(self.user().pending_email_address,'again@example.invalid')
        self.verify('bad')
        self.verify(delivered[0])
        self.assertEqual(self.user().email_address,'again@example.invalid')
