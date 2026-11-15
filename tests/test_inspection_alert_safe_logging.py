"""Synthetic failure injection at inspection reminder HTTP/CLI boundaries."""
import io
import logging
import unittest
from unittest.mock import patch
from sqlalchemy.exc import DataError
from test_inspection_alerts import InspectionAlertTests as _Base

CANARY = 'SYNTHETIC_INSPECTION_PRIVATE_PAYLOAD'


class InspectionAlertSafeLogging(unittest.TestCase):
    setUpClass = classmethod(_Base.setUpClass.__func__)
    tearDownClass = classmethod(_Base.tearDownClass.__func__)
    setUp = _Base.setUp
    tearDown = _Base.tearDown

    def capture(self):
        self.output = io.StringIO()
        self.records = []
        handler = logging.StreamHandler(self.output)
        handler.addFilter(lambda record: self.records.append(record) or True)
        self.m.app.logger.addHandler(handler)
        self.addCleanup(self.m.app.logger.removeHandler, handler)

    def failure(self):
        return DataError('synthetic SQL ' + CANARY, {'private': CANARY}, ValueError(CANARY))

    def assert_safe_failure(self, mode):
        self.assertNotIn(CANARY, self.output.getvalue())
        self.assertNotIn('Traceback', self.output.getvalue())
        self.assertEqual(len(self.records), 1)
        self.assertEqual(self.records[0].getMessage(),
                         f'INSPECTION_ALERT_FAILED mode={mode} error_type=database')
        self.assertIsNone(self.records[0].exc_info)
        self.assertNotIn(CANARY, repr(self.records[0].__dict__))

    def test_http_poll_failure_preserves_response_and_logs_metadata_only(self):
        self.capture()
        with patch.object(self.m.db.session, 'commit', side_effect=self.failure()):
            response = self.client.get('/api/notifications/unread-count')
        self.assertEqual(response.status_code, 200)
        self.assert_safe_failure('poll')
        self.assertEqual(self.m.inspection_alerts.Run.query.count(), 0)
        self.assertEqual(self.m.Notification.query.count(), 0)

    def test_single_cli_failure_is_nonzero_without_raw_exception(self):
        self.capture()
        with patch.object(self.m.db.session, 'commit', side_effect=self.failure()):
            result = self.m.app.test_cli_runner().invoke(args=['inspection-plan-alerts'])
        self.assertNotEqual(result.exit_code, 0)
        self.assertNotIn(CANARY, result.output)
        self.assertNotIn(CANARY, str(result.exception))
        self.assertIn('点検通知の処理に失敗しました。', result.output)
        self.assert_safe_failure('command')
        self.assertEqual(self.m.inspection_alerts.Run.query.count(), 0)

    def test_watch_failure_retries_next_tick_without_external_delivery(self):
        self.capture()
        original_commit = self.m.db.session.commit
        count = 0
        def commit():
            nonlocal count
            count += 1
            if count == 1:
                raise self.failure()
            return original_commit()
        with patch.object(self.m.db.session, 'commit', side_effect=commit), \
             patch('vehicle_inspection_alerts.time.sleep', side_effect=[None, KeyboardInterrupt]), \
             patch.object(self.m, 'dispatch_external_notification') as external:
            result = self.m.app.test_cli_runner().invoke(args=['inspection-plan-alerts', '--watch'])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(count, 2)
        self.assert_safe_failure('watch')
        self.assertEqual(self.m.inspection_alerts.Run.query.count(), 1)
        external.assert_not_called()


del _Base


class InspectionAlertMetadata(unittest.TestCase):
    def test_arbitrary_type_name_payload_and_mode_never_enter_log_record(self):
        from dkss_app.inspection_alert_failure_logging import log_inspection_alert_failure
        from unittest.mock import Mock
        logger = Mock()
        unsafe_type = type(CANARY, (Exception,), {'__str__': lambda self: (_ for _ in ()).throw(AssertionError('must not stringify'))})
        error = unsafe_type(CANARY)
        log_inspection_alert_failure(logger, mode=CANARY, error=error)
        logger.error.assert_called_once_with('INSPECTION_ALERT_FAILED mode=%s error_type=%s', 'unknown', 'unexpected')

    def test_only_fixed_failure_categories_are_retained(self):
        from dkss_app.inspection_alert_failure_logging import log_inspection_alert_failure
        from unittest.mock import Mock
        for error, category in ((ValueError(CANARY), 'input'), (RuntimeError(CANARY), 'runtime'), (Exception(CANARY), 'unexpected')):
            logger = Mock()
            log_inspection_alert_failure(logger, mode='poll', error=error)
            logger.error.assert_called_once_with('INSPECTION_ALERT_FAILED mode=%s error_type=%s', 'poll', category)
