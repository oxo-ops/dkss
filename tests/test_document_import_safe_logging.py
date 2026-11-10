"""Real import handlers with synthetic files, mocked extraction and no database."""
from concurrent.futures import Future
import io
import json
import logging
from queue import Empty
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

from flask import Flask, jsonify, session
from sqlalchemy.exc import SQLAlchemyError
from dkss_app import vehicle_imports as imports

CANARY = 'SYNTHETIC_PRIVATE_IMPORT_CANARY'


class Capture(logging.StreamHandler):
    def __init__(self):
        self.output = io.StringIO()
        self.records = []
        super().__init__(self.output)

    def emit(self, record):
        self.records.append(record)
        super().emit(record)


class ImmediateExecutor:
    def __init__(self, **kwargs):
        self.shutdown = Mock()

    def submit(self, function, *args, **kwargs):
        result = Future()
        try:
            result.set_result(function(*args, **kwargs))
        except Exception as error:
            result.set_exception(error)
        return result


class EmptyUpdates:
    def put(self, value):
        pass

    def get(self, **kwargs):
        raise Empty()


class DocumentImportLoggingTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask('synthetic-import-test')
        self.app.secret_key = 'synthetic-only'
        self.capture = Capture()
        self.logger = logging.Logger('synthetic-import', logging.DEBUG)
        self.logger.addHandler(self.capture)
        self.db = MagicMock()
        self.drafts = [self.draft('one')]
        self.prepare = self.enterContext(patch.object(imports, 'prepare_vehicle_document_import', return_value=(self.drafts, [])))
        self.access = self.enterContext(patch.object(imports._dkss_access, 'require_master_admin', return_value=True))
        self.extract = Mock(return_value={'synthetic': True})
        self.factory = self.enterContext(patch.object(imports, 'vehicle_document_extractor', return_value=self.extract))
        self.preview = self.enterContext(patch.object(imports, 'apply_maintenance_invoice_preview', return_value={'records': [{}]}))
        self.suggest = self.enterContext(patch.object(imports, 'suggest_vehicle_document_type', return_value=None))
        self.identity = self.enterContext(patch.object(imports._dkss_import_owner, 'identity_for_actor', return_value='synthetic-owner'))
        self.enterContext(patch.object(imports._dkss_runtime, 'app', SimpleNamespace(logger=self.logger)))
        self.enterContext(patch.object(imports._dkss_common, 'db', self.db))
        self.enterContext(patch.object(imports._dkss_common, 'url_for', return_value='/synthetic-preview'))
        self.enterContext(patch.object(imports._dkss_http, 'return_form_errors', side_effect=lambda errors, status_code=400: (jsonify({'errors': errors}), status_code)))
        self.executor = ImmediateExecutor()
        self.pool = self.enterContext(patch('concurrent.futures.ThreadPoolExecutor', return_value=self.executor))
        self.enterContext(patch('queue.Queue', EmptyUpdates))

    def draft(self, name):
        return SimpleNamespace(id=name, batch_id='synthetic-batch', document_type='inspection',
            owner_identity='synthetic-owner', source_file=b'synthetic-content',
            source_filename=CANARY+'-'+name+'.pdf', preview_json='{}', status='new')

    def call_route(self, mode, headers=None):
        with self.app.test_request_context('/synthetic', method='POST', data={'document_type': 'inspection'}, headers=headers or {}):
            session.update(company_code='SYNTHETIC', username='synthetic-user')
            if mode == 'progress':
                response = imports.vehicle_data_import_progress()
                if not hasattr(response, 'get_data'):
                    response = self.app.make_response(response)
                events = [json.loads(line) for line in response.get_data(as_text=True).splitlines()]
                return response, events
            response = self.app.make_response(imports.vehicle_data_import())
            return response, response.get_json(silent=True)

    def assert_safe_log(self, mode, stage, category, code='unknown'):
        self.assertEqual(len(self.capture.records), 1)
        record = self.capture.records[0]
        self.assertEqual(record.getMessage(), 'DOCUMENT_IMPORT_FAILED mode=%s stage=%s error_type=%s error_code=%s' % (mode, stage, category, code))
        self.assertEqual(record.levelno, logging.ERROR)
        self.assertIsNone(record.exc_info)
        self.assertIsNone(record.stack_info)
        self.assertNotIn(CANARY, repr(record.__dict__))
        self.assertNotIn('Traceback', self.capture.output.getvalue())

    def extraction_failure(self, mode, error, category, code='unknown'):
        self.extract.side_effect = error
        response, body = self.call_route(mode)
        self.assert_safe_log(mode, 'extract', category, code)
        self.assertEqual(self.extract.call_count, 1)
        self.db.session.add_all.assert_not_called()
        self.db.session.commit.assert_not_called()
        self.db.session.rollback.assert_not_called()
        self.assertIn(CANARY+'-one.pdf', json.dumps(body))
        if mode == 'form':
            self.assertEqual(response.status_code, 503)
        else:
            self.assertEqual(response.status_code, 200)
            self.assertEqual([row['phase'] for row in body], ['accepted', 'reading', 'processed', 'error'])
            self.assertEqual(response.headers['Cache-Control'], 'no-store, no-transform')
            self.assertEqual(response.headers['X-Accel-Buffering'], 'no')
            self.pool.assert_called_once_with(max_workers=1)
            self.executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
        return body

    def test_form_known_network_failure_retains_safe_code_and_response(self):
        body = self.extraction_failure('form', RuntimeError('OPENAI_NETWORK_OR_TIMEOUT:'+CANARY), 'runtime', 'OPENAI_NETWORK_OR_TIMEOUT')
        self.assertIn('AIとの通信が中断、または時間切れになりました。', str(body))

    def test_progress_known_network_failure_retains_safe_code_and_response(self):
        body = self.extraction_failure('progress', RuntimeError('OPENAI_NETWORK_OR_TIMEOUT:'+CANARY), 'runtime', 'OPENAI_NETWORK_OR_TIMEOUT')
        self.assertIn('AIとの通信が中断、または時間切れになりました。', str(body))

    def test_form_unknown_failure_does_not_log_payload(self):
        self.extraction_failure('form', RuntimeError(CANARY), 'runtime')

    def test_progress_unknown_failure_does_not_log_payload(self):
        self.extraction_failure('progress', RuntimeError(CANARY), 'runtime')

    def test_form_invalid_pdf_is_safe(self):
        self.extraction_failure('form', ValueError('INVALID_INSPECTION_PDF:'+CANARY), 'input', 'INVALID_INSPECTION_PDF')

    def test_progress_invalid_pdf_is_safe(self):
        self.extraction_failure('progress', ValueError('INVALID_INSPECTION_PDF:'+CANARY), 'input', 'INVALID_INSPECTION_PDF')

    def test_exception_class_name_and_chained_exception_are_not_logged(self):
        error = type(CANARY, (RuntimeError,), {})(CANARY)
        error.__cause__ = ValueError(CANARY+'-inner')
        self.extraction_failure('form', error, 'runtime')

    def test_user_message_is_preserved_only_in_authorized_response(self):
        error = ValueError(CANARY)
        error.user_message = '合成利用者向け案内'
        body = self.extraction_failure('progress', error, 'input')
        self.assertIn(error.user_message, str(body))
        self.assertNotIn(error.user_message, self.capture.output.getvalue())

    def test_form_empty_extraction_preserves_no_records_result(self):
        self.preview.return_value = {'records': []}
        response, _ = self.call_route('form')
        self.assertEqual(response.status_code, 503)
        self.assert_safe_log('form', 'extract', 'input', 'OCR_NO_RECORDS')

    def test_progress_empty_extraction_preserves_no_records_result(self):
        self.preview.return_value = {'records': []}
        _, body = self.call_route('progress')
        self.assertEqual(body[-1]['phase'], 'error')
        self.assert_safe_log('progress', 'extract', 'input', 'OCR_NO_RECORDS')

    def test_form_owner_failure_rolls_back_without_logging_identity(self):
        self.identity.return_value = None
        response, _ = self.call_route('form')
        self.assertEqual(response.status_code, 503)
        self.db.session.rollback.assert_called_once_with()
        self.db.session.commit.assert_not_called()
        self.assert_safe_log('form', 'process', 'input')

    def test_form_database_failure_rolls_back_without_sql_parameters(self):
        self.db.session.commit.side_effect = SQLAlchemyError('INSERT '+CANARY)
        response, _ = self.call_route('form')
        self.assertEqual(response.status_code, 500)
        self.db.session.rollback.assert_called_once_with()
        self.db.session.commit.assert_called_once_with()
        self.assert_safe_log('form', 'persist', 'database')

    def test_progress_database_failure_rolls_back_without_sql_parameters(self):
        self.db.session.commit.side_effect = SQLAlchemyError('INSERT '+CANARY)
        _, body = self.call_route('progress')
        self.assertEqual(body[-1]['phase'], 'error')
        self.db.session.rollback.assert_called_once_with()
        self.db.session.commit.assert_called_once_with()
        self.assert_safe_log('progress', 'process', 'database')

    def test_progress_unexpected_failure_rolls_back_without_payload(self):
        self.extract.side_effect = OSError(CANARY)
        _, body = self.call_route('progress')
        self.assertEqual(body[-1]['phase'], 'error')
        self.db.session.rollback.assert_called_once_with()
        self.assert_safe_log('progress', 'process', 'unexpected')

    def test_progress_type_mismatch_still_exits_without_failure_logging(self):
        self.extract.side_effect = ValueError('NO_INSPECTION_FOUND')
        self.suggest.side_effect = [None, 'maintenance']
        _, body = self.call_route('progress')
        self.assertEqual(body[-1]['phase'], 'type_mismatch')
        self.assertEqual(body[-1]['document_type'], 'maintenance')
        self.assertFalse(self.capture.records)
        self.db.session.commit.assert_not_called()

    def test_partial_success_preserves_failure_names_and_commits_once(self):
        for mode in ('form', 'progress'):
            with self.subTest(mode=mode):
                self.capture.records.clear()
                self.db.reset_mock()
                self.drafts[:] = [self.draft('one'), self.draft('two')]
                self.extract.side_effect = [ValueError('INVALID_INSPECTION_PDF:'+CANARY), {}]
                response, body = self.call_route(mode)
                self.db.session.add_all.assert_called_once_with([self.drafts[1]])
                self.db.session.commit.assert_called_once_with()
                self.db.session.rollback.assert_not_called()
                self.assertIn(CANARY+'-one.pdf', self.drafts[1].preview_json)
                self.assert_safe_log(mode, 'extract', 'input', 'INVALID_INSPECTION_PDF')
                if mode == 'form':
                    self.assertEqual((response.status_code, response.location), (302, '/synthetic-preview'))
                else:
                    self.assertEqual(body[-1]['phase'], 'complete')

    def test_success_does_not_add_logs_or_change_commit(self):
        for mode in ('form', 'progress'):
            with self.subTest(mode=mode):
                self.db.reset_mock()
                self.call_route(mode)
                self.db.session.commit.assert_called_once_with()
                self.db.session.rollback.assert_not_called()
                self.assertFalse(self.capture.records)

    def test_validation_only_never_extracts_or_persists(self):
        response, body = self.call_route('form', {'X-DKSS-Validation-Only': '1'})
        self.assertEqual((response.status_code, body), (200, {'ok': True}))
        self.extract.assert_not_called()
        self.db.session.commit.assert_not_called()
        self.assertFalse(self.capture.records)

    def test_progress_close_rolls_back_and_does_not_log_generator_exit(self):
        with self.app.test_request_context('/synthetic', method='POST', data={'document_type': 'inspection'}):
            session.update(company_code='SYNTHETIC', username='synthetic-user')
            response = imports.vehicle_data_import_progress()
            self.assertEqual(json.loads(next(iter(response.response)))['phase'], 'accepted')
            response.close()
        self.db.session.rollback.assert_called_once_with()
        self.db.session.commit.assert_not_called()
        self.extract.assert_not_called()
        self.assertFalse(self.capture.records)


