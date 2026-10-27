"""QP-20261027 Q02-AUTH-04: real password/MFA flow, mail transport mocked only."""
import os
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from werkzeug.security import generate_password_hash


class Q02MFABoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='dkss-q02-mfa-')
        from dkss_app import create_app, models, auth
        from dkss_app.extensions import db, limiter
        cls.db,cls.models,cls.auth=db,models,auth
        cls.password='Isolated-Login-742!'
        cls.password_hash=generate_password_hash(cls.password)
        with patch.dict(os.environ,{'SECRET_KEY':'q02-isolated-mfa', 'RENDER':'',
            'DATABASE_URL':'sqlite:///'+str(Path(cls.temp.name)/'test.db'),
            'S3_BUCKET_NAME':'','OPENAI_API_KEY':'','SMTP_HOST':'','VAPID_PRIVATE_KEY':'',
            'VAPID_PUBLIC_KEY':'','RATELIMIT_STORAGE_URI':'memory://'}):
            cls.app=create_app({'TESTING':True,'MFA_ENABLED':True,'WTF_CSRF_ENABLED':False})
        limiter.enabled=False

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            cls.db.session.remove();cls.db.engine.dispose()
        cls.temp.cleanup()

    def setUp(self):
        self.ctx=self.app.app_context();self.ctx.push()
        self.db.drop_all();self.db.create_all()
        m=self.models
        stamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for company in ('A','B'):
            self.db.session.add(m.Company(company_code=company,company_name=company,active=True))
            self.db.session.add(m.User(company_code=company,username='same',password=self.password_hash,
                last_name='Test',first_name='User',role='user',password_changed_at=stamp,
                email_address='test@example.invalid'))
        self.db.session.commit()
        self.client=self.app.test_client()
        self.codes=[]
        def delivery(user,code):
            self.codes.append((user.company_code,code))
            return True
        self.mail=patch.object(self.auth,'send_mfa_code_email',side_effect=delivery)
        self.mail.start();self.addCleanup(self.mail.stop)

    def tearDown(self):
        self.db.session.remove();self.ctx.pop()

    def request(self,method,url,client=None,**kw):
        r=(client or self.client).open(url,method=method,**kw)
        self.addCleanup(r.close)
        return r

    def user(self,company='A'):
        return self.models.User.query.filter_by(company_code=company,username='same').one()

    def login(self,company='A',client=None):
        r=self.request('POST','/login',client=client,data={
            'company_code':company,'username':'same','password':self.password})
        self.assertEqual(r.status_code,302)
        self.assertEqual(r.location,'/mfa')
        return self.codes[-1][1]

    def assert_not_authenticated(self,client=None):
        with (client or self.client).session_transaction() as session:
            self.assertNotIn('username',session)
        self.assertEqual(self.request('GET','/api/notifications/unread-count',client=client).status_code,401)

    def copy_pending_client(self):
        other=self.app.test_client()
        cookie=self.client.get_cookie(self.app.config['SESSION_COOKIE_NAME'])
        self.assertIsNotNone(cookie)
        other.set_cookie(self.app.config['SESSION_COOKIE_NAME'],cookie.value)
        return other

    def test_password_success_is_pending_until_correct_mfa(self):
        code=self.login('a')
        self.assert_not_authenticated()
        r=self.request('POST','/mfa',data={'code':code})
        self.assertEqual(r.status_code,302)
        with self.client.session_transaction() as session:
            self.assertEqual((session['company_code'],session['username']),('A','same'))
        self.assertEqual(self.request('GET','/api/notifications/unread-count').status_code,200)

    def test_same_username_in_another_company_cannot_use_our_code(self):
        code=self.login()
        other=self.app.test_client();other_code=self.login('B',other)
        if other_code==code:
            # Make this deterministic even if the random six-digit codes collide.
            self.user('B').mfa_code_hash=generate_password_hash('999999' if code!='999999' else '888888')
            self.db.session.commit()
        self.request('POST','/mfa',client=other,data={'code':code})
        self.assert_not_authenticated(other)

    def test_successful_code_is_single_use_even_with_copied_cookie(self):
        code=self.login();other=self.copy_pending_client()
        self.assertEqual(self.request('POST','/mfa',data={'code':code}).status_code,302)
        self.request('POST','/mfa',client=other,data={'code':code})
        self.assert_not_authenticated(other)

    def test_expired_code_does_not_authenticate(self):
        code=self.login()
        self.user().mfa_code_expires_at=(datetime.now()-timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S')
        self.db.session.commit()
        self.request('POST','/mfa',data={'code':code})
        self.assert_not_authenticated()
        self.assertIsNone(self.user().mfa_code_hash)

    def test_account_lock_during_mfa_revokes_pending_session(self):
        code=self.login();self.user().login_locked=True;self.db.session.commit()
        self.request('POST','/mfa',data={'code':code});self.assert_not_authenticated()

    def test_company_disable_during_mfa_revokes_pending_session(self):
        code=self.login()
        self.models.Company.query.filter_by(company_code='A').one().active=False
        self.db.session.commit()
        self.request('POST','/mfa',data={'code':code});self.assert_not_authenticated()

    def test_password_change_during_mfa_revokes_pending_session(self):
        code=self.login();self.user().password_changed_at='2000-01-01 00:00:00';self.db.session.commit()
        self.request('POST','/mfa',data={'code':code});self.assert_not_authenticated()

    def test_five_failures_invalidate_code(self):
        code=self.login()
        wrong='000000' if code!='000000' else '111111'
        for _ in range(5):self.request('POST','/mfa',data={'code':wrong})
        self.assertIsNone(self.user().mfa_code_hash)
        self.request('POST','/mfa',data={'code':code});self.assert_not_authenticated()

    def test_copied_pending_cookie_cannot_reset_five_attempt_limit(self):
        code=self.login()
        wrong='000000' if code!='000000' else '111111'
        clients=[self.copy_pending_client() for _ in range(6)]
        for client in clients[:5]:
            self.request('POST','/mfa',client=client,data={'code':wrong})
        self.db.session.expire_all()
        self.assertIsNone(self.user().mfa_code_hash,'Five failures must invalidate the server-side challenge across copied cookies')
        self.request('POST','/mfa',client=clients[-1],data={'code':code})
        self.assert_not_authenticated(clients[-1])


    def test_newly_issued_code_rejects_old_pending_session(self):
        self.login();old=self.copy_pending_client()
        self.user().mfa_code_sent_at=(datetime.now()-timedelta(seconds=61)).strftime('%Y-%m-%d %H:%M:%S')
        self.db.session.commit()
        fresh=self.app.test_client();code=self.login(client=fresh)
        self.request('POST','/mfa',client=old,data={'code':code})
        self.assert_not_authenticated(old)
        self.assertEqual(self.request('POST','/mfa',client=fresh,data={'code':code}).status_code,302)
        with fresh.session_transaction() as session:self.assertEqual(session['username'],'same')

    def test_old_challenge_failures_do_not_count_against_new_code(self):
        code=self.login();wrong='000000' if code!='000000' else '111111'
        for _ in range(4):self.request('POST','/mfa',data={'code':wrong})
        self.user().mfa_code_sent_at=(datetime.now()-timedelta(seconds=61)).strftime('%Y-%m-%d %H:%M:%S')
        self.db.session.commit()
        fresh=self.app.test_client();code=self.login(client=fresh)
        wrong='000000' if code!='000000' else '111111'
        self.request('POST','/mfa',client=fresh,data={'code':wrong})
        self.assertIsNotNone(self.user().mfa_code_hash)
        self.request('POST','/mfa',client=fresh,data={'code':code})
        with fresh.session_transaction() as session:self.assertEqual(session['username'],'same')

    def test_other_company_failures_cannot_invalidate_own_code(self):
        code=self.login();other=self.app.test_client();other_code=self.login('B',other)
        wrong='000000' if other_code!='000000' else '111111'
        for _ in range(5):self.request('POST','/mfa',client=other,data={'code':wrong})
        self.assertIsNone(self.user('B').mfa_code_hash)
        self.request('POST','/mfa',data={'code':code})
        with self.client.session_transaction() as session:self.assertEqual(session['company_code'],'A')

    def test_code_delivery_failure_does_not_authenticate(self):
        with patch.object(self.auth,'send_mfa_code_email',return_value=False):
            r=self.request('POST','/login',data={'company_code':'A','username':'same','password':self.password})
        self.assertEqual(r.status_code,200)
        self.assert_not_authenticated()
        self.assertIsNone(self.user().mfa_code_hash)

    def test_resend_within_sixty_seconds_does_not_replace_challenge(self):
        code=self.login();before=self.user().mfa_code_hash
        r=self.request('POST','/login',data={'company_code':'A','username':'same','password':self.password})
        self.assertEqual(r.status_code,200)
        self.assertEqual(len(self.codes),1)
        self.assertEqual(self.user().mfa_code_hash,before)
        self.request('POST','/mfa',data={'code':code})
        with self.client.session_transaction() as session:self.assertEqual(session['username'],'same')

    def test_wrong_password_never_starts_mfa(self):
        r=self.request('POST','/login',data={'company_code':'A','username':'same','password':'wrong'})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.codes,[])
        self.assert_not_authenticated()

if __name__=='__main__':unittest.main()
