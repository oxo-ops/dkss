"""Real HTTP error dispatch and rollback on synthetic, temporary SQLite only."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flask import current_app, jsonify
from sqlalchemy.exc import StatementError
from werkzeug.exceptions import TooManyRequests

from dkss_app import create_app, models
from dkss_app.extensions import db


class HTTPDiagnosticsTests(unittest.TestCase):
    private = {
        'parameter': 'Q09_SYNTHETIC_SQL_PARAMETER',
        'connection': 'postgresql://q09:Q09_SYNTHETIC_PASSWORD@invalid.example/db',
        'exception': 'Q09_SYNTHETIC_EXCEPTION_TEXT',
        'query': 'Q09_SYNTHETIC_QUERY_TOKEN',
        'path': 'Q09_SYNTHETIC_PRIVATE_PATH',
        'body': 'Q09_SYNTHETIC_REQUEST_BODY',
    }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='q09-http-')
        self.addCleanup(self.temp.cleanup)
        with patch.dict(os.environ, {
            'RENDER': '', 'DATABASE_URL': 'sqlite:///:memory:',
            'S3_BUCKET_NAME': '', 'AWS_EC2_METADATA_DISABLED': 'true',
            'OPENAI_API_KEY': '', 'SMTP_HOST': '',
            'DOCUMENT_IMPORT_WORKER_ENABLED': '0',
        }):
            self.app = create_app({
                'TESTING': True, 'SECRET_KEY': 'q09-synthetic-only',
                'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(Path(self.temp.name) / 'http.db'),
                'WTF_CSRF_ENABLED': False, 'RATELIMIT_ENABLED': False,
                'S3_BUCKET_NAME': '', 'MFA_ENABLED': False,
            })
        self.app.extensions['q09_http_failure'] = None

        def operation(**kwargs):
            failure = current_app.extensions['q09_http_failure']
            if isinstance(failure, TooManyRequests):
                raise failure
            company = models.Company.query.filter_by(company_code='Q09').one()
            company.company_name = 'pending change'
            db.session.flush()
            if failure == 'sqlite-integrity':
                db.session.add(models.Company(
                    company_code=self.private['parameter'], company_name=None))
                db.session.flush()  # Real IntegrityError, including a bound parameter.
            elif failure is not None:
                raise failure
            db.session.commit()
            return jsonify(ok=True)

        self.app.add_url_rule('/api/q09-http/<private_path>', 'q09_api', operation, methods=['POST'])
        self.app.add_url_rule('/q09-http', 'q09_text', operation, methods=['POST'])
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        self.addCleanup(self.close_database)
        db.create_all()
        db.session.add(models.Company(company_code='Q09', company_name='original', active=True))
        user = models.User(company_code='Q09', username='synthetic', role='admin',
                           password='unused', last_name='Synthetic',
                           password_changed_at='2026-10-29 10:00:00')
        db.session.add(user)
        db.session.commit()
        self.client = self.app.test_client()
        with self.client.session_transaction() as state:
            state.update(company_code='Q09', username=user.username, role=user.role,
                         account_identity=user.account_identity,
                         password_changed_at=user.password_changed_at)

    def close_database(self):
        db.session.remove()
        db.engine.dispose()

    def request(self, path=None, *, accept='application/json'):
        path = path or '/api/q09-http/' + self.private['path']
        response = self.client.post(path + '?token=' + self.private['query'],
                                    data={'password': self.private['body']},
                                    headers={'Accept': accept, 'Referer': 'http://localhost/q09-http'})
        self.addCleanup(response.close)
        return response

    def assert_rolled_back(self):
        db.session.expire_all()
        self.assertEqual(models.Company.query.filter_by(company_code='Q09').one().company_name, 'original')
        self.assertEqual(models.Company.query.count(), 1)

    def assert_safe_log(self, logs, error_type):
        output = '\n'.join(logs.output)
        for value in self.private.values():
            self.assertFalse(value in output, 'Synthetic secret/request data reached the operator log')
        self.assertIn('HTTP_UNEXPECTED_ERROR stage=request error_type=' + error_type, output)
        self.assertEqual(len(logs.records), 1)
        self.assertTrue(all(r.exc_info is None and not r.stack_info for r in logs.records))

    def test_real_sql_failure_redacts_parameters_rolls_back_and_allows_retry(self):
        self.app.extensions['q09_http_failure'] = 'sqlite-integrity'
        with self.assertLogs(self.app.logger, level='ERROR') as logs:
            response = self.request()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json, {'ok': False, 'message': '処理中にエラーが発生しました。'})
        self.assert_rolled_back()
        self.assert_safe_log(logs, 'IntegrityError')
        self.app.extensions['q09_http_failure'] = None
        with self.assertNoLogs(self.app.logger, level='ERROR'):
            retried = self.request()
        self.assertEqual((retried.status_code, retried.json), (200, {'ok': True}))
        self.assertEqual(models.Company.query.filter_by(company_code='Q09').one().company_name, 'pending change')
        self.assertEqual(models.Company.query.count(), 1)

    def test_api_sql_exception_omits_statement_connection_and_exception_chain(self):
        cause = ValueError(self.private['connection'])
        error = StatementError(self.private['exception'], 'SELECT ' + self.private['parameter'],
                               {'password': self.private['parameter']}, cause)
        error.__cause__ = cause
        self.app.extensions['q09_http_failure'] = error
        with self.assertLogs(self.app.logger, level='ERROR') as logs:
            response = self.request()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json, {'ok': False, 'message': '処理中にエラーが発生しました。'})
        self.assert_rolled_back()
        self.assert_safe_log(logs, 'StatementError')

    def test_html_failure_preserves_redirect_and_flash(self):
        self.app.extensions['q09_http_failure'] = RuntimeError(self.private['exception'])
        with self.assertLogs(self.app.logger, level='ERROR') as logs:
            response = self.request('/q09-http', accept='text/html')
        self.assertEqual((response.status_code, response.location), (302, '/q09-http'))
        with self.client.session_transaction() as state:
            self.assertIn(('error:', '処理中にエラーが発生しました。もう一度お試しください。'), state['_flashes'])
        self.assert_rolled_back()
        self.assert_safe_log(logs, 'RuntimeError')

    def test_non_html_failure_preserves_plain_500(self):
        self.app.extensions['q09_http_failure'] = ValueError(self.private['exception'])
        with self.assertLogs(self.app.logger, level='ERROR') as logs:
            response = self.request('/q09-http', accept='text/plain')
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_data(as_text=True), '処理中にエラーが発生しました。')
        self.assert_rolled_back()
        self.assert_safe_log(logs, 'ValueError')

    def import_failure(self, accept):
        self.app.extensions['q09_http_failure'] = RuntimeError(self.private['exception'])
        with patch.dict(self.app.view_functions, vehicle_document_import_confirm=self.app.view_functions['q09_text']), \
                self.assertLogs(self.app.logger, level='ERROR') as logs:
            response = self.request('/vehicle/data-import/q09-batch/confirm', accept=accept)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers['X-DKSS-Import-Recovery'], '1')
        self.assertEqual(response.headers['X-DKSS-Form-Errors'], '1')
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
        self.assert_rolled_back()
        self.assert_safe_log(logs, 'RuntimeError')
        return response

    def test_import_html_failure_preserves_review_and_back_guidance(self):
        response = self.import_failure('text/html')
        text = response.get_data(as_text=True)
        self.assertIn('/vehicle/data-import/q09-batch/preview', text)
        self.assertIn('元の取込画面へ戻る', text)
        self.assertIn('元の画面で受付・登録結果を確認してから再試行してください。', text)

    def test_import_json_failure_preserves_recovery_errors(self):
        response = self.import_failure('application/json')
        self.assertEqual(response.json, {'errors': [{'message':
            '処理を完了できませんでした。元の画面で受付・登録結果を確認してから再試行してください。', 'field': ''}]})

    def test_http_exception_api_preserves_status_and_retry_header(self):
        self.app.extensions['q09_http_failure'] = TooManyRequests(retry_after=7)
        with self.assertNoLogs(self.app.logger, level='ERROR'):
            response = self.request()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers['Retry-After'], '7')
        self.assert_rolled_back()

    def test_http_exception_import_preserves_recovery_and_retry_header(self):
        self.app.extensions['q09_http_failure'] = TooManyRequests(retry_after=7)
        with patch.dict(self.app.view_functions, vehicle_document_import_confirm=self.app.view_functions['q09_text']), \
                self.assertNoLogs(self.app.logger, level='ERROR'):
            response = self.request('/vehicle/data-import/q09-batch/confirm')
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers['Retry-After'], '7')
        self.assertEqual(response.headers['X-DKSS-Import-Recovery'], '1')
        self.assert_rolled_back()
