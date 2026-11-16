import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('invite_runner', Path(__file__).parents[1] / 'tools/predeploy_company_invites.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.ca = tempfile.NamedTemporaryFile()
        self.sha = 'a' * 40
        self.env = {'RENDER_GIT_COMMIT': self.sha, 'DATABASE_URL': 'postgresql://synthetic:synthetic@' + runner.HOST + '/' + runner.DATABASE}

    def tearDown(self):
        self.ca.close()

    def test_tls_and_timeouts_pinned(self):
        self.env.update(PGHOST='wrong', PGSERVICE='wrong', PGOPTIONS='wrong')
        env = runner.guarded_environment(self.env, self.sha, self.ca.name)
        self.assertNotIn('PGHOST', env)
        self.assertNotIn('PGSERVICE', env)
        self.assertEqual(env['PGSSLMODE'], 'verify-full')
        self.assertIn('lock_timeout=5000', env['PGOPTIONS'])
        self.assertEqual(env['PGCONNECT_TIMEOUT'], '10')

    def test_reject_wrong_sha_and_database(self):
        for key, value in [('RENDER_GIT_COMMIT', 'b'*40), ('DATABASE_URL', 'postgresql://localhost/other')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                runner.guarded_environment(dict(self.env, **{key:value}), self.sha, self.ca.name)

    def test_reject_all_query_overrides(self):
        for suffix in ['?sslmode=require', '?host=localhost', '?options=bad', '?sslmode=verify-full&sslmode=disable', '?sslrootcert=bad']:
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                runner.guarded_environment(dict(self.env, DATABASE_URL=self.env['DATABASE_URL']+suffix), self.sha, self.ca.name)

    def test_parent_timeout_safe(self):
        with patch.object(runner, 'guarded_environment', return_value={}), patch.object(runner.subprocess, 'run', side_effect=subprocess.TimeoutExpired('secret-must-not-display',120)), patch('builtins.print') as output:
            self.assertEqual(runner.main(['--expected-sha', self.sha]), 11)
            output.assert_called_once_with('INVITE_MIGRATION_STOP_TIMEOUT_STATE_REQUIRES_CHECK')

    def test_parent_failure_stops(self):
        with patch.object(runner, 'guarded_environment', return_value={}), patch.object(runner.subprocess, 'run', return_value=subprocess.CompletedProcess([], 21)), patch('builtins.print') as output:
            self.assertEqual(runner.main(['--expected-sha', self.sha]), 13)
            output.assert_called_once_with('INVITE_MIGRATION_STOP_STATE_REQUIRES_CHECK')

    def test_parent_success_uses_no_raw_output(self):
        with patch.object(runner, 'guarded_environment', return_value={}), patch.object(runner.subprocess, 'run', return_value=subprocess.CompletedProcess([],0)) as execute, patch('builtins.print') as output:
            self.assertEqual(runner.main(['--expected-sha', self.sha]), 0)
            self.assertEqual(execute.call_args.kwargs['stdout'], subprocess.DEVNULL)
            self.assertEqual(execute.call_args.kwargs['timeout'], 120)
            output.assert_called_once_with('INVITE_MIGRATION_VERIFIED')

class SnapshotTests(unittest.TestCase):
    def test_legacy_migration_and_repeat_preserve_counts(self):
        from sqlalchemy import create_engine, text
        engine = create_engine('sqlite://')
        with engine.begin() as c:
            c.execute(text('CREATE TABLE company_registration_invite(id INTEGER PRIMARY KEY)'))
            c.execute(text('CREATE TABLE company_registration_application(id INTEGER PRIMARY KEY)'))
            c.execute(text('INSERT INTO company_registration_invite(id) VALUES (1), (2)'))
            c.execute(text('INSERT INTO company_registration_application(id) VALUES (1)'))
            before = runner.snapshot(c)
            c.execute(text("ALTER TABLE company_registration_invite ADD COLUMN purpose VARCHAR(20) NOT NULL DEFAULT 'legacy'"))
            after = runner.snapshot(c)
            self.assertFalse(before[0])
            self.assertTrue(after[0])
            self.assertEqual(before[1:], after[1:])
            self.assertEqual(after, runner.snapshot(c))

    def test_wrong_shape_and_missing_table_fail(self):
        from sqlalchemy import create_engine, text
        engine = create_engine('sqlite://')
        with engine.begin() as c:
            with self.assertRaises(ValueError):
                runner.snapshot(c)
            c.execute(text('CREATE TABLE company_registration_invite(id INTEGER, purpose VARCHAR(20))'))
            c.execute(text('CREATE TABLE company_registration_application(id INTEGER)'))
            with self.assertRaises(ValueError):
                runner.snapshot(c)

    def test_similar_or_expression_defaults_rejected(self):
        from sqlalchemy import create_engine, text
        for default in ["'notlegacy'", "'legacy-extra'", "('leg' || 'acy')"]:
            with self.subTest(default=default):
                engine = create_engine('sqlite://')
                with engine.begin() as c:
                    c.execute(text('CREATE TABLE company_registration_invite(id INTEGER, purpose VARCHAR(20) NOT NULL DEFAULT ' + default + ')'))
                    c.execute(text('CREATE TABLE company_registration_application(id INTEGER)'))
                    with self.assertRaises(ValueError):
                        runner.snapshot(c)
