"""Delete-error logging contract with synthetic exceptions and no storage IO."""
import ast
import io
import logging
import os
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError
from werkzeug.security import safe_join
from werkzeug.utils import secure_filename


class CaptureRecords(logging.StreamHandler):
    def __init__(self, stream):
        super().__init__(stream)
        self.records = []

    def emit(self, record):
        self.records.append(record)
        super().emit(record)


class StorageDeleteSafeLoggingTests(unittest.TestCase):
    def setUp(self):
        source_path = Path(__file__).resolve().parents[1] / 'dkss_app/storage.py'
        source = source_path.read_text(encoding='utf-8')
        node = next(n for n in ast.parse(source).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'delete_uploaded_file')
        self.output = io.StringIO()
        self.capture = CaptureRecords(self.output)
        self.logger = logging.Logger('synthetic-delete-contract', logging.DEBUG)
        self.logger.propagate = False
        self.logger.addHandler(self.capture)
        self.client = Mock()
        self.remove = Mock()
        self.isfile = Mock(return_value=True)
        self.forget = Mock()
        profile = ModuleType('dkss_app.profile_images')
        profile.forget = self.forget
        modules = patch.dict('sys.modules', {'dkss_app.profile_images': profile})
        modules.start()
        self.addCleanup(modules.stop)
        self.common = SimpleNamespace(
            session={'company_code': 'TEST'}, ClientError=ClientError,
            secure_filename=secure_filename, safe_join=safe_join,
            os=SimpleNamespace(path=SimpleNamespace(
                basename=os.path.basename, isfile=self.isfile), remove=self.remove),
        )
        self.app = SimpleNamespace(
            extensions={'dkss': {'s3_client': self.client}},
            config={'S3_BUCKET_NAME': 'synthetic-bucket', 'UPLOAD_FOLDER': '/synthetic/uploads'},
            logger=self.logger,
        )
        scope = {'__package__': 'dkss_app', '_dkss_common': self.common,
                 '_dkss_runtime': SimpleNamespace(app=self.app)}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source_path), 'exec'), scope)
        self.delete = scope['delete_uploaded_file']

    def assert_safe_failure(self, backend, error_type):
        self.assertEqual(len(self.capture.records), 1)
        record = self.capture.records[0]
        self.assertEqual(record.levelno, logging.ERROR)
        self.assertEqual(record.getMessage(),
                         f'UPLOAD_DELETE_FAILED backend={backend} error_type={error_type}')
        self.assertFalse(record.args)
        self.assertIsNone(record.exc_info)
        self.assertIsNone(record.stack_info)
        text = self.output.getvalue()
        for value in ('CANARY', 'synthetic-bucket', 'private-name.pdf',
                      'Traceback', 'https://', 'postgresql://', 'TEST/'):
            self.assertNotIn(value, text)

    def test_s3_failure_logs_no_provider_payload_url_path_or_traceback(self):
        error = ClientError({'Error': {
            'Code': 'AccessDenied',
            'Message': 'CANARY https://synthetic.invalid/x?token=CANARY postgresql://u:CANARY@host/db',
        }}, 'DeleteObject CANARY private-name.pdf')
        self.client.delete_object.side_effect = error
        self.assertIsNone(self.delete('private-name.pdf'))
        self.assert_safe_failure('s3', 'ClientError')
        self.client.delete_object.assert_called_once_with(
            Bucket='synthetic-bucket', Key='uploads/TEST/private-name.pdf')
        self.remove.assert_not_called()
        self.forget.assert_called_once_with('TEST', 'private-name.pdf')

    def test_local_failure_logs_no_os_message_filename_or_traceback(self):
        self.app.extensions['dkss']['s3_client'] = None
        self.remove.side_effect = PermissionError(13, 'CANARY private data', '/synthetic/CANARY/private-name.pdf')
        self.assertIsNone(self.delete('private-name.pdf'))
        self.assert_safe_failure('local', 'OSError')
        self.remove.assert_called_once_with('/synthetic/uploads/TEST/private-name.pdf')
        self.client.delete_object.assert_not_called()

    def test_s3_success_preserves_upload_and_manual_keys_without_logs(self):
        for folder, prefix in ((None, 'uploads'), ('static/manuals', 'manuals')):
            with self.subTest(folder=folder):
                self.client.reset_mock()
                self.assertIsNone(self.delete('x.pdf', folder=folder))
                self.client.delete_object.assert_called_once_with(
                    Bucket='synthetic-bucket', Key=f'{prefix}/TEST/x.pdf')
        self.remove.assert_not_called()
        self.assertEqual(self.capture.records, [])

    def test_local_success_preserves_upload_and_manual_paths_without_logs(self):
        self.app.extensions['dkss']['s3_client'] = None
        for folder, path in ((None, '/synthetic/uploads/TEST/x.pdf'),
                             ('static/manuals', 'static/manuals/TEST/x.pdf')):
            with self.subTest(folder=folder):
                self.remove.reset_mock()
                self.assertIsNone(self.delete('x.pdf', folder=folder))
                self.remove.assert_called_once_with(path)
        self.client.delete_object.assert_not_called()
        self.assertEqual(self.capture.records, [])

    def test_missing_company_or_filename_is_noop(self):
        self.delete('')
        self.common.session.clear()
        self.delete('x.pdf')
        self.forget.assert_not_called()
        self.client.delete_object.assert_not_called()
        self.remove.assert_not_called()
        self.assertEqual(self.capture.records, [])

    def test_invalid_local_company_is_still_rejected(self):
        self.app.extensions['dkss']['s3_client'] = None
        self.common.session['company_code'] = '../OTHER'
        self.delete('x.pdf')
        self.isfile.assert_not_called()
        self.remove.assert_not_called()
        self.assertEqual(self.capture.records, [])

    def test_missing_local_file_is_noop(self):
        self.app.extensions['dkss']['s3_client'] = None
        self.isfile.return_value = False
        self.delete('x.pdf')
        self.remove.assert_not_called()
        self.assertEqual(self.capture.records, [])

    def test_unexpected_s3_error_is_not_swallowed_or_retried(self):
        error = RuntimeError('synthetic unexpected error')
        self.client.delete_object.side_effect = error
        with self.assertRaises(RuntimeError) as raised:
            self.delete('x.pdf')
        self.assertIs(raised.exception, error)
        self.assertEqual(self.client.delete_object.call_count, 1)
        self.remove.assert_not_called()
        self.assertEqual(self.capture.records, [])

    def test_unexpected_local_error_is_not_swallowed_or_retried(self):
        self.app.extensions['dkss']['s3_client'] = None
        error = RuntimeError('synthetic unexpected error')
        self.remove.side_effect = error
        with self.assertRaises(RuntimeError) as raised:
            self.delete('x.pdf')
        self.assertIs(raised.exception, error)
        self.assertEqual(self.remove.call_count, 1)
        self.assertEqual(self.capture.records, [])

    def test_imported_module_preserves_the_same_safe_failure_contract(self):
        # Also exercise the module-bound function, not only the extracted AST.
        # Namespaces are replaced before invocation; no app or DB is initialized.
        from dkss_app import storage
        with patch.object(storage, '_dkss_common', self.common), \
                patch.object(storage, '_dkss_runtime', SimpleNamespace(app=self.app)):
            self.client.delete_object.side_effect = ClientError(
                {'Error': {'Code': 'AccessDenied', 'Message': 'CANARY'}}, 'DeleteObject')
            storage.delete_uploaded_file('private-name.pdf')
            self.assert_safe_failure('s3', 'ClientError')
            self.capture.records.clear()
            self.output.seek(0)
            self.output.truncate()
            self.app.extensions['dkss']['s3_client'] = None
            self.remove.side_effect = OSError('CANARY')
            storage.delete_uploaded_file('private-name.pdf')
            self.assert_safe_failure('local', 'OSError')


if __name__ == '__main__':
    unittest.main()
