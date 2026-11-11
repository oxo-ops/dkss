"""Existing human repair/recheck originals, without inferring S25 semantics."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from sqlalchemy import event
import test_priority_common_workflow as common
import test_priority_stage2_workflow as stage2
from dkss_app.priority_observations import read_inspection_observation_sources


class PriorityObservationSourceTests(unittest.TestCase):
    setUpClass = classmethod(common.CommonPriorityWorkflowTests.setUpClass.__func__)
    tearDownClass = classmethod(common.CommonPriorityWorkflowTests.tearDownClass.__func__)
    tearDown = common.CommonPriorityWorkflowTests.tearDown
    login = common.CommonPriorityWorkflowTests.login
    request = common.CommonPriorityWorkflowTests.request
    save = common.CommonPriorityWorkflowTests.save
    complete = common.CommonPriorityWorkflowTests.complete
    state = common.CommonPriorityWorkflowTests.state
    decision_data = common.CommonPriorityWorkflowTests.decision_data
    decide = common.CommonPriorityWorkflowTests.decide
    snapshot = common.CommonPriorityWorkflowTests.snapshot
    begin_priority = stage2.PriorityStage2WorkflowTests.begin_priority
    repair_priority = stage2.PriorityStage2WorkflowTests.repair_priority

    def setUp(self):
        common.CommonPriorityWorkflowTests.setUp(self)
        self.begin_priority(); self.decide('運行可')

    def refs(self):
        from dkss_app.priority_projection import registered_inspection_provenance
        proof = registered_inspection_provenance(self.vehicle, self.row)
        return [value['input_ref'] for value in proof['events']]

    def read(self, refs=None):
        before = self.snapshot()
        result = read_inspection_observation_sources(self.vehicle, refs or self.refs(), as_of=self.day)
        self.assertEqual(self.snapshot(), before)
        return result

    def recheck(self, result='異常なし', note='合成試験。左側の同一箇所を再確認し異常なし。'):
        self.login('reviewer')
        response = self.request('POST', f'/vehicle/checklist-results/{self.row.id}/defects/1/repair', data={
            'judgment_version': str(self.state()['version']), 'recheck_result': result,
            'repair_note': note, 'repair_performed_date': self.day.isoformat()})
        self.assertEqual(response.status_code, 302)

    def test_original_repair_then_recheck_proves_recorded_resolution_not_recurrence(self):
        self.repair_priority(); self.recheck()
        value = self.read()['observations'][0]
        self.assertTrue(value['lifecycle_verified'])
        self.assertTrue(value['resolved_after_repair_and_recheck'])
        self.assertFalse(value['comparison_verified'])
        self.assertEqual([v['kind'] for v in value['transitions']], ['repair', 'recheck'])
        self.assertEqual(value['transitions'][-1]['note'], '合成試験。左側の同一箇所を再確認し異常なし。')
        actor = self.models.User.query.filter_by(company_code='A', username='reviewer').one()
        self.assertEqual(value['transitions'][-1]['actor_identity'], actor.account_identity)
        self.assertEqual(value['transitions'][-1]['actor_user_id'], actor.id)
        self.assertEqual(self.state()['status'], '未判定')
        self.assertNotIn('priority', value)
        self.assertNotIn('effective_score', value)

    def test_pending_recheck_and_abnormal_recheck_do_not_prove_resolved_baseline(self):
        self.repair_priority()
        pending = self.read()['observations'][0]
        self.assertTrue(pending['lifecycle_verified'])
        self.assertFalse(pending['resolved_after_repair_and_recheck'])
        self.recheck('異常あり', '修理後の再確認で異常あり。前回より悪化したとの申告は未確認。')
        value = self.read()['observations'][0]
        self.assertTrue(value['lifecycle_verified'])
        self.assertFalse(value['resolved_after_repair_and_recheck'])
        self.assertFalse(value['comparison_verified'])
        self.assertEqual(value['transitions'][-1]['result'], '異常あり')

    def test_note_even_with_explicit_recurrence_words_never_verifies_comparison_itself(self):
        self.repair_priority()
        self.recheck('異常あり', '昨日解消した左側の同じ症状が本日再発した。別の記録番号は未指定。')
        value = self.read()['observations'][0]
        self.assertFalse(value['comparison_verified'])
        self.assertIn('本日再発', value['transitions'][-1]['note'])

    def test_missing_repair_event_cannot_be_reconstructed_from_final_json(self):
        self.repair_priority(); self.recheck()
        self.models.ChecklistEvent.query.filter_by(event_type='再確認待ち').delete()
        self.db.session.commit()
        value = self.read()['observations'][0]
        self.assertFalse(value['lifecycle_verified'])
        self.assertFalse(value['resolved_after_repair_and_recheck'])
        self.assertEqual(value['transitions'], [])

    def test_source_version_actor_and_identity_tampering_fail_closed(self):
        self.repair_priority(); self.recheck()
        row = self.models.ChecklistEvent.query.filter_by(event_type='解消').one()
        original = row.detail_json
        for field, value in [('actor_identity', None), ('actor_user_id', None), ('actor_username', 'another')]:
            before = getattr(row, field)
            setattr(row, field, value); self.db.session.commit()
            self.assertFalse(self.read()['observations'][0]['lifecycle_verified'], field)
            setattr(row, field, before); self.db.session.commit()
        raw = json.loads(original)
        raw['previous_defect']['reported_answer']['comment'] = 'different observation'
        row.detail_json = json.dumps(raw); self.db.session.commit()
        self.assertFalse(self.read()['observations'][0]['lifecycle_verified'])

    def test_cross_company_vehicle_and_forged_reference_never_return_partial_sources(self):
        self.repair_priority(); self.recheck()
        refs = self.refs()
        other = self.models.Vehicle.query.filter_by(company_code='B').one()
        self.assertEqual(read_inspection_observation_sources(other, refs, as_of=self.day)['observations'], [])
        forged = refs[0][:-1] + ('0' if refs[0][-1] != '0' else '1')
        self.assertEqual(self.read(refs + [forged])['observations'], [])
        self.assertEqual(self.read(['inspection:999999999999:defect:1:' + 'a'*24])['observations'], [])

    def test_existing_username_reassignment_does_not_rebind_historical_actor(self):
        self.repair_priority(); self.recheck()
        before = self.read()['observations'][0]['transitions'][-1]['actor_identity']
        actor = self.models.User.query.filter_by(company_code='A', username='reviewer').one()
        self.db.session.delete(actor); self.db.session.flush()
        replacement = self.models.User(company_code='A', username='reviewer', role='user',
            password='unused', last_name='別の合成担当', first_name='',
            password_changed_at='2026-11-11 00:00:00')
        self.db.session.add(replacement); self.db.session.commit()
        self.assertNotEqual(replacement.account_identity, before)
        self.assertEqual(self.read()['observations'][0]['transitions'][-1]['actor_identity'], before)

    def test_dirty_session_and_history_limit_never_flush_or_read_partial_chain(self):
        self.repair_priority(); self.recheck()
        refs = self.refs()
        self.vehicle.chassis_number = 'unsaved'
        with patch.object(self.db.session(), 'flush', side_effect=AssertionError('flush forbidden')):
            result = read_inspection_observation_sources(self.vehicle, refs, as_of=self.day)
        self.assertEqual(result['observations'], [])
        self.db.session.rollback()
        with patch('dkss_app.priority_observations.MAX_EVENTS', 1):
            self.assertEqual(self.read(refs)['observations'], [])

    def test_reads_are_select_only_and_batched(self):
        self.repair_priority(); self.recheck(); refs = self.refs()
        statements = []
        def capture(_connection, _cursor, sql, _params, _context, _many): statements.append(sql)
        event.listen(self.db.engine, 'before_cursor_execute', capture)
        try:
            result = read_inspection_observation_sources(self.vehicle, refs, as_of=self.day)
        finally:
            event.remove(self.db.engine, 'before_cursor_execute', capture)
        self.assertTrue(result['observations'][0]['lifecycle_verified'])
        self.assertLessEqual(len(statements), 3)
        self.assertTrue(all(sql.lstrip().upper().startswith('SELECT') for sql in statements))
