"""Optional real Redis acceptance: only an explicitly owned loopback CI service.

Never reads the application RATELIMIT_STORAGE_URI environment variable. No FLUSH,
SCAN or global cleanup: only random-epoch keys created by this test are deleted.
"""
import os
import time
import unittest
from urllib.parse import urlsplit
from uuid import uuid4
from flask import Flask, session
from werkzeug.exceptions import HTTPException
from dkss_app import public_demo_sessions as sessions


class DemoRealRedisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        uri = os.environ.get('PUBLIC_DEMO_TEST_REDIS_URL', '')
        required = os.environ.get('PUBLIC_DEMO_REQUIRE_REDIS') == '1'
        if not uri:
            if required:
                raise RuntimeError('Required disposable Redis URL is missing')
            raise unittest.SkipTest('Owned disposable Redis not provided')
        parsed = urlsplit(uri)
        if (os.environ.get('PUBLIC_DEMO_TEST_REDIS_OWNED') != '1'
                or parsed.scheme != 'redis' or parsed.hostname != '127.0.0.1'
                or parsed.port != 6379 or parsed.path != '/15'
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise RuntimeError('Only explicitly owned loopback Redis DB 15 is allowed')
        import redis
        cls.store = redis.Redis.from_url(uri, socket_connect_timeout=2, socket_timeout=2)
        if cls.store.ping() is not True:
            raise RuntimeError('Disposable Redis not ready')
        cls.uri = uri

    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = 'synthetic-fixture-only'
        self.app.config.update(RATELIMIT_STORAGE_URI=self.uri,
            PUBLIC_DEMO_EPOCH='synthetic-test-' + str(uuid4()),
            PUBLIC_DEMO_UNTIL=int(time.time()) + 60)
        self.ctx = self.app.test_request_context('/')
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        session.update(company_code='SYNTHETIC_ONLY', account_identity=str(uuid4()))
        sessions.issue()
        self.key = sessions._key(session['public_demo_token'])
        self.addCleanup(self.store.delete, self.key)

    def rejected(self, function, status):
        with self.assertRaises(HTTPException) as caught:
            function()
        self.assertEqual(caught.exception.code, status)

    def test_real_set_get_ttl_and_logout_delete(self):
        self.assertTrue(self.key.startswith('alseon:demo:active:'))
        self.assertGreater(self.store.ttl(self.key), 0)
        self.assertLessEqual(self.store.ttl(self.key), 60)
        sessions.verify()
        sessions.revoke()
        self.assertIsNone(self.store.get(self.key))
        self.rejected(sessions.verify, 410)

    def test_missing_or_expired_active_record_denies_cookie(self):
        self.store.pexpire(self.key, 1)
        time.sleep(.03)
        self.rejected(sessions.verify, 410)
        self.assertNotIn('username', session)

    def test_corrupt_or_wrong_owner_record_denies_cookie(self):
        self.store.set(self.key, 'not-the-owner', ex=60)
        self.rejected(sessions.verify, 410)

    def test_role_switch_keeps_fixed_entry_binding(self):
        session['account_identity'] = str(uuid4())
        sessions.verify()
        session['company_code'] = 'OTHER_COMPANY'
        self.rejected(sessions.verify, 410)


    def test_pool_reuses_real_connection_and_checks_every_get(self):
        with self.app.app_context():
            client = sessions._store()
            self.assertIs(client, sessions._store())
            connection_id = client.client_id()
        for _ in range(10):
            sessions.verify()
        self.assertEqual(client.client_id(), connection_id)
        # Reuse must not cache the authorization result.
        self.store.delete(self.key)
        self.rejected(sessions.verify, 410)

    def test_server_closed_socket_recovers_without_auth_cache(self):
        client = sessions._store()
        connection_id = client.client_id()
        self.assertEqual(self.store.client_kill_filter(_id=connection_id), 1)
        # redis-py may reconnect immediately or fail closed on first attempt.
        try:
            sessions.verify()
        except HTTPException as exc:
            self.assertEqual(exc.code, 503)
        sessions.verify()
        self.assertNotEqual(client.client_id(), connection_id)
        self.store.delete(self.key)
        self.rejected(sessions.verify, 410)

    def test_pool_disconnect_reconnect_preserves_expiry(self):
        client = sessions._store()
        old_id = client.client_id()
        client.connection_pool.disconnect()
        sessions.verify()
        self.assertNotEqual(client.client_id(), old_id)
        self.store.pexpire(self.key, 1)
        time.sleep(.03)
        self.rejected(sessions.verify, 410)

    def test_actual_connection_refusal_fails_closed_then_recovers(self):
        import socket
        blocker = socket.socket()
        blocker.bind(('127.0.0.1', 0))
        self.addCleanup(blocker.close)
        # Owned bound-but-not-listening loopback port; never a real service.
        self.app.config['RATELIMIT_STORAGE_URI'] = 'redis://127.0.0.1:%s/15' % blocker.getsockname()[1]
        self.rejected(sessions.verify, 503)
        self.app.config['RATELIMIT_STORAGE_URI'] = self.uri
        sessions.verify()

    def test_real_concurrent_verification_and_revocation(self):
        from concurrent.futures import ThreadPoolExecutor
        state = dict(session)
        def verify_one(_):
            with self.app.test_request_context('/'):
                session.update(state)
                sessions.verify()
        with ThreadPoolExecutor(max_workers=8) as workers:
            list(workers.map(verify_one, range(80)))
        sessions.revoke()
        with ThreadPoolExecutor(max_workers=8) as workers:
            futures = [workers.submit(verify_one, i) for i in range(8)]
            for future in futures:
                with self.assertRaises(HTTPException) as caught:
                    future.result()
                self.assertEqual(caught.exception.code, 410)
