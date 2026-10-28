"""Q05: actual vehicle inspection routes use one user-local business clock."""
from identity_fixture import identity_for
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import test_workflow_regressions as workflow
from dkss_app import checklists as module


class UTCServerClock(datetime):
    @classmethod
    def now(cls, tz=None):
        instant = datetime(2026, 12, 31, 15, 30, tzinfo=timezone.utc)
        return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)


class ChecklistBusinessDateTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = workflow.WorkflowRegressionTests.setUp
    tearDown = workflow.WorkflowRegressionTests.tearDown
    workflow_checklist = workflow.WorkflowRegressionTests.workflow_checklist

    def save_cases(self, route):
        for user_zone, expected in (('', '2027-01-01 00:30'),
                                    ('invalid/timezone', '2027-01-01 00:30'),
                                    ('Pacific/Honolulu', '2026-12-31 05:30')):
            for existing in (False, True):
                with self.subTest(route=route, timezone=user_zone, existing=existing):
                    self.m.User.query.filter_by(company_code='TEST', username='admin').one().timezone = user_zone
                    checklist = self.workflow_checklist('車両管理', [])
                    if existing:
                        self.m.db.session.add(self.m.VehicleChecklistResult(
                            company_code='TEST', checklist_id=checklist.id,
                            vehicle_record_id=self.vehicle.id, year='2026', month='10', day='23',
                            checked_date='2026-10-23 09:00', status='差し戻し',
                            answers_json='[]', approvals_json='[]'))
                        self.m.db.session.commit()
                    form = dict(vehicle_record_id=self.vehicle.id, year='2026', month='10',
                                day='23', item_no='0', value='確認済み', comment='架空の確認',
                                notify_users='admin', answer_0='確認済み')
                    with patch.object(module._dkss_common, 'datetime', UTCServerClock):
                        response = self.client.post(f'/vehicle/checklists/{checklist.id}/{route}', data=form)
                    self.assertEqual(response.status_code, 302)
                    row = self.m.VehicleChecklistResult.query.filter_by(checklist_id=checklist.id).one()
                    self.assertEqual(row.checked_date, expected)
                    self.assertEqual((row.year, row.month, row.day), ('2026', '10', '23'))
                    if existing:
                        event = self.m.ChecklistEvent.query.filter_by(result_type='vehicle', result_id=row.id).order_by(self.m.ChecklistEvent.id.desc()).first()
                        self.assertIsNotNone(event)
                        self.assertEqual(event.created_at, expected + ':00')

    def test_cell_save_new_and_existing(self):
        self.save_cases('save-one')

    def test_detail_save_new_and_existing(self):
        self.save_cases('save-detail')

    def test_completion_new_and_existing(self):
        self.save_cases('complete')

    def test_new_form_and_new_record_use_user_local_clock(self):
        checklist = self.workflow_checklist('車両管理', [])
        user = self.m.User.query.filter_by(company_code='TEST', username='admin').one()
        user.timezone = 'Pacific/Honolulu'
        self.m.db.session.commit()
        with self.m.app.test_request_context('/'):
            self.m.session.update(account_identity=identity_for('TEST', 'admin'), company_code='TEST', username='admin', role='admin')
            with patch.object(module._dkss_common, 'datetime', UTCServerClock), \
                 patch.object(module._dkss_common, 'render_template', side_effect=lambda template, **kw: kw):
                context = module.new_vehicle_checklist_result(checklist.id)
        self.assertEqual((context['now_year'], context['now_month'], context['now_day']), (2026, 12, 31))
        with patch.object(module._dkss_common, 'datetime', UTCServerClock):
            response = self.client.post(f'/vehicle/checklists/{checklist.id}/new', data={
                'vehicle_record_id': self.vehicle.id, 'year': '2026', 'month': '10', 'day': '23',
                'answer_0': '確認済み',
            })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.m.VehicleChecklistResult.query.one().checked_date, '2026-12-31 05:30')

    def test_calendar_defaults_follow_user_day_and_explicit_selection_is_preserved(self):
        checklist = self.workflow_checklist('車両管理', [])
        for zone, expected in (('', ('2027', '01', '01')),
                               ('Pacific/Honolulu', ('2026', '12', '31'))):
            with self.subTest(timezone=zone):
                self.m.User.query.filter_by(company_code='TEST', username='admin').one().timezone = zone
                self.m.db.session.commit()
                for query, selected in (('', expected),
                                        ('?year=2026&month=10&active_day=23', ('2026', '10', '23'))):
                    with self.m.app.test_request_context('/' + query):
                        self.m.session.update(account_identity=identity_for('TEST', 'admin'), company_code='TEST', username='admin', role='admin')
                        with patch.object(module._dkss_common, 'datetime', UTCServerClock), \
                             patch.object(module._dkss_common, 'render_template', side_effect=lambda template, **kw: kw):
                            context = module.vehicle_checklist_results(checklist.id)
                    self.assertEqual(tuple(str(context[k]) for k in ('year', 'month', 'active_day')), selected)

    def test_empty_selection_defaults_match_daily_monthly_and_yearly_grids(self):
        for frequency, display, expected in (('day', 'month', '01'),
                                              ('month', 'year', '01'),
                                              ('year', 'year', '2027')):
            checklist = self.workflow_checklist('車両管理', [])
            checklist.frequency_unit, checklist.display_type = frequency, display
            self.m.db.session.commit()
            for query in ('', '?active_day='):
                with self.subTest(frequency=frequency, query=query):
                    with self.m.app.test_request_context('/' + query):
                        self.m.session.update(account_identity=identity_for('TEST', 'admin'), company_code='TEST', username='admin', role='admin')
                        with patch.object(module._dkss_common, 'datetime', UTCServerClock), \
                             patch.object(module._dkss_common, 'render_template', side_effect=lambda template, **kw: kw):
                            context = module.vehicle_checklist_results(checklist.id)
                    self.assertEqual(str(context['active_day']), expected)
