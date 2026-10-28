"""Usage counts and audit writes share the caller's transaction."""
import unittest
from unittest.mock import patch

import test_workflow_regressions as fixtures
from dkss_app import audit


class UsageSummaryTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = fixtures.WorkflowRegressionTests.setUp
    tearDown = fixtures.WorkflowRegressionTests.tearDown

    def log(self, company='TEST'):
        with self.m.app.test_request_context('/'):
            audit.add_audit_log('login_success', company_code=company, username='admin')

    def summary(self, company='TEST'):
        return self.m.CompanyUsageSummary.query.filter_by(company_code=company).one()

    def test_initial_counts_keep_company_and_deleted_vehicle_rules(self):
        m = self.m
        m.db.session.add_all([
            m.Company(company_code='OTHER', company_name='Other'),
            m.User(company_code='OTHER', username='admin', password='unused', last_name='Other'),
            m.Vehicle(company_code='OTHER', chassis_number='OTHER'),
            m.Vehicle(company_code='TEST', chassis_number='DELETED', deleted=True),
            m.ChecklistResult(company_code='TEST', checklist_id=1),
            m.VehicleChecklistResult(company_code='TEST', checklist_id=2, vehicle_record_id=self.vehicle.id),
            m.ChecklistResult(company_code='OTHER', checklist_id=3),
        ])
        m.db.session.commit()
        audit.update_company_usage_summary('TEST')
        m.db.session.commit()
        row = self.summary()
        self.assertEqual((row.user_count, row.vehicle_count, row.checklist_result_count, row.login_count), (1, 1, 2, 0))
        self.assertTrue(row.last_used_at)
        self.assertTrue(row.updated_at)
        self.assertEqual(m.CompanyUsageSummary.query.count(), 1)

    def test_existing_counts_refresh_without_resetting_login_history(self):
        m = self.m
        m.db.session.add(m.CompanyUsageSummary(company_code='TEST', login_count=19,
            user_count=99, vehicle_count=98, checklist_result_count=97,
            last_used_at='2000-01-01 00:00:00', updated_at='2000-01-01 00:00:00'))
        m.db.session.commit()
        row = self.summary()
        original_id = row.id
        audit.update_company_usage_summary('TEST')
        m.db.session.commit()
        self.assertEqual((row.id, row.login_count, row.user_count, row.vehicle_count, row.checklist_result_count),
                         (original_id, 19, 1, 1, 0))
        self.assertNotEqual(row.updated_at, '2000-01-01 00:00:00')
        audit.update_company_usage_summary('TEST', increment_login=True)
        m.db.session.commit()
        self.assertEqual(row.login_count, 20)

    def test_new_row_and_audit_roll_back_then_retry_once(self):
        m = self.m
        self.log()
        audit.update_company_usage_summary('TEST', increment_login=True)
        m.db.session.flush()
        m.db.session.rollback()
        self.assertEqual(m.CompanyUsageSummary.query.count(), 0)
        self.assertEqual(m.AuditLog.query.count(), 0)
        self.log()
        audit.update_company_usage_summary('TEST', increment_login=True)
        m.db.session.commit()
        self.assertEqual(self.summary().login_count, 1)
        self.assertEqual(m.AuditLog.query.count(), 1)

    def test_new_row_without_other_writes_is_not_committed_early(self):
        audit.update_company_usage_summary('TEST', increment_login=True)
        self.m.db.session.flush()
        self.m.db.session.rollback()
        self.assertEqual(self.m.CompanyUsageSummary.query.count(), 0)

    def test_existing_row_and_pending_user_change_roll_back_then_retry(self):
        m = self.m
        m.db.session.add(m.CompanyUsageSummary(company_code='TEST', login_count=7,
            last_used_at='2000-01-01 00:00:00', updated_at='2000-01-01 00:00:00'))
        m.db.session.commit()
        user = m.User.query.filter_by(company_code='TEST', username='admin').one()
        original_name = user.last_name
        user.last_name = 'rollback-only'
        self.log()
        audit.update_company_usage_summary('TEST', increment_login=True)
        m.db.session.flush()
        m.db.session.rollback()
        self.assertEqual(user.last_name, original_name)
        self.assertEqual(self.summary().login_count, 7)
        self.assertEqual(self.summary().last_used_at, '2000-01-01 00:00:00')
        self.assertEqual(m.AuditLog.query.count(), 0)
        self.log()
        audit.update_company_usage_summary('TEST', increment_login=True)
        m.db.session.commit()
        self.assertEqual(self.summary().login_count, 8)
        self.assertEqual(m.AuditLog.query.count(), 1)

    def test_repeated_calls_in_one_transaction_preserve_increments(self):
        audit.update_company_usage_summary('TEST', increment_login=True)
        audit.update_company_usage_summary('TEST', increment_login=True)
        audit.update_company_usage_summary('TEST')
        self.m.db.session.commit()
        self.assertEqual(self.summary().login_count, 2)

    def test_empty_company_does_not_create_or_commit(self):
        self.log()
        for company in (None, ''):
            audit.update_company_usage_summary(company, increment_login=True)
        self.m.db.session.rollback()
        self.assertEqual(self.m.CompanyUsageSummary.query.count(), 0)
        self.assertEqual(self.m.AuditLog.query.count(), 0)

    def test_password_and_mfa_callers_increment_only_on_success(self):
        from dkss_app import auth
        from werkzeug.security import generate_password_hash
        m = self.m
        user = m.User.query.filter_by(company_code='TEST', username='admin').one()
        user.password = generate_password_hash('Usage-test-only-742!')
        user.email_address = 'usage@example.invalid'
        m.db.session.commit()
        for previous, mfa in enumerate((False, True)):
            with self.subTest(mfa=mfa), patch.dict(m.app.config, MFA_ENABLED=mfa):
                client = m.app.test_client()
                codes = []
                def delivery(user, code):
                    codes.append(code)
                    return True
                with patch.object(auth, 'send_mfa_code_email', side_effect=delivery):
                    response = client.post('/login', data=dict(company_code='TEST',
                        username='admin', password='Usage-test-only-742!'))
                    self.assertEqual(response.status_code, 302)
                    if mfa:
                        self.assertEqual(response.location, '/mfa')
                        m.db.session.expire_all()
                        self.assertEqual(self.summary().login_count, previous)
                        response = client.post('/mfa', data={'code': codes[-1]})
                        self.assertEqual(response.status_code, 302)
                m.db.session.expire_all()
                self.assertEqual(self.summary().login_count, previous + 1)
                self.assertEqual(m.AuditLog.query.filter_by(action='login_success', company_code='TEST').count(), previous + 1)

    def test_unrelated_insert_error_propagates_and_caller_can_roll_back(self):
        from sqlalchemy import event
        from sqlalchemy.exc import IntegrityError
        engine = self.m.db.engine
        def fail(conn, cursor, statement, parameters, context, many):
            if statement.lower().startswith('insert into company_usage_summary'):
                raise IntegrityError('synthetic non-duplicate failure', {}, RuntimeError('test only'))
        event.listen(engine, 'before_cursor_execute', fail)
        try:
            self.log()
            with self.assertRaises(IntegrityError):
                audit.update_company_usage_summary('TEST', increment_login=True)
                self.m.db.session.flush()
        finally:
            event.remove(engine, 'before_cursor_execute', fail)
            self.m.db.session.rollback()
        self.assertEqual(self.m.CompanyUsageSummary.query.count(), 0)
        self.assertEqual(self.m.AuditLog.query.count(), 0)
