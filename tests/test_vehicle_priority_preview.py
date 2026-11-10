"""Non-production priority API tests; fixture writes use only temporary SQLite."""
from copy import deepcopy
from dataclasses import replace
from datetime import date
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlsplit
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

from sqlalchemy import event

from test_workflow_regressions import WorkflowRegressionTests as _Base
from dkss_app.priority_preview import (
    ENABLE_KEY, EXTENSION_KEY, SyntheticPreviewFixture, register_synthetic_fixture, snapshot_hash,
)
from vehicle_priority_assessment import Candidate, Evidence, Fact, InvalidInput, Scope



class PreviewHTML(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.forms, self.links, self._form, self.body = [], [], None, {}
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'body':
            self.body = attrs
        if tag == 'a':
            self.links.append(attrs)
        if tag == 'form':
            self._form = dict(attrs, fields={})
            self.forms.append(self._form)
        if tag == 'input' and self._form is not None and attrs.get('name'):
            self._form['fields'][attrs['name']] = attrs.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'form':
            self._form = None


class VehiclePriorityPreviewTests(unittest.TestCase):
    setUpClass = classmethod(_Base.setUpClass.__func__)
    tearDownClass = classmethod(_Base.tearDownClass.__func__)
    tearDown = _Base.tearDown
    base_set_up = _Base.setUp

    def setUp(self):
        self.base_set_up()
        self.m.app.config.pop(ENABLE_KEY, None)
        self.m.app.extensions.pop(EXTENSION_KEY, None)
        self.day = date(2026, 11, 10)

    @property
    def url(self):
        return f'/vehicle/karte/{self.vehicle.id}/analysis/result?priority_preview=1'

    def save_synthetic_analysis(self, labels=('低',)):
        m = self.m
        proposals = []
        sources = {}
        candidates = {}
        evidence = {}
        for i, label in enumerate(labels):
            record = m.VehicleMaintenanceRecord(company_code='TEST', vehicle_record_id=self.vehicle.id,
                content=f'【合成試験】部位{i}の指摘。実車の事実ではありません。', entry_date='2026-11-10')
            m.db.session.add(record)
            m.db.session.flush()
            source_id = f'maintenance:{record.id}'
            proposal = dict(priority=label, category='整備・点検', target=f'合成部位{i}',
                title='合成試験の提案', current_state='合成データの指摘', timing='試験用',
                action='合成データの確認', reason='API接続試験', uncertainty='実車の事実ではない',
                confirmation_steps=['合成記録を確認'], confirmation_branch='実車の判断はしない',
                basis_type='記録上の指摘・対応', knowledge_ids=[], source_ids=[source_id],
                risk_status='unassessed', risk='機能への影響は未判定です。', risk_source_ids=[])
            proposals.append(proposal)
            sources[source_id] = {'snapshot': {'source_id': source_id, 'content': record.content, 'date': '2026-11-10'}}
            key, _revision = m.vehicle_analysis_proposal_ids(proposal)
            scope = Scope('TEST', self.vehicle.id, proposal['target'])
            evidence[source_id] = Evidence(source_id, scope, self.day, f'event-{i}', record.content, True, 'record', 'open')
            facts = (Fact('safety_issue_open', (source_id,), True),) if i % 2 == 0 else ()
            candidates[key] = Candidate(key, scope, f'event-{i}', facts,
                                        missing_conditions=('合成測定値を確認要',), input_is_current=True)
        analysis = {'overview': '【合成試験】保存済み提案', 'recommendations': proposals}
        bundle = dict(analysis=analysis, sources=sources, fingerprints={'original': 'unchanged'}, generated_at='2026-11-10T00:00:00Z')
        state = m.VehicleKarteAnalysis(company_code='TEST', vehicle_record_id=self.vehicle.id, status='completed',
            result_json=json.dumps(bundle, ensure_ascii=False))
        m.db.session.add(state)
        m.db.session.commit()
        fixture = SyntheticPreviewFixture('TEST', self.vehicle.id, snapshot_hash(analysis), snapshot_hash(sources),
                                          self.day, candidates, evidence, {})
        return state, bundle, fixture

    def install(self, fixture):
        self.m.app.config[ENABLE_KEY] = True
        register_synthetic_fixture(self.m.app, fixture)

    def test_default_off_even_when_query_requests_preview(self):
        self.save_synthetic_analysis()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_server_flag_must_be_literal_true(self):
        self.save_synthetic_analysis()
        for value in ('1', 1, 'true', False):
            with self.subTest(value=value):
                self.m.app.config[ENABLE_KEY] = value
                self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_testing_false_cannot_enable_preview(self):
        _state, _bundle, fixture = self.save_synthetic_analysis()
        self.install(fixture)
        self.m.app.config['TESTING'] = False
        try:
            self.assertEqual(self.client.get(self.url).status_code, 404)
        finally:
            self.m.app.config['TESTING'] = True

    def test_render_production_marker_cannot_enable_preview(self):
        _state, _bundle, fixture = self.save_synthetic_analysis()
        self.install(fixture)
        with patch.dict(os.environ, {'RENDER': 'true'}):
            self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_ordinary_user_cannot_preview_even_with_stale_admin_session(self):
        _state, _bundle, fixture = self.save_synthetic_analysis()
        self.install(fixture)
        self.m.User.query.filter_by(username='admin', company_code='TEST').one().role = 'user'
        self.m.db.session.commit()
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_foreign_vehicle_remains_inaccessible(self):
        foreign = self.m.Vehicle(company_code='OTHER', chassis_number='OTHER-SYNTHETIC')
        self.m.db.session.add(foreign)
        self.m.db.session.commit()
        self.m.app.config[ENABLE_KEY] = True
        self.assertEqual(self.client.get(f'/vehicle/karte/{foreign.id}/analysis/result?priority_preview=1').status_code, 404)

    def test_anonymous_cannot_read_preview(self):
        _state, _bundle, fixture = self.save_synthetic_analysis()
        self.install(fixture)
        with self.client.session_transaction() as session:
            session.clear()
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (302, 401))
        self.assertNotIn('合成部位', response.get_data(as_text=True))

    def test_registered_fixture_returns_only_three_priority_labels(self):
        _state, _bundle, fixture = self.save_synthetic_analysis(('低', '高'))
        self.install(fixture)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        data = response.json
        self.assertEqual(data['priority_preview']['status'], 'available')
        self.assertFalse(data['priority_preview']['production_enabled'])
        self.assertTrue(data['priority_preview']['synthetic_only'])
        previews = [item['priority_preview'] for item in data['analysis']['recommendations']]
        self.assertEqual([p['label'] for p in previews], ['中', '低'])
        self.assertEqual([p['effective_score'] for p in previews], [25, 0])
        self.assertTrue(all(p['operation_decision'] == 'human_only' for p in previews))
        self.assertTrue(all(p['label'] != '未評価' for p in previews))
        self.assertTrue(all('確認要' in p['evidence_status'] or p['evidence_status'] == '根拠不足' for p in previews))
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_preview_never_claims_saved_inputs_are_current(self):
        _state, _bundle, fixture = self.save_synthetic_analysis()
        self.install(fixture)
        data = self.client.get(self.url).json
        self.assertIsNone(data['is_current'])
        self.assertIn('最新性は未確認', data['priority_preview']['message'])
        self.assertTrue(any('最新性' in s for s in data['analysis']['recommendations'][0]['priority_preview']['missing_conditions']))

    def test_original_priority_id_revision_feedback_and_saved_bytes_are_preserved(self):
        state, bundle, fixture = self.save_synthetic_analysis(('低', '高'))
        original_bytes = state.result_json
        original_keys = [self.m.vehicle_analysis_proposal_ids(item) for item in bundle['analysis']['recommendations']]
        first_key, first_revision = original_keys[0]
        self.m.db.session.add(self.m.VehicleAnalysisFeedback(company_code='TEST', vehicle_record_id=self.vehicle.id,
            proposal_key=first_key, proposal_revision=first_revision, status='in_progress', comment='合成コメント',
            created_by='admin', created_at='2026-11-10T00:00:00Z', snapshot_json='{}'))
        self.m.db.session.commit()
        self.install(fixture)
        data = self.client.get(self.url).json
        items = data['analysis']['recommendations']
        self.assertEqual([item['priority'] for item in items], ['低', '高'])
        self.assertEqual([(item['proposal_id'], item['proposal_revision']) for item in items], original_keys)
        self.assertEqual(items[0]['feedback']['status'], 'in_progress')
        self.assertEqual(items[0]['feedback']['comment'], '合成コメント')
        self.assertEqual(items[0]['risk_status'], 'unassessed')
        self.m.db.session.expire_all()
        self.assertEqual(self.m.VehicleKarteAnalysis.query.get(state.id).result_json, original_bytes)
        self.assertEqual(self.m.VehicleAnalysisFeedback.query.count(), 1)

    def test_preview_get_emits_no_database_mutation_or_ai_cache_work(self):
        _state, _bundle, fixture = self.save_synthetic_analysis()
        self.install(fixture)
        writes = []

        def inspect_sql(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().split(None, 1)[0].upper() in {'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP', 'REPLACE'}:
                writes.append(statement.split(None, 1)[0])

        event.listen(self.m.db.engine, 'before_cursor_execute', inspect_sql)
        try:
            from dkss_app import analysis as analysis_module
            with patch.object(analysis_module, 'get_vehicle_analysis_read_projection') as cache, \
                    patch.object(analysis_module, 'get_vehicle_karte_analysis_job_data') as inputs, \
                    patch.object(self.m, 'analyze_vehicle_karte') as ai:
                response = self.client.get(self.url)
            self.assertEqual(response.status_code, 200)
            cache.assert_not_called()
            inputs.assert_not_called()
            ai.assert_not_called()
            self.assertEqual(writes, [])
        finally:
            event.remove(self.m.db.engine, 'before_cursor_execute', inspect_sql)

    def test_missing_fixture_blocks_without_fabricating_low(self):
        self.save_synthetic_analysis()
        self.m.app.config[ENABLE_KEY] = True
        data = self.client.get(self.url).json
        self.assertEqual(data['priority_preview']['status'], 'blocked')
        self.assertNotIn('priority_preview', data['analysis']['recommendations'][0])

    def test_changed_saved_proposal_blocks_stale_registry(self):
        state, bundle, fixture = self.save_synthetic_analysis()
        self.install(fixture)
        bundle['analysis']['recommendations'][0]['action'] = '変更された合成対応'
        state.result_json = json.dumps(bundle, ensure_ascii=False)
        self.m.db.session.commit()
        data = self.client.get(self.url).json
        self.assertEqual(data['priority_preview']['status'], 'blocked')
        self.assertNotIn('priority_preview', data['analysis']['recommendations'][0])

    def test_changed_saved_source_blocks_stale_registry(self):
        state, bundle, fixture = self.save_synthetic_analysis()
        self.install(fixture)
        next(iter(bundle['sources'].values()))['snapshot']['content'] = '変更された原文'
        state.result_json = json.dumps(bundle, ensure_ascii=False)
        self.m.db.session.commit()
        self.assertEqual(self.client.get(self.url).json['priority_preview']['status'], 'blocked')

    def test_missing_candidate_binding_blocks_whole_preview(self):
        _state, _bundle, fixture = self.save_synthetic_analysis()
        self.install(replace(fixture, candidates={}))
        data = self.client.get(self.url).json
        self.assertEqual(data['priority_preview']['status'], 'blocked')
        self.assertNotIn('priority_preview', data['analysis']['recommendations'][0])

    def test_foreign_normalization_cannot_be_bound_to_current_vehicle(self):
        _state, _bundle, fixture = self.save_synthetic_analysis()
        candidates = {key: replace(value, scope=replace(value.scope, vehicle_id=self.vehicle.id + 1))
                      for key, value in fixture.candidates.items()}
        self.install(replace(fixture, candidates=candidates))
        self.assertEqual(self.client.get(self.url).json['priority_preview']['status'], 'blocked')

    def test_unknown_source_binding_blocks_preview(self):
        _state, _bundle, fixture = self.save_synthetic_analysis()
        evidence = dict(fixture.evidence)
        evidence['not-saved'] = replace(next(iter(evidence.values())), source_id='not-saved')
        self.install(replace(fixture, evidence=evidence))
        self.assertEqual(self.client.get(self.url).json['priority_preview']['status'], 'blocked')

    def test_fixture_registration_copies_inputs(self):
        _state, _bundle, fixture = self.save_synthetic_analysis()
        self.install(fixture)
        fixture.candidates.clear()
        self.assertEqual(self.client.get(self.url).json['priority_preview']['status'], 'available')

    def test_query_cannot_register_or_approve_input(self):
        self.save_synthetic_analysis()
        self.m.app.config[ENABLE_KEY] = True
        data = self.client.get(self.url + '&verified=true&score=100&label=高&synthetic_only=true').json
        self.assertEqual(data['priority_preview']['status'], 'blocked')

    def test_non_synthetic_fixture_registration_is_rejected(self):
        _state, _bundle, fixture = self.save_synthetic_analysis()
        self.m.app.config[ENABLE_KEY] = True
        with self.assertRaises(InvalidInput):
            register_synthetic_fixture(self.m.app, replace(fixture, synthetic_only=False))

    def test_registration_requires_testing_and_explicit_flag(self):
        _state, _bundle, fixture = self.save_synthetic_analysis()
        with self.assertRaises(InvalidInput):
            register_synthetic_fixture(self.m.app, fixture)

    def test_no_saved_result_has_no_manufactured_recommendations(self):
        self.m.app.config[ENABLE_KEY] = True
        data = self.client.get(self.url).json
        self.assertFalse(data['has_result'])
        self.assertIsNone(data['analysis'])
        self.assertEqual(data['priority_preview']['status'], 'blocked')

    def test_normal_endpoint_stays_on_existing_contract(self):
        _state, _bundle, fixture = self.save_synthetic_analysis()
        self.install(fixture)
        data = self.client.get(self.url.split('?')[0]).json
        self.assertNotIn('priority_preview', data)
        self.assertNotIn('priority_preview', data['analysis']['recommendations'][0])
        self.assertIn('risk_assessment', data['analysis']['recommendations'][0])

    def test_normal_result_preserves_invalid_historical_priority_without_reclassification(self):
        state, bundle, _fixture = self.save_synthetic_analysis(('unexpected', None, '中'))
        before = state.result_json
        identities = [self.m.vehicle_analysis_proposal_ids(item)
                      for item in bundle['analysis']['recommendations']]
        for _ in range(2):
            response = self.client.get(self.url.split('?')[0])
            self.assertEqual(response.status_code, 200)
            data = response.json
            self.assertNotIn('priority_preview', data)
            proposals = data['analysis']['recommendations']
            self.assertEqual([item['priority'] for item in proposals], ['unexpected', None, '中'])
            self.assertEqual([(item['proposal_id'], item['proposal_revision']) for item in proposals], identities)
            self.assertEqual([item['action'] for item in proposals],
                             [item['action'] for item in bundle['analysis']['recommendations']])
            self.assertEqual(self.m.VehicleKarteAnalysis.query.get(state.id).result_json, before)

    def test_repeated_preview_is_stable_and_does_not_accumulate_annotations(self):
        state, _bundle, fixture = self.save_synthetic_analysis()
        self.install(fixture)
        before = state.result_json
        first = self.client.get(self.url).json
        second = self.client.get(self.url).json
        self.assertEqual(first, second)
        self.assertEqual(state.result_json, before)

    def test_actual_api_payload_matches_shared_browser_contract(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node is required for cross-runtime contract validation')
        _state, _bundle, fixture = self.save_synthetic_analysis(('低', '高'))
        self.install(fixture)
        payload = self.client.get(self.url).get_data(as_text=True)
        script = "const p=require('./static/js/vehicle_priority_preview.js');let s='';process.stdin.on('data',d=>s+=d);process.stdin.on('end',()=>{const r=p.validate(JSON.parse(s));if(!r.available||r.items.length!==2)process.exit(1);});"
        result = subprocess.run([node, '-e', script], input=payload, text=True, capture_output=True,
                                cwd=Path(__file__).resolve().parents[1], timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_html_preview_requires_enabled_isolated_admin_access(self):
        _state, _bundle, fixture = self.save_synthetic_analysis()
        routes = [f'/vehicle/karte/{self.vehicle.id}?priority_preview=1',
                  f'/vehicle/karte/{self.vehicle.id}/analysis?priority_preview=1']
        for url in routes:
            self.assertEqual(self.client.get(url).status_code, 404)
        self.install(fixture)
        for url in routes:
            self.assertEqual(self.client.get(url).status_code, 200)
            with patch.dict(os.environ, {'RENDER': 'true'}):
                self.assertEqual(self.client.get(url).status_code, 404)
        self.m.User.query.filter_by(username='admin', company_code='TEST').one().role = 'user'
        self.m.db.session.commit()
        for url in routes:
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_html_preview_first_and_other_vehicle_get_do_not_save_last_vehicle(self):
        _state, _bundle, fixture = self.save_synthetic_analysis()
        self.install(fixture)
        other = self.m.Vehicle(company_code='TEST', chassis_number='SYNTHETIC-SECOND')
        self.m.db.session.add(other)
        user = self.m.User.query.filter_by(username='admin', company_code='TEST').one()
        user.dashboard_settings_json = '{"synthetic_keep": "unchanged"}'
        self.m.db.session.commit()
        before = user.dashboard_settings_json
        writes = []
        def inspect_sql(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().split(None, 1)[0].upper() in {'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP', 'REPLACE'}:
                writes.append(statement.split(None, 1)[0])
        event.listen(self.m.db.engine, 'before_cursor_execute', inspect_sql)
        try:
            for vehicle_id in [self.vehicle.id, other.id, self.vehicle.id]:
                for suffix in ['', '/analysis']:
                    response = self.client.get(f'/vehicle/karte/{vehicle_id}{suffix}?priority_preview=1')
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('優先度の試算・表示のみ読み取り専用', response.get_data(as_text=True))
            self.assertEqual(writes, [])
            self.m.db.session.expire_all()
            self.assertEqual(user.dashboard_settings_json, before)
        finally:
            event.remove(self.m.db.engine, 'before_cursor_execute', inspect_sql)
        data = self.client.get(f'/vehicle/karte/{other.id}/analysis/result?priority_preview=1').json
        self.assertEqual(data['priority_preview']['status'], 'blocked')

    def test_normal_overview_still_saves_last_vehicle_and_exposes_note_edit(self):
        _state, _bundle, fixture = self.save_synthetic_analysis()
        self.install(fixture)
        text = self.client.get(f'/vehicle/karte/{self.vehicle.id}').get_data(as_text=True)
        user = self.m.User.query.filter_by(username='admin', company_code='TEST').one()
        self.assertEqual(json.loads(user.dashboard_settings_json)['vehicle_karte_last_vehicle_id'], self.vehicle.id)
        self.assertIn('data-note-edit', text)
        self.assertIn('data-note-form', text)
        self.assertNotIn('priority-preview-context-banner', text)
        preview_text = self.client.get(f'/vehicle/karte/{self.vehicle.id}?priority_preview=1').get_data(as_text=True)
        self.assertNotIn('data-note-edit', preview_text)
        self.assertNotIn('data-note-form', preview_text)

    def test_preview_notification_marker_and_normal_return_are_server_scoped(self):
        _state, _bundle, fixture = self.save_synthetic_analysis()
        self.install(fixture)
        for suffix in ['', '/analysis']:
            base = f'/vehicle/karte/{self.vehicle.id}{suffix}'
            preview_response = self.client.get(base + '?priority_preview=1')
            self.assertEqual(preview_response.status_code, 200)
            text = preview_response.get_data(as_text=True)
            self.assertEqual(PreviewHTML(text).body.get('data-priority-preview'), 'true')
            exit_links = [a for a in PreviewHTML(text).links
                          if a.get('href') == base]
            self.assertGreaterEqual(len(exit_links), 1)
            normal = self.client.get(exit_links[0]['href'])
            self.assertEqual(normal.status_code, 200)
            self.assertEqual(PreviewHTML(normal.get_data(as_text=True)).body.get('data-priority-preview'), 'false')
        # A query on an unrelated normal view cannot declare a trusted preview.
        normal_history = self.client.get(f'/master/vehicles/{self.vehicle.id}/karte/history?priority_preview=1')
        self.assertEqual(normal_history.status_code, 200)
        self.assertEqual(PreviewHTML(normal_history.get_data(as_text=True)).body.get('data-priority-preview'), 'false')

    def test_preview_analysis_post_is_rejected_before_ai(self):
        _state, _bundle, fixture = self.save_synthetic_analysis()
        self.install(fixture)
        with patch.object(self.m, 'analyze_vehicle_karte') as ai:
            response = self.client.post(f'/vehicle/karte/{self.vehicle.id}/analysis?priority_preview=1')
        self.assertEqual(response.status_code, 405)
        ai.assert_not_called()

    def test_preview_tabs_and_usage_switches_preserve_trial_only_for_trial_pages(self):
        _state, _bundle, fixture = self.save_synthetic_analysis()
        self.install(fixture)
        other = self.m.Vehicle(company_code='TEST', chassis_number='SYNTHETIC-SWITCH')
        self.m.db.session.add(other)
        self.m.db.session.flush()
        self.m.db.session.add(self.m.Driver(company_code='TEST', employee_id='admin', name='Synthetic',
            vehicles_json=json.dumps([str(self.vehicle.id), str(other.id)])))
        self.m.db.session.commit()
        for suffix in ['', '/analysis']:
            base = f'/vehicle/karte/{self.vehicle.id}{suffix}'
            text = self.client.get(base+'?priority_preview=1').get_data(as_text=True)
            links = PreviewHTML(text).links
            tabs = [a for a in links if a.get('class') == 'vehicle-karte-tab']
            self.assertEqual(len(tabs), 8)
            for a in tabs:
                target = urlsplit(a['href'])
                trial = target.path in [f'/vehicle/karte/{self.vehicle.id}', f'/vehicle/karte/{self.vehicle.id}/analysis']
                self.assertEqual(parse_qs(target.query).get('priority_preview') == ['1'], trial)
            switches = [a for a in links if 'karte-vehicle-switcher-link' in a.get('class', '').split()]
            self.assertEqual(len(switches), 2)
            for a in switches:
                self.assertEqual(parse_qs(urlsplit(a['href']).query).get('priority_preview'), ['1'])
                self.assertEqual(self.client.get(a['href']).status_code, 200)
            normal_tabs = [a for a in PreviewHTML(self.client.get(base).get_data(as_text=True)).links if a.get('class') == 'vehicle-karte-tab']
            self.assertTrue(all('priority_preview' not in a['href'] for a in normal_tabs))

    def test_preview_period_and_comparison_forms_preserve_trial(self):
        self.vehicle.model_code = 'SYNTHETIC-MODEL'
        _state, _bundle, fixture = self.save_synthetic_analysis()
        self.install(fixture)
        url = f'/vehicle/karte/{self.vehicle.id}/analysis'
        text = self.client.get(url+'?priority_preview=1').get_data(as_text=True)
        forms = [f for f in PreviewHTML(text).forms if f.get('class') in ['ka-period-form', 'ka7-peer-conditions']]
        self.assertEqual(len(forms), 2)
        for form in forms:
            fields = dict(form['fields'], start_date='2026-01-01', end_date='2026-11-10')
            self.assertEqual(fields['priority_preview'], '1')
            response = self.client.get(urlsplit(form['action']).path+'?'+urlencode(fields))
            self.assertEqual(response.status_code, 200)
            self.assertIn('priority-preview-context-banner', response.get_data(as_text=True))
        normal_forms = [f for f in PreviewHTML(self.client.get(url).get_data(as_text=True)).forms if f.get('class') in ['ka-period-form', 'ka7-peer-conditions']]
        self.assertTrue(all('priority_preview' not in f['fields'] for f in normal_forms))

    def test_preview_coupling_overview_link_preserves_trial(self):
        from dkss_app.models import VehicleCoupling
        _state, _bundle, fixture = self.save_synthetic_analysis()
        self.install(fixture)
        self.vehicle.type = 'トラクタ'
        trailer = self.m.Vehicle(company_code='TEST', chassis_number='SYNTHETIC-TRAILER', type='トレーラ')
        self.m.db.session.add(trailer)
        self.m.db.session.flush()
        self.m.db.session.add(VehicleCoupling(company_code='TEST', towing_vehicle_id=self.vehicle.id,
            trailer_vehicle_id=trailer.id, kind='semi', created_at='2026-11-10T00:00:00', created_by_username='admin'))
        self.m.db.session.commit()
        text = self.client.get(f'/vehicle/karte/{self.vehicle.id}?priority_preview=1').get_data(as_text=True)
        target_links = [a for a in PreviewHTML(text).links if urlsplit(a.get('href','')).path == f'/vehicle/karte/{trailer.id}']
        self.assertGreaterEqual(len(target_links), 2)
        self.assertTrue(all(parse_qs(urlsplit(a['href']).query).get('priority_preview') == ['1'] for a in target_links))


del _Base
