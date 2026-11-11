"""Optional confirmation forms, real source readers and narrowly allowed POSTs.

No model, OCR, network, source-provider or scoring mocks. All records and original
PDFs are synthetic. Existing GET-only scenarios do not import this module.
"""
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from io import BytesIO
import hashlib
from unittest.mock import patch
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

KINDS = {'confirmation_manufacturer': 'manufacturer_immediate',
         'confirmation_legal': 'legal_deadline', 'confirmation_progression': 'progression'}
WIDTHS = ((1440, 900), (1024, 768), (768, 1024), (390, 780), (320, 640))
CONFIRM, WITHDRAW = '優先度根拠確認', '優先度根拠取消'
# Normal screen bookkeeping only. Every business/source/analysis table and user
# row remains protected. Event appends are inspected separately, never excluded.
BOOKKEEPING = {'analysis_input_epoch', 'analysis_input_read_cache'}


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

    def start(self):
        c = self.case
        c.setUpClass(); self.started = True; c.setUp(); self.setup = True
        if self.kind == 'manufacturer_immediate': c.use_original_instruction_only()
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
                if table.name == 'analysis_input_epoch' and row['company_code'] == 'A' and row['bucket'] == f'vehicle:{self.case.vehicle.id}':
                    continue
                if table.name == 'analysis_input_read_cache' and row['company_code'] == 'A' and row['vehicle_record_id'] == self.case.vehicle.id:
                    continue
                protected.append(tuple(row.values()))
            result[table.name] = protected
        return result

    def analysis_others(self, rows):
        table = self.case.models.VehicleKarteAnalysis.__table__
        keys = [column.name for column in table.columns]
        owner, vehicle = keys.index('company_code'), keys.index('vehicle_record_id')
        return [row for row in rows if not (row[owner] == 'A' and row[vehicle] == self.case.vehicle.id)]

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
                vehicle_record_id=self.case.vehicle.id).count() == 1, 'Only one target analysis state may change')
        changed = sorted(k for k in set(compared) | set(baseline) if compared.get(k) != baseline.get(k))
        require(not changed, 'Protected tables changed: ' + ', '.join(changed))
        events = self.events()
        require(all(events.get(key) == value for key, value in self.seen_events.items()), 'Existing event changed/deleted')
        new = {key: value for key, value in events.items() if key not in self.seen_events}
        require(allow_append or not new, 'Read/rejected request appended an event')
        for value in new.values():
            require(value['company_code'] == 'A' and value['result_type'] == 'vehicle_priority'
                    and value['result_id'] == self.case.vehicle.id and value['event_type'] in (CONFIRM, WITHDRAW),
                    'Unexpected event append')
        self.seen_events = events

    def count(self):
        return len(self.events()) - len(self.original_events)

    def request(self, method, path, *, body=None, csrf=True, raw=None, headers=None):
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
        calls = []
        def empty_model(request, **kwargs):
            wire = generator.expand_vehicle_karte_analysis_wire_payload(json.loads(json.loads(request.data)['input']))
            require('_confirmed_priority_candidates' not in wire, 'Server candidates leaked into model transport')
            calls.append(wire)
            result = {'overview': '合成空応答。検証済み根拠の補完は実サーバー処理。', 'recommendations': []}
            return BytesIO(json.dumps({'status': 'completed', 'output': [{'content': [
                {'type': 'output_text', 'text': json.dumps(result)}]}]}).encode())
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-local-test-only'}), \
                patch.object(generator.urllib.request, 'urlopen', side_effect=empty_model):
            require(service.run_vehicle_karte_analysis_job(state.id), 'Normal analysis job failed')
        self.db.session.refresh(state)
        require(state.status == 'completed', 'Normal analysis job did not complete')
        method = json.loads(state.result_json)['analysis_method']
        expected_calls = int(method == 'ai')
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
        if active_event is None: return None
        selected = [item for item in items if any(value['event_id'] == active_event for value in
            item['priority_assessment'].get('confirmation_details_list', []) or
            [item['priority_assessment']['confirmation_details']])]
        require(len(selected) == 1, 'Saved confirmation does not identify exactly one completed candidate')
        require(selected[0]['priority_assessment']['confirmation_details']['kind'] == self.kind, 'Wrong confirmation source')
        return selected[0]

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
    require(f.request('POST', f.url, body=f.confirmation_body(stale)).status_code == 409, 'Old preview accepted')
    cancel = {'token': next(v['cancel_token'] for v in f.history() if v['event_id'] == active_event)}
    require(f.request('POST', f.url, body=cancel).status_code == 200, 'Cancellation failed')
    f.assert_state(4, 0)
    f.assert_generated(f.read_result(), previous_ids=remaining_ids)
    f.assert_generated(f.generate(), previous_ids=remaining_ids)
    require(f.request('POST', f.url, body=cancel).status_code == 409, 'Cancellation replay accepted')
    prepared = f.preview()
    require(f.request('POST', f.url, body=f.confirmation_body(prepared)).status_code == 200, 'Cannot confirm after cancellation')
    f.assert_state(5, 1)
    f.report['cases'].append('Real options/preview/CSRF/save/replay/correction/stale revision/cancel/new confirmation; real empty-response queue/job completion and cancellation GET/regeneration; original records unchanged')


