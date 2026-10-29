"""Explicitly opted-in disposable local PostgreSQL account-reuse regression.

Never accepts an arbitrary DATABASE_URL. The database is created outside tests
and must be named dkss_q03_test on loopback.
"""
import os
import tempfile
import unittest
from unittest.mock import patch
from sqlalchemy.engine import make_url

import test_q03_person_identity as identity


@unittest.skipUnless(os.environ.get('Q03_POSTGRES_TEST_URL'), 'local Q03 PostgreSQL URL not configured')
class Q03PostgresPersonIdentityTests(identity.Q03PersonIdentityTests):
    @classmethod
    def setUpClass(cls):
        url = make_url(os.environ['Q03_POSTGRES_TEST_URL'])
        if url.host not in {'127.0.0.1', 'localhost'} or url.database != 'dkss_q03_test':
            raise RuntimeError('Only the disposable local dkss_q03_test database is supported')
        cls.temp = tempfile.TemporaryDirectory(prefix='dkss-q03-postgres-')
        from dkss_app import create_app, models
        from dkss_app.extensions import db, limiter
        cls.db, cls.models = db, models
        env = {'SECRET_KEY': 'q03-postgres-test-only', 'RENDER': '',
            'DATABASE_URL': os.environ['Q03_POSTGRES_TEST_URL'], 'OPENAI_API_KEY': '',
            'SMTP_HOST': '', 'S3_BUCKET_NAME': '', 'VAPID_PRIVATE_KEY': '',
            'VAPID_PUBLIC_KEY': '', 'AWS_EC2_METADATA_DISABLED': 'true'}
        with patch.dict(os.environ, env):
            cls.app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False})
        from identity_fixture import PersonSelectionClient
        cls.app.test_client_class = PersonSelectionClient
        limiter.enabled = False

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            cls.db.session.remove()
            cls.db.drop_all()
            cls.db.engine.dispose()
        cls.temp.cleanup()

    def test_candidate_capture_serializes_against_account_deletion(self):
        from sqlalchemy import text
        from sqlalchemy.exc import OperationalError
        from dkss_app.safety_identity import user_ids
        a = self.models.User.query.filter_by(company_code='A', username='reviewer').one()
        self.assertEqual(user_ids('A', ['reviewer']), [a.id])
        with self.db.engine.connect() as connection:
            with self.assertRaises(OperationalError) as caught:
                with connection.begin():
                    connection.execute(text("SET LOCAL lock_timeout = '200ms'"))
                    connection.execute(text('DELETE FROM "user" WHERE id = :id'), {'id': a.id})
            self.assertIn('lock timeout', str(caught.exception).lower())
        self.db.session.rollback()


if __name__ == '__main__':
    unittest.main(verbosity=2)
