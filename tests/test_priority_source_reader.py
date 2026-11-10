"""Scoped ORM-to-shadow integration; only fresh temporary synthetic SQLite."""
from datetime import date
import os
import unittest
from unittest.mock import patch

from sqlalchemy import event, update
import test_workflow_regressions as workflow_fixture
from dkss_app.priority_sources import ENABLE_KEY, read_registered_defect_priorities
from vehicle_priority_assessment import InvalidInput, ProductionUseBlocked


class PrioritySourceReaderTests(unittest.TestCase):
    setUpClass = classmethod(workflow_fixture.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow_fixture.WorkflowRegressionTests.tearDownClass.__func__)
    def setUp(self):
        workflow_fixture.WorkflowRegressionTests.setUp(self)
        self.vehicle_id = self.vehicle.id
        self.m.app.config.pop(ENABLE_KEY, None)

    tearDown = workflow_fixture.WorkflowRegressionTests.tearDown
    day = date(2026, 11, 10)

    def read(self, **changes):
        params = dict(company_code='TEST', vehicle_id=self.vehicle_id, captured_on=self.day)
        params.update(changes)
        return read_registered_defect_priorities(**params)

    def seed(self):
        m = self.m
        other = m.Vehicle(company_code='TEST', chassis_number='SECOND')
        foreign = m.Vehicle(company_code='OTHER', chassis_number='FOREIGN')
        m.db.session.add_all([other, foreign]); m.db.session.flush()
        records = [m.VehiclePatrol(company_code='TEST', vehicle_record_id=self.vehicle.id,
                                  occurred_date='2020-01-01', content='合成ブレーキ指摘', priority='高', status='未対応'),
                   m.VehiclePatrol(company_code='TEST', vehicle_record_id=self.vehicle.id,
                                  occurred_date='2026-10-01', content='合成完了記録', priority='高', status='修理完了',repair_date='2026-10-02'),
                   m.VehiclePatrol(company_code='TEST', vehicle_record_id=self.vehicle.id,
                                  content='合成の旧状態', priority='不明な旧値',status=None),
                   m.VehiclePatrol(company_code='TEST', vehicle_record_id=other.id,content='別車両',status='未対応'),
                   m.VehiclePatrol(company_code='OTHER', vehicle_record_id=foreign.id,content='他社',status='未対応'),
                   m.VehiclePatrol(company_code='OTHER', vehicle_record_id=self.vehicle.id,content='不整合な他社行',status='未対応')]
        m.db.session.add_all(records); m.db.session.commit()
        # The model default fills None on insert. Deliberately retain a legacy NULL.
        records[2].status = None; m.db.session.commit()
        return records, other, foreign

    def test_default_off_and_production_marker_block_before_reading(self):
        self.m.app.config.pop(ENABLE_KEY, None)
        for enabled in (None, False, 'true', 1):
            self.m.app.config[ENABLE_KEY] = enabled
            with self.assertRaises(ProductionUseBlocked): self.read()
        self.m.app.config[ENABLE_KEY] = True
        self.m.app.config['TESTING'] = False
        try:
            with self.assertRaises(ProductionUseBlocked): self.read()
        finally: self.m.app.config['TESTING'] = True
        with patch.dict(os.environ, {'RENDER':'true'}):
            with self.assertRaises(ProductionUseBlocked): self.read()

    def test_scoped_existing_schema_reads_preserve_values_and_make_no_writes(self):
        m = self.m
        records, other, foreign = self.seed()
        self.m.app.config[ENABLE_KEY] = True
        before = [(r.id,r.company_code,r.vehicle_record_id,r.content,r.priority,r.status,r.repair_date) for r in records]
        mutations = []
        def observe(_conn,_cursor,statement,_parameters,_context,_many):
            verb = statement.lstrip().split(None,1)[0].upper()
            if verb not in {'SELECT','PRAGMA'}: mutations.append(verb)
        event.listen(m.db.engine, 'before_cursor_execute', observe)
        try:
            with patch.object(m,'analyze_vehicle_karte',side_effect=AssertionError('No AI')), \
                 patch.object(m,'queue_vehicle_karte_analysis',side_effect=AssertionError('No scheduling')):
                first, second = self.read(), self.read()
        finally: event.remove(m.db.engine,'before_cursor_execute',observe)
        self.assertEqual(mutations, [])
        self.assertEqual(first, second)
        self.assertEqual([r['record']['record_id'] for r in first['items']], [records[0].id,records[2].id])
        self.assertEqual([r['record_id'] for r in first['excluded_records']], [records[1].id])
        self.assertEqual(first['items'][0]['assessment']['base_score'],10)
        self.assertEqual(first['items'][1]['assessment']['base_score'],0)
        self.assertEqual(before,[(r.id,r.company_code,r.vehicle_record_id,r.content,r.priority,r.status,r.repair_date) for r in records])
        self.assertEqual(m.VehicleKarteAnalysis.query.count(),0)
        self.assertFalse(m.db.session.new or m.db.session.dirty or m.db.session.deleted)

    def test_other_company_deleted_vehicle_and_bad_scope_do_not_fall_back(self):
        _records,_other,foreign = self.seed()
        self.m.app.config[ENABLE_KEY] = True
        for changes in ({'vehicle_id':foreign.id},{'company_code':'OTHER'}, {'company_code':''},
                        {'vehicle_id':True}, {'captured_on':'2026-11-10'}):
            with self.assertRaises(InvalidInput): self.read(**changes)
        self.vehicle.deleted=True; self.m.db.session.commit()
        with self.assertRaises(InvalidInput): self.read()

    def test_pending_insert_update_or_delete_is_never_autoflushed_by_reader(self):
        m=self.m
        records,_,_=self.seed()
        self.m.app.config[ENABLE_KEY]=True
        record=records[0]
        record.content='pending change'
        with self.assertRaises(InvalidInput): self.read()
        m.db.session.rollback()
        m.db.session.add(m.VehiclePatrol(company_code='TEST',vehicle_record_id=self.vehicle.id,content='pending insert'))
        with self.assertRaises(InvalidInput): self.read()
        m.db.session.rollback()
        m.db.session.delete(record)
        with self.assertRaises(InvalidInput): self.read()
        m.db.session.rollback()
        self.assertEqual(m.VehiclePatrol.query.count(),6)

    def test_clean_identity_map_is_refreshed_from_stored_state(self):
        m=self.m
        records,_,_=self.seed()
        self.m.app.config[ENABLE_KEY]=True
        ident=records[0].id
        self.assertEqual(records[0].status,'未対応')
        with m.db.engine.begin() as connection:
            connection.execute(update(m.VehiclePatrol).where(m.VehiclePatrol.id==ident).values(status='修理完了'))
        self.assertEqual(records[0].status,'未対応')
        output=self.read()
        self.assertIn(ident,[row['record_id'] for row in output['excluded_records']])
        self.assertNotIn(ident,[item['record']['record_id'] for item in output['items']])
        self.assertEqual(records[0].status,'修理完了')
        with m.db.engine.begin() as connection:
            connection.execute(update(m.VehiclePatrol).where(m.VehiclePatrol.id==ident).values(status='対応中'))
        self.assertEqual(records[0].status,'修理完了')
        reopened=self.read()
        self.assertNotIn(ident,[row['record_id'] for row in reopened['excluded_records']])
        self.assertEqual(next(item for item in reopened['items'] if item['record']['record_id']==ident)['assessment']['base_score'],10)
        self.assertEqual(records[0].status,'対応中')

    def test_reader_has_no_http_route_or_normal_runtime_hook(self):
        self.assertFalse(any('read_registered_defect_priorities' in rule.endpoint for rule in self.m.app.url_map.iter_rules()))
        self.m.app.config[ENABLE_KEY]=True
        self.assertEqual(self.read()['items'],[])


if __name__=='__main__':
    unittest.main()
