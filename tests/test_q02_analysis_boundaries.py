"""Analysis reads and writes retain company, vehicle and current-account boundaries."""
import unittest
from unittest.mock import patch
from test_workflow_regressions import WorkflowRegressionTests as Fixture
from test_analysis_result_consistency import AnalysisResultConsistencyTests as AnalysisFixture


class Q02AnalysisBoundaryTests(unittest.TestCase):
    setUpClass = classmethod(Fixture.setUpClass.__func__)
    tearDownClass = classmethod(Fixture.tearDownClass.__func__)
    tearDown = Fixture.tearDown
    fixture_set_up = Fixture.setUp
    payload = AnalysisFixture.payload
    saved_result = AnalysisFixture.saved_result

    def setUp(self):
        self.fixture_set_up()
        m = self.m
        self.stamp = m.User.query.filter_by(company_code='TEST', username='admin').one().password_changed_at
        m.db.session.add(m.Company(company_code='OTHER', company_name='Synthetic', active=True))
        for company, username, role in [('TEST','reader','user'), ('OTHER','admin','admin')]:
            m.db.session.add(m.User(company_code=company, username=username, role=role,
                password='unused', last_name='Synthetic', password_changed_at=self.stamp))
        self.other_vehicle = m.Vehicle(company_code='TEST', chassis_number='SYNTHETIC-SECOND')
        self.foreign_vehicle = m.Vehicle(company_code='OTHER', chassis_number='SYNTHETIC-FOREIGN')
        m.db.session.add_all([self.other_vehicle, self.foreign_vehicle])
        m.db.session.flush()
        self.other_record = m.VehicleMaintenanceRecord(company_code='TEST', vehicle_record_id=self.other_vehicle.id,
            content='SECOND-VEHICLE-SECRET', entry_date='2026-10-21')
        self.foreign_record = m.VehicleMaintenanceRecord(company_code='OTHER', vehicle_record_id=self.foreign_vehicle.id,
            content='FOREIGN-COMPANY-SECRET', entry_date='2026-10-21')
        m.db.session.add_all([self.other_record, self.foreign_record])
        m.db.session.commit()
        self.record, self.state, self.body = self.saved_result()

    def request(self, method, path, **kwargs):
        response = self.client.open(path, method=method, **kwargs)
        self.addCleanup(response.close)
        return response

    def actor(self, company='TEST', username='admin', role='admin'):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(company_code=company, username=username, role=role, password_changed_at=self.stamp)

    def url(self, suffix, vehicle=None):
        return f'/vehicle/karte/{(vehicle or self.vehicle).id}/analysis/{suffix}'

    def evaluation_body(self, **extra):
        return dict(proposal_id=self.body['proposal_id'], proposal_revision=self.body['proposal_revision'],
                    verdict='appropriate', comment='Synthetic evaluation', **extra)

    def snapshot(self):
        self.m.db.session.expire_all()
        m = self.m
        return ([(r.id, r.company_code, r.vehicle_record_id, r.status, r.created_by, r.comment, r.snapshot_json)
                 for r in m.VehicleAnalysisFeedback.query.order_by(m.VehicleAnalysisFeedback.id).all()],
                [(r.id, r.company_code, r.vehicle_record_id, r.verdict, r.created_by, r.comment, r.snapshot_json)
                 for r in m.VehicleAnalysisEvaluation.query.order_by(m.VehicleAnalysisEvaluation.id).all()],
                [(r.id, r.status, r.result_json) for r in m.VehicleKarteAnalysis.query.order_by(m.VehicleKarteAnalysis.id).all()],
                m.AuditLog.query.count(), m.VehicleMaintenanceRecord.query.count())

    def assert_all_denied(self, expected, vehicle=None):
        before = self.snapshot()
        for method, suffix, body in [('GET','result',None), ('POST','feedback',self.body),
                                     ('POST','evaluation',self.evaluation_body())]:
            with self.subTest(suffix=suffix):
                response = self.request(method, self.url(suffix, vehicle), **({'json':body} if body else {}))
                self.assertEqual(response.status_code, expected)
                self.assertEqual(self.snapshot(), before)

    def test_own_result_excludes_other_vehicle_and_company_secrets(self):
        with patch.object(self.m, 'analyze_vehicle_karte') as ai:
            response = self.request('GET', self.url('result'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['has_result'])
        self.assertNotIn('SECOND-VEHICLE-SECRET', response.get_data(as_text=True))
        self.assertNotIn('FOREIGN-COMPANY-SECRET', response.get_data(as_text=True))
        ai.assert_not_called()

    def test_general_user_can_record_feedback_and_evaluation_with_server_identity(self):
        self.actor(username='reader', role='user')
        forged = dict(company_code='OTHER', vehicle_record_id=self.foreign_vehicle.id, created_by='forged-admin')
        self.assertEqual(self.request('POST', self.url('feedback'), json=dict(self.body, **forged)).status_code, 200)
        self.assertEqual(self.request('POST', self.url('evaluation'), json=self.evaluation_body(**forged)).status_code, 200)
        for row in (self.m.VehicleAnalysisFeedback.query.one(), self.m.VehicleAnalysisEvaluation.query.one()):
            self.assertEqual((row.company_code, row.vehicle_record_id, row.created_by), ('TEST', self.vehicle.id, 'reader'))

    def test_foreign_vehicle_id_cannot_read_or_write(self):
        self.assert_all_denied(404, self.foreign_vehicle)

    def test_other_company_same_username_cannot_read_or_write_our_vehicle(self):
        self.actor(company='OTHER')
        self.assert_all_denied(404)

    def test_deleted_vehicle_cannot_read_or_write(self):
        self.vehicle.deleted = True
        self.m.db.session.commit()
        self.assert_all_denied(404)

    def test_deleted_vehicle_analysis_page_is_denied_before_loading_summary(self):
        from dkss_app import analysis
        self.vehicle.deleted = True
        self.m.db.session.commit()
        for role in ('admin', 'user'):
            with self.subTest(role=role):
                self.m.User.query.filter_by(company_code='TEST', username='admin').one().role = role
                self.m.db.session.commit()
                self.actor(role=role)
                before = self.snapshot()
                with patch.object(analysis, 'build_vehicle_karte_analysis_summary',
                        wraps=analysis.build_vehicle_karte_analysis_summary) as summary, patch.object(
                        self.m, 'analyze_vehicle_karte') as ai:
                    response = self.request('GET', f'/vehicle/karte/{self.vehicle.id}/analysis')
                self.assertEqual(response.status_code, 404)
                self.assertNotIn('ブレーキ調整', response.get_data(as_text=True))
                summary.assert_not_called()
                ai.assert_not_called()
                self.assertEqual(self.snapshot(), before)

    def test_current_vehicle_analysis_page_remains_readable_by_general_user(self):
        for role in ('admin', 'user'):
            with self.subTest(role=role):
                self.m.User.query.filter_by(company_code='TEST', username='admin').one().role = role
                self.m.db.session.commit()
                self.actor(role=role)
                with patch.object(self.m, 'analyze_vehicle_karte') as ai:
                    response = self.request('GET', f'/vehicle/karte/{self.vehicle.id}/analysis')
                self.assertEqual(response.status_code, 200)
                ai.assert_not_called()

    def test_analysis_page_does_not_expose_legacy_synchronous_post(self):
        with patch.object(self.m, 'analyze_vehicle_karte') as ai:
            response = self.request('POST', f'/vehicle/karte/{self.vehicle.id}/analysis')
        self.assertEqual(response.status_code, 405)
        ai.assert_not_called()

    def test_locked_account_cannot_use_open_analysis_page(self):
        self.m.User.query.filter_by(company_code='TEST', username='admin').one().login_locked = True
        self.m.db.session.commit()
        self.assert_all_denied(302)

    def test_deleted_account_cannot_use_open_analysis_page(self):
        self.m.db.session.delete(self.m.User.query.filter_by(company_code='TEST', username='admin').one())
        self.m.db.session.commit()
        self.assert_all_denied(302)

    def test_inactive_company_cannot_use_open_analysis_page(self):
        self.m.Company.query.filter_by(company_code='TEST').one().active = False
        self.m.db.session.commit()
        self.assert_all_denied(302)

    def test_feedback_rejects_other_vehicle_and_foreign_maintenance_links(self):
        before = self.snapshot()
        for record in (self.other_record, self.foreign_record):
            with self.subTest(record=record.id):
                response = self.request('POST', self.url('feedback'), json=dict(self.body, maintenance_record_id=record.id))
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.snapshot(), before)
        response = self.request('POST', self.url('feedback'), json=dict(self.body, maintenance_record_id=self.record.id))
        self.assertEqual(response.status_code, 200)

    def test_changed_proposal_revision_cannot_save_feedback_or_evaluation(self):
        before = self.snapshot()
        for suffix, body in [('feedback', dict(self.body, proposal_revision='0'*64)),
                             ('evaluation', dict(self.evaluation_body(), proposal_revision='0'*64))]:
            self.assertEqual(self.request('POST', self.url(suffix), json=body).status_code, 409)
            self.assertEqual(self.snapshot(), before)

    def test_replayed_feedback_and_evaluation_do_not_duplicate_records(self):
        for suffix, body in [('feedback', self.body), ('evaluation', self.evaluation_body())]:
            self.assertEqual(self.request('POST', self.url(suffix), json=body).status_code, 200)
            before = self.snapshot()
            # Feedback is itself a new analysis input; its replay needs a fresh analysis.
            expected = 409 if suffix == 'feedback' else 200
            self.assertEqual(self.request('POST', self.url(suffix), json=body).status_code, expected)
            self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.m.VehicleAnalysisFeedback.query.count(), 1)
        self.assertEqual(self.m.VehicleAnalysisEvaluation.query.count(), 1)

    def test_feedback_and_evaluation_require_csrf_without_writes(self):
        before = self.snapshot()
        self.m.app.config['WTF_CSRF_ENABLED'] = True
        try:
            for suffix, body in [('feedback', self.body), ('evaluation', self.evaluation_body())]:
                self.assertEqual(self.request('POST', self.url(suffix), json=body).status_code, 400)
                self.assertEqual(self.snapshot(), before)
        finally:
            self.m.app.config['WTF_CSRF_ENABLED'] = False


del Fixture, AnalysisFixture

if __name__ == '__main__':
    unittest.main(verbosity=2)