class ImportFailureMetadataTests(unittest.TestCase):
    def setUp(self):
        from dkss_app.import_failure_logging import log_document_import_failure
        self.log_failure = log_document_import_failure
        self.capture = Capture()
        self.logger = logging.Logger('synthetic-import-helper', logging.DEBUG)
        self.logger.addHandler(self.capture)

    def emit(self, **kwargs):
        values = dict(mode='form', stage='extract', error=RuntimeError(CANARY))
        values.update(kwargs)
        self.log_failure(self.logger, **values)
        record = self.capture.records[-1]
        self.assertIsNone(record.exc_info)
        self.assertIsNone(record.stack_info)
        self.assertNotIn(CANARY, repr(record.__dict__))
        return record.getMessage()

    def test_unknown_metadata_and_objects_are_not_formatted(self):
        class Unprintable:
            def __str__(self):
                raise AssertionError('must not format metadata')
        for value in (CANARY, [], {}, Unprintable(), None):
            with self.subTest(kind=type(value).__name__):
                self.assertEqual(self.emit(mode=value, stage=value, code=value),
                    'DOCUMENT_IMPORT_FAILED mode=unknown stage=unknown error_type=runtime error_code=unknown')

    def test_string_subclasses_do_not_supply_metadata(self):
        class UnsafeString(str):
            def __hash__(self):
                raise AssertionError('must not hash string subclass')
        self.assertEqual(self.emit(mode=UnsafeString('form'), stage=UnsafeString('extract'), code=UnsafeString('API_KEY_NOT_SET')),
            'DOCUMENT_IMPORT_FAILED mode=unknown stage=unknown error_type=runtime error_code=unknown')

    def test_exception_payload_is_never_formatted(self):
        class UnprintableError(RuntimeError):
            def __str__(self):
                raise AssertionError('must not format exception')
        self.assertIn('error_type=runtime error_code=unknown', self.emit(error=UnprintableError()))

    def test_known_codes_keep_only_exact_values(self):
        codes = ('API_KEY_NOT_SET', 'OPENAI_NETWORK_OR_TIMEOUT', 'NO_INVOICE_FOUND',
                 'NO_INSPECTION_FOUND', 'NO_DRIVING_REPORT_FOUND', 'INVALID_DRIVING_REPORT_PDF',
                 'INVALID_DRIVING_REPORT_EXTRACTION', 'INVALID_INSPECTION_PDF',
                 'INVALID_INSPECTION_EXTRACTION', 'OCR_NO_RECORDS', 'DOCUMENT_TOO_LARGE',
                 'CONVERTED_PDF_TOO_LARGE', 'IMAGE_TOO_LARGE', 'IMAGE_READ_FAILED',
                 'INVALID_SOURCE_PAGES', 'EXTRACTION_NOT_COMPLETED')
        for code in codes:
            with self.subTest(code=code):
                self.assertTrue(self.emit(code=code).endswith('error_code='+code))
                self.assertTrue(self.emit(code=code+':'+CANARY).endswith('error_code=unknown'))
                self.assertTrue(self.emit(code=code+'\n'+CANARY).endswith('error_code=unknown'))

    def test_unknown_exception_class_name_is_not_logged(self):
        error = type(CANARY, (Exception,), {})(CANARY)
        self.assertIn('error_type=unexpected', self.emit(error=error))

    def test_database_error_retains_only_category(self):
        self.assertIn('error_type=database', self.emit(error=SQLAlchemyError('SELECT '+CANARY)))
