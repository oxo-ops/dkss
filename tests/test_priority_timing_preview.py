"""Synthetic-only condition API integration; no real DB or network is used."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

from sqlalchemy import event

import test_vehicle_priority_preview as preview_tests
import test_priority_timing_condition_view as condition_tests
from dkss_app.priority_preview import (
    ENABLE_KEY, EXTENSION_KEY, SyntheticTimingInput, snapshot_hash,
)
from vehicle_priority_timing_sources import timing_snapshot_hash


class PriorityTimingPreviewTests(unittest.TestCase):
    setUpClass = classmethod(preview_tests.VehiclePriorityPreviewTests.setUpClass.__func__)
    tearDownClass = classmethod(preview_tests.VehiclePriorityPreviewTests.tearDownClass.__func__)
    tearDown = preview_tests.VehiclePriorityPreviewTests.tearDown
    base_set_up = preview_tests.VehiclePriorityPreviewTests.base_set_up
    setUp = preview_tests.VehiclePriorityPreviewTests.setUp
    url = preview_tests.VehiclePriorityPreviewTests.url
    install = preview_tests.VehiclePriorityPreviewTests.install
    save_synthetic_analysis = preview_tests.VehiclePriorityPreviewTests.save_synthetic_analysis

    def condition_fixture(self, relation='all', criteria=None):
        state, bundle, fixture = self.save_synthetic_analysis()
        proposal = bundle['analysis']['recommendations'][0]
        candidate = next(iter(fixture.candidates.values()))
        rule, timing, binding, _evidence, references = condition_tests.TimingConditionViewTests().case(
            criteria=criteria, relation=relation, baseline='2026-10-31', as_of=self.day.isoformat())
        rule['analysis_adoption']['vehicle_source_id'] = f'vehicle:{self.vehicle.id}'
        timing['source_ids'] = [f'vehicle:{self.vehicle.id}' if sid == 'vehicle:1' else sid
                                for sid in timing['source_ids']]
        for sid in timing['source_ids']:
            bundle['sources'][sid] = {'snapshot': {'source_id': sid, 'content': 'Synthetic timing source'}}
        proposal['source_ids'] = sorted(set(proposal['source_ids']) | set(timing['source_ids']))
        key, revision = self.m.vehicle_analysis_proposal_ids(proposal)
        binding = replace(binding, scope=candidate.scope, event_id=candidate.event_id,
                          snapshot_hash=timing_snapshot_hash(rule, timing),
                          event_source_ids=tuple(fixture.evidence))
        value = SyntheticTimingInput(revision, rule, timing, binding, True)
        fixture = replace(fixture, analysis_hash=snapshot_hash(bundle['analysis']),
                          sources_hash=snapshot_hash(bundle['sources']),
                          candidates={key: replace(candidate, candidate_id=key)}, references=references,
                          timing_conditions={key: value})
        state.result_json = json.dumps(bundle, ensure_ascii=False)
        self.m.db.session.commit()
        return state, bundle, fixture, key

    def test_and_condition_field_is_separate_without_score_order_or_saved_changes(self):
        state, _bundle, fixture, key = self.condition_fixture()
        saved = state.result_json
        self.install(replace(fixture, timing_conditions={}))
        baseline = self.client.get(self.url).json
        self.install(fixture)
        response = self.client.get(self.url)
        data = response.json
        envelope = data['priority_timing_conditions']
        self.assertEqual(envelope['version'], 'priority-timing-preview-v1')
        self.assertEqual(envelope['status'], 'available')
        self.assertEqual(envelope['company_code'], 'TEST')
        self.assertEqual(envelope['vehicle_id'], self.vehicle.id)
        self.assertEqual(envelope['as_of'], self.day.isoformat())
        entry = envelope['entries'][0]
        self.assertEqual(entry['proposal_id'], key)
        self.assertEqual(entry['proposal_revision'], data['analysis']['recommendations'][0]['proposal_revision'])
        self.assertEqual(entry['relation'], 'all')
        self.assertEqual(entry['status'], 'verified_condition_facts')
        self.assertEqual(entry['condition_group']['calendar_threshold_on'], '2026-12-15')
        self.assertFalse(entry['scoring_input_emitted'])
        self.assertIn('AND', ' '.join(entry['missing_conditions']))
        self.assertEqual(data['analysis'], baseline['analysis'])
        self.assertEqual(data['sources'], baseline['sources'])
        self.m.db.session.expire_all()
        self.assertEqual(self.m.VehicleKarteAnalysis.query.get(state.id).result_json, saved)
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_single_month_keeps_month_threshold_separate_from_day_count_without_ratio(self):
        _state, _bundle, fixture, _key = self.condition_fixture('single', [{'metric':'period_months','value':1}])
        self.install(fixture)
        entry = self.client.get(self.url).json['priority_timing_conditions']['entries'][0]
        condition = entry['condition_group']['conditions'][0]
        self.assertEqual(condition['unit'], 'calendar_months')
        self.assertEqual(condition['quantity_unit'], 'days')
        self.assertEqual(condition['due_on'], '2026-11-30')
        self.assertEqual(condition['remaining_quantity'], '20')
        self.assertIn('90', ' '.join(entry['missing_conditions']))
        self.assertNotIn('progress_ratio', condition)

    def test_mixed_and_exposes_no_fabricated_whole_group_date(self):
        _state, _bundle, fixture, _key = self.condition_fixture('all', [
            {'metric':'distance_km','value':1000}, {'metric':'period_months','value':1}])
        self.install(fixture)
        entry = self.client.get(self.url).json['priority_timing_conditions']['entries'][0]
        self.assertIsNone(entry['condition_group']['calendar_threshold_on'])
        self.assertFalse(entry['scoring_input_emitted'])

    def test_invalid_condition_bindings_block_only_conditions_and_never_leak_previous_entry(self):
        _state, _bundle, fixture, key = self.condition_fixture()
        value = fixture.timing_conditions[key]
        bad_rule = deepcopy(value.rule); bad_rule['source_quote'] = 'changed'
        cyclic_rule = deepcopy(value.rule); cyclic_rule['cycle_data'] = cyclic_rule
        mutations = [
            {key: replace(value, proposal_revision='stale')},
            {key: replace(value, proposal_binding_verified=False)},
            {key: replace(value, proposal_binding_verified=1)},
            {key: replace(value, binding=replace(value.binding, event_id='different'))},
            {key: replace(value, binding=replace(value.binding, scope=replace(value.binding.scope, company_code='OTHER')))},
            {key: replace(value, binding=replace(value.binding, scope=replace(value.binding.scope, vehicle_id=999)))},
            {key: replace(value, binding=replace(value.binding, scope=replace(value.binding.scope, target='different')))},
            {key: replace(value, binding=replace(value.binding, as_of=self.day.replace(day=9)))},
            {key: replace(value, rule=bad_rule)},
            {key: replace(value, rule=None)},
            {key: replace(value, timing=None)},
            {key: replace(value, binding=None)},
            {key: replace(value, rule=cyclic_rule)},
            {key: {'condition_group': 'not a trusted host input'}},
            {key: value, 'missing-proposal': value},
            [],
        ]
        self.install(fixture)
        original = self.client.get(self.url).json['analysis']
        for inputs in mutations:
            with self.subTest(inputs=type(inputs).__name__):
                self.install(replace(fixture, timing_conditions=inputs))
                data = self.client.get(self.url).json
                self.assertEqual(data['priority_preview']['status'], 'available')
                self.assertEqual(data['analysis'], original)
                self.assertEqual(data['priority_timing_conditions']['status'], 'blocked')
                self.assertEqual(data['priority_timing_conditions']['entries'], [])
                self.assertNotIn('changed', data['priority_timing_conditions']['message'])

    def test_provenance_requires_original_citation_and_saved_source(self):
        _state, original_bundle, original_fixture, key = self.condition_fixture()
        from dkss_app.priority_preview import _condition_preview
        from dkss_app.analysis_feedback import analysis_with_vehicle_feedback
        for absent_from in ('citation', 'source'):
            bundle, fixture = deepcopy(original_bundle), deepcopy(original_fixture)
            sid = fixture.timing_conditions[key].timing['source_ids'][0]
            if absent_from == 'citation':
                proposal = bundle['analysis']['recommendations'][0]
                proposal['source_ids'].remove(sid)
                new_key, revision = self.m.vehicle_analysis_proposal_ids(proposal)
                value = replace(fixture.timing_conditions[key], proposal_revision=revision)
                fixture = replace(fixture, candidates={new_key:replace(fixture.candidates[key],candidate_id=new_key)},
                                  timing_conditions={new_key:value})
            else:
                del bundle['sources'][sid]
            fixture = replace(fixture, analysis_hash=snapshot_hash(bundle['analysis']), sources_hash=snapshot_hash(bundle['sources']))
            with self.m.app.test_request_context(self.url):
                decorated = analysis_with_vehicle_feedback(bundle['analysis'], self.vehicle)
                result = _condition_preview(fixture, decorated, bundle['sources'])
            self.assertEqual(result['status'], 'blocked')
            self.assertEqual(result['entries'], [])

    def test_changed_saved_snapshot_clears_both_score_and_conditions(self):
        state, bundle, fixture, _key = self.condition_fixture()
        self.install(fixture)
        self.assertEqual(self.client.get(self.url).json['priority_timing_conditions']['status'], 'available')
        bundle['analysis']['recommendations'][0]['action'] = 'Changed source proposal'
        state.result_json = json.dumps(bundle, ensure_ascii=False); self.m.db.session.commit()
        data = self.client.get(self.url).json
        self.assertEqual(data['priority_preview']['status'], 'blocked')
        self.assertEqual(data['priority_timing_conditions']['status'], 'blocked')
        self.assertEqual(data['priority_timing_conditions']['entries'], [])

    def test_calculation_unavailable_is_data_state_not_priority_category(self):
        _state, _bundle, fixture, _key = self.condition_fixture('all', [
            {'metric':'distance_km','value':1000}, {'metric':'engine_hours','value':100}])
        self.install(fixture)
        data = self.client.get(self.url).json
        entry = data['priority_timing_conditions']['entries'][0]
        self.assertEqual(entry['status'], 'calculation_unavailable')
        self.assertIsNone(entry['condition_group'])
        self.assertIn(data['analysis']['recommendations'][0]['priority_preview']['label'], ('高', '中', '低'))

    def test_empty_registry_is_absent_and_request_payload_cannot_register(self):
        _state, _bundle, fixture, _key = self.condition_fixture()
        self.install(replace(fixture, timing_conditions={}))
        response = self.client.get(self.url, json={'timing_conditions': {'spoof':'approved'}})
        self.assertEqual(response.json['priority_timing_conditions']['status'], 'absent')
        self.assertEqual(response.json['priority_timing_conditions']['entries'], [])
        self.assertEqual(self.client.post(self.url, json={'timing_conditions':'spoof'}).status_code, 405)

    def test_fixture_deepcopy_and_reference_version_mismatch(self):
        _state, _bundle, fixture, key = self.condition_fixture()
        self.install(fixture)
        fixture.timing_conditions[key].rule['source_quote'] = 'mutated caller object'
        self.assertEqual(self.client.get(self.url).json['priority_timing_conditions']['status'], 'available')
        registered = self.m.app.extensions[EXTENSION_KEY][('TEST', self.vehicle.id)]
        refs = dict(registered.references)
        rid = next(iter(refs)); refs[rid] = replace(refs[rid], version='different')
        self.install(replace(registered, references=refs))
        data = self.client.get(self.url).json
        self.assertEqual(data['priority_timing_conditions']['status'], 'blocked')
        self.assertEqual(data['priority_preview']['status'], 'available')

    def test_condition_preview_has_no_database_write_ai_or_cache_work(self):
        _state, _bundle, fixture, _key = self.condition_fixture()
        self.install(fixture)
        writes = []
        def inspect_sql(_connection, _cursor, statement, _params, _context, _many):
            if statement.lstrip().split(None,1)[0].upper() in {'INSERT','UPDATE','DELETE','CREATE','ALTER','DROP','REPLACE'}:
                writes.append(statement.split(None,1)[0])
        event.listen(self.m.db.engine, 'before_cursor_execute', inspect_sql)
        try:
            from dkss_app import analysis as analysis_module
            with patch.object(analysis_module, 'get_vehicle_analysis_read_projection') as cache, \
                 patch.object(analysis_module, 'get_vehicle_karte_analysis_job_data') as inputs, \
                 patch.object(self.m, 'analyze_vehicle_karte') as ai:
                data = self.client.get(self.url).json
            self.assertEqual(data['priority_timing_conditions']['status'], 'available')
            self.assertEqual(writes, [])
            cache.assert_not_called(); inputs.assert_not_called(); ai.assert_not_called()
        finally:
            event.remove(self.m.db.engine, 'before_cursor_execute', inspect_sql)

    def test_disabled_or_production_marker_cannot_expose_condition_field(self):
        _state, _bundle, fixture, _key = self.condition_fixture()
        self.install(fixture)
        self.m.app.config[ENABLE_KEY] = False
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.m.app.config[ENABLE_KEY] = True
        with patch.dict('os.environ', {'RENDER':'true'}):
            self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_normal_result_omits_conditions_even_with_registered_fixture(self):
        _state, _bundle, fixture, _key = self.condition_fixture()
        self.install(fixture)
        data = self.client.get(self.url.split('?')[0]).json
        self.assertNotIn('priority_timing_conditions', data)
        self.assertNotIn('priority_preview', data)
        self.assertNotIn('priority_timing_conditions', data['analysis']['recommendations'][0])

    def test_populated_feedback_and_saved_evaluation_are_preserved_with_conditions(self):
        state, _bundle, fixture, key = self.condition_fixture()
        value = fixture.timing_conditions[key]
        self.m.db.session.add(self.m.VehicleAnalysisFeedback(company_code='TEST', vehicle_record_id=self.vehicle.id,
            proposal_key=key, proposal_revision=value.proposal_revision, status='in_progress', comment='Synthetic comment',
            created_by='admin', created_at='2026-11-10T00:00:00Z', snapshot_json='{}'))
        self.m.db.session.commit()
        original = state.result_json
        self.install(replace(fixture, timing_conditions={}))
        baseline = self.client.get(self.url).json
        self.install(fixture)
        for _ in range(2):
            data = self.client.get(self.url).json
            self.assertEqual(data['priority_timing_conditions']['status'], 'available')
            self.assertEqual(data['analysis'], baseline['analysis'])
            self.assertEqual(data['analysis']['recommendations'][0]['feedback']['comment'], 'Synthetic comment')
        self.m.db.session.expire_all()
        self.assertEqual(self.m.VehicleKarteAnalysis.query.get(state.id).result_json, original)
        self.assertEqual(self.m.VehicleAnalysisFeedback.query.count(), 1)

    def test_actual_condition_api_payload_is_accepted_by_shared_ui_contract_and_render(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node is required for cross-runtime contract validation')
        _state, _bundle, fixture, _key = self.condition_fixture()
        self.install(fixture)
        payload = self.client.get(self.url).get_data(as_text=True)
        script = """
const p=require('./static/js/vehicle_priority_preview.js');let text='';
process.stdin.on('data',d=>text+=d);process.stdin.on('end',()=>{
 const data=JSON.parse(text), before=JSON.stringify(data), priority=p.validate(data);
 const timing=p.validateTiming(data,priority.items);
 if(!priority.available||timing.status!=='available'||timing.entries.size!==1) process.exit(1);
 const element=tag=>({tag,children:[],dataset:{},textContent:'',setAttribute(){},append(...c){this.children.push(...c)}});
 const tree=p.render({createElement:element},data);
 const walk=e=>[e,...e.children.flatMap(walk)];
 if(walk(tree).filter(e=>e.className==='priority-timing-preview').length!==1) process.exit(2);
 if(before!==JSON.stringify(data)) process.exit(3);
});
"""
        result = subprocess.run([node,'-e',script],input=payload,text=True,capture_output=True,
                                cwd=Path(__file__).resolve().parents[1],timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
