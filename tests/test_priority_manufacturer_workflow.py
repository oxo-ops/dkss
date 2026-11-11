"""Actual manufacturer original reader -> optional HTTP confirmation workflow.

All sources/accounts/vehicles are isolated synthetic fixtures. Providers, HTTP
routes, signature/audit storage and active-source rereads are not mocked.
"""
import json
import unittest

import test_priority_manufacturer_evidence as maker
from dkss_app.priority_confirmations import active_priority_confirmations, confirmation_statuses


class ManufacturerConfirmationWorkflowTests(unittest.TestCase):
    setUpClass = classmethod(maker.ManufacturerEvidenceTests.setUpClass.__func__)
    tearDownClass = classmethod(maker.ManufacturerEvidenceTests.tearDownClass.__func__)
    tearDown = maker.ManufacturerEvidenceTests.tearDown
    login = maker.ManufacturerEvidenceTests.login
    request = maker.ManufacturerEvidenceTests.request
    save = maker.ManufacturerEvidenceTests.save
    complete = maker.ManufacturerEvidenceTests.complete
    state = maker.ManufacturerEvidenceTests.state
    decision_data = maker.ManufacturerEvidenceTests.decision_data
    decide = maker.ManufacturerEvidenceTests.decide
    snapshot = maker.ManufacturerEvidenceTests.snapshot
    begin_priority = maker.ManufacturerEvidenceTests.begin_priority
    repair_priority = maker.ManufacturerEvidenceTests.repair_priority
    refs = maker.ManufacturerEvidenceTests.refs
    recheck = maker.ManufacturerEvidenceTests.recheck
    use_original_instruction_only = maker.ManufacturerEvidenceTests.use_original_instruction_only

    def setUp(self):
        maker.ManufacturerEvidenceTests.setUp(self)
        self.login('admin')
        self.url = f'/vehicle/karte/{self.vehicle.id}/priority-confirmations'

    def prepare(self):
        observation = self.selection['observation_input_ref']
        response = self.client.get(self.url, query_string={'kind': 'manufacturer_immediate',
            'selection': json.dumps({'observation_input_ref': observation})})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        form = response.json['form']
        choice = next(f for f in form['fields'] if f['key'] == 'manufacturer_rule')['options'][0]['value']
        selection = {'observation_input_ref': observation, 'manufacturer_rule': choice}
        response = self.client.get(self.url, query_string={'kind': 'manufacturer_immediate',
            'selection': json.dumps(selection)})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        for key in ('condition_quote', 'action_quote'):
            options = next(f for f in response.json['form']['fields'] if f['key'] == key)['options']
            self.assertEqual(options[0]['value'], self.extracted.get('quote') or maker.QUOTE)
            selection[key] = options[0]['value']
        response = self.client.post(self.url + '/preview', json={'kind': 'manufacturer_immediate', 'selection': selection})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.json

    def confirm(self, prepared=None):
        prepared = prepared or self.prepare()
        response = self.client.post(self.url, json={'token': prepared['token'],
            'statements': [s['key'] for s in prepared['preview']['statements']]})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.json['event_id'], prepared

    def test_real_options_preview_post_active_confirmation_keep_originals_and_operation(self):
        before = self.row.operation_judgment_json
        prepared = self.prepare()
        self.assertEqual(len(prepared['preview']['display_sources']), 4)
        self.assertNotIn('effective_score', prepared['preview'])
        event_id, _ = self.confirm(prepared)
        entries = active_priority_confirmations(self.vehicle, 'manufacturer_immediate', as_of=self.day)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['event_id'], event_id)
        self.assertEqual(entries[0]['selection']['observation_input_ref'], self.refs()[0])
        self.assertEqual(entries[0]['actor']['username'], 'admin')
        self.assertEqual(entries[0]['fingerprint'], prepared['preview']['fingerprint'])
        self.db.session.refresh(self.row)
        self.assertEqual(self.row.operation_judgment_json, before)
        repeated = self.client.post(self.url, json={'token': prepared['token'],
            'statements': [s['key'] for s in prepared['preview']['statements']]})
        self.assertEqual(repeated.status_code, 409)
        self.assertEqual(len(active_priority_confirmations(self.vehicle, as_of=self.day)), 1)

    def test_changed_original_blocks_stale_save_and_holds_existing_confirmation(self):
        prepared = self.prepare()
        self.document.original_data = maker.original_pdf('A changed original without the selected conditions.')
        self.db.session.commit()
        response = self.client.post(self.url, json={'token': prepared['token'],
            'statements': [s['key'] for s in prepared['preview']['statements']]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(active_priority_confirmations(self.vehicle, as_of=self.day), [])
        self.document.original_data = self.raw; self.db.session.commit()
        event_id, _ = self.confirm()
        saved = self.models.ChecklistEvent.query.filter_by(id=event_id).one().detail_json
        self.public.available = False; self.db.session.commit()
        self.assertEqual(active_priority_confirmations(self.vehicle, as_of=self.day), [])
        entry = next(v for v in confirmation_statuses(self.vehicle, as_of=self.day) if v['event_id'] == event_id)
        self.assertEqual(entry['status'], 'held')
        self.assertEqual(self.models.ChecklistEvent.query.filter_by(id=event_id).one().detail_json, saved)

    def test_explicit_cancellation_withdraws_only_selected_confirmation(self):
        first, _ = self.confirm()
        second, _ = self.confirm()
        response = self.client.get(self.url, query_string={'kind': 'manufacturer_immediate'})
        self.assertEqual(response.status_code, 200)
        cancel = next(row['cancel_token'] for row in response.json['history'] if row['event_id'] == first)
        response = self.client.post(self.url, json={'token': cancel})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        entries = confirmation_statuses(self.vehicle, as_of=self.day)
        self.assertEqual({e['event_id']: e['status'] for e in entries}, {first: 'withdrawn', second: 'active'})
        self.assertEqual([e['event_id'] for e in active_priority_confirmations(self.vehicle, as_of=self.day)], [second])
        self.assertEqual(self.state()['status'], '運行可')

    def test_verified_repair_and_normal_recheck_terminal_is_not_a_bare_status(self):
        event_id, _ = self.confirm()
        self.repair_priority(); self.recheck()
        entry = next(e for e in confirmation_statuses(self.vehicle, as_of=self.day) if e['event_id'] == event_id)
        self.assertEqual(entry['status'], 'resolved')
        self.assertEqual(active_priority_confirmations(self.vehicle, as_of=self.day), [])
        self.models.ChecklistEvent.query.filter_by(event_type='解消').delete(); self.db.session.commit()
        entry = next(e for e in confirmation_statuses(self.vehicle, as_of=self.day) if e['event_id'] == event_id)
        self.assertEqual(entry['status'], 'held')


    def test_nonperiodic_http_confirmation_normal_generation_result_source_hold_and_cancel(self):
        from dkss_app.analysis import get_vehicle_karte_analysis_job_data
        from vehicle_priority_inputs import validate_priority_input
        self.use_original_instruction_only()
        confirmed_event, _ = self.confirm()
        with self.app.test_request_context('/'):
            payload, sources = get_vehicle_karte_analysis_job_data(self.vehicle)
        offers = [offer for record in payload['records'] for offer in record.get('priority_inputs', [])]
        confirmation = next(offer for offer in offers if offer['ref'].startswith(f'confirmation:{confirmed_event}:'))
        observation = next(offer for offer in offers if offer['ref'] == self.refs()[0])
        proposals = []
        for offer in (confirmation, observation):
            item = dict(priority='低', category='整備・点検', target=offer['display_target'],
                title='元資料に基づく対応', action='原文と確認した対応を実施', current_state='選択した登録原事実',
                source_ids=offer['source_ids'], priority_input_ref=offer['ref'])
            validate_priority_input(item, payload); proposals.append(item)
        self.assertEqual(proposals[0]['priority'], '高')
        bundle = {'analysis': {'recommendations': proposals}, 'sources': sources, 'fingerprints': payload['_fingerprints']}
        stored = self.models.VehicleKarteAnalysis(company_code='A', vehicle_record_id=self.vehicle.id,
            status='completed', result_json=json.dumps(bundle, ensure_ascii=False))
        self.db.session.add(stored); self.db.session.commit()
        original_json = stored.result_json
        url = f'/vehicle/karte/{self.vehicle.id}/analysis/result'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        recommendations = response.json['analysis']['recommendations']
        value = next(item for item in recommendations if item['priority_input_ref'] == confirmation['ref'])
        assessment = value['priority_assessment']
        self.assertEqual((value['priority'], assessment['effective_score']), ('高', 60))
        self.assertEqual(assessment['applied_floors'][0]['code'], 'manufacturer_immediate_condition')
        self.assertEqual(assessment['confirmation_details']['kind'], 'manufacturer_immediate')
        self.assertEqual(len(assessment['confirmation_details']['display_sources']), 4)
        original_id = value['proposal_id']
        self.assertEqual(self.state()['status'], '運行可')
        self.assertEqual(stored.result_json, original_json)
        # A changed original/public version holds the saved high classification
        # without a newly invented score or a fourth unevaluated category.
        self.public.available = False; self.db.session.commit()
        response = self.client.get(url)
        value = next(item for item in response.json['analysis']['recommendations'] if item['priority_input_ref'] == confirmation['ref'])
        self.assertEqual((value['priority'], value['priority_assessment']['effective_score']), ('高', None))
        self.assertEqual(value['proposal_id'], original_id)
        # Explicit cancellation removes only this confirmed subject; the normal
        # inspection offer remains independently present and the saved JSON stays.
        history = self.client.get(self.url, query_string={'kind': 'manufacturer_immediate'}).json['history']
        token = next(item['cancel_token'] for item in history if item['event_id'] == confirmed_event)
        self.assertEqual(self.client.post(self.url, json={'token': token}).status_code, 200)
        response = self.client.get(url)
        remaining = response.json['analysis']['recommendations']
        self.assertEqual([item['priority_input_ref'] for item in remaining], [observation['ref']])
        self.assertEqual(response.json['analysis']['priority_resolved_proposals'][0]['proposal_id'], original_id)
        self.db.session.refresh(stored); self.assertEqual(stored.result_json, original_json)
        self.assertEqual(self.state()['status'], '運行可')


if __name__ == '__main__': unittest.main()
