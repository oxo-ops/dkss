"""Optional confirmation forms and normal generation on synthetic source records.

Source readers, routes, scoring, queue/job and persistence are real. Only model
urllib transport returns a synthetic empty recommendation response; no external
AI/OCR request is made and no result JSON is seeded directly.

Browser POSTs remain limited to the two confirmation endpoints. The controlled
background helper may change only this vehicle's normal analysis state, which is
re-protected after the job. Other business records and prior audit rows remain
protected; only the target vehicle's input epoch/read cache are exempt. The
manufacturer history branch explicitly revises/restores one original PDF field,
verifies the complete database delta, and rebases only that owned row. After the
real carry job, one saved source-map entry is deliberately removed with the same
exact-field protection. No candidate, proof, score or gap response is seeded.

These are prepared acceptance assertions, not a claim of browser execution.
Existing GET-only scenarios do not import this module.
"""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from io import BytesIO
import hashlib
from unittest.mock import patch
import json
import os
from pathlib import Path
from urllib.parse import urlsplit, urljoin
from native_pdf_navigation import NativePdfNavigation

KINDS = {'confirmation_manufacturer': 'manufacturer_immediate',
         'confirmation_legal': 'legal_deadline', 'confirmation_progression': 'progression'}
WIDTHS = ((1440, 900), (1024, 768), (768, 1024), (390, 780), (320, 640))
CONFIRM, WITHDRAW = '優先度根拠確認', '優先度根拠取消'
# Normal screen bookkeeping only. Every business/source/analysis table and user
# row remains protected. Event appends are inspected separately, never excluded.
BOOKKEEPING = {'analysis_input_epoch', 'analysis_input_read_cache'}
SOURCE_GAP_MESSAGE = ('前回保存時の出典リンクが一部残っていません。保存された区分・確認者・日時・原文だけを示しています。'
                      '現在の条件成立や点数を示すものではありません。')


def require(value, message):
    if not value:
        raise AssertionError(message)


class Markup(HTMLParser):
    def __init__(self, html):
        super().__init__(); self.csrf = None; self.depth = 0; self.nested = False
        self.confirmation_forms = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'meta' and attrs.get('name') == 'csrf-token': self.csrf = attrs.get('content')
        if tag == 'form':
            self.nested |= self.depth > 0
            self.depth += 1
            self.confirmation_forms.extend(k for k in attrs if k in
                ('data-confirmation-selection', 'data-confirmation-preview'))

    def handle_endtag(self, tag):
        if tag == 'form': self.depth = max(0, self.depth - 1)


