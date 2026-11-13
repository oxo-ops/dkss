"""Owned loopback PostgreSQL only; actual app reader, synthetic records, no AI."""
import os
import unittest
from unittest.mock import patch
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from analysis_runtime_ci_support import verify_owned_service, CONNECT_ARGS
from tools.quality.scoped_analysis.reader import ReadScope, read_scoped_inputs


class ScopedReaderPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = os.environ.get('ANALYSIS_RUNTIME_POSTGRES_TEST_URL', '')
        if not raw:
            if os.environ.get('ANALYSIS_RUNTIME_REQUIRE_POSTGRES') == '1':
                raise AssertionError('Owned PostgreSQL required')
            raise unittest.SkipTest('Owned PostgreSQL not configured')
        verify_owned_service(raw, os.environ)
        from dkss_app import create_app, models
        from dkss_app.extensions import db
        cls.db, cls.models = db, models
        cls.app = create_app({'SQLALCHEMY_DATABASE_URI': raw, 'TESTING':True,
            'SQLALCHEMY_ENGINE_OPTIONS': {'connect_args':CONNECT_ARGS}})
        with cls.app.app_context():
            db.create_all()  # Only freshly provisioned, ownership-verified CI service.
            db.session.add_all([models.Company(company_code=c,company_name=c) for c in ('SYNTHETIC_A','SYNTHETIC_B')])
            for n, company in ((1,'SYNTHETIC_A'),(2,'SYNTHETIC_A'),(3,'SYNTHETIC_A'),(4,'SYNTHETIC_B')):
                db.session.add(models.Vehicle(id=n, company_code=company, model_code='FIXTURE',
                    manufacturer='SYNTHETIC', first_registration_date='2020-01', deleted=False))
            db.session.flush()
            for n in range(1,5):
                db.session.add(models.VehicleMaintenanceRecord(id=n, company_code='SYNTHETIC_B' if n==4 else 'SYNTHETIC_A',
                    vehicle_record_id=n, entry_date='2026-11-01', completion_date='2026-11-01',
                    status='完了', content=f'SYNTHETIC_SENTINEL_{n}', mileage=100*n))
            db.session.commit()

    def setUp(self):
        self.ctx=self.app.test_request_context('/')
        self.ctx.push()
        self.scope=ReadScope('SYNTHETIC_A',(1,),(2,))

    def tearDown(self):
        self.db.session.remove(); self.ctx.pop()

    def test_actual_reader_limits_loaded_rows_and_comparison_before_fetch(self):
        loaded=[]
        def record(session,obj):
            if isinstance(obj,self.models.Vehicle): loaded.append(('vehicle',obj.id))
            elif hasattr(obj,'vehicle_record_id'): loaded.append(('record',obj.vehicle_record_id))
        session=self.db.session()
        event.listen(session,'loaded_as_persistent',record)
        try:
            snapshots=read_scoped_inputs(self.scope)
        finally: event.remove(session,'loaded_as_persistent',record)
        self.assertTrue(loaded)
        self.assertTrue(all(n in (1,2) for _,n in loaded),loaded)
        result=snapshots[0]
        self.assertEqual(result['target'].vehicle_id,1)
        self.assertEqual(result['payload']['comparison']['comparison_scope']['cohort_vehicle_ids'],[2])
        self.assertTrue(result['payload']['comparison']['comparison_scope']['acceptance_limited'])
        self.assertFalse(session.in_transaction())
        self.assertEqual(len(session.identity_map),0)
        self.assertEqual(self.models.VehicleMaintenanceRecord.query.count(),4)
        self.assertEqual(self.models.VehicleKarteAnalysis.query.count(),0)

    def test_unscoped_orm_query_is_constrained_before_rows_materialize(self):
        from dkss_app import analysis
        original=analysis.get_vehicle_karte_analysis_job_data
        def probe(vehicle,**kw):
            self.assertEqual([v.id for v in self.models.Vehicle.query.order_by(self.models.Vehicle.id).all()],[1,2])
            self.assertEqual([r.vehicle_record_id for r in self.models.VehicleMaintenanceRecord.query.order_by(self.models.VehicleMaintenanceRecord.id).all()],[1,2])
            return original(vehicle,**kw)
        with patch.object(analysis,'get_vehicle_karte_analysis_job_data',side_effect=probe):
            read_scoped_inputs(self.scope)

    def test_database_rejects_raw_write_and_rolls_back(self):
        from dkss_app import analysis
        def probe(*a,**kw):
            connection=self.db.session.connection()
            self.assertEqual(connection.exec_driver_sql('SHOW transaction_read_only').scalar(),'on')
            self.assertEqual(connection.exec_driver_sql('SHOW transaction_isolation').scalar(),'repeatable read')
            connection.exec_driver_sql("UPDATE vehicle SET model_code='ILLEGAL' WHERE id=1")
        with patch.object(analysis,'get_vehicle_karte_analysis_job_data',side_effect=probe):
            with self.assertRaises(DBAPIError) as caught: read_scoped_inputs(self.scope)
        self.assertEqual(caught.exception.orig.pgcode,'25006')
        self.assertFalse(self.db.session().in_transaction())
        self.assertEqual(self.db.session.get(self.models.Vehicle,1).model_code,'FIXTURE')

    def test_commit_flush_and_transaction_replacement_refused(self):
        from dkss_app import analysis
        for action in ('commit','flush','replace'):
            self.db.session.remove()
            def probe(vehicle,**kw):
                if action=='commit': self.db.session.commit()
                elif action=='flush':
                    vehicle.model_code='ILLEGAL'; self.db.session.flush()
                else:
                    self.db.session.rollback()
                    self.models.Vehicle.query.all()
            with patch.object(analysis,'get_vehicle_karte_analysis_job_data',side_effect=probe):
                with self.assertRaises(ValueError): read_scoped_inputs(self.scope)
        self.assertEqual(self.db.session.get(self.models.Vehicle,1).model_code,'FIXTURE')

    def test_outside_company_target_fails_and_dirty_session_is_not_touched(self):
        with self.assertRaisesRegex(ValueError,'UNAVAILABLE'):
            read_scoped_inputs(ReadScope('SYNTHETIC_A',(4,),()))
        vehicle=self.db.session.get(self.models.Vehicle,1)
        vehicle.model_code='UNCOMMITTED'
        with self.assertRaisesRegex(ValueError,'FRESH_READ_SESSION'):
            read_scoped_inputs(self.scope)
        self.assertEqual(vehicle.model_code,'UNCOMMITTED')
        self.db.session.rollback()

    def test_read_snapshot_stable_during_concurrent_change(self):
        from dkss_app import analysis
        original=analysis.get_vehicle_karte_analysis_job_data
        def probe(vehicle,**kw):
            self.assertEqual(self.db.session.get(self.models.VehicleMaintenanceRecord,1).content,'SYNTHETIC_SENTINEL_1')
            with self.db.engine.begin() as other:
                other.execute(text("UPDATE vehicle_maintenance_record SET content='SYNTHETIC_CHANGED' WHERE id=1"))
            self.db.session.expire_all()
            self.assertEqual(self.db.session.get(self.models.VehicleMaintenanceRecord,1).content,'SYNTHETIC_SENTINEL_1')
            return original(vehicle,**kw)
        try:
            with patch.object(analysis,'get_vehicle_karte_analysis_job_data',side_effect=probe):
                read_scoped_inputs(self.scope)
        finally:
            with self.db.engine.begin() as other:
                other.execute(text("UPDATE vehicle_maintenance_record SET content='SYNTHETIC_SENTINEL_1' WHERE id=1"))
