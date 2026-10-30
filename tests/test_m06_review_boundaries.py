"""Audit and completion evidence cannot cross company, vehicle or plan boundaries."""
import json
import unittest
from test_m06_review_regressions import ReviewRegressionTests as _Review


class ReviewBoundaryTests(unittest.TestCase):
    setUpClass = classmethod(_Review.setUpClass.__func__)
    tearDownClass = classmethod(_Review.tearDownClass.__func__)
    setUp = _Review.setUp
    tearDown = _Review.tearDown
    upload_inspection = _Review.upload_inspection
    inspection_form = _Review.inspection_form
    confirmed_plan = _Review.confirmed_plan

    def manual_plan(self, **extra):
        plan = self.m.VehicleInspectionPlan(company_code='TEST', vehicle_record_id=self.vehicle.id,
            kind='12month', period_key='2026-09', planned_month='2026-09', source='manual', version=1, **extra)
        self.m.db.session.add(plan)
        self.m.db.session.commit()
        return plan

    def test_completed_record_must_match_vehicle_company_and_completion_relation(self):
        _, record, _ = self.confirmed_plan()
        plan = self.manual_plan(status='completed', completed_record_id=record.id)
        self.assertEqual(self.m.inspection_plans.plan_kind(plan), '12month')
        for field, wrong in (('vehicle_record_id', self.vehicle.id + 99), ('company_code', 'FOREIGN')):
            original = getattr(plan, field)
            setattr(plan, field, wrong)
            self.assertEqual(self.m.inspection_plans.plan_kind(plan), 'annual_unconfirmed')
            setattr(plan, field, original)
        plan.reservation_date = '2026-09-20'
        self.assertEqual(self.m.inspection_plans.plan_kind(plan), 'annual_unconfirmed')

    def test_audit_requires_scoped_plan_and_record_not_just_kind_text(self):
        _, record, _ = self.confirmed_plan()
        plan = self.manual_plan(status='planned')
        snapshot = dict(id=plan.id, vehicle_record_id=self.vehicle.id, kind='12month', source_record_id=record.id)
        audit = self.m.VehicleInspectionPlanEvent(company_code='TEST', plan_id=plan.id, action='saved',
            created_by='admin', created_at='2026-10-22T00:00:00+00:00', detail_json=json.dumps({'before': snapshot}))
        self.m.db.session.add(audit)
        self.m.db.session.commit()
        self.assertEqual(self.m.inspection_plans.plan_kind(plan), '12month')
        for changes in ({'id': plan.id + 99}, {'vehicle_record_id': self.vehicle.id + 99},
                        {'id': True}, {'vehicle_record_id': True}, {'source_record_id': None},
                        {'source_record_id': True}, {'kind': 'ad_hoc'}, {'kind': []}, {'kind': {}}):
            audit.detail_json = json.dumps({'before': {**snapshot, **changes}})
            self.assertEqual(self.m.inspection_plans.plan_kind(plan), 'annual_unconfirmed')
        audit.detail_json = json.dumps({'before': snapshot})
        audit.company_code = 'FOREIGN'
        self.assertEqual(self.m.inspection_plans.plan_kind(plan), 'annual_unconfirmed')


del _Review
