"""Actual normal reader on ownership-verified disposable PostgreSQL only."""
import unittest
from unittest.mock import patch
from sqlalchemy.exc import DBAPIError
import test_analysis_worker_postgres as fixture
from tools.quality.scoped_analysis.preflight import NormalReadScope, read_normal_input


class NormalPreflightPostgresTests(unittest.TestCase):
    setUpClass=classmethod(fixture.AnalysisWorkerPostgresTests.setUpClass.__func__)
    tearDownClass=classmethod(fixture.AnalysisWorkerPostgresTests.tearDownClass.__func__)
    tearDown=fixture.AnalysisWorkerPostgresTests.tearDown

    def setUp(self):
        fixture.AnalysisWorkerPostgresTests.setUp(self)
        v=self.db.session.get(self.models.Vehicle,self.vehicle_id)
        v.model_code='SYNTHETIC';v.first_registration_date='2020-01';v.deleted=False
        peer=self.models.Vehicle(company_code='TEST',model_code='SYNTHETIC',
            first_registration_date='2020-01',deleted=False)
        self.db.session.add(peer)
        self.db.session.add(self.models.VehicleMaintenanceRecord(
            company_code='TEST',vehicle_record_id=self.vehicle_id,
            entry_date='2026-11-01',completion_date='2026-11-01',status='完了',
            content='SYNTHETIC_PREFLIGHT_SOURCE',mileage=100))
        self.db.session.commit()
        self.peer_id=peer.id;self.db.session.remove()
        self.scope=NormalReadScope('TEST',self.vehicle_id,self.state_id,(self.vehicle_id,self.peer_id),True)

    def test_actual_complete_builder_no_limited_cohort_and_detached_sources(self):
        with self.app.test_request_context('/'):
            result=read_normal_input(self.scope)
            self.assertEqual(result.comparison_vehicle_ids,(self.peer_id,))
            self.assertNotIn('acceptance_limited',result.payload['comparison']['comparison_scope'])
            self.assertTrue(result.sources)
            self.assertFalse(self.db.session().in_transaction())
            self.assertFalse(self.db.session().identity_map)

    def test_actual_ordinary_cohort_exceeding_permission_refuses_not_truncates(self):
        scope=NormalReadScope('TEST',self.vehicle_id,self.state_id,(self.vehicle_id,),True)
        with self.app.test_request_context('/'),self.assertRaisesRegex(ValueError,'OUTSIDE_APPROVED'):
            read_normal_input(scope)

    def test_database_readonly_repeatable_read_rejects_direct_write(self):
        from dkss_app import analysis
        def attempt(vehicle):
            conn=self.db.session.connection()
            self.assertEqual(conn.exec_driver_sql('SHOW transaction_read_only').scalar(),'on')
            self.assertEqual(conn.exec_driver_sql('SHOW transaction_isolation').scalar(),'repeatable read')
            conn.exec_driver_sql("UPDATE vehicle SET model_code='ILLEGAL'")
        with self.app.test_request_context('/'),patch.object(analysis,'get_vehicle_karte_analysis_job_data',side_effect=attempt):
            with self.assertRaises(DBAPIError):read_normal_input(self.scope)
            self.assertFalse(self.db.session().in_transaction())
        self.assertEqual(self.db.session.get(self.models.Vehicle,self.vehicle_id).model_code,'SYNTHETIC')