class Fixture:
    def __init__(self, scenario, report):
        if scenario == 'confirmation_manufacturer':
            from test_priority_manufacturer_workflow import ManufacturerConfirmationWorkflowTests
            self.case = ManufacturerConfirmationWorkflowTests()
        elif scenario == 'confirmation_legal':
            from test_priority_certificate_sources import CertificateSourceTests
            self.case = CertificateSourceTests()
        else:
            from test_priority_progression_workflow import ProgressionWorkflowTests
            self.case = ProgressionWorkflowTests()
        self.kind, self.report = KINDS[scenario], report
        self.started = self.setup = False
        self.background_confirmations = set()
        self.original_downloads = {}
        self.background_items = {}
        self.missing_source_id = None

    def start(self):
        c = self.case
        c.setUpClass(); self.started = True; c.setUp(); self.setup = True
        if self.kind == 'manufacturer_immediate':
            # Use the certificate fixture's synthetic model before either source
            # is prepared. FICTIONAL-ONLY is an explicit nonofficial PDF marker.
            c.vehicle.model_code = 'TESTMODEL'
            c.db.session.commit()
            c.use_original_instruction_only()
            self.prepare_manufacturer_companion()
        if self.kind == 'progression':
            self.prepare_background_observations()
            c.prepare_pair(same_day=True)
        if self.kind == 'legal_deadline':
            # Already expired: independent of interpretation of the expiry day.
            expiry = (c.day - timedelta(days=1)).isoformat()
            c.document.status = 'deleted'; c.vehicle.inspection_expiry = expiry
            c.document = c.add_document(expiry); c.selection = {'document_id': c.document.id}
        c.login('admin')
        # The unittest keeps one app context across requests; clear the token
        # cached before fixture login reset its session. Real requests have a
        # fresh app context and do not need this fixture-only housekeeping.
        from flask import g
        g.pop('csrf_token', None)
        self.db, self.app = c.db, c.app
        self.vehicle_id = c.vehicle.id  # Primitive: safe inside Playwright route greenlets.
        self.url = f'/vehicle/karte/{c.vehicle.id}/priority-confirmations'
        self.analysis = f'/vehicle/karte/{c.vehicle.id}/analysis'
        self.overview = f'/vehicle/karte/{c.vehicle.id}'
        self.post_paths = {self.url, self.url + '/preview'}
        root = Path(os.environ['DKSS_VALIDATION_TMP']).resolve()
        require(self.db.engine.url.drivername == 'sqlite' and
                Path(self.db.engine.url.database).resolve().is_relative_to(root), 'Wrong fixture database')
        # Authentication is synthetic. CSRF is real for every confirmation action.
        self.app.config['WTF_CSRF_ENABLED'] = True
        for path in (self.overview, self.analysis):
            response = c.client.get(path)
            require(response.status_code == 200, f'Normal page failed: {path}')
        markup = Markup(response.get_data(as_text=True))
        require(markup.csrf and not markup.nested, 'Missing CSRF or nested forms')
        require(set(markup.confirmation_forms) == {'data-confirmation-selection', 'data-confirmation-preview'},
                'Separate optional forms missing')
        self.csrf = markup.csrf
        # base.js immediately polls this normal route. Prime its initial alert
        # bookkeeping before the protected baseline, without excluding its table.
        warm = c.client.get('/api/notifications/unread-count')
        require(warm.status_code == 200, 'Normal unread-count warm-up failed')
        self.saved = self.snapshot()
        self.original_events = self.events()
        self.seen_events = dict(self.original_events)
        self.selection = dict(c.selection)
        if self.kind == 'manufacturer_immediate':
            self.selection = {'observation_input_ref': c.selection['observation_input_ref']}
            data = self.options(self.selection)
            self.selection['manufacturer_rule'] = self.option(data, 'manufacturer_rule')
            data = self.options(self.selection)
            for key in ('condition_quote', 'action_quote'): self.selection[key] = self.option(data, key)
        self.report['fixture'] = dict(synthetic=True, csrf_enabled=True, source_readers_mocked=False,
            external_ai_or_ocr_called=False, ai_transport_only_mocked=True, scoring_mocked=False, kind=self.kind,
            progression_same_day=self.kind == 'progression', permitted_post_paths=sorted(self.post_paths),
            bookkeeping_exceptions='Only this company/vehicle epoch and read-cache rows',
            controlled_generation_exception='Only this company/vehicle normal analysis state, during queue/job helper',
            background_confirmation_count=len(self.background_confirmations))
        return self

    def prepare_manufacturer_companion(self):
        """One independent current candidate, via real certificate/confirmation."""
        from test_priority_certificate_sources import CertificateSourceTests
        c = self.case
        expiry = (c.day - timedelta(days=1)).isoformat()
        c.vehicle.chassis_number = 'TEST-12345'
        c.vehicle.inspection_expiry = expiry
        c.db.session.commit()
        document = CertificateSourceTests.add_document(c, expiry)
        c.login('admin')
        url = f'/vehicle/karte/{c.vehicle.id}/priority-confirmations'
        preview = c.client.post(url + '/preview', json=dict(
            kind='legal_deadline', selection={'document_id': document.id}))
        require(preview.status_code == 200, 'Companion certificate preview failed')
        saved = c.client.post(url, json=self.confirmation_body(preview.json))
        require(saved.status_code == 200, 'Companion certificate confirmation failed')
        self.background_confirmations.add(saved.json['event_id'])
        self.report['manufacturer_companion'] = dict(kind='legal_deadline',
            document_id=document.id, event_id=saved.json['event_id'],
            setup='Synthetic source before baseline; real preview/save and normal job; no proposal JSON seed')

    def prepare_background_observations(self):
        """Five real distinct events, not seeded result JSON, for the top-five UI."""
        c = self.case
        old_day = c.day - timedelta(days=9)
        baseline = c.begin(old_day)
        c.repair(day=old_day)
        c.repair(day=old_day, recheck='異常なし', hour=10, minute=30)
        resolution = c.models.ChecklistEvent.query.filter_by(result_type='vehicle',
            result_id=c.row.id, event_type='解消').one()
        for offset in range(5):
            current = c.begin(c.day - timedelta(days=8-offset))
            c.selection = {'current_observation': current + '|reported',
                'baseline_observation': baseline + f'|event:{resolution.id}', 'relation': 'recurrent'}
            c.login('admin')
            event_id, _ = c.confirm()
            self.background_confirmations.add(event_id)

    @staticmethod
    def option(data, key):
        options = next(f for f in data['form']['fields'] if f['key'] == key)['options']
        require(options, f'No real source option: {key}')
        return options[0]['value']

    def snapshot(self):
        self.db.session.expire_all()
        result = {}
        for table in self.db.metadata.sorted_tables:
            if table.name == 'checklist_event': continue
            rows = self.db.session.execute(table.select().order_by(*table.primary_key.columns)).mappings()
            protected = []
            for row in rows:
                if table.name == 'analysis_input_epoch' and row['company_code'] == 'A' and row['bucket'] == f'vehicle:{self.vehicle_id}':
                    continue
                if table.name == 'analysis_input_read_cache' and row['company_code'] == 'A' and row['vehicle_record_id'] == self.vehicle_id:
                    continue
                protected.append(tuple(row.values()))
            result[table.name] = protected
        return result

    def analysis_others(self, rows):
        table = self.case.models.VehicleKarteAnalysis.__table__
        keys = [column.name for column in table.columns]
        owner, vehicle = keys.index('company_code'), keys.index('vehicle_record_id')
        return [row for row in rows if not (row[owner] == 'A' and row[vehicle] == self.vehicle_id)]

    def events(self):
        table = self.case.models.ChecklistEvent.__table__
        require(table.name == 'checklist_event', 'Event protection table mismatch')
        return {row['id']: dict(row) for row in self.db.session.execute(table.select()).mappings()}

    def protected(self, *, allow_append=False, allow_analysis=False):
        current = self.snapshot()
        analysis_table = self.case.models.VehicleKarteAnalysis.__table__.name
        compared, baseline = dict(current), dict(self.saved)
        if allow_analysis:
            compared[analysis_table] = self.analysis_others(compared[analysis_table])
            baseline[analysis_table] = self.analysis_others(baseline[analysis_table])
            require(self.case.models.VehicleKarteAnalysis.query.filter_by(company_code='A',
                vehicle_record_id=self.vehicle_id).count() == 1, 'Only one target analysis state may change')
        changed = sorted(k for k in set(compared) | set(baseline) if compared.get(k) != baseline.get(k))
        require(not changed, 'Protected tables changed: ' + ', '.join(changed))
        events = self.events()
        require(all(events.get(key) == value for key, value in self.seen_events.items()), 'Existing event changed/deleted')
        new = {key: value for key, value in events.items() if key not in self.seen_events}
        require(allow_append or not new, 'Read/rejected request appended an event')
        for value in new.values():
            require(value['company_code'] == 'A' and value['result_type'] == 'vehicle_priority'
                    and value['result_id'] == self.vehicle_id and value['event_type'] in (CONFIRM, WITHDRAW),
                    'Unexpected event append')
        self.seen_events = events

    def count(self):
        return len(self.events()) - len(self.original_events)

    def request(self, method, path, *, body=None, csrf=True, raw=None, headers=None):
        # Sync Playwright RouteGreenlet does not inherit the fixture's contextvars.
        # Cover both Flask dispatch and every protection query in this context.
        with self.app.app_context():
            require(method == 'GET' or (method == 'POST' and path in self.post_paths), 'Forbidden bridge write')
            if method == 'GET': response = self.case.client.get(path)
            else:
                kwargs = {'headers': headers if headers is not None else
                          ({'X-CSRFToken': self.csrf} if csrf else {})}
                if raw is not None: kwargs.update(data=raw, content_type='application/json')
                else: kwargs['json'] = body
                response = self.case.client.post(path, **kwargs)
            entry = dict(method=method, path=urlsplit(path).path, status=response.status_code)
            if urlsplit(path).path in self.original_downloads:
                entry['source_sha256'] = hashlib.sha256(response.get_data()).hexdigest()
                require(entry['source_sha256'] == self.original_downloads[urlsplit(path).path], 'Original response bytes changed')
            self.report['requests'].append(entry)
            self.protected(allow_append=method == 'POST' and path == self.url and response.status_code == 200)
            return response

    def options(self, selection=None):
        from urllib.parse import urlencode
        path = self.url + '?' + urlencode({'kind': self.kind, 'selection': json.dumps(selection or {})})
        response = self.request('GET', path)
        require(response.status_code == 200 and response.json['can_confirm'], 'Options unavailable')
        return response.json

    def preview(self, replace=None):
        response = self.request('POST', self.url + '/preview', body=dict(kind=self.kind,
            selection=self.selection, replace_event_id=replace))
        require(response.status_code == 200, f'Real source preview failed ({response.status_code}, {response.headers.get("Location")}): ' + response.get_data(as_text=True))
        result = response.json
        require(result['preview']['display_sources'] and result['preview']['statements'], 'Empty original preview')
        require('effective_score' not in result['preview'], 'Preview is not a score-entry form')
        return result

    @staticmethod
    def confirmation_body(prepared):
        return dict(token=prepared['token'], statements=[s['key'] for s in prepared['preview']['statements']])

    def history(self):
        return self.options(self.selection)['history']

    def assert_state(self, count, active):
        require(self.count() == count, f'Expected {count} append-only events, got {self.count()}')
        history = self.history()
        require(sum(row['status'] == 'active' for row in history) == active + len(self.background_confirmations), 'Wrong active confirmation count')
        require(self.background_confirmations <= {row['event_id'] for row in history if row['status'] == 'active'}, 'Unrelated confirmation changed')
        self.protected()

    def generate(self):
        """Drive the real background queue/job; never assign result_json here."""
        from dkss_app import analysis as service
        import vehicle_karte_analysis_ai as generator
        self.protected()
        with self.app.test_request_context('/'):
            payload, _ = service.get_vehicle_karte_analysis_job_data(self.case.vehicle)
            state = service.queue_vehicle_karte_analysis(self.case.vehicle, payload)
        # Advance only the synthetic worker's due time, not its inputs/results.
        state.next_analysis_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.db.session.commit()
        self.protected(allow_analysis=True)
        calls, observations, analyzer_calls = [], [], []
        # Observe actual Python frames without replacing analyzer, queue or job.
        # analysis_method='ai' can still take the real no-source early return.
        import sys
        analyzer_code = generator.analyze_vehicle_karte.__code__
        once_code = generator._analyze_vehicle_karte_once.__code__
        no_sources_result = {'overview': '分析の根拠となる履歴がありません。', 'recommendations': []}
        def evidence_ids(payload):
            ids = {str(row['source_id']) for row in payload.get('records', [])}
            for fact in payload.get('preventive_facts', {}).get('part_replacements', []):
                ids.update(str(sid) for sid in fact.get('source_ids', []))
            vehicle_source = payload.get('vehicle_source', {}).get('source_id')
            if vehicle_source: ids.add(str(vehicle_source))
            knowledge_ids = {str(item['source_id']) for item in payload.get('maintenance_knowledge', [])}
            confirmed_ids = {sid for offer in generator.generation_priority_inputs(payload).values()
                if offer.get('kind') == 'confirmed_priority' for sid in offer.get('source_ids', [])
                if isinstance(sid, str)}
            return sorted(ids | (confirmed_ids - knowledge_ids))
        def observe(frame, event, returned):
            if frame.f_code is analyzer_code and event == 'call':
                analyzer_calls.append(True)
            if frame.f_code is not once_code: return
            if event == 'call':
                observations.append(dict(input_vehicle_evidence_ids=evidence_ids(frame.f_locals['payload'])))
            elif event == 'return' and observations:
                observations[-1].update(
                    actual_vehicle_evidence_ids=sorted(frame.f_locals.get('vehicle_evidence_ids', [])),
                    source_set_constructed='vehicle_evidence_ids' in frame.f_locals,
                    exact_no_source_return=returned == no_sources_result)
        def empty_model(request, **kwargs):
            require(request.full_url == 'https://api.openai.com/v1/responses' and
                    request.get_method() == 'POST', 'Unexpected model transport endpoint or method')
            require(not calls, 'Unexpected multiple model transport calls')
            wire = generator.expand_vehicle_karte_analysis_wire_payload(json.loads(json.loads(request.data)['input']))
            require('_confirmed_priority_candidates' not in wire, 'Server candidates leaked into model transport')
            calls.append(wire)
            result = {'overview': '合成空応答。検証済み根拠の補完は実サーバー処理。', 'recommendations': []}
            return BytesIO(json.dumps({'status': 'completed', 'output': [{'content': [
                {'type': 'output_text', 'text': json.dumps(result)}]}]}).encode())
        require(sys.getprofile() is None, 'Unexpected existing profiler; do not replace it')
        try:
            sys.setprofile(observe)
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-local-test-only'}), \
                    patch.object(generator.urllib.request, 'urlopen', side_effect=empty_model):
                require(service.run_vehicle_karte_analysis_job(state.id), 'Normal analysis job failed')
        finally:
            sys.setprofile(None)
            self.report.setdefault('generation_source_observations', []).append(dict(
                analyzer_calls=len(analyzer_calls), sources=observations, transport_calls=len(calls)))
        self.db.session.refresh(state)
        require(state.status == 'completed', 'Normal analysis job did not complete')
        method = json.loads(state.result_json)['analysis_method']
        require(method in ('ai', 'record_check'), 'Unexpected analysis method')
        require(len(analyzer_calls) == len(observations) == int(method == 'ai'),
                'Normal analyzer entry count changed')
        expected_calls = 0
        if method == 'ai':
            observed = observations[0]
            require(observed['source_set_constructed'] and
                    observed['input_vehicle_evidence_ids'] == observed['actual_vehicle_evidence_ids'],
                    'Actual generator sources differ from its observed input')
            expected_calls = int(bool(observed['input_vehicle_evidence_ids']))
            if not expected_calls:
                require(observed['exact_no_source_return'], 'Zero-source generator return was replaced')
        require(len(calls) == expected_calls, f'Unexpected model transport calls: {len(calls)} for {method}')
        self.protected(allow_analysis=True)
        table = self.case.models.VehicleKarteAnalysis.__table__.name
        # Re-protect the saved target result immediately after the controlled job.
        # All unrelated rows were compared above and are never rebased silently.
        self.saved[table] = self.snapshot()[table]
        data = self.read_result()
        require(data['is_current'] is True and data['status'] == 'completed', 'Normal GET is not current after job')
        self.report.setdefault('generations', []).append(dict(state_id=state.id,
            transport_calls=len(calls), analysis_method=method, model_recommendations=0,
            saved_recommendations=len(json.loads(state.result_json)['analysis']['recommendations']),
            result_sha256=hashlib.sha256(state.result_json.encode()).hexdigest()))
        return data

    def read_result(self):
        response = self.request('GET', self.analysis + '/result')
        require(response.status_code == 200 and response.json['ok'], 'Normal result GET failed')
        return response.json

    def assert_generated(self, data, active_event=None, previous_ids=None):
        items = data['analysis']['recommendations']
        expected = len(self.background_confirmations) + int(active_event is not None)
        require(len(items) == expected, 'Verified candidate missing or duplicate')
        ids = {item['proposal_id'] for item in items}
        require(len(ids) == expected, 'Duplicate generated proposal IDs')
        if previous_ids is not None: require(ids == previous_ids, 'Unrelated proposal disappeared after cancellation')
        score = 65 if self.kind == 'progression' else 60
        for item in items:
            assessment = item['priority_assessment']
            require((assessment['label'], assessment['effective_score']) == ('高', score), 'Wrong completed common assessment')
        if active_event is None:
            self.assert_background(items)
            return None
        selected = [item for item in items if any(value['event_id'] == active_event for value in
            item['priority_assessment'].get('confirmation_details_list', []) or
            [item['priority_assessment']['confirmation_details']])]
        require(len(selected) == 1, 'Saved confirmation does not identify exactly one completed candidate')
        require(selected[0]['priority_assessment']['confirmation_details']['kind'] == self.kind, 'Wrong confirmation source')
        if self.kind == 'manufacturer_immediate':
            others = [value for value in items if value['proposal_id'] != selected[0]['proposal_id']]
            require(len(others) == 1, 'One independently generated companion required')
            if not self.background_items:
                self.background_items = {value['proposal_id']: deepcopy(value) for value in others}
            self.assert_background(others)
        return selected[0]

    def assert_background(self, items):
        if self.kind != 'manufacturer_immediate':
            return
        require(self.background_items and {v['proposal_id'] for v in items} == set(self.background_items),
                'Independent companion identity changed')
        for value in items:
            previous = self.background_items[value['proposal_id']]
            for key in ('proposal_id', 'priority_input_ref', 'source_ids', 'target', 'title', 'action'):
                require(value[key] == previous[key], 'Companion source/subject/action changed: ' + key)
            assessment = value['priority_assessment']
            require((assessment['label'], assessment['effective_score'], assessment['calculation_status']) ==
                    ('高', 60, 'computed'), 'Companion lost its current legal assessment')
            require(not assessment.get('historical_source_gaps') and not value.get('priority_candidate_carryover'),
                    'Independent companion was converted into history')
            details = assessment['confirmation_details']
            require(details == previous['priority_assessment']['confirmation_details'] and
                    details['kind'] == 'legal_deadline' and details['event_id'] in self.background_confirmations,
                    'Companion original confirmation changed')

    def replace_manufacturer_original(self, replacement, phase):
        """Permit one explicit fixture PDF-field change, never a table exclusion."""
        require(self.kind == 'manufacturer_immediate' and phase in {'revision', 'restore'},
                'Original revision is only a manufacturer fixture operation')
        require(isinstance(replacement, bytes) and replacement.startswith(b'%PDF-'),
                'A synthetic PDF original is required')
        self.protected()
        table = self.case.document.__table__
        require(table.name == 'maintenance_knowledge_document', 'Unexpected original table')
        document_id = self.case.document.id
        columns = [column.name for column in table.columns]
        id_at, company_at, data_at = (columns.index(name) for name in ('id', 'company_code', 'original_data'))
        rows = list(self.saved[table.name])
        matching = [index for index, row in enumerate(rows)
                    if row[id_at] == document_id and row[company_at] == 'A']
        require(len(matching) == 1, 'Original change must identify one owned row')
        index = matching[0]
        before = rows[index][data_at]
        require(before != replacement, 'Original change must be explicit')
        changed = list(rows[index]); changed[data_at] = replacement
        rows[index] = tuple(changed)
        expected = dict(self.saved); expected[table.name] = rows
        updated = self.db.session.execute(table.update().where(
            table.c.id == document_id, table.c.company_code == 'A').values(original_data=replacement))
        require(updated.rowcount == 1, 'Original change affected another row')
        self.db.session.commit()
        require(self.snapshot() == expected, 'Original change touched more than one allowed row/field')
        require(self.events() == self.seen_events, 'Original change mutated audit history')
        # Rebase only this exact row after proving all other tables/columns equal.
        self.saved[table.name][index] = rows[index]
        self.protected()
        self.report.setdefault('intentional_source_changes', []).append(dict(
            table=table.name, row_id=document_id, field='original_data', phase=phase,
            before_sha256=hashlib.sha256(before).hexdigest(),
            after_sha256=hashlib.sha256(replacement).hexdigest()))
        return before

    def revise_manufacturer_original(self):
        from test_priority_manufacturer_evidence import original_pdf
        return self.replace_manufacturer_original(
            original_pdf('REVISED-SYNTHETIC-ORIGINAL-ONLY. The former instruction is absent.'), 'revision')

    def assert_historical(self, data, previous_item, previous_generated_at):
        require(data['status'] == 'completed' and data['is_current'] is True,
                'Historical display must come from the completed normal job')
        items = data['analysis']['recommendations']
        matching = [value for value in items if value['proposal_id'] == previous_item['proposal_id']]
        require(len(matching) == 1 and len(items) == 1 + len(self.background_items),
                'Historical candidate identity was lost or duplicated')
        self.assert_background([value for value in items if value['proposal_id'] != previous_item['proposal_id']])
        item = matching[0]; assessment = item['priority_assessment']
        original = previous_item['priority_assessment']['confirmation_details']
        require((assessment['label'], assessment['effective_score']) == ('高', None),
                'Historical class must not become a current numeric score')
        require(assessment['calculation_status'] == 'legacy_preserved', 'Historical result was recalculated')
        require(not assessment.get('confirmation_details') and not assessment.get('confirmation_details_list'),
                'Old confirmation was presented as current')
        require(assessment.get('historical_confirmation_details') == [original],
                'Historical actor/time/statements/original text changed')
        prior = assessment.get('previous_result') or {}
        require(prior.get('label') == '高' and prior.get('reason') and
                prior.get('confirmed_at') == [original['confirmed_at']] and
                prior.get('previous_generated_at') == previous_generated_at,
                'Historical attribution or saved-generation time missing')
        if self.missing_source_id:
            require(self.missing_source_id not in data['sources'], 'Missing source was silently fabricated')
            require(assessment.get('historical_source_gaps') == dict(
                version='saved-confirmed-source-gaps-v1', source_ids=[self.missing_source_id],
                message=SOURCE_GAP_MESSAGE), 'Scoped historical source-gap response mismatch')
        else:
            require(not assessment.get('historical_source_gaps'), 'Unmodified carry acquired a source gap')
        self.protected()
        return item

    def omit_saved_manufacturer_metadata(self, previous_item):
        """Inject one missing link after the real carry job, not a fake result."""
        require(self.kind == 'manufacturer_immediate' and self.missing_source_id is None,
                'Source omission is a one-time manufacturer fixture action')
        self.protected()
        table = self.case.models.VehicleKarteAnalysis.__table__
        columns = [column.name for column in table.columns]
        owner, vehicle, result_at, id_at = (columns.index(name) for name in
            ('company_code', 'vehicle_record_id', 'result_json', 'id'))
        rows = list(self.saved[table.name])
        matching = [i for i, row in enumerate(rows) if row[owner] == 'A' and row[vehicle] == self.vehicle_id]
        require(len(matching) == 1, 'Source omission must identify one owned analysis row')
        index = matching[0]; before = rows[index][result_at]
        original = json.loads(before); changed = deepcopy(original)
        sid = f'knowledge:{self.case.knowledge.id}'
        require(isinstance(original['sources'].get(sid), dict) and original['sources'][sid].get('url'),
                'The selected saved source metadata must exist before omission')
        proposals = original['analysis']['recommendations']
        selected = [v for v in proposals if v['priority_input_ref'] == previous_item['priority_input_ref']]
        require(len(selected) == 1 and sid in selected[0]['source_ids'], 'Missing source is not on the saved manufacturer candidate')
        carried = selected[0]; marker = carried.get('priority_candidate_carryover') or {}
        require(marker.get('version') == 'previous-confirmed-priority-result-v1' and
                marker.get('original_revision') == previous_item['proposal_revision'] and
                carried.get('priority_historical_confirmations') ==
                    [previous_item['priority_assessment']['confirmation_details']],
                'Only an actual normally generated carry may lose this metadata')
        require(all(f'priority_confirmation:{value["event_id"]}' in original['sources']
                    for value in carried['priority_historical_confirmations']), 'Saved audit metadata missing')
        removed = changed['sources'].pop(sid)
        require({**changed['sources'], sid: removed} == original['sources'] and
                {k: v for k, v in changed.items() if k != 'sources'} ==
                {k: v for k, v in original.items() if k != 'sources'},
                'Source omission changed another JSON field')
        after = json.dumps(changed, ensure_ascii=False)
        expected_rows = list(rows); replacement = list(rows[index]); replacement[result_at] = after
        expected_rows[index] = tuple(replacement)
        expected = dict(self.saved); expected[table.name] = expected_rows
        updated = self.db.session.execute(table.update().where(
            table.c.id == rows[index][id_at], table.c.company_code == 'A',
            table.c.vehicle_record_id == self.vehicle_id).values(result_json=after))
        require(updated.rowcount == 1, 'Source omission changed another analysis row')
        self.db.session.commit()
        require(self.snapshot() == expected, 'Source omission changed more than the owned result_json field')
        require(self.events() == self.seen_events, 'Source omission changed confirmation audit')
        self.saved[table.name][index] = expected_rows[index]
        self.missing_source_id = sid
        self.report['intentional_saved_source_omission'] = dict(
            table=table.name, row_id=rows[index][id_at], field='result_json',
            json_path=['sources', sid], operation='remove_one_existing_metadata_entry_after_real_carry_job',
            before_sha256=hashlib.sha256(before.encode()).hexdigest(),
            after_sha256=hashlib.sha256(after.encode()).hexdigest(),
            proposals_audit_proofs_markers_and_all_other_json_unchanged=True,
            all_other_database_rows_fields_and_audit_unchanged=True)
        self.protected()

    def close(self):
        if self.setup: self.case.tearDown(); self.case.doCleanups()
        if self.started: self.case.tearDownClass()


