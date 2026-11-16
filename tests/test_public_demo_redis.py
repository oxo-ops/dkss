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
