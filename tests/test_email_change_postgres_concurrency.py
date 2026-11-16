"""Owned loopback PostgreSQL only; share the established MFA fixture guards."""
import unittest
import test_q02_postgres_mfa_concurrency as fixtures

class EmailChangePostgresTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.Q02PostgresMFAConcurrencyTests.setUpClass.__func__)
    drop_private_schema = classmethod(fixtures.Q02PostgresMFAConcurrencyTests.drop_private_schema.__func__)
    setUp = fixtures.Q02PostgresMFAConcurrencyTests.setUp
    pending = fixtures.Q02PostgresMFAConcurrencyTests.pending
    clone = fixtures.Q02PostgresMFAConcurrencyTests.clone
    together = fixtures.Q02PostgresMFAConcurrencyTests.together
    user = fixtures.Q02PostgresMFAConcurrencyTests.user
    logs = fixtures.Q02PostgresMFAConcurrencyTests.logs

    def prepare(self, company):
        client, mfa = self.pending(company)
        response=client.post('/mfa',data={'code':mfa}); response.close()
        code=self.auth.create_email_change_code(self.user(company),'next@example.invalid')
        self.db.session.commit()
        return client,code

    def submit(self, client, code):
        response=client.post('/settings/email/verify',data={'code':code})
        try: return response.status_code, (None,None)
        finally: response.close()

    def test_eight_parallel_failures_stop_at_five(self):
        company=self.companies[0]
        client,code=self.prepare(company)
        self.together([(self.clone(client),'wrong') for _ in range(8)])
        self.assertEqual(len(self.logs(company,'email_change_failed')),5)
        self.assertEqual(len(self.logs(company,'email_change_code_invalidated')),1)
        self.assertIsNone(self.user(company).email_change_code_hash)
        self.assertEqual(self.user(company).email_address,'q02@example.invalid')

    def test_parallel_valid_code_consumed_once(self):
        company=self.companies[0]
        client,code=self.prepare(company)
        self.together([(self.clone(client),code) for _ in range(8)])
        self.assertEqual(len(self.logs(company,'email_changed')),1)
        self.assertEqual(self.user(company).email_address,'next@example.invalid')

    def test_two_failures_after_four_only_add_one(self):
        company=self.companies[0]
        client,code=self.prepare(company)
        for _ in range(4): self.submit(self.clone(client),'wrong')
        self.together([(self.clone(client),'wrong') for _ in range(2)])
        self.assertEqual(len(self.logs(company,'email_change_failed')),5)
        self.assertEqual(len(self.logs(company,'email_change_code_invalidated')),1)

    def test_issuance_lock_serializes_old_verification(self):
        """Hold issuance at mocked SMTP; the second backend must wait on its row."""
        import hashlib
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        from sqlalchemy import event, text
        company=self.companies[0]
        client,old_code=self.prepare(company)
        held=threading.Event(); attempted=threading.Event(); release=threading.Event()
        new_codes=[]
        pids={}
        replacement = (int(old_code) + 1) % 1000000
        def delivery(address, code):
            pids['issuer']=self.db.session.execute(text('SELECT pg_backend_pid()')).scalar_one()
            new_codes.append(code); held.set()
            if not release.wait(15): raise AssertionError('release timeout')
            return True
        def observe(conn,cursor,statement,parameters,context,many):
            if threading.current_thread().name.endswith('verify') and 'FOR UPDATE' in statement:
                pids['verifier']=cursor.connection.get_backend_pid()
                attempted.set()
        def issue():
            response=self.clone(client).post('/settings',data={
                'action':'notifications','email_address':'newer@example.invalid',
                'notification_current_password':self.password,'timezone':'Asia/Tokyo'})
            try: return response.status_code
            finally: response.close()
        def verify():
            threading.current_thread().name='email-verify'
            return self.submit(self.clone(client),old_code)
        event.listen(self.engine,'before_cursor_execute',observe)
        try:
            with patch.object(self.auth,'send_email_change_code_email',side_effect=delivery), \
                    patch.object(self.auth._dkss_common.secrets,'randbelow',return_value=replacement):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    issuance=pool.submit(issue)
                    try:
                        self.assertTrue(held.wait(15))
                        verification=pool.submit(verify)
                        self.assertTrue(attempted.wait(15))
                        blocked=False
                        deadline=time.monotonic()+10
                        with self.admin_engine.connect() as observer:
                            while time.monotonic()<deadline and not verification.done():
                                blocked=bool(observer.scalar(text("""
                                    SELECT EXISTS (SELECT 1 FROM pg_stat_activity
                                    WHERE pid=:verifier AND wait_event_type='Lock'
                                    AND :issuer=ANY(pg_blocking_pids(pid)))
                                """),pids))
                                if blocked: break
                                time.sleep(0.02)
                        self.assertTrue(blocked, 'Verifier must actually wait on issuer backend lock')
                        self.assertFalse(verification.done())
                    finally: release.set()
                    self.assertEqual(issuance.result(timeout=20),302)
                    self.assertIn(verification.result(timeout=20)[0],(200,302))
        finally: event.remove(self.engine,'before_cursor_execute',observe)
        self.assertEqual(self.user(company).pending_email_address,'newer@example.invalid')
        current_hash=self.user(company).email_change_code_hash
        prefix='Email change challenge '+hashlib.sha256(current_hash.encode('utf-8')).hexdigest()+': '
        failures=self.logs(company,'email_change_failed')
        self.assertEqual(len(failures),1)
        self.assertTrue(failures[0].detail.startswith(prefix))
        self.assertEqual(self.user(company).email_address,'q02@example.invalid')
        self.assertNotEqual(new_codes[0],old_code)
        self.submit(self.clone(client),new_codes[0])
        self.assertEqual(self.user(company).email_address,'newer@example.invalid')
