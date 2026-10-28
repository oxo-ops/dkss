"""Rank legacy recorded dates chronologically without repairing stored values."""
from datetime import date
from types import SimpleNamespace
import unittest

import test_workflow_regressions as fixtures
from dkss_app.dashboard_repository import DashboardRepository
from dkss_app.dashboard_service import DashboardService


class LegacyRankingDateTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = fixtures.WorkflowRegressionTests.setUp
    tearDown = fixtures.WorkflowRegressionTests.tearDown

    def driver(self, ident, day, office='Tokyo', company='TEST'):
        self.m.db.session.add(self.m.Driver(company_code=company, employee_id=ident,
            name='架空' + ident, office=office, safe_start_date=day))

    def rank(self):
        scope = SimpleNamespace(company_code='TEST', office='Tokyo', office_missing=False,
                                today=date(2026, 12, 31))
        repository = DashboardRepository(scope)
        service = DashboardService(scope, repository, checklist_to_dict=None,
            patrol_to_dict=None, history=None, url_for=None)
        return service.ranking()

    def snapshot(self):
        return [(r.id, r.safe_start_date) for r in self.m.Driver.query.order_by(self.m.Driver.id)]

    def test_legacy_unpadded_date_keeps_its_value_and_ranks_by_calendar_day(self):
        self.driver('february', '2026-2-03')
        self.driver('october', '2026-10-01')
        self.driver('other-office', '2000-01-01', office='Osaka')
        self.driver('foreign', '2000-01-01', company='OTHER')
        self.m.db.session.commit()
        before = self.snapshot()
        rows = self.rank()
        self.assertEqual([row['employee_id'] for row in rows], ['february', 'october'])
        self.assertEqual(rows[0]['safe_start_date'], '2026-2-03')
        self.assertEqual(rows[0]['safe_days'], (date(2026, 12, 31) - date(2026, 2, 3)).days)
        self.assertEqual(self.snapshot(), before)

    def test_unknown_or_invalid_dates_do_not_consume_the_ten_valid_rank_slots(self):
        for index, day in enumerate((None, '', '0000-01-01', '1900-02-29', '2026-02') * 4):
            self.driver('unknown-' + str(index), day)
        for index in range(12):
            self.driver('valid-' + str(index), f'2026-03-{index + 1:02d}')
        self.m.db.session.commit()
        before = self.snapshot()
        rows = self.rank()
        self.assertEqual([row['employee_id'] for row in rows], ['valid-' + str(i) for i in range(10)])
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
