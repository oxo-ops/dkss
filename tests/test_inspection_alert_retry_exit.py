"""Synthetic retry reports must not mark an incomplete CLI tick successful."""
import json
import unittest
from unittest.mock import patch
from sqlalchemy.exc import IntegrityError, OperationalError
from test_inspection_alert_safe_logging import InspectionAlertSafeLogging as _Base, CANARY


class InspectionAlertRetryExit(unittest.TestCase):
    setUpClass = classmethod(_Base.setUpClass.__func__)
    tearDownClass = classmethod(_Base.tearDownClass.__func__)
    setUp = _Base.setUp
    tearDown = _Base.tearDown
    capture = _Base.capture
    assert_safe_failure = _Base.assert_safe_failure

    def test_single_cli_retry_is_nonzero_for_both_database_failure_types(self):
        self.capture()
        for failure_type in (OperationalError, IntegrityError):
            with self.subTest(failure_type=failure_type.__name__):
                self.records.clear()
                self.output.seek(0); self.output.truncate(0)
                failure = failure_type('synthetic SQL '+CANARY, {'private': CANARY}, ValueError(CANARY))
                with patch.object(self.m.db.session, 'commit', side_effect=failure):
                    result = self.m.app.test_cli_runner().invoke(args=['inspection-plan-alerts'])
                self.assertNotEqual(result.exit_code, 0)
                self.assertNotIn(CANARY, result.output)
                self.assertNotIn(CANARY, str(result.exception))
                self.assert_safe_failure('command')
                self.assertEqual(self.m.inspection_alerts.Run.query.count(), 0)

    def test_watch_retry_then_success_keeps_running_without_external_delivery(self):
        self.capture()
        original_commit = self.m.db.session.commit
        count = 0
        def commit():
            nonlocal count
            count += 1
            if count == 1:
                raise OperationalError('SQL '+CANARY, {}, ValueError(CANARY))
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

    def test_partial_company_success_is_preserved_but_command_fails(self):
        self.capture()
        self.vehicle.inspection_expiry = '2026-10-22'
        self.m.db.session.add(self.m.Company(company_code='ZZZ', company_name='Synthetic second company', active=True))
        self.m.db.session.commit()
        original_commit = self.m.db.session.commit
        count = 0
        def commit():
            nonlocal count
            count += 1
            if count == 2:
                raise OperationalError('SQL '+CANARY, {}, ValueError(CANARY))
            return original_commit()
        with patch.object(self.m.db.session, 'commit', side_effect=commit), \
             patch.object(self.m, 'dispatch_external_notification') as external:
            result = self.m.app.test_cli_runner().invoke(args=['inspection-plan-alerts'])
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(count, 2)
        self.assert_safe_failure('command')
        reports = json.loads(result.output.splitlines()[0])
        self.assertEqual(reports['TEST']['notifications'], 1)
        self.assertTrue(reports['ZZZ']['retry'])
        self.assertEqual(self.m.inspection_alerts.Run.query.one().company_code, 'TEST')
        self.assertEqual(self.m.Notification.query.one().company_code, 'TEST')
        self.assertEqual(self.m.inspection_alerts.ExpiryDelivery.query.count(), 1)
        external.assert_not_called()

    def test_rolled_back_expiry_report_contains_no_delivered_items(self):
        self.vehicle.inspection_expiry = '2026-10-22'
        self.m.db.session.commit()
        with patch.object(self.m.db.session, 'commit', side_effect=OperationalError('SQL '+CANARY, {}, ValueError(CANARY))):
            report = self.m.inspection_alerts.run('TEST', force=True)['TEST']
        self.assertTrue(report['retry'])
        self.assertEqual((report['notifications'], report['plans'], report['expiry_candidates']), (0, 0, 0))
        self.assertEqual(self.m.Notification.query.count(), 0)
        self.assertEqual(self.m.inspection_alerts.ExpiryDelivery.query.count(), 0)
        self.assertEqual(self.m.inspection_alerts.Run.query.count(), 0)


del _Base
