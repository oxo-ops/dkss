"""Normal saves must not turn completed manual work into future/undated work."""
import unittest
from test_q02_vehicle_boundaries import Q02VehicleBoundaryTests as Fixture

class CompletedMaintenanceDateTests(unittest.TestCase):
    setUpClass = classmethod(Fixture.setUpClass.__func__)
    tearDownClass = classmethod(Fixture.tearDownClass.__func__)
    setUp = Fixture.setUp
    tearDown = Fixture.tearDown
    request = Fixture.request
    payload = Fixture.payload
    version = Fixture.version
    edit_url = Fixture.edit_url
    snapshot = Fixture.snapshot

    def submit_date(self, date, action='draft'):
        return self.request('POST', self.edit_url(), data=self.payload(
            record_version=self.version(), total_cost='11111',
            completion_date=date, maintenance_action=action))

    def test_ordinary_save_rejects_future_completion_without_any_write(self):
        before = self.snapshot()
        response = self.submit_date('2099-01-01')
        self.assertEqual(response.status_code, 400)
        self.assertIn('整備完了日に未来の日付は指定できません', response.get_data(as_text=True))
        self.assertEqual(self.snapshot(), before)

    def test_ordinary_save_rejects_removing_completion_without_any_write(self):
        before = self.snapshot()
        response = self.submit_date('', action='save')
        self.assertEqual(response.status_code, 400)
        self.assertIn('完了済みの整備には完了日', response.get_data(as_text=True))
        self.assertEqual(self.snapshot(), before)

    def test_past_date_correction_keeps_completed_status(self):
        self.assertEqual(self.submit_date('2026-10-03').status_code, 302)
        self.db.session.refresh(self.ra)
        self.assertEqual((self.ra.status, self.ra.completion_date), ('完了', '2026-10-03'))

    def test_unchanged_legacy_unknown_date_does_not_require_invented_date(self):
        self.ra.completion_date = None
        self.db.session.commit()
        self.assertEqual(self.submit_date('').status_code, 302)
        self.db.session.refresh(self.ra)
        self.assertIsNone(self.ra.completion_date)

    def test_in_progress_work_can_keep_a_planned_future_date(self):
        self.ra.status = '整備中'
        self.db.session.commit()
        self.assertEqual(self.submit_date('2099-01-01').status_code, 302)
        self.db.session.refresh(self.ra)
        self.assertEqual(self.ra.status, '整備中')

    def test_invalid_date_returns_field_error_without_server_error(self):
        before = self.snapshot()
        self.assertEqual(self.submit_date('2026-02-31').status_code, 400)
        self.assertEqual(self.snapshot(), before)


del Fixture
