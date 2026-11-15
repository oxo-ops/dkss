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

    def add_person(self, name):
        from werkzeug.security import generate_password_hash
        user=self.models.User(company_code='SYNTH', username=name, role='user',
            password=generate_password_hash(self.password), last_name='Synthetic',first_name=name,
            password_changed_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            email_address=name+'@example.invalid')
        self.db.session.add(user);self.db.session.commit()
        return user.account_identity

    def test_user_change_requires_personal_credentials_and_retires_previous_identity(self):
        self.login();old=self.assert_authority();next_identity=self.add_person('second')
        name=self.app.config['SESSION_COOKIE_NAME']
        old_copy=self.app.test_client();old_copy.set_cookie(name,self.client.get_cookie(name).value)
        bad=self.client.post('/login',data={'company_code':'SYNTH','username':'second','password':'wrong'})
        self.assertEqual(bad.status_code,200)
        self.db.session.expire_all();self.assertFalse(old.revoked)
        good=self.client.post('/login',data={'company_code':'SYNTH','username':'second','password':self.password})
        self.assertEqual(good.status_code,302)
        with self.client.session_transaction() as s:
            self.assertEqual(s['username'],'second')
            self.assertEqual(s['account_identity'],next_identity)
        self.db.session.expire_all();self.assertTrue(old.revoked)
        self.assertEqual(old_copy.get('/api/notifications/unread-count').status_code,401)

    def test_mfa_user_change_retires_old_person_before_pending_challenge(self):
        self.login();old=self.assert_authority();self.add_person('second')
        self.app.config['MFA_ENABLED']=True
        with patch.object(self.auth,'send_mfa_code_email',return_value=True):
            r=self.client.post('/login',data={'company_code':'SYNTH','username':'second','password':self.password})
        self.assertEqual((r.status_code,r.location),(302,'/mfa'))
        with self.client.session_transaction() as s:
            self.assertNotIn('username',s)
            self.assertNotIn('authority_token',s)
            self.assertEqual(s['mfa_pending_username'],'second')
        self.db.session.expire_all();self.assertTrue(old.revoked)

    def test_conflict_page_does_not_set_or_delete_the_browser_cookie(self):
        from dkss_app import session_authority
        self.login();self.add_person('second')
        name=self.app.config['SESSION_COOKIE_NAME'];cookie=self.client.get_cookie(name).value
        with patch.object(session_authority,'begin_replacement',return_value=False):
            response=self.client.post('/login',data={'company_code':'SYNTH','username':'second','password':self.password},
                headers={'Accept':'text/html','Sec-Fetch-Dest':'document','Sec-Fetch-Mode':'navigate'})
        self.assertEqual(response.status_code,409)
        self.assertNotIn('Location',response.headers)
        self.assertEqual(response.headers.getlist('Set-Cookie'),[])
        self.assertIn('no-store',response.headers['Cache-Control'])
        self.assertIn('現在の利用者を確認する',response.get_data(as_text=True))
        self.assertNotIn('second',response.get_data(as_text=True))
        self.assertEqual(self.client.get_cookie(name).value,cookie)

    def csrf_request(self, method, path, **kwargs):
        # A production request has fresh app-context g, unlike the DB-fixture
        # context held by setUp. Do not reuse cached CSRF state across requests.
        with self.app.app_context():
            return getattr(self.client,method)(path,**kwargs)

    def csrf_token(self):
        response=self.csrf_request('get','/login/csrf-token',headers={'Accept':'application/json'})
        self.assertEqual(response.status_code,200)
        return response.get_json()['csrf_token']

    def test_csrf_enabled_login_and_missing_token_cannot_issue_authority(self):
        from dkss_app.session_authority_model import SessionAuthority
        self.app.config['WTF_CSRF_ENABLED']=True
        data={'company_code':'SYNTH','username':'operator','password':self.password}
        rejected=self.csrf_request('post','/login',data=data)
        self.assertEqual((rejected.status_code,rejected.location),(302,'/login'))
        self.assertEqual(self.db.session.execute(self.db.select(self.db.func.count()).select_from(SessionAuthority)).scalar(),0)
        data['csrf_token']=self.csrf_token()
        self.assertEqual(self.csrf_request('post','/login',data=data).status_code,302)
        self.assert_authority()

    def test_csrf_previous_person_form_cannot_log_out_successor(self):
        self.app.config['WTF_CSRF_ENABLED']=True
        self.add_person('second')
        first={'company_code':'SYNTH','username':'operator','password':self.password,'csrf_token':self.csrf_token()}
        self.assertEqual(self.csrf_request('post','/login',data=first).status_code,302)
        old_person_form=self.csrf_token()
        second={'company_code':'SYNTH','username':'second','password':self.password,'csrf_token':old_person_form}
        self.assertEqual(self.csrf_request('post','/login',data=second).status_code,302)
        self.assertEqual(self.csrf_request('post','/logout',data={'csrf_token':old_person_form}).status_code,400)
        self.assertEqual(self.csrf_request('get','/api/notifications/unread-count').status_code,200)
        with self.client.session_transaction() as state: self.assertEqual(state['username'],'second')
        valid_form=self.csrf_token()
        self.assertEqual(self.csrf_request('post','/logout',data={'csrf_token':valid_form}).status_code,302)
        self.assertEqual(self.csrf_request('get','/api/notifications/unread-count').status_code,401)

    def test_csrf_mfa_transition_needs_new_form_token_and_real_challenge(self):
        self.app.config.update(WTF_CSRF_ENABLED=True,MFA_ENABLED=True)
        token=self.csrf_token();codes=[]
        with patch.object(self.auth,'send_mfa_code_email',side_effect=lambda user,code: codes.append(code) or True):
            result=self.csrf_request('post','/login',data={'company_code':'SYNTH','username':'operator',
                'password':self.password,'csrf_token':token})
        self.assertEqual((result.status_code,result.location),(302,'/mfa'))
        rejected=self.csrf_request('post','/mfa',data={'code':codes[0],'csrf_token':token})
        self.assertEqual((rejected.status_code,rejected.location),(302,'/login'))
        with self.client.session_transaction() as state: self.assertNotIn('authority_token',state)
        fresh=self.csrf_token()
        wrong='000000' if codes[0]!='000000' else '999999'
        self.assertEqual(self.csrf_request('post','/mfa',data={'code':wrong,'csrf_token':fresh}).status_code,200)
        with self.client.session_transaction() as state:
            self.assertNotIn('authority_token',state)
            self.assertNotIn('username',state)
        from dkss_app.session_authority_model import SessionAuthority
        self.assertEqual(self.db.session.execute(self.db.select(self.db.func.count()).select_from(SessionAuthority)).scalar(),0)
        self.assertEqual(self.csrf_request('post','/mfa',data={'code':codes[0],'csrf_token':fresh}).status_code,302)
        self.assert_authority()

    def test_late_expired_api_response_preserves_successor_cookie(self):
        """A rejected old poll cannot delete the successor cookie."""
        from http.cookies import SimpleCookie
        self.login(); self.add_person('second')
        name = self.app.config['SESSION_COOKIE_NAME']
        old = self.app.test_client()
        old.set_cookie(name, self.client.get_cookie(name).value)
        winner = self.client.post('/login', data={'company_code':'SYNTH',
            'username':'second', 'password':self.password})
        self.assertEqual(winner.status_code, 302)
        late = old.get('/api/notifications/unread-count')
        self.assertEqual(late.status_code, 401)
        jar = SimpleCookie()
        for header in winner.headers.getlist('Set-Cookie'):
            jar.load(header)
        self.assertTrue(jar[name].value)
        for header in late.headers.getlist('Set-Cookie'):
            jar.load(header)
        self.assertEqual(late.headers.getlist('Set-Cookie'), [])
        latest = self.app.test_client(); latest.set_cookie(name, jar[name].value)
        self.assertEqual(latest.get('/api/notifications/unread-count').status_code, 200)
        with latest.session_transaction() as state: self.assertEqual(state['username'], 'second')

    def evaluation_fixture(self):
        import json
        from dkss_app.analysis_feedback import vehicle_analysis_proposal_ids
        vehicle = self.models.Vehicle(company_code='SYNTH', chassis_number='SYNTHETIC-FENCE')
        self.db.session.add(vehicle); self.db.session.flush()
        item = {'title':'Synthetic review', 'category':'inspection', 'source_ids':[]}
        self.db.session.add(self.models.VehicleKarteAnalysis(company_code='SYNTH',
            vehicle_record_id=vehicle.id, status='completed',
            result_json=json.dumps({'analysis':{'recommendations':[item]}})))
        self.db.session.commit()
        key, revision = vehicle_analysis_proposal_ids(item)
        return vehicle.id, {'proposal_id':key,'proposal_revision':revision,
            'verdict':'appropriate','comment':'Synthetic only'}

    def test_real_evaluation_write_rejected_after_revocation(self):
        from dkss_app import session_authority
        from dkss_app.session_authority_model import SessionAuthority
        vehicle_id, body = self.evaluation_fixture()
        self.login()
        original = session_authority.commit_vehicle_write
        def revoke_then_commit(identifier):
            # Separate transaction simulates completed revocation before the
            # commit fence; no pending domain row is flushed by this connection.
            with self.db.engine.begin() as conn:
                conn.execute(self.db.update(SessionAuthority).values(revoked=True))
            return original(identifier)
        with patch.object(session_authority, 'commit_vehicle_write', side_effect=revoke_then_commit):
            response = self.client.post(f'/vehicle/karte/{vehicle_id}/analysis/evaluation',
                json=body, headers={'Accept':'application/json'})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.models.VehicleAnalysisEvaluation.query.count(), 0)

    def test_real_evaluation_write_allowed_for_current_person(self):
        vehicle_id, body = self.evaluation_fixture(); self.login()
        response = self.client.post(f'/vehicle/karte/{vehicle_id}/analysis/evaluation',
            json=body, headers={'Accept':'application/json'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.models.VehicleAnalysisEvaluation.query.count(), 1)

    def test_expired_poll_then_interactive_relogin(self):
        from dkss_app.session_authority_model import SessionAuthority
        self.login()
        self.db.session.execute(self.db.update(SessionAuthority).values(idle_until=0))
        self.db.session.commit()
        poll = self.csrf_request('get', '/api/notifications/unread-count')
        self.assertEqual(poll.status_code, 401)
        self.assertEqual(poll.headers.getlist('Set-Cookie'), [])
        # Only the explicit interactive login reset clears the expired cookie.
        first = self.csrf_request('get', '/login')
        self.assertEqual(first.status_code, 302)
        self.assertTrue(first.headers.getlist('Set-Cookie'))
        self.assertEqual(self.client.get('/login').status_code, 200)
        self.login()
        self.assertEqual(self.client.get('/api/notifications/unread-count').status_code, 200)

    def test_reauthentication_locks_authority_before_dirty_user_flush(self):
        from sqlalchemy import event
        self.login()
        self.db.session.execute(self.db.update(self.models.User).values(failed_login_count=1))
        self.db.session.commit()
        updates = []
        def record(conn, cursor, statement, parameters, context, executemany):
            normalized = statement.lower().lstrip()
            if normalized.startswith('update '): updates.append(normalized.split()[1])
        event.listen(self.db.engine, 'before_cursor_execute', record)
        try: self.login()
        finally: event.remove(self.db.engine, 'before_cursor_execute', record)
        authority_at = next(i for i, name in enumerate(updates) if 'session_authority_candidate' in name)
        user_at = next(i for i, name in enumerate(updates) if name.strip('"') == 'user')
        self.assertLess(authority_at, user_at)

    def test_postgres_write_lock_serializes_revocation_after_commit(self):
        if not os.environ.get('SESSION_AUTHORITY_POSTGRES_TEST_URL'):
            self.skipTest('Row locks require the isolated PostgreSQL job')
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from sqlalchemy import event
        from sqlalchemy.orm import Session
        from dkss_app.session_authority_model import SessionAuthority
        vehicle_id, body = self.evaluation_fixture(); self.login()
        name = self.app.config['SESSION_COOKIE_NAME']
        cookie = self.client.get_cookie(name).value
        engine = self.db.engine
        locked, release, revoke_started = threading.Event(), threading.Event(), threading.Event()
        pids = {}
        def before_commit(sqlsession):
            if any(isinstance(obj, self.models.VehicleAnalysisEvaluation) for obj in sqlsession.new):
                pids['writer'] = sqlsession.connection().exec_driver_sql('SELECT pg_backend_pid()').scalar()
                locked.set()
                if not release.wait(10): raise RuntimeError('Test fence release timed out')
        def write():
            client = self.app.test_client(); client.set_cookie(name, cookie)
            return client.post(f'/vehicle/karte/{vehicle_id}/analysis/evaluation',
                json=body, headers={'Accept':'application/json'}).status_code
        def revoke():
            with engine.begin() as conn:
                pids['revoker'] = conn.exec_driver_sql('SELECT pg_backend_pid()').scalar()
                revoke_started.set()
                conn.execute(self.db.update(SessionAuthority).values(revoked=True))
            return True
        event.listen(Session, 'before_commit', before_commit)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                writer = pool.submit(write)
                self.assertTrue(locked.wait(10))
                revoker = pool.submit(revoke)
                try:
                    self.assertTrue(revoke_started.wait(10))
                    import time
                    deadline = time.monotonic() + 5
                    blockers = []
                    with engine.connect() as observer:
                        while time.monotonic() < deadline:
                            blockers = observer.exec_driver_sql('SELECT pg_blocking_pids(%s)',
                                (pids['revoker'],)).scalar()
                            if pids['writer'] in blockers: break
                            threading.Event().wait(0.01)
                    self.assertIn(pids['writer'], blockers)
                finally:
                    release.set()
                self.assertEqual(writer.result(timeout=10), 200)
                self.assertTrue(revoker.result(timeout=10))
        finally:
            release.set()
            event.remove(Session, 'before_commit', before_commit)
        self.db.session.expire_all()
        self.assertEqual(self.models.VehicleAnalysisEvaluation.query.count(), 1)
        self.assertTrue(self.db.session.execute(self.db.select(SessionAuthority.revoked)).scalar_one())

    def test_commit_fence_rechecks_account_company_and_expiry(self):
        from dkss_app import session_authority
        from dkss_app.session_authority_model import SessionAuthority
        vehicle_id, body = self.evaluation_fixture(); self.login()
        original = session_authority.commit_vehicle_write
        changes = [
            self.db.update(self.models.User).values(login_locked=True),
            self.db.update(self.models.Company).values(active=False),
            self.db.update(SessionAuthority).values(idle_until=0),
            self.db.update(self.models.Vehicle).values(deleted=True),
        ]
        for statement in changes:
            with self.subTest(change=str(statement)):
                def change_then_commit(identifier):
                    with self.db.engine.begin() as conn: conn.execute(statement)
                    return original(identifier)
                with patch.object(session_authority, 'commit_vehicle_write', side_effect=change_then_commit):
                    response = self.csrf_request('post',
                        f'/vehicle/karte/{vehicle_id}/analysis/evaluation', json=body,
                        headers={'Accept':'application/json'})
                self.assertEqual(response.status_code, 401)
                self.assertEqual(self.models.VehicleAnalysisEvaluation.query.count(), 0)
                self.db.session.execute(self.db.update(self.models.User).values(login_locked=False))
                self.db.session.execute(self.db.update(self.models.Company).values(active=True))
                self.db.session.execute(self.db.update(self.models.Vehicle).values(deleted=False))
                self.db.session.execute(self.db.update(SessionAuthority).values(idle_until=9999999999))
                self.db.session.commit()

    def test_postgres_concurrent_user_changes_allow_only_one_successor(self):
        if not os.environ.get('SESSION_AUTHORITY_POSTGRES_TEST_URL'):
            self.skipTest('Real PostgreSQL concurrency belongs to the isolated PG job')
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from dkss_app import session_authority
        from dkss_app.session_authority_model import SessionAuthority
        self.login();self.add_person('second');self.add_person('third')
        name=self.app.config['SESSION_COOKIE_NAME'];cookie=self.client.get_cookie(name).value
        clients=[self.app.test_client(),self.app.test_client()]
        for client in clients: client.set_cookie(name,cookie)
        barrier=threading.Barrier(2)
        original=session_authority.begin_replacement
        def simultaneous_claim():
            barrier.wait(timeout=10)
            return original()
        def attempt(pair):
            client,username=pair
            response=client.post('/login',data={'company_code':'SYNTH','username':username,'password':self.password},
                headers={'Accept':'text/html','Sec-Fetch-Dest':'document','Sec-Fetch-Mode':'navigate'})
            try: return response.status_code, response.headers.getlist("Set-Cookie")
            finally: response.close()
        # The barrier only aligns real requests. No SQL or authentication is mocked.
        with patch.object(session_authority,'begin_replacement',side_effect=simultaneous_claim):
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses=list(pool.map(attempt,zip(clients,['second','third'])))
        self.assertEqual(sorted(status for status, _ in responses),[302,409])
        winner_headers=next(headers for status, headers in responses if status==302)
        loser_headers=next(headers for status, headers in responses if status==409)
        self.assertTrue(winner_headers)
        self.assertEqual(loser_headers,[])
        # Deliver winner first, loser last into one browser cookie jar.
        from http.cookies import SimpleCookie
        jar=SimpleCookie()
        for header in winner_headers + loser_headers: jar.load(header)
        latest=self.app.test_client();latest.set_cookie(name,jar[name].value)
        self.assertEqual(latest.get('/api/notifications/unread-count').status_code,200)
        winner_name=['second','third'][next(i for i,(status,_) in enumerate(responses) if status==302)]
        with latest.session_transaction() as current:
            self.assertEqual(current['username'],winner_name)
        self.db.session.expire_all()
        rows=self.db.session.execute(self.db.select(SessionAuthority)).scalars().all()
        self.assertEqual(len(rows),2)
        self.assertEqual(sum(not row.revoked for row in rows),1)


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
