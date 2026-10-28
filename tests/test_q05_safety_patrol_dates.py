"""Safety checklist links and their operation events use Tokyo calendar time."""
from datetime import datetime
import unittest
from unittest.mock import patch

import test_workflow_regressions as fixtures
from test_q05_inspection_dates import clock_at
from dkss_app import checklists


class SafetyPatrolDateTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = fixtures.WorkflowRegressionTests.setUp
    tearDown = fixtures.WorkflowRegressionTests.tearDown
    workflow_checklist = fixtures.WorkflowRegressionTests.workflow_checklist
    safety_edit_token = fixtures.WorkflowRegressionTests.safety_edit_token

    def prepare(self):
        self.m.db.session.add(self.m.Driver(company_code='TEST', employee_id='admin',
                                           name='架空対象', role='admin'))
        self.m.db.session.commit()
        return self.workflow_checklist(approvals=[])

    def form(self, linked=True):
        return dict(answer_0='架空の確認', target_type='user', target_user='admin',
                    patrol_link_0='1' if linked else '0')

    def test_new_linked_patrol_and_checklist_have_same_tokyo_day(self):
        checklist = self.prepare()
        for instant, day in (('2026-12-31T14:59:59+00:00', '2026-12-31'),
                             ('2026-12-31T15:00:00+00:00', '2027-01-01'),
                             ('2028-02-28T15:00:00+00:00', '2028-02-29'),
                             ('2028-02-29T15:00:00+00:00', '2028-03-01')):
            with self.subTest(instant=instant), patch.object(
                checklists._dkss_common, 'datetime', clock_at(instant)
            ):
                response = self.client.post(f'/safety/checklists/{checklist.id}/new', data=self.form())
                self.assertEqual(response.status_code, 302)
                record = self.m.ChecklistResult.query.order_by(self.m.ChecklistResult.id.desc()).first()
                patrol = self.m.PatrolResult.query.order_by(self.m.PatrolResult.id.desc()).first()
                self.assertEqual(record.checked_date[:10], day)
                self.assertEqual(patrol.date, day)

    def test_edit_new_patrol_and_event_use_operation_day_and_keep_original_check_date(self):
        checklist = self.prepare()
        with patch.object(checklists._dkss_common, 'datetime', clock_at('2026-12-31T14:50:00+00:00')):
            self.assertEqual(self.client.post(f'/safety/checklists/{checklist.id}/new',
                data=self.form(False)).status_code, 302)
        record = self.m.ChecklistResult.query.one()
        original = record.checked_date
        form = self.form()
        form['record_version'] = self.safety_edit_token(record)
        with patch.object(checklists._dkss_common, 'datetime', clock_at('2026-12-31T15:00:00+00:00')):
            self.assertEqual(self.client.post(f'/safety/checklist-results/{record.id}/edit',
                                             data=form).status_code, 302)
        self.m.db.session.refresh(record)
        self.assertEqual(record.checked_date, original)
        self.assertEqual(self.m.PatrolResult.query.one().date, '2027-01-01')
        self.assertEqual(self.m.ChecklistEvent.query.one().created_at, '2027-01-01 00:00:00')

    def test_edit_does_not_redate_or_duplicate_existing_patrol(self):
        checklist = self.prepare()
        with patch.object(checklists._dkss_common, 'datetime', clock_at('2026-12-31T14:50:00+00:00')):
            self.assertEqual(self.client.post(f'/safety/checklists/{checklist.id}/new',
                                             data=self.form()).status_code, 302)
        record = self.m.ChecklistResult.query.one()
        patrol = self.m.PatrolResult.query.one()
        original = (record.checked_date, patrol.date)
        form = self.form()
        form['record_version'] = self.safety_edit_token(record)
        with patch.object(checklists._dkss_common, 'datetime', clock_at('2026-12-31T15:00:00+00:00')):
            self.assertEqual(self.client.post(f'/safety/checklist-results/{record.id}/edit',
                                             data=form).status_code, 302)
        self.m.db.session.expire_all()
        self.assertEqual(self.m.PatrolResult.query.count(), 1)
        self.assertEqual((record.checked_date, patrol.date), original)


if __name__ == '__main__':
    unittest.main()
