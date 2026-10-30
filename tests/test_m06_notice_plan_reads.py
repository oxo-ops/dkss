"""Bounded plan hints must agree with the original notification predicates."""
import inspect
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from inspection_alert_plan_reads import PlanReadHints
import test_m06_confirmed_periodic_notice as source


class NoticePlanReadTests(unittest.TestCase):
    setUpClass = classmethod(source.ConfirmedPeriodicNoticeTests.setUpClass.__func__)
    tearDownClass = classmethod(source.ConfirmedPeriodicNoticeTests.tearDownClass.__func__)
    setUp = source.ConfirmedPeriodicNoticeTests.setUp
    tearDown = source.ConfirmedPeriodicNoticeTests.tearDown
    confirmed_plan = source.ConfirmedPeriodicNoticeTests.confirmed_plan
    upload_inspection = source.ConfirmedPeriodicNoticeTests.upload_inspection
    inspection_form = source.ConfirmedPeriodicNoticeTests.inspection_form

    def plan(self, vehicle, kind, period='2026-10', **values):
        row = self.m.VehicleInspectionPlan(company_code=vehicle.company_code,
            vehicle_record_id=vehicle.id, kind=kind, period_key=period,
            planned_month='2026-10', status='planned', source='manual', version=1)
        for key, value in values.items():
            setattr(row, key, value)
        self.m.db.session.add(row)
        return row

    def vehicle_for(self, index, company='TEST'):
        row = self.m.Vehicle(company_code=company, chassis_number=f'HINT-{company}-{index}',
                             office=self.vehicle.office, inspection_expiry='2026-10-30')
        self.m.db.session.add(row)
        self.m.db.session.flush()
        return row

    def hints(self, pairs):
        return PlanReadHints(self.m.db, self.m.VehicleInspectionPlan,
                             self.m.app.extensions['inspection_plan_sync'], 'TEST', pairs)

    def test_vehicle_plan_query_count_is_bounded(self):
        from sqlalchemy import event
        for index in range(25):
            self.plan(self.vehicle_for(index + 10), 'vehicle_inspection')
        self.m.db.session.commit()
        queries = []
        def capture(conn, cursor, statement, params, context, many):
            if 'FROM vehicle_inspection_plan ' in statement and 'vehicle_inspection_plan.vehicle_record_id =' in statement:
                queries.append(statement)
        event.listen(self.m.db.engine, 'before_cursor_execute', capture)
        try:
            self.m.inspection_alerts.run('TEST', date(2026,10,22), True)
        finally:
            event.remove(self.m.db.engine, 'before_cursor_execute', capture)
        self.assertLessEqual(len(queries), 1)

    def test_resolved_kinds_months_and_company_match_old_predicates(self):
        known, record, draft = self.confirmed_plan()
        unknown_vehicle = self.vehicle_for(2)
        unknown = self.plan(unknown_vehicle, '12month')
        other = self.vehicle_for(3)
        self.plan(other, 'vehicle_inspection', reservation_date='2026-10-20')
        self.plan(other, 'periodic_12month', period='2026-11', planned_month='2026-11')
        self.m.db.session.add(self.m.Company(company_code='FOREIGN', company_name='Other', active=True))
        foreign = self.vehicle_for(4, 'FOREIGN')
        self.plan(foreign, 'vehicle_inspection')
        self.m.db.session.commit()
        pairs = [(v.id, mon) for v in (self.vehicle, unknown_vehicle, other, foreign)
                 for mon in ('2026-10', '2026-11')]
        hints = self.hints(pairs)
        resolve = self.m.app.extensions['inspection_plan_sync'].plan_kind
        for vehicle, mon in pairs:
            rows = self.m.VehicleInspectionPlan.query.filter_by(company_code='TEST',
                vehicle_record_id=vehicle).all()
            rows = [p for p in rows if p.status in ('planned', 'completed') and
                    (p.period_key == mon or p.planned_month == mon)]
            expected = (any(resolve(p) == 'vehicle_inspection' for p in rows),
                        any(p.kind == '12month' and resolve(p) == 'annual_unconfirmed' for p in rows))
            self.assertEqual(hints.get('TEST', vehicle, mon), expected)
        self.assertIsNone(hints.get('FOREIGN', foreign.id, '2026-10'))
        self.assertEqual((known.kind, unknown.kind, record.inspection_type), ('12month',)*3)

    def test_overfull_batch_and_key_limit_fall_back_without_partial_answers(self):
        for index in range(205):
            self.plan(self.vehicle, 'vehicle_inspection', period=f'{2000 + index//12:04}-{index%12+1:02}')
        self.m.db.session.commit()
        hints = self.hints([(self.vehicle.id, '2026-10')])
        self.assertEqual(hints.peak_rows, 201)
        self.assertIsNone(hints.get('TEST', self.vehicle.id, '2026-10'))
        # A relevant unknown row after the fast-path limit must still hold a notice.
        self.plan(self.vehicle, '12month')
        self.m.db.session.commit()
        process = inspect.getclosurevars(self.m.inspection_alerts.run).nonlocals['process_company']
        variables = inspect.getclosurevars(process).nonlocals
        token = variables['plan_read_hints'].set(self.hints([(self.vehicle.id, '2026-10')]))
        try:
            self.assertTrue(variables['legacy_expiry_dependency'](self.vehicle, '2026-10-30', date(2026,10,22)))
            self.assertTrue(variables['expiry_is_planned'](self.vehicle, '2026-10-30'))
        finally:
            variables['plan_read_hints'].reset(token)
        with patch.object(PlanReadHints, 'MAX_KEYS', 1):
            limited = self.hints([(self.vehicle.id, '2026-11'), (self.vehicle.id, '2026-12')])
        self.assertIsNone(limited.get('TEST', self.vehicle.id, '2026-12'))

    def test_no_stale_hint_after_unflushed_flush_bulk_or_transaction_end(self):
        plan, record, draft = self.confirmed_plan()
        process = inspect.getclosurevars(self.m.inspection_alerts.run).nonlocals['process_company']
        variables = inspect.getclosurevars(process).nonlocals
        context = variables['plan_read_hints']
        predicate = variables['expiry_is_planned']
        pairs = [(self.vehicle.id, '2026-10')]
        for mutation in ('unflushed', 'flush', 'bulk', 'commit', 'rollback'):
            with self.subTest(mutation=mutation):
                token = context.set(self.hints(pairs))
                try:
                    if mutation == 'bulk':
                        self.m.VehicleInspectionPlan.query.filter_by(id=plan.id).update({'kind': 'vehicle_inspection'})
                    elif mutation == 'rollback':
                        self.m.db.session.rollback()
                    else:
                        plan.kind = 'vehicle_inspection'
                        if mutation == 'flush': self.m.db.session.flush()
                        if mutation == 'commit': self.m.db.session.commit()
                    with self.m.db.session.no_autoflush:
                        self.assertEqual(predicate(self.vehicle, '2026-10-30'), mutation != 'rollback')
                    self.assertFalse(context.get().valid)
                finally:
                    context.reset(token)
                    self.m.db.session.rollback()
                    plan.kind = '12month'
                    self.m.db.session.commit()

    def rich_outcome(self, fallback):
        m = self.m
        plan, record, draft = self.confirmed_plan()
        unknown = self.vehicle_for(2)
        self.plan(unknown, '12month')
        same_day = self.vehicle_for(3)
        self.plan(same_day, 'periodic_12month', reservation_date='2026-10-20')
        # A nonempty same-month Record plus two independent executions on one day.
        values = {c.name: getattr(record, c.name) for c in record.__table__.columns if not c.primary_key}
        values.update(vehicle_record_id=same_day.id, inspection_type='periodic_12month',
                      inspection_date='2026-10-12', source_draft_id=draft.id, source_record_index=1)
        m.db.session.add(m.VehiclePeriodicInspectionRecord(**values))
        for kind in ('periodic_12month', 'vehicle_inspection'):
            m.db.session.add(m.inspection_plans.Execution(company_code='TEST', vehicle_record_id=same_day.id,
                kind=kind, performed_date='2026-10-12', created_by='admin', created_at='fixed'))
        m.db.session.add(m.inspection_plans.Execution(company_code='TEST', vehicle_record_id=unknown.id,
            kind='12month', performed_date='2026-10-13', created_by='admin', created_at='fixed'))
        other = self.vehicle_for(4)
        self.plan(other, 'vehicle_inspection', period='2026-11', planned_month='2026-11')
        held = m.Notification(company_code='TEST', target_username='admin', target_user='Admin',
            title='held', message='retain exact body', link='/vehicle/inspection-plans', read=False,
            workflow_context_json='{"action":"inspection_plan_alert"}', created_at='fixed')
        m.db.session.add(held); m.db.session.flush()
        m.db.session.add(m.inspection_alerts.ExpiryDelivery(company_code='TEST', vehicle_record_id=unknown.id,
            expiry_date='2026-10-30', notification_id=held.id, target_username='admin', office=unknown.office,
            phase='expiry_month', bucket=0, sent_day='2026-10-01'))
        m.db.session.commit()
        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None): return datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
        tables = ('vehicle_inspection_plan','vehicle_periodic_inspection_record','vehicle_inspection_execution')
        def facts(): return {t: [dict(r) for r in m.db.session.execute(m.db.text('SELECT * FROM '+t)).mappings()] for t in tables}
        before = facts()
        with patch('vehicle_inspection_alerts.datetime', FixedDatetime):
            with patch.object(PlanReadHints, 'get', return_value=None) if fallback else patch.object(PlanReadHints, 'MAX_KEYS', 2000):
                reports = [m.inspection_alerts.run('TEST', date(2026,10,22), True)]
                # Preserve real held and ended receipts over a later bucket and a new expiry.
                for receipt in m.inspection_alerts.Delivery.query.all():
                    receipt.ended_status = 'closed'
                    m.db.session.get(m.Notification, receipt.notification_id).read = True
                other.inspection_expiry = '2027-10-30'
                m.db.session.commit()
                reports.append(m.inspection_alerts.run('TEST', date(2026,10,29), True))
                reports.append(m.inspection_alerts.run('TEST', date(2027,9,1), True))
        self.assertEqual(facts(), before)
        states = {model.__tablename__: [dict(r) for r in m.db.session.execute(model.__table__.select()).mappings()]
                  for model in (m.Notification, m.inspection_alerts.Delivery, m.inspection_alerts.ExpiryDelivery)}
        # Separate isolated DBs deliberately generate different account UUIDs.
        # Assert the exact owner in each DB, then compare its stable fixture name.
        owner = m.User.query.filter_by(company_code='TEST', username='admin').one().account_identity
        for row in states[m.Notification.__tablename__]:
            self.assertEqual(row['owner_identity'], owner)
            row['owner_identity'] = 'TEST/admin'
        return reports, states

    def test_nonempty_actuals_and_notification_fields_equal_original_path(self):
        baseline = self.rich_outcome(True)
        self.tearDown()
        self.setUp()
        optimized = self.rich_outcome(False)
        self.assertEqual(optimized, baseline)
