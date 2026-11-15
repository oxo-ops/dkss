"""New real-app integration; synthetic isolated database, never production."""
import os
import tempfile
import unittest
import uuid
from datetime import datetime
from unittest.mock import patch


class SessionAuthorityIntegration(unittest.TestCase):
    def setUp(self):
        from dkss_app import create_app, models, auth
        from dkss_app.extensions import db, limiter
        from werkzeug.security import generate_password_hash
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        uri = 'sqlite:///:memory:'
        engine_options = {}
        pg_url = os.environ.get('SESSION_AUTHORITY_POSTGRES_TEST_URL', '')
        if os.environ.get('SESSION_AUTHORITY_REQUIRE_POSTGRES') == '1' and not pg_url:
            raise RuntimeError('Isolated PostgreSQL URL required; no fallback permitted')
        if pg_url:
            from sqlalchemy import create_engine, text
            from sqlalchemy.engine import make_url
            parsed = make_url(pg_url)
            if (parsed.query or parsed.get_backend_name() != 'postgresql' or
                parsed.host not in ('127.0.0.1', 'localhost', '::1') or
                parsed.database != 'dkss_q02_ci'):
                raise RuntimeError('Only isolated loopback dkss_q02_ci allowed')
            admin = create_engine(pg_url, isolation_level='AUTOCOMMIT')
            self.addCleanup(admin.dispose)
            schema = 'q02_session_' + uuid.uuid4().hex
            with admin.connect() as conn:
                if conn.scalar(text('SELECT current_database()')) != 'dkss_q02_ci':
                    raise RuntimeError('Wrong isolated database')
                conn.execute(text('CREATE SCHEMA "' + schema + '"'))
            def cleanup_schema():
                with admin.connect() as conn:
                    conn.execute(text('DROP SCHEMA "' + schema + '" CASCADE'))
            self.addCleanup(cleanup_schema)
            uri = pg_url
            engine_options = {'connect_args': {'options': '-csearch_path=' + schema +
                ' -cstatement_timeout=30000 -clock_timeout=10000'}}
        with patch.dict(os.environ, {'RENDER':'', 'SECRET_KEY':'isolated-test-only',
            'DATABASE_URL':'', 'S3_BUCKET_NAME':'', 'OPENAI_API_KEY':'',
            'VAPID_PRIVATE_KEY':'', 'VAPID_PUBLIC_KEY':'', 'SMTP_HOST':''}):
            self.app = create_app({'TESTING':True, 'SQLALCHEMY_DATABASE_URI':
                uri, 'SQLALCHEMY_ENGINE_OPTIONS':engine_options, 'MFA_ENABLED':False,
                'WTF_CSRF_ENABLED':False, 'SESSION_AUTHORITY_CANDIDATE':True,
                'SESSION_AUTHORITY_IDLE_SECONDS':60, 'SESSION_AUTHORITY_ABSOLUTE_SECONDS':120})
        limiter.enabled=False
        self.db,self.models,self.auth = db,models,auth
        self.ctx=self.app.app_context();self.ctx.push()
        self.addCleanup(self.ctx.pop)
        self.addCleanup(db.engine.dispose)
        self.addCleanup(db.session.remove)
        db.create_all()
        from dkss_app.session_authority_model import SessionAuthority
        SessionAuthority.__table__.create(db.engine)
        self.password='Synthetic-Only-123!'
        db.session.add(models.Company(company_code='SYNTH',company_name='Synthetic',active=True))
        db.session.add(models.User(company_code='SYNTH', username='operator',role='user',
            password=generate_password_hash(self.password),last_name='Test',first_name='User',
            password_changed_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            email_address='test@example.invalid'))
        db.session.commit()
        self.client=self.app.test_client()

    def login(self):
        r=self.client.post('/login',data={'company_code':'SYNTH','username':'operator','password':self.password})
        self.assertEqual(r.status_code,302)
        return r

    def assert_authority(self):
        from dkss_app.session_authority_model import SessionAuthority
        with self.client.session_transaction() as s:
            self.assertEqual(len(s['authority_token']),64)
        row=self.db.session.execute(self.db.select(SessionAuthority)).scalar_one()
        self.assertFalse(row.revoked)
        return row

    def test_password_login_issues_and_logout_revokes_copied_cookie(self):
        self.login();row=self.assert_authority()
        name=self.app.config['SESSION_COOKIE_NAME']
        cookie=self.client.get_cookie(name)
        copied=self.app.test_client();copied.set_cookie(name,cookie.value)
        self.client.post('/logout')
        self.db.session.expire_all();self.assertTrue(row.revoked)
        self.assertEqual(copied.get('/api/notifications/unread-count').status_code,401)

    def test_mfa_completion_issues_not_password_step(self):
        self.app.config['MFA_ENABLED']=True
        codes=[]
        with patch.object(self.auth,'send_mfa_code_email',side_effect=lambda user,code: codes.append(code) or True):
            self.assertEqual(self.login().location,'/mfa')
        with self.client.session_transaction() as s:
            self.assertNotIn('authority_token',s)
        r=self.client.post('/mfa',data={'code':codes[0]})
        self.assertEqual(r.status_code,302)
        self.assert_authority()

    def test_polling_does_not_extend_and_protected_files_expire(self):
        self.login();row=self.assert_authority();deadline=row.idle_until
        self.client.get('/api/notifications/unread-count')
        self.db.session.expire_all();self.assertEqual(row.idle_until,deadline)
        row.idle_until=0;self.db.session.commit()
        r=self.client.get('/static/uploads/not-a-real-file.pdf')
        self.assertEqual((r.status_code,r.location),(302,'/login'))

    def test_absolute_expiry_not_bypassed_by_idle_deadline(self):
        self.login();row=self.assert_authority();row.absolute_until=0;self.db.session.commit()
        self.assertEqual(self.client.get('/api/notifications/unread-count').status_code,401)

    def test_legacy_cookie_without_authority_fails_closed(self):
        self.login()
        with self.client.session_transaction() as s: s.pop('authority_token')
        self.assertEqual(self.client.get('/api/notifications/unread-count').status_code,401)


