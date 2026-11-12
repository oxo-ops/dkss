"""Reflection ownership through real Flask routes and disposable SQLite only."""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flask import request, session
from sqlalchemy import event, update
from sqlalchemy.engine import Engine
from werkzeug.exceptions import Forbidden

import test_driving_workspace as workspace
import test_workflow_regressions as workflow
from driving_report_data import payload, version
from driving_report_reflection import stamp, validate_result
from dkss_app.models import DrivingReportReflection, User


class ReflectionIdentityTests(unittest.TestCase):
    # Reuse existing representative company, office, report and signed-session data.
    setUp = workspace.WorkspaceTests.setUp
    tearDown = workflow.WorkflowRegressionTests.tearDown
    save = workspace.WorkspaceTests.save
    render = workspace.WorkspaceTests.render
    endpoint = '/safety/driving-reports/reflection?period=all'

    @classmethod
    def setUpClass(cls):
        cls.resources = ExitStack()
        cls.addClassCleanup(cls.resources.close)
        cls.temp = cls.resources.enter_context(tempfile.TemporaryDirectory(prefix='reflection-identity-'))
        database = Path(cls.temp) / 'test.db'
        cls.resources.enter_context(patch.dict(os.environ, {
            'SECRET_KEY': 'reflection-isolated-test-key',
            'DATABASE_URL': 'sqlite:///' + str(database),
            'MFA_ENABLED': 'false', 'RENDER': '',
            'RATELIMIT_STORAGE_URI': 'memory://',
            'AWS_EC2_METADATA_DISABLED': 'true',
            'OPENAI_API_KEY': '', 'SMTP_HOST': '', 'S3_BUCKET_NAME': '',
            'VAPID_PRIVATE_KEY': '', 'VAPID_PUBLIC_KEY': '',
            'DOCUMENT_IMPORT_WORKER_ENABLED': '0',
        }, clear=True))
        # Fail closed even if application code accidentally reaches an integration.
        for target in ('socket.socket.connect', 'socket.socket.connect_ex',
                       'socket.create_connection', 'urllib.request.urlopen',
                       'smtplib.SMTP', 'smtplib.SMTP_SSL', 'boto3.client'):
            cls.resources.enter_context(patch(target, side_effect=AssertionError('External I/O forbidden')))

        def restrict_database(dialect, connection_record, args, kwargs):
            if dialect.name != 'sqlite' or not args or Path(args[0]).resolve() != database.resolve():
                raise AssertionError('Only the explicitly created fixture database is permitted')
        event.listen(Engine, 'do_connect', restrict_database)
        cls.resources.callback(event.remove, Engine, 'do_connect', restrict_database)

        from dkss_app import create_app
        from application_fixture import ApplicationFixture
        from driving_report_reflection import register_reflections

        def capture_registration(app, db, prepare, history):
            service = register_reflections(app, db, prepare, history)
            cls.reflection_service = service
            cls.prepare = staticmethod(prepare)
            cls.history = staticmethod(history)
            return service

        with patch('driving_report_management.register_reflections', side_effect=capture_registration):
            cls.m = ApplicationFixture(create_app())
        cls.m.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        cls.m.limiter.enabled = False
        cls.executor = cls.m.app.extensions['driving_reflection_executor']

    @classmethod
    def tearDownClass(cls):
        cls.executor.shutdown(wait=True)
        with cls.m.app.app_context():
            cls.m.db.session.remove()
            cls.m.db.engine.dispose()

    def claims(self):
        with self.client.session_transaction() as current:
            return dict(current)

    def context(self):
        with self.m.app.test_request_context(self.endpoint):
            session.update(self.claims())
            rows, previous, _, _, filters, board, facts = self.prepare(request.args)
            key, document = self.reflection_service['context'](rows, previous, filters, board, facts)
            return key, document, (rows, previous, filters, board, facts)

    def free_get(self):
        with patch('driving_report_reflection.generate', side_effect=AssertionError('GET must not generate')) as generate, \
                patch.object(self.executor, 'submit', side_effect=AssertionError('GET must not queue')) as submit:
            response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        generate.assert_not_called()
        submit.assert_not_called()
        return response.json

    def snapshot(self):
        self.m.db.session.expire_all()
        return [(row.id, row.company_code, row.cache_key, row.status, row.result_json,
                 row.created_at, row.updated_at)
                for row in DrivingReportReflection.query.order_by(DrivingReportReflection.id).all()]

    def complete_current(self):
        before = self.free_get()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-not-a-real-key'}), \
                patch.object(self.executor, 'submit') as submit:
            response = self.client.post(self.endpoint, data={'period': 'all', 'input_key': before['key']})
        self.assertEqual(response.status_code, 202)
        submit.assert_called_once()
        work, company, key, document = submit.call_args.args
        first = document['evidence'][0]
        with patch('driving_report_reflection.generate', return_value={
                'items': [{'evidence_id': first['id'], 'action': first['allowed_actions'][0]}]}) as generate:
            work(company, key, document)
        generate.assert_called_once_with(document)
        completed = self.free_get()
        self.assertEqual(completed['status'], 'completed')
        self.assertTrue(completed['items'])
        return key, document

    def recreate_account(self):
        user = User.query.filter_by(company_code='TEST', username='admin').one()
        old_identity = user.account_identity
        values = {field: getattr(user, field) for field in (
            'id', 'company_code', 'username', 'role', 'password', 'password_changed_at',
            'last_name', 'first_name', 'office')}
        self.m.db.session.delete(user)
        self.m.db.session.commit()
        replacement = User(**values)
        self.m.db.session.add(replacement)
        self.m.db.session.commit()
        self.assertEqual(replacement.id, values['id'])
        self.assertEqual(replacement.username, values['username'])
        self.assertNotEqual(replacement.account_identity, old_identity)
        with self.client.session_transaction() as current:
            current['account_identity'] = replacement.account_identity
        return old_identity

    def change_report(self):
        values = payload(self.a)
        values['distance'] = '25'
        self.a.details_json = json.dumps(values)
        self.m.db.session.commit()

    def test_current_identity_reuses_completed_result_without_paid_get(self):
        key, _ = self.complete_current()
        saved = self.snapshot()
        for _ in range(2):
            state = self.free_get()
            self.assertEqual((state['key'], state['status']), (key, 'completed'))
        self.assertEqual(self.snapshot(), saved)

    def test_recreated_numeric_id_and_username_do_not_inherit_completed_cache(self):
        key, document = self.complete_current()
        saved = self.snapshot()
        self.recreate_account()
        new_key, new_document, _ = self.context()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-not-a-real-key'}):
            state = self.free_get()
        self.assertEqual(state['status'], 'new')
        self.assertNotEqual(new_key, key)
        self.assertNotEqual(new_document['refresh_scope'], document['refresh_scope'])
        self.assertEqual(state['items'], [])
        self.assertFalse(state['auto_refresh'])
        self.assertEqual(self.snapshot(), saved)

    def test_recreated_account_can_explicitly_generate_its_own_result(self):
        old_key, old_document = self.complete_current()
        saved = self.snapshot()
        self.recreate_account()
        new_key, new_document = self.complete_current()
        self.assertNotEqual(new_key, old_key)
        self.assertNotEqual(new_document['refresh_scope'], old_document['refresh_scope'])
        self.assertEqual(len(self.snapshot()), 2)
        self.assertEqual(self.snapshot()[:1], saved)
        self.change_report()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-not-a-real-key'}):
            self.assertTrue(self.free_get()['auto_refresh'])

    def test_refresh_enrollment_survives_data_change_but_not_account_recreation(self):
        old_key, _ = self.complete_current()
        saved = self.snapshot()
        self.change_report()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-not-a-real-key'}):
            own = self.free_get()
            self.assertNotEqual(own['key'], old_key)
            self.assertEqual(own['status'], 'new')
            self.assertTrue(own['auto_refresh'])
            self.recreate_account()
            replacement = self.free_get()
        self.assertEqual(replacement['status'], 'new')
        self.assertFalse(replacement['auto_refresh'])
        self.assertEqual(self.snapshot(), saved)

    def legacy_result(self):
        """Freeze the pre-UUID fingerprint format, with actual prepared app inputs."""
        _, current_document, (rows, previous, filters, board, facts) = self.context()
        user = User.query.filter_by(company_code='TEST', username='admin').one()
        scope = [user.company_code, user.id, user.role, user.username, dict(filters)]
        refresh_scope = hashlib.sha256(json.dumps(scope, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        document = deepcopy(current_document)
        document['refresh_scope'] = refresh_scope
        # This fixture deliberately has no reader bindings or maintenance history.
        from dkss_app import driving_access
        with self.m.app.test_request_context(self.endpoint):
            session.update(self.claims())
            self.assertEqual(driving_access.bindings(rows + previous), {})
            self.assertEqual(self.history(board, facts), [])
        self.assertFalse(board.get('personal_held_facts'))
        identity = scope + [sorted((row.id, version(row)) for row in rows + previous),
                            [], [], [], document, [], 'reflection-v3-personal-holds']
        key = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
        first = document['evidence'][0]
        result = validate_result({'items': [{'evidence_id': first['id'], 'action': first['allowed_actions'][0]}]}, document)
        result['refresh_scope'] = refresh_scope
        now = stamp()
        row = DrivingReportReflection(company_code='TEST', cache_key=key, status='completed',
            result_json=json.dumps(result, ensure_ascii=False, indent=2), created_at=now, updated_at=now)
        self.m.db.session.add(row)
        self.m.db.session.commit()
        return key

    def test_legacy_completed_json_is_preserved_without_assignment_or_refresh(self):
        legacy_key = self.legacy_result()
        saved = self.snapshot()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-not-a-real-key'}):
            # Even the current account cannot inherit a cache with no UUID proof.
            own = self.free_get()
            self.assertEqual((own['status'], own['items'], own['auto_refresh']), ('new', [], False))
            self.assertNotEqual(own['key'], legacy_key)
            self.change_report()
            self.assertFalse(self.free_get()['auto_refresh'])
            self.recreate_account()
            replacement = self.free_get()
            self.assertEqual((replacement['status'], replacement['items'], replacement['auto_refresh']), ('new', [], False))
            with patch.object(self.executor, 'submit', side_effect=AssertionError('Page GET must not queue')), \
                    patch('driving_report_reflection.generate', side_effect=AssertionError('Page GET must not generate')):
                response, context = self.render(self.base)
            self.assertFalse(context['reflection']['auto_refresh'])
            self.assertIn('data-auto-refresh="false"', response.get_data(as_text=True))
        self.assertEqual(self.snapshot(), saved)

    def test_stale_or_missing_session_is_rejected_by_existing_http_auth(self):
        self.complete_current()
        saved = self.snapshot()
        old_identity = self.recreate_account()
        good_claims = self.claims()
        for identity in (old_identity, None, ''):
            for method in ('GET', 'POST'):
                with self.subTest(identity=identity, method=method):
                    with self.client.session_transaction() as current:
                        current.clear()
                        current.update(good_claims)
                        if identity is None:
                            current.pop('account_identity', None)
                        else:
                            current['account_identity'] = identity
                    with patch.object(self.executor, 'submit', side_effect=AssertionError('Rejected request must not queue')):
                        response = self.client.open(self.endpoint, method=method)
                    self.assertEqual(response.status_code, 302)
                    self.assertEqual(response.location, '/login')
        self.assertEqual(self.snapshot(), saved)

    def test_context_defense_rejects_missing_or_stale_session_identity(self):
        # Defense in depth: HTTP auth above already rejects these requests.
        good_claims = self.claims()
        for identity in (None, '', 'different-account-generation'):
            with self.subTest(identity=identity), self.m.app.test_request_context(self.endpoint):
                session.update(good_claims)
                if identity is None:
                    session.pop('account_identity', None)
                else:
                    session['account_identity'] = identity
                with self.assertRaises(Forbidden):
                    self.reflection_service['context']([], [], {}, {}, [])

    def test_context_defense_rejects_missing_stored_identity(self):
        claims = self.claims()
        for identity in (None, ''):
            with self.subTest(identity=identity):
                # Simulate a legacy row only in this disposable DB, without changing
                # production immutability rules or inferring an owner from username.
                self.m.db.session.execute(update(User).where(User.username == 'admin').values(account_identity=identity))
                self.m.db.session.commit()
                with self.m.app.test_request_context(self.endpoint):
                    session.update(claims)
                    session['account_identity'] = identity
                    with self.assertRaises(Forbidden):
                        self.reflection_service['context']([], [], {}, {}, [])


if __name__ == '__main__':
    unittest.main()
