"""Synthetic SQLite fence tests; PostgreSQL READ ONLY still needs owned CI."""
from dataclasses import replace
import unittest
from sqlalchemy import create_engine, Column, Integer, String, Boolean, text
from sqlalchemy.orm import declarative_base, Session
from tools.quality.scoped_analysis.preflight import NormalReadScope, _read


class NormalPreflightTests(unittest.TestCase):
    def setUp(self):
        self.Base = declarative_base()
        class Vehicle(self.Base):
            __tablename__ = 'synthetic_vehicle'
            id = Column(Integer, primary_key=True)
            company_code = Column(String)
            deleted = Column(Boolean, default=False)
        class State(self.Base):
            __tablename__ = 'synthetic_state'
            id = Column(Integer, primary_key=True)
            company_code = Column(String)
            vehicle_record_id = Column(Integer)
        self.V, self.S = Vehicle, State
        self.engine = create_engine('sqlite:///:memory:')
        self.addCleanup(self.engine.dispose)
        self.Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.addCleanup(self.session.close)
        self.session.add_all([Vehicle(id=1,company_code='A'),Vehicle(id=2,company_code='A'),
            Vehicle(id=3,company_code='A'),Vehicle(id=4,company_code='B'),
            State(id=1,company_code='A',vehicle_record_id=1)])
        self.session.commit(); self.session.expunge_all()
        self.scope = NormalReadScope('A',1,1,(1,2,3),True)

    def payload(self, peers):
        return {'comparison': {'comparison_scope': {'cohort_vehicle_ids':peers,
            'same_company_only':True,'target_vehicle_excluded':True}},
            'maintenance_knowledge': {'text':'synthetic company maintenance knowledge'}}

    def read(self, builder=None, scope=None):
        return _read(scope or self.scope,self.session,self.Base.registry,self.V,self.S,
                     builder or (lambda v:(self.payload([2,3]),{})),_sqlite_memory_test=True)

    def test_complete_cohort_and_company_knowledge_detached_without_scope_truncation(self):
        def builder(vehicle):
            self.assertEqual(vehicle.id,1)
            self.assertEqual({v.id for v in self.session.query(self.V).all()},{1,2,3})
            return self.payload([2,3]), {'source':'synthetic'}
        result=self.read(builder)
        self.assertEqual(result.comparison_vehicle_ids,(2,3))
        self.assertIn('maintenance_knowledge',result.payload)
        self.assertNotIn('synthetic company maintenance knowledge',repr(result))
        self.assertFalse(self.session.in_transaction());self.assertFalse(self.session.identity_map)

    def test_partial_allowlist_rejects_whole_result_not_reduced_cohort(self):
        with self.assertRaisesRegex(ValueError,'OUTSIDE_APPROVED'):
            self.read(scope=replace(self.scope,allowed_vehicle_ids=(1,2)))
        self.assertFalse(self.session.in_transaction())

    def test_forged_cross_company_cohort_rejected_even_if_allowlisted(self):
        with self.assertRaisesRegex(ValueError,'COMPANY_MISMATCH'):
            self.read(lambda v:(self.payload([4]),{}),replace(self.scope,allowed_vehicle_ids=(1,4)))

    def test_missing_company_knowledge_permission_rejected(self):
        with self.assertRaisesRegex(ValueError,'EXPLICIT'):
            replace(self.scope,company_knowledge_allowed=False)

    def test_wrong_state_company_or_target_rejected(self):
        with self.assertRaisesRegex(ValueError,'UNAVAILABLE'):
            self.read(scope=replace(self.scope,company='B'))
        with self.assertRaisesRegex(ValueError,'UNAVAILABLE'):
            self.read(scope=replace(self.scope,state_id=999))

    def test_commit_flush_raw_statement_and_connection_write_rejected(self):
        def commit(v):self.session.commit()
        def flush(v):
            self.session.add(self.V(id=5,company_code='A'));self.session.flush()
        def raw(v):self.session.execute(text('SELECT 1'))
        def write(v):self.session.connection().exec_driver_sql("INSERT INTO synthetic_vehicle VALUES (9,'A',0)")
        for builder in (commit,flush,raw,write):
            with self.subTest(builder=builder.__name__), self.assertRaises(Exception):self.read(builder)
            self.assertFalse(self.session.in_transaction())
        self.assertEqual(self.session.query(self.V).count(),4)

    def test_dirty_or_loaded_session_rejected(self):
        self.session.get(self.V,1)
        with self.assertRaisesRegex(ValueError,'FRESH'):self.read()

    def test_acceptance_limited_input_rejected(self):
        def builder(v):
            p=self.payload([2]);p['comparison']['comparison_scope']['acceptance_limited']=True
            return p,{}
        with self.assertRaisesRegex(ValueError,'COMPARISON_SCOPE'):self.read(builder)

