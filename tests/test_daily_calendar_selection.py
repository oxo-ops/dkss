"""Daily inspection calendar rejects nonexistent dates without mutating records."""
import unittest
from datetime import datetime
from unittest.mock import patch
from test_q02_daily_inspection_flow import Q02DailyInspectionFlowTests as Fixture
from dkss_app import checklists as module


class DailyCalendarSelectionTests(unittest.TestCase):
    setUpClass = classmethod(Fixture.setUpClass.__func__)
    tearDownClass = classmethod(Fixture.tearDownClass.__func__)
    setUp = Fixture.setUp
    tearDown = Fixture.tearDown
    login = Fixture.login
    request = Fixture.request
    snapshot = Fixture.snapshot
    begin = Fixture.begin
    save = Fixture.save
    complete = Fixture.complete
    state = Fixture.state
    decision_data = Fixture.decision_data
    decide = Fixture.decide

    def calendar(self, **query):
        self.request('GET', '/vehicle/checklists')
        checklist = self.models.Checklist.query.filter_by(company_code='A').one()
        vehicle = self.models.Vehicle.query.filter_by(company_code='A').one()
        return self.request('GET', f'/vehicle/checklists/{checklist.id}', query_string={
            'vehicle_record_id': vehicle.id, 'year': '2026', 'month': '02', **query})

    def test_explicit_invalid_day_is_rejected_without_writes(self):
        for day in ('31', '29', '00', '-1', 'abc'):
            with self.subTest(day=day):
                # Create the standard template before taking the read-only snapshot.
                self.request('GET', '/vehicle/checklists')
                before = self.snapshot()
                response = self.calendar(active_day=day)
                self.assertEqual(response.status_code, 400)
                body = response.get_data(as_text=True)
                self.assertTrue('点検日を選び直してください' in body)
                self.assertTrue('name="active_day" required' in body)
                self.assertTrue('value="28"' in body)
                self.assertFalse('value="31"' in body)
                self.assertFalse('operation-judgment' in body)
                self.assertEqual(self.snapshot(), before)

    def test_omitted_day_clamps_default_to_selected_month(self):
        with patch.object(module._dkss_checklist_common, 'get_user_local_now',
                          return_value=datetime(2026, 3, 31, 12)):
            response = self.calendar()
        self.assertEqual(response.status_code, 200)
        self.assertTrue('data-active-day="28"' in response.get_data(as_text=True))
        self.assertFalse('data-active-day="31"' in response.get_data(as_text=True))

    def test_valid_day_normalizes_and_leap_day_remains_valid(self):
        response = self.calendar(active_day='7')
        self.assertEqual(response.status_code, 200)
        self.assertTrue('data-active-day="07"' in response.get_data(as_text=True))
        response = self.calendar(year='2028', active_day='29')
        self.assertEqual(response.status_code, 200)
        self.assertTrue('data-active-day="29"' in response.get_data(as_text=True))

    def test_reselecting_day_recovers_same_vehicle_and_month(self):
        from html.parser import HTMLParser

        class RecoveryForm(HTMLParser):
            def __init__(self):
                super().__init__()
                self.action, self.fields = None, {}
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == 'form' and attrs.get('method') == 'get':
                    self.action = attrs.get('action')
                if tag == 'input' and attrs.get('type') == 'hidden':
                    self.fields[attrs.get('name')] = attrs.get('value')

        response = self.calendar(active_day='31')
        self.assertEqual(response.status_code, 400)
        form = RecoveryForm()
        form.feed(response.get_data(as_text=True))
        self.assertEqual(form.fields['year'], '2026')
        self.assertEqual(form.fields['month'], '02')
        self.assertEqual(form.fields['vehicle_record_id'],
                         str(self.models.Vehicle.query.filter_by(company_code='A').one().id))
        response = self.request('GET', form.action,
                                query_string={**form.fields, 'active_day': '28'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue('data-active-day="28"' in response.get_data(as_text=True))

    def test_valid_history_link_keeps_exact_approved_result_and_company_boundary(self):
        self.begin()
        self.decide()
        before = self.snapshot()
        response = self.calendar(month='10', active_day='23')
        self.assertEqual(response.status_code, 200)
        self.assertTrue('data-event-type="運行判断"' in response.get_data(as_text=True))
        self.assertEqual(self.snapshot(), before)
        self.login('admin', company='B')
        response = self.request('GET', f'/vehicle/checklists/{self.checklist.id}',
            query_string={'vehicle_record_id': self.row.vehicle_record_id,
                          'year': '2026', 'month': '10', 'active_day': '23'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse('data-event-type="運行判断"' in response.get_data(as_text=True))
        self.assertEqual(self.snapshot(), before)


del Fixture