def exercise_http(f):
    """Affected-route preflight. Does not claim DOM interaction/browser success."""
    body = dict(kind=f.kind, selection=f.selection)
    require(f.request('POST', f.url + '/preview', body=body, csrf=False).status_code == 400, 'CSRF not enforced')
    prepared = f.preview()
    for source in prepared['preview']['display_sources']:
        url = source.get('url') or ''
        if url.startswith('/vehicle/'):
            response = f.request('GET', url)
            require(response.status_code == 200, 'Preview original source is not reachable')
    save = f.confirmation_body(prepared)
    incomplete = dict(save, statements=save['statements'][:-1])
    require(f.request('POST', f.url, body=incomplete).status_code in (400, 409), 'Missing fixed statement accepted')
    f.assert_state(0, 0)
    response = f.request('POST', f.url, body=save)
    require(response.status_code == 200, 'Confirmation failed')
    event_id = response.json['event_id']; f.assert_state(1, 1)
    require(f.request('POST', f.url, body=save).status_code == 409, 'Replay accepted')
    stale = f.preview()
    corrected = f.preview(replace=event_id)
    correction = f.request('POST', f.url, body=f.confirmation_body(corrected))
    require(correction.status_code == 200, 'Correction failed')
    active_event = correction.json['event_id']; f.assert_state(3, 1)
    generated = f.generate(); item = f.assert_generated(generated, active_event)
    remaining_ids = {v['proposal_id'] for v in generated['analysis']['recommendations']} - {item['proposal_id']}
    original_bytes = None
    if f.kind == 'manufacturer_immediate':
        original_bytes = f.revise_manufacturer_original()
        carried = f.generate()
        f.assert_historical(carried, item, generated['generated_at'])
        f.omit_saved_manufacturer_metadata(item)
        f.assert_historical(f.read_result(), item, generated['generated_at'])
        f.report['cases'].append('Manufacturer original revised in one PDF field; real carry job, then one saved source-metadata key deliberately removed; normal GET preserves previous label/actor/time/text without points, reports missing link, and retains independently confirmed current legal candidate')
    require(f.request('POST', f.url, body=f.confirmation_body(stale)).status_code == 409, 'Old preview accepted')
    cancel = {'token': next(v['cancel_token'] for v in f.history() if v['event_id'] == active_event)}
    require(f.request('POST', f.url, body=cancel).status_code == 200, 'Cancellation failed')
    f.assert_state(4, 0)
    f.assert_generated(f.read_result(), previous_ids=remaining_ids)
    f.assert_generated(f.generate(), previous_ids=remaining_ids)
    if original_bytes is not None: f.replace_manufacturer_original(original_bytes, 'restore')
    require(f.request('POST', f.url, body=cancel).status_code == 409, 'Cancellation replay accepted')
    prepared = f.preview()
    require(f.request('POST', f.url, body=f.confirmation_body(prepared)).status_code == 200, 'Cannot confirm after cancellation')
    f.assert_state(5, 1)
    f.report['cases'].append('Real options/preview/CSRF/save/replay/correction/stale revision/cancel/new confirmation; real empty-response queue/job completion and cancellation GET/regeneration; protected records unchanged outside the explicit manufacturer revision/restore and one-key saved-source omission')


