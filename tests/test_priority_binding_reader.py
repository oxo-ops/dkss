"""Actual ORM fields to explicit proposal binding, isolated synthetic SQLite only."""
from copy import deepcopy
from dataclasses import replace
from datetime import date
import unittest

from sqlalchemy import event, update
import test_workflow_regressions as workflow_fixture
from dkss_app.priority_sources import (
    ENABLE_KEY, read_bound_registered_defect_priorities, read_registered_defect_snapshot,
)
from vehicle_priority_binding import DefectBindingSet, ExplicitDefectBinding, projection_snapshot_hash
from vehicle_priority_sources import assess_registered_defects
from vehicle_priority_assessment import InvalidInput, ProductionUseBlocked


class BoundPriorityReaderTests(unittest.TestCase):
    setUpClass=classmethod(workflow_fixture.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass=classmethod(workflow_fixture.WorkflowRegressionTests.tearDownClass.__func__)
    tearDown=workflow_fixture.WorkflowRegressionTests.tearDown
    day=date(2026,11,10)

    def setUp(self):
        workflow_fixture.WorkflowRegressionTests.setUp(self)
        self.vehicle_id=self.vehicle.id
        self.m.app.config[ENABLE_KEY]=True
        m=self.m
        record=m.VehiclePatrol(company_code='TEST',vehicle_record_id=self.vehicle_id,
                               occurred_date='2026-11-01',content='合成の指摘',priority='中',status='未対応')
        m.db.session.add(record);m.db.session.commit()
        self.record_id=record.id
        self.source_id=f'defect:{record.id}'
        proposal=dict(target='合成部位',category='点検',source_ids=[self.source_id],priority='高',action='合成確認')
        ident,revision=m.vehicle_analysis_proposal_ids(proposal)
        self.analysis={'recommendations':[dict(proposal,proposal_id=ident,proposal_revision=revision)]}
        self.sources={self.source_id:{'label':'元の出典','url':'/synthetic'}}
        snapshot=read_registered_defect_snapshot(company_code='TEST',vehicle_id=self.vehicle_id,captured_on=self.day)
        self.binding=DefectBindingSet('TEST',self.vehicle_id,self.day,
            projection_snapshot_hash(self.analysis),projection_snapshot_hash(self.sources),
            assess_registered_defects(snapshot,as_of=self.day)['snapshot_fingerprint'],
            (ExplicitDefectBinding(ident,revision,proposal['target'],self.source_id,True),))

    def read(self):return read_bound_registered_defect_priorities(self.analysis,self.sources,self.binding)

    def test_orm_to_existing_proposal_preserves_state_and_performs_only_reads(self):
        before=deepcopy((self.analysis,self.sources,self.binding))
        mutations=[]
        def observer(_conn,_cursor,statement,_parameters,_context,_many):
            verb=statement.lstrip().split(None,1)[0].upper()
            if verb not in {'SELECT','PRAGMA'}:mutations.append(verb)
        event.listen(self.m.db.engine,'before_cursor_execute',observer)
        try:output=self.read()
        finally:event.remove(self.m.db.engine,'before_cursor_execute',observer)
        self.assertEqual(mutations,[])
        self.assertEqual((self.analysis,self.sources,self.binding),before)
        self.assertEqual(output['recommendations'][0]['priority'],'高')
        self.assertEqual(output['recommendations'][0]['priority_preview']['base_score'],10)
        row=self.m.db.session.get(self.m.VehiclePatrol,self.record_id)
        self.assertEqual((row.priority,row.status,row.content),('中','未対応','合成の指摘'))
        self.assertEqual(self.m.VehicleKarteAnalysis.query.count(),0)
        self.assertFalse(self.m.db.session.new or self.m.db.session.dirty or self.m.db.session.deleted)

    def test_after_stored_record_changes_original_binding_cannot_replay(self):
        self.read()
        with self.m.db.engine.begin() as connection:
            connection.execute(update(self.m.VehiclePatrol).where(self.m.VehiclePatrol.id==self.record_id).values(status='対応中'))
        with self.assertRaises(InvalidInput):self.read()

    def test_binding_reader_inherits_off_switch_and_dirty_session_guard(self):
        self.m.app.config[ENABLE_KEY]=False
        with self.assertRaises(ProductionUseBlocked):self.read()
        self.m.app.config[ENABLE_KEY]=True
        self.vehicle.deleted=True
        with self.assertRaises(InvalidInput):self.read()
        self.m.db.session.rollback()
        with self.assertRaises(InvalidInput):read_bound_registered_defect_priorities(self.analysis,self.sources,{})

    def test_bound_reader_is_not_a_route_or_normal_runtime_hook(self):
        self.assertFalse(any('read_bound_registered_defect_priorities' in rule.endpoint
                             for rule in self.m.app.url_map.iter_rules()))


if __name__=='__main__':unittest.main()