def run_browser(args, f, report, out, origin):
    from playwright.sync_api import sync_playwright, expect
    captured = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(args.chromium.resolve()))
        report.update(browser_started=True, browser_version=browser.version)
        context = browser.new_context(service_workers='block')

        def bridge(route):
            request = route.request; parsed = urlsplit(request.url)
            same_origin = f'{parsed.scheme}://{parsed.netloc}' == origin and not parsed.username and not parsed.password
            allowed = request.method == 'GET' or (request.method == 'POST' and parsed.path in f.post_paths and not parsed.query)
            if not same_origin or not allowed:
                report['blocked_requests'].append(dict(method=request.method, host=parsed.hostname, path=parsed.path))
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
            route.fulfill(status=response.status_code, headers=headers, body=response.get_data())
        context.route('**/*', bridge)

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
                for index in range(rows.count()): expect(rows.nth(index).locator('.ka7-priority')).to_have_text(badge)
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
                    if original.mimetype == 'application/pdf':
                        f.original_downloads[parsed.path] = hashlib.sha256(original.get_data()).hexdigest()
                    require(page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Completed priority drawer overflows')
                    page.screenshot(path=str(out / f'{args.case}-completed-detail-{view_width}.png'), full_page=True)
                    with page.expect_response(response_is(parsed.path, 'GET')) as opened:
                        details.locator(f'a.priority-response-confirmation-source[href="{origin + source_url}"]').first.click(no_wait_after=True)
                    require(opened.value.status == 200, 'Rendered original link did not reach the source')
                    if parsed.path in f.original_downloads:
                        observed = next(value for value in reversed(report['requests']) if value['path'] == parsed.path)
                        require(observed.get('source_sha256') == f.original_downloads[parsed.path], 'Browser original response bytes differ')
                else:
                    page.screenshot(path=str(out / f'{args.case}-cancelled-analysis-{view_width}.png'), full_page=True)
                report['cases'].append(f'Browser {view_width}: {phase} normal job GET/poll, {len(order)} total proposals, top-five and remaining-analysis navigation, exact common scores and source details' + ('/original GET' if item else '; only cancelled candidate removed'))
                f.protected()

        page = new_page()
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
                report['cases'].append(f'Browser {width}: real selects/original preview/required checkboxes/double click/save/correction/stale second-tab 409/cancel/dismiss/replays/Escape/overview/Back; protected originals unchanged')
            require(not report['page_errors'] and not report['failed_gets'] and not report['blocked_requests'], 'Browser script/request failure')
            report.update(status='PASS', browser_acceptance_passed=True, protected_records_unchanged=True)
        except Exception:
            if not page.is_closed(): page.screenshot(path=str(out / 'failure.png'), full_page=True)
            raise
        finally: browser.close()


def run(args, sha, tree, out, origin):
    report = dict(candidate_sha=sha, candidate_tree=tree, scenario=args.case, status='FAILED',
        fixture_only=True, production_accessed=False, browser_started=False, browser_acceptance_passed=False,
        page_errors=[], blocked_requests=[], failed_gets=[], requests=[], cases=[],
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
