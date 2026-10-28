"""Prevent destructive fixture setup from reaching non-Q10 databases."""
import os
import unittest
from unittest.mock import MagicMock, patch

from q10_postgres_support import PostgresFixture


class AcceptanceGuardTests(unittest.TestCase):
    def fixture(self):
        class Disposable(PostgresFixture, unittest.TestCase):
            pass
        self.addCleanup(Disposable.doClassCleanups)
        return Disposable

    def test_missing_required_postgres_does_not_fall_back(self):
        with patch.dict(os.environ, {'Q10_POSTGRES_TEST_URL':'', 'Q10_REQUIRE_POSTGRES':'1'}):
            with self.assertRaisesRegex(RuntimeError, 'no SQLite fallback'):
                self.fixture().setUpClass()

    def test_nonlocal_or_wrong_database_is_rejected_before_connect(self):
        for url in ('sqlite:///:memory:', 'postgresql://q10@example.invalid/dkss_q10_ci',
                    'postgresql://q10@127.0.0.1/other_database'):
            with self.subTest(url=url), patch.dict(os.environ, {'Q10_POSTGRES_TEST_URL':url}), patch('q10_postgres_support.create_engine') as factory:
                with self.assertRaisesRegex(RuntimeError, 'Only loopback'):
                    self.fixture().setUpClass()
                factory.assert_not_called()

    def test_unmarked_database_cannot_create_a_schema(self):
        engine = MagicMock()
        connection = engine.connect.return_value.__enter__.return_value
        connection.scalar.return_value = None
        with patch.dict(os.environ, {'Q10_POSTGRES_TEST_URL':'postgresql://q10@127.0.0.1/dkss_q10_ci'}), patch(
            'q10_postgres_support.create_engine', return_value=engine
        ):
            with self.assertRaisesRegex(RuntimeError, 'unmarked'):
                self.fixture().setUpClass()
        connection.execute.assert_not_called()