class CandidateBoundaryTests(unittest.TestCase):
    def app(self):
        from flask import Flask
        app=Flask(__name__)
        app.config.update(TESTING=True, SESSION_AUTHORITY_CANDIDATE=True,
            SESSION_AUTHORITY_IDLE_SECONDS=60,SESSION_AUTHORITY_ABSOLUTE_SECONDS=120,
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        return app

    def test_production_and_remote_db_rejected(self):
        from dkss_app.session_authority import configure
        app=self.app();app.testing=False
        with self.assertRaises(RuntimeError): configure(app)
        app=self.app();app.config['SQLALCHEMY_DATABASE_URI']='postgresql://example.invalid/production'
        with self.assertRaises(RuntimeError): configure(app)
        app=self.app();app.config['SQLALCHEMY_DATABASE_URI']='postgresql://localhost/dkss_q02_ci?host=remote.invalid'
        with self.assertRaises(RuntimeError): configure(app)
        app=self.app();app.config['SQLALCHEMY_ENGINE_OPTIONS']={'connect_args':{'host':'remote.invalid'}}
        with self.assertRaises(RuntimeError): configure(app)
        app=self.app();app.config['SQLALCHEMY_DATABASE_URI']='sqlite:///existing.db'
        with self.assertRaises(RuntimeError): configure(app)

    def test_missing_duration_rejected(self):
        from dkss_app.session_authority import configure
        app=self.app();app.config.pop('SESSION_AUTHORITY_IDLE_SECONDS')
        with self.assertRaises(RuntimeError): configure(app)

    def test_candidate_not_registered_in_application_metadata(self):
        from dkss_app.extensions import db
        from dkss_app.session_authority_model import SessionAuthority
        self.assertNotIn(SessionAuthority.__tablename__,db.metadata.tables)