def run_browser(args, f, report, out, origin):
    from playwright.sync_api import sync_playwright, expect
    captured = []
    pdf = NativePdfNavigation(report, origin)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(args.chromium.resolve()))
        report.update(browser_started=True, browser_version=browser.version)
        context = browser.new_context(service_workers='block')

        def bridge(route):
            request = route.request; parsed = urlsplit(request.url)
            same_origin = f'{parsed.scheme}://{parsed.netloc}' == origin and not parsed.username and not parsed.password
            allowed = request.method == 'GET' or (request.method == 'POST' and parsed.path in f.post_paths and not parsed.query)
            if not same_origin or not allowed:
                if pdf.abort_if_native(route): return
                report['blocked_requests'].append(dict(url=request.url, scheme=parsed.scheme,
                    method=request.method, host=parsed.hostname, path=parsed.path,
                    resource_type=request.resource_type))
                route.abort(); return
            path = parsed.path + ('?' + parsed.query if parsed.query else '')
            if request.method == 'POST':
                require(request.headers.get('content-type', '').startswith('application/json'), 'Only JSON confirmation POST allowed')
                body = json.loads(request.post_data or '{}')
                response = f.request('POST', path, raw=request.post_data,
                    headers={'X-CSRFToken': request.headers.get('x-csrftoken', '')})
                captured.append(dict(path=path, body=body, status=response.status_code))
            else:
                response = f.request('GET', path)
                if response.status_code >= 400: report['failed_gets'].append(dict(path=path, status=response.status_code))
            headers = {k: v for k, v in response.headers.items() if k.lower() not in
                       {'content-length', 'transfer-encoding', 'connection', 'set-cookie'}}
            pdf.observe_response(request, response.status_code, headers, response.get_data())
            route.fulfill(status=response.status_code, headers=headers, body=response.get_data())
        context.route('**/*', bridge)
        context.on('requestfailed', lambda request: None if pdf.record_request_failed(request) else
            report['failed_requests'].append(dict(method=request.method, url=request.url, failure=request.failure)))

        def new_page():
            p = context.new_page()
            p.on('pageerror', lambda error: report['page_errors'].append(str(error)))
            return p

        def response_is(path, method):
            return lambda r: urlsplit(r.url).path == path and r.request.method == method

        def open_form(page):
            page.goto(origin + f.analysis, wait_until='networkidle')
            root = page.locator('#priority-evidence')
            expect(root).to_be_visible()
            require(root.evaluate('(r)=>!r.closest("form") && !r.querySelector("form form")'), 'Optional form is nested')
            expect(root.locator('summary')).to_contain_text('任意')
            expect(root).to_contain_text('通常の点検や取込に追加必須の操作ではありません')
            require(root.locator('input[name="score"]').count() == 0, 'Score input appeared')
            with page.expect_response(response_is(f.url, 'GET')):
                root.locator('summary').click()
            kind = root.locator('[data-confirmation-kind]')
            if kind.input_value() != f.kind:
                with page.expect_response(response_is(f.url, 'GET')): kind.select_option(f.kind)
            expect(root.locator('[data-confirmation-controls]')).to_be_visible()
            return root

        def select_and_preview(page, root, *, select=True):
            if select:
                for key, value in f.selection.items():
                    locator = root.locator(f'[data-confirmation-fields] select[name="{key}"]')
                    if f.kind == 'manufacturer_immediate' and key in ('observation_input_ref', 'manufacturer_rule'):
                        with page.expect_response(response_is(f.url, 'GET')): locator.select_option(str(value))
                    else: locator.select_option(str(value))
                    expect(root.locator(f'select[name="{key}"]')).to_have_value(str(value))
            with page.expect_response(response_is(f.url + '/preview', 'POST')) as pending:
                root.locator('[data-confirmation-selection] button[type=submit]').click()
            response = pending.value
            require(response.status == 200, 'Browser preview failed')
            data = response.json(); preview = root.locator('[data-confirmation-preview]')
            expect(preview).to_be_visible()
            expect(root.locator('[data-confirmation-subject]')).to_have_text(data['preview']['subject'])
            for index, source in enumerate(data['preview']['display_sources']):
                article = root.locator('[data-confirmation-sources] article').nth(index)
                expect(article.locator('h5')).to_have_text(source['label'])
                expect(article.locator('p')).to_have_text(source['text'])
                if source.get('url'):
                    parsed = urlsplit(source['url'])
                    if not parsed.netloc or parsed.netloc == 'www.mlit.go.jp':
                        target = source['url'] if parsed.netloc else origin + source['url']
                        expect(article.locator('a')).to_have_attribute('href', target)
            boxes = preview.locator('input[type=checkbox][name=statement]')
            require(boxes.evaluate_all('(xs)=>xs.every(x=>x.required)') and boxes.count() == len(data['preview']['statements']), 'Fixed statements changed')
            for statement in data['preview']['statements']:
                expect(preview.locator(f'input[value="{statement["key"]}"] + span')).to_have_text(statement['label'])
            return data, preview, boxes

        def check_all(boxes):
            for index in range(boxes.count()): boxes.nth(index).check()

        def save(page, preview, expected=200, double=False):
            with page.expect_response(response_is(f.url, 'POST')) as pending:
                button = preview.locator('button[type=submit]')
                if double: button.dblclick()
                else: button.click()
            require(pending.value.status == expected, f'Unexpected save status {pending.value.status}')
            if expected == 200:
                expect(page.locator('[data-confirmation-history] article')).to_have_count(len(f.history()))
                expect(page.locator('[data-confirmation-preview]')).to_be_hidden()
                expect(page.locator('[data-confirmation-history]')).to_contain_text('確認済み')
            else:
                expect(page.locator('[data-confirmation-preview]')).to_be_hidden()
                expect(page.locator('[data-confirmation-message]')).not_to_be_empty()
            return pending.value.json()

        def replay(page, body):
            # Deliberate transport replay, distinct from the actual DOM double-click.
            result = page.evaluate('''async ({url,body}) => { const r=await fetch(url,{method:'POST',
                headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name=csrf-token]').content},
                body:JSON.stringify(body)}); return r.status; }''', {'url': f.url, 'body': body})
            require(result == 409, 'Replay not rejected')

        def completed_views(page, data, item=None, *, cancelled_id=None):
            """Real GET/poll rendering after the controlled scheduled job."""
            values = data['analysis']['recommendations']
            indices = data['analysis'].get('priority_order_indices')
            ordered = ([values[index] for index in indices] if indices is not None else
                [{value['proposal_id']: value for value in values}[key] for key in data['analysis']['priority_order']])
            order = [value['proposal_id'] for value in ordered]
            require(len(order) == len(values) and len(set(order)) == len(values), 'Bad generated common order')
            score = 65 if f.kind == 'progression' else 60
            badge = f'高 · {score}点'
            for view_width, view_height in WIDTHS:
                page.set_viewport_size(dict(width=view_width, height=view_height))
                with page.expect_response(response_is(f.analysis + '/result', 'GET')) as fetched:
                    page.goto(origin + f.overview, wait_until='networkidle')
                shown = fetched.value.json()
                require(shown['status'] == 'completed' and shown['is_current'] is True, 'Browser normal poll did not obtain current job result')
                require({v['proposal_id'] for v in shown['analysis']['recommendations']} == set(order), 'Browser result differs from saved job')
                cards = page.locator('#ko-ai .ko-proposal')
                expect(cards).to_have_count(min(5, len(order)))
                require(cards.evaluate_all('(xs)=>xs.map(x=>x.dataset.proposalId)') == order[:5], 'Overview top-five order is wrong')
                for index in range(cards.count()): expect(cards.nth(index).locator('.ko-priority')).to_have_text(badge)
                expect(page.locator('[data-ko-summary-count]')).to_have_text(f'{len(order)}件')
                if cancelled_id:
                    expect(page.locator(f'#ko-ai [data-proposal-id="{cancelled_id}"]')).to_have_count(0)
                require(page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Completed overview overflows')
                phase = 'cancelled' if cancelled_id else 'completed'
                page.screenshot(path=str(out / f'{args.case}-{phase}-overview-{view_width}.png'), full_page=True)
                if len(order) > 5:
                    more = page.locator('#ko-ai .ko-action-button')
                    expect(more).to_have_text(f'残り{len(order)-5}件を分析で確認 →')
                    with page.expect_response(response_is(f.analysis + '/result', 'GET')):
                        more.click()
                    require(urlsplit(page.url).path == f.analysis, 'Remaining proposals link missed analysis')
                elif item:
                    with page.expect_response(response_is(f.analysis + '/result', 'GET')):
                        page.locator(f'#ko-ai .ko-proposal[data-proposal-id="{item["proposal_id"]}"] .ko-proposal-detail').click()
                else:
                    with page.expect_response(response_is(f.analysis + '/result', 'GET')):
                        page.goto(origin + f.analysis, wait_until='networkidle')
                rows = page.locator('.ka7-proposal-table tbody tr')
                expect(page.locator('.ka7-board')).to_be_visible()
                expect(rows).to_have_count(len(order))
                for index, value in enumerate(ordered):
                    row = rows.nth(index)
                    expect(row.locator('.ka7-priority')).to_have_text(badge)
                    expect(row.locator('.ka7-target > strong')).to_have_text(value.get('target') or value.get('title') or '確認項目')
                    ids = value['source_ids']
                    sid = next((sid for sid in ids if str(sid).startswith(('inspection:', 'periodic:'))),
                        next((sid for sid in ids if str(sid).startswith('maintenance:')), ids[0]))
                    source_url = data['sources'][sid]['url']
                    expected_url = source_url if urlsplit(source_url).netloc else origin + source_url
                    expect(row.locator('.ka7-record-link')).to_have_attribute('href', expected_url)
                if item:
                    drawer = page.locator('.ka-reference-drawer')
                    if len(order) > 5:
                        rows.nth(order.index(item['proposal_id'])).locator('.ka-reference-detail-button').click()
                    expect(drawer).to_be_visible()
                    expect(drawer.locator('.ka-drawer-priority-row .ka-ai-priority')).to_have_text(badge)
                    details = drawer.locator('.priority-response-details')
                    details.locator('summary').click()
                    expect(details.locator('.priority-response-confirmation')).to_be_visible()
                    confirmation = item['priority_assessment']['confirmation_details']
                    expect(details).to_contain_text(confirmation['actor_name'])
                    for statement in confirmation['statements']: expect(details).to_contain_text(statement)
                    internal = []
                    for source in confirmation['display_sources']:
                        expect(details).to_contain_text(source['text'])
                        if source.get('url'):
                            parsed = urlsplit(source['url'])
                            target = source['url'] if parsed.netloc else origin + source['url']
                            expect(details.locator(f'a.priority-response-confirmation-source[href="{target}"]').first).to_be_visible()
                            if not parsed.netloc and parsed.path.startswith('/vehicle/'): internal.append(source['url'])
                    require(internal, 'No real original-source link')
                    # Choose the original PDF when present, otherwise the real
                    # inspection page. This verifies the linked GET/bytes, not
                    # Chromium PDF-viewer text extraction or external MLIT pages.
                    source_url = next((url for url in internal if '/source' in url or '/original' in url), internal[0])
                    parsed = urlsplit(source_url)
                    source_path = parsed.path + ('?' + parsed.query if parsed.query else '')
                    original = f.request('GET', source_path)
                    require(original.status_code == 200, 'Generated original link unavailable')
                    require(f.kind == 'progression' or original.mimetype == 'application/pdf',
                            'Manufacturer/legal original must remain a PDF')
                    if original.mimetype == 'application/pdf':
                        f.original_downloads[parsed.path] = hashlib.sha256(original.get_data()).hexdigest()
                    require(page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Completed priority drawer overflows')
                    page.screenshot(path=str(out / f'{args.case}-completed-detail-{view_width}.png'), full_page=True)
                    previous_url = page.url
                    if parsed.path in f.original_downloads:
                        pdf.begin(page, origin + source_url, f.original_downloads[parsed.path])
                    with page.expect_response(response_is(parsed.path, 'GET')) as opened:
                        details.locator(f'a.priority-response-confirmation-source[href="{origin + source_url}"]').first.click(no_wait_after=True)
                    require(opened.value.status == 200, 'Rendered original link did not reach the source')
                    if parsed.path in f.original_downloads:
                        observed = next(value for value in reversed(report['requests']) if value['path'] == parsed.path)
                        require(observed.get('source_sha256') == f.original_downloads[parsed.path], 'Browser original response bytes differ')
                        page.wait_for_url(origin + source_url, wait_until='networkidle')
                        pdf.finish(page, opened.value)
                        pdf.end()
                        page.go_back(wait_until='networkidle')
                        expect(page).to_have_url(previous_url)
                        expect(page.locator('.ka-reference-drawer')).to_be_visible()
                else:
                    page.screenshot(path=str(out / f'{args.case}-cancelled-analysis-{view_width}.png'), full_page=True)
                report['cases'].append(f'Browser {view_width}: {phase} normal job GET/poll, {len(order)} total proposals, top-five and remaining-analysis navigation, exact common scores and source details' + ('/original GET' if item else '; only cancelled candidate removed'))
                f.protected()

        def historical_views(page, data, previous_item, previous_generated_at):
            """Display real carry plus current companion after one metadata omission."""
            original = previous_item['priority_assessment']['confirmation_details']
            historical_item = f.assert_historical(data, previous_item, previous_generated_at)
            ids = data['analysis']['priority_order']
            require(set(ids) == {historical_item['proposal_id'], *f.background_items}, 'Historical ordered identities changed')
            companion_id = next(iter(f.background_items))
            companion = next(v for v in data['analysis']['recommendations'] if v['proposal_id'] == companion_id)
            expected_records = [urljoin(origin, data['sources'][sid]['url']) for sid in historical_item['source_ids']
                if sid != f.missing_source_id and not sid.startswith('knowledge:')]
            for view_width, view_height in WIDTHS:
                page.set_viewport_size(dict(width=view_width, height=view_height))
                with page.expect_response(response_is(f.analysis + '/result', 'GET')) as fetched:
                    page.goto(origin + f.overview, wait_until='networkidle')
                f.assert_historical(fetched.value.json(), previous_item, previous_generated_at)
                cards = page.locator('#ko-ai .ko-proposal')
                expect(cards).to_have_count(2)
                require(cards.evaluate_all('(xs)=>xs.map(x=>x.dataset.proposalId)') == ids, 'Historical coexistence order changed')
                old_card = page.locator(f'#ko-ai .ko-proposal[data-proposal-id="{historical_item["proposal_id"]}"]')
                current_card = page.locator(f'#ko-ai .ko-proposal[data-proposal-id="{companion_id}"]')
                expect(old_card.locator('.ko-priority')).to_have_text('高')
                require(old_card.get_attribute('data-priority-score') is None, 'Historical overview exposed a current score')
                expect(current_card.locator('.ko-priority')).to_have_text('高 · 60点')
                expect(current_card).to_have_attribute('data-priority-score', '60')
                expect(page.locator('[data-ko-summary-count]')).to_have_text('2件（前回評価を含む）')
                require(page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Historical overview overflows')
                page.screenshot(path=str(out / f'{args.case}-historical-overview-{view_width}.png'), full_page=True)
                with page.expect_response(response_is(f.analysis + '/result', 'GET')) as fetched:
                    old_card.locator('.ko-proposal-detail').click()
                f.assert_historical(fetched.value.json(), previous_item, previous_generated_at)
                rows = page.locator('.ka7-proposal-table tbody tr')
                expect(rows).to_have_count(2)
                old_row = rows.nth(ids.index(historical_item['proposal_id']))
                current_row = rows.nth(ids.index(companion_id))
                expect(old_row.locator('.ka7-target > strong')).to_have_text(historical_item['target'])
                expect(old_row.locator('.ka7-priority')).to_have_text('高')
                expect(current_row.locator('.ka7-target > strong')).to_have_text(companion['target'])
                expect(current_row.locator('.ka7-priority')).to_have_text('高 · 60点')
                expect(page.locator('.ka7-count')).to_have_text('2件（前回評価を含む）')
                drawer = page.locator('.ka-reference-drawer')
                expect(drawer).to_be_visible()
                expect(page).to_have_url(origin + f.analysis + '#proposal=' + historical_item['proposal_id'])
                expect(drawer.locator('.ka-drawer-priority-row .ka-ai-priority')).to_have_text('高')
                expect(drawer.locator('p.ka-historical-source-gap')).to_have_count(1)
                expect(drawer.locator('p.ka-historical-source-gap')).to_have_text(SOURCE_GAP_MESSAGE)
                expect(drawer.locator('p.ka-historical-source-gap a')).to_have_count(0)
                actual_records = drawer.locator('.ka-reference-source-links a').evaluate_all('(xs)=>xs.map(x=>x.href)')
                require(actual_records == expected_records, 'Missing source gained a fabricated link or a real record link vanished')
                details = drawer.locator('.priority-response-details')
                details.locator('summary').click()
                prior = details.locator('.priority-response-previous')
                expect(prior).to_contain_text('前回の評価：高（現在の再計算値ではありません）')
                expect(prior).to_contain_text(previous_generated_at)
                expect(prior).to_contain_text(original['confirmed_at'])
                expect(prior).to_contain_text(historical_item['priority_assessment']['previous_result']['reason'])
                history = details.locator('.priority-response-confirmation')
                expect(history).to_have_count(1)
                expect(history.locator('strong').first).to_have_text('前回保存時の根拠確認（現在の成立を示すものではありません）')
                expect(history).to_contain_text(original['actor_name'])
                expect(history).to_contain_text(original['confirmed_at'])
                for statement in original['statements']: expect(history).to_contain_text(statement)
                for source in original['display_sources']: expect(history).to_contain_text(source['text'])
                expect(history).not_to_contain_text('REVISED-SYNTHETIC-ORIGINAL-ONLY')
                # The original URL now refers to revised bytes. Do not click it
                # here or weaken the completed-state original_downloads hashes.
                require(page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Historical drawer overflows')
                page.screenshot(path=str(out / f'{args.case}-historical-detail-{view_width}.png'), full_page=True)
                # The drawer scrolls independently; full-page capture alone can
                # leave the already-asserted missing-source explanation offscreen.
                gap = drawer.locator('p.ka-historical-source-gap')
                gap.scroll_into_view_if_needed()
                expect(gap).to_be_in_viewport()
                page.screenshot(path=str(out / f'{args.case}-historical-source-gap-{view_width}.png'), full_page=True)
                drawer.locator('.ka-drawer-close').click()
                expect(drawer).to_be_hidden()
                current_row.locator('.ka-reference-detail-button').click()
                expect(drawer).to_be_visible()
                # A row button opens the drawer without adding a deep-link hash.
                expect(page).to_have_url(origin + f.analysis)
                expect(drawer.locator('#ka-reference-drawer-title')).to_have_text(companion['target'])
                expect(drawer.locator('.ka-drawer-priority-row .ka-ai-priority')).to_have_text('高 · 60点')
                expect(drawer.locator('.ka-historical-source-gap')).to_have_count(0)
                current_details = drawer.locator('.priority-response-details')
                current_details.locator('summary').click()
                expect(current_details.locator('.priority-response-previous')).to_have_count(0)
                current_confirmation = companion['priority_assessment']['confirmation_details']
                current_section = current_details.locator('.priority-response-confirmation')
                expect(current_section).to_have_count(1)
                expect(current_section).to_contain_text(current_confirmation['actor_name'])
                expect(current_section).to_contain_text(current_confirmation['confirmed_at'])
                for statement in current_confirmation['statements']:
                    expect(current_section).to_contain_text(statement)
                for source in current_confirmation['display_sources']:
                    expect(current_section).to_contain_text(source['text'])
                    if source.get('url'):
                        expect(current_section.locator('a[href="' + urljoin(origin, source['url']) + '"]').first).to_be_visible()
                require(page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Current companion drawer overflows')
                page.screenshot(path=str(out / f'{args.case}-historical-companion-{view_width}.png'), full_page=True)
                f.protected()
                report['cases'].append(f'Browser {view_width}: real manufacturer carry job, then explicit one-key saved-source omission; same historical proposal/actor/time/text, previous high without current points and missing-link explanation; independent current legal high60 remains visible with real source links and no gap')

        page = new_page()
        original_bytes = None
        try:
            for width, height in WIDTHS:
                page.set_viewport_size(dict(width=width, height=height))
                start_count = f.count(); root = open_form(page)
                _, preview, boxes = select_and_preview(page, root)
                for index in range(boxes.count() - 1): boxes.nth(index).check()
                before = len(captured)
                preview.locator('button[type=submit]').click()
                require(not preview.evaluate('(f)=>f.checkValidity()'), 'Unchecked fixed statement not required')
                require(len(captured) == before and f.count() == start_count, 'Incomplete browser form submitted')
                boxes.last.check()
                require(page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Optional preview overflows')
                page.screenshot(path=str(out / f'{args.case}-preview-{width}.png'), full_page=True)
                before = len([r for r in captured if r['path'] == f.url])
                save(page, preview, double=True)
                require(len([r for r in captured if r['path'] == f.url]) == before + 1, 'Double click produced extra requests')
                f.assert_state(start_count + 1, 1)
                replay(page, captured[-1]['body']); f.assert_state(start_count + 1, 1)

                stale_page = new_page(); stale_page.set_viewport_size(dict(width=width, height=height))
                stale_root = open_form(stale_page)
                _, stale_preview, stale_boxes = select_and_preview(stale_page, stale_root)
                check_all(stale_boxes)
                with page.expect_response(response_is(f.url, 'GET')):
                    root.get_by_role('button', name='元記録を選び直して訂正', exact=True).first.click()
                expect(root.locator('[data-confirmation-replacing]')).to_be_visible()
                _, preview, boxes = select_and_preview(page, root, select=False)
                check_all(boxes); corrected = save(page, preview)
                f.assert_state(start_count + 3, 1)
                save(stale_page, stale_preview, expected=409)
                f.assert_state(start_count + 3, 1); stale_page.close()
                expect(root.locator('[data-confirmation-history]')).to_contain_text('取消済み')
                page.screenshot(path=str(out / f'{args.case}-corrected-{width}.png'), full_page=True)
                if width == WIDTHS[0][0]:
                    generated = f.generate()
                    completed_item = f.assert_generated(generated, corrected['event_id'])
                    remaining_ids = {v['proposal_id'] for v in generated['analysis']['recommendations']} - {completed_item['proposal_id']}
                    completed_views(page, generated, completed_item)
                    if f.kind == 'manufacturer_immediate':
                        original_bytes = f.revise_manufacturer_original()
                        carried = f.generate()
                        f.assert_historical(carried, completed_item, generated['generated_at'])
                        f.omit_saved_manufacturer_metadata(completed_item)
                        historical_views(page, f.read_result(), completed_item, generated['generated_at'])
                    page.set_viewport_size(dict(width=width, height=height)); root = open_form(page)

                before = len(captured)
                page.once('dialog', lambda d: d.dismiss())
                root.get_by_role('button', name='この根拠確認を取り消す', exact=True).first.click()
                require(len(captured) == before, 'Dismissed cancellation posted')
                page.once('dialog', lambda d: d.accept())
                with page.expect_response(response_is(f.url, 'POST')) as pending:
                    root.get_by_role('button', name='この根拠確認を取り消す', exact=True).first.click()
                require(pending.value.status == 200, 'Browser cancellation failed')
                expect(root.get_by_role('button', name='この根拠確認を取り消す', exact=True)).to_have_count(len(f.background_confirmations))
                f.assert_state(start_count + 4, 0)
                replay(page, captured[-1]['body']); f.assert_state(start_count + 4, 0)
                if width == WIDTHS[0][0]:
                    f.assert_generated(f.read_result(), previous_ids=remaining_ids)
                    regenerated = f.generate()
                    f.assert_generated(regenerated, previous_ids=remaining_ids)
                    completed_views(page, regenerated, cancelled_id=completed_item['proposal_id'])
                    if original_bytes is not None:
                        f.replace_manufacturer_original(original_bytes, 'restore')
                        original_bytes = None
                    page.set_viewport_size(dict(width=width, height=height)); root = open_form(page)

                # Cancelled evidence is not a prerequisite for ordinary navigation.
                root.locator('summary').focus(); page.keyboard.press('Escape')
                expect(root).not_to_have_attribute('open', '')
                expect(root.locator('summary')).to_be_focused()
                page.locator(f'.vehicle-karte-tabs a[href="{f.overview}"]').click()
                page.wait_for_load_state('networkidle')
                require(urlsplit(page.url).path == f.overview, 'Normal overview link blocked')
                page.go_back(wait_until='networkidle')
                expect(page.locator('#priority-evidence')).to_be_visible()
                require(page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Optional page overflows')
                f.assert_state(start_count + 4, 0)
                report['cases'].append(f'Browser {width}: real selects/original preview/required checkboxes/double click/save/correction/stale second-tab 409/cancel/dismiss/replays/Escape/overview/Back; protected records unchanged outside the explicit manufacturer revision/restore and one-key saved-source omission')
            require(not report['page_errors'] and not report['failed_gets'] and not report['blocked_requests'] and not report['failed_requests'], 'Browser script/request failure')
            report.update(status='PASS', browser_acceptance_passed=True, protected_records_unchanged=True)
        except Exception:
            if not page.is_closed(): page.screenshot(path=str(out / 'failure.png'), full_page=True)
            raise
        finally: browser.close()


def run(args, sha, tree, out, origin):
    report = dict(candidate_sha=sha, candidate_tree=tree, scenario=args.case, status='FAILED',
        fixture_only=True, production_accessed=False, browser_started=False, browser_acceptance_passed=False,
        page_errors=[], blocked_requests=[], failed_gets=[], failed_requests=[], requests=[], cases=[],
        started_utc=datetime.now(timezone.utc).isoformat())
    fixture = Fixture(args.case, report)
    try:
        fixture.start()
        if args.preflight_only:
            exercise_http(fixture)
            report.update(status='PREFLIGHT_PASS_BROWSER_NOT_RUN', protected_records_unchanged=True)
        else: run_browser(args, fixture, report, out, origin)
        return 0
    finally:
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        (out / 'browser-result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        fixture.close()
        print(json.dumps(report, ensure_ascii=False, default=str))
