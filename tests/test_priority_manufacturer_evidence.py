"""Synthetic manufacturer originals + normal HTTP inspection provenance only.

No original/reference/adoption/observation reader is mocked. No live database,
AI, network, notification delivery, or production configuration is used.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
from io import BytesIO
import json
import unittest
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from sqlalchemy import event
import test_priority_observation_sources as observed
from dkss_app.priority_manufacturer_evidence import (read_manufacturer_priority_evidence,
    manufacturer_confirmation_options, preview_manufacturer_confirmation, manufacturer_confirmation_inputs, manufacturer_confirmation_terminal, STATEMENTS)
from dkss_app.priority_timing import _rule_key


QUOTE = 'Inspect the test component every 30 days. If abnormal motion is observed, inspect the affected component immediately.'


def original_pdf(text=QUOTE):
    """Entirely fictional but actual parseable PDF bytes, not asserted PDF flags."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
        DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    escaped = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    stream.set_data(('BT /F1 10 Tf 20 700 Td (' + escaped + ') Tj ET').encode('ascii'))
    page[NameObject('/Contents')] = writer._add_object(stream)
    output = BytesIO(); writer.write(output)
    return output.getvalue()


class ManufacturerEvidenceTests(unittest.TestCase):
    setUpClass = classmethod(observed.PriorityObservationSourceTests.setUpClass.__func__)
    tearDownClass = classmethod(observed.PriorityObservationSourceTests.tearDownClass.__func__)
    tearDown = observed.PriorityObservationSourceTests.tearDown
    login = observed.PriorityObservationSourceTests.login
    request = observed.PriorityObservationSourceTests.request
    save = observed.PriorityObservationSourceTests.save
    complete = observed.PriorityObservationSourceTests.complete
    state = observed.PriorityObservationSourceTests.state
    decision_data = observed.PriorityObservationSourceTests.decision_data
    decide = observed.PriorityObservationSourceTests.decide
    snapshot = observed.PriorityObservationSourceTests.snapshot
    begin_priority = observed.PriorityObservationSourceTests.begin_priority
    repair_priority = observed.PriorityObservationSourceTests.repair_priority
    refs = observed.PriorityObservationSourceTests.refs
    recheck = observed.PriorityObservationSourceTests.recheck

    def setUp(self):
        observed.PriorityObservationSourceTests.setUp(self)
        from dkss_app.maintenance_knowledge_import_models import get_models
        from dkss_app.public_maintenance_knowledge_models import get_models as public_models
        from maintenance_knowledge_import import verify_maintenance_rule_sources
        self.Document, _ = get_models(self.db)
        _, self.PublicFile = public_models(self.db)
        self.vehicle.manufacturer = '日野'; self.vehicle.model_code = 'FICTIONAL-ONLY'
        self.raw = original_pdf()
        checksum = hashlib.sha256(self.raw).hexdigest()
        self.rule = {'action': 'inspect', 'cycle': 'repeat', 'relation': 'single',
            'criteria': [{'metric': 'period_days', 'value': 30}], 'model_codes': [], 'engine_codes': [],
            'conditions': 'Fictional scope only', 'source_page': 1, 'source_quote': QUOTE}
        self.rule = verify_maintenance_rule_sources(self.raw, [{'maintenance_rules': [self.rule]}])[0]['maintenance_rules'][0]
        self.rule['semantic_review'] = {'status': 'supported', 'document_checksum': checksum,
            'evidence': [{'source_page': 1, 'source_quote': QUOTE,
                'source_verification': deepcopy(self.rule['source_verification'])}],
            'applicability': {'scope': 'unrestricted', 'coverage': 'complete',
                'requirements': [], 'unresolved_conditions': []}}
        self.document_id = '11111111-1111-4111-8111-111111111111'
        self.knowledge = self.models.VehicleMaintenanceKnowledge(company_code='A', title='合成試験資料',
            part_name='合成試験部品', manufacturer='日野', model_code='', conditions='合成試験条件',
            guidance='合成試験専用', source_kind='メーカー公式資料',
            source_reference='https://example.test/manufacturer.pdf / [knowledge-document:' + self.document_id + ']',
            provider='合成メーカー', valid_from='2026-01-01', status='draft', created_by='admin', created_at='2026/11/11 00:00')
        self.db.session.add(self.knowledge); self.db.session.flush()
        self.extracted = {key: getattr(self.knowledge, key) for key in
            ('title', 'part_name', 'model_code', 'conditions', 'guidance', 'provider')}
        self.extracted.update(maintenance_rules=[self.rule],
            vehicle_scope={'mode': 'unrestricted', 'categories': [], 'quote': 'Fictional scope only'})
        self.document = self.Document(id=self.document_id, company_code='A', checksum=checksum,
            filename='synthetic-manufacturer-test.pdf', original_data=self.raw, mimetype='application/pdf',
            knowledge_ids_json=json.dumps([self.knowledge.id]), extraction_json=json.dumps([self.extracted]),
            created_by='admin', created_at='2026/11/11 00:00')
        self.db.session.add(self.document)
        now = datetime.now()
        self.public = self.PublicFile(company_code='A', url='https://example.test/manufacturer.pdf',
            title='合成試験資料', available=True, next_check=now+timedelta(days=2),
            last_checked=now-timedelta(days=1), checksum=checksum, document_id=self.document_id, status='unchanged')
        self.db.session.add(self.public); self.db.session.commit()
        self.selection = {'knowledge_source_id': f'knowledge:{self.knowledge.id}',
            'rule_key': _rule_key(self.knowledge.id, self.document_id, checksum, self.rule),
            'observation_input_ref': self.refs()[0]}

    def read(self, selections=None):
        return read_manufacturer_priority_evidence(self.vehicle,
            [self.selection] if selections is None else selections, as_of=self.day)

    def save_rule(self):
        self.extracted['maintenance_rules'] = [self.rule]
        self.document.extraction_json = json.dumps([self.extracted]); self.db.session.commit()

    def test_original_bytes_quotes_adoption_and_exact_observation_are_bound_without_floor(self):
        before = self.snapshot(); selection = deepcopy(self.selection)
        statements = []
        def capture(_c, _cursor, statement, _p, _ctx, _many): statements.append(statement)
        event.listen(self.db.engine, 'before_cursor_execute', capture)
        try:
            with patch('dkss_app.analysis.get_vehicle_karte_peer_comparison', side_effect=AssertionError('peer forbidden')):
                result = self.read()
        finally:
            event.remove(self.db.engine, 'before_cursor_execute', capture)
        self.assertEqual(result['missing_conditions'], [])
        self.assertEqual(len(result['bundles']), 1)
        bundle = result['bundles'][0]
        self.assertEqual(bundle['manufacturer']['original_verification']['source']['status'], 'quote_matched')
        self.assertEqual(bundle['observation']['input_ref'], self.refs()[0])
        self.assertFalse(bundle['condition_match_verified']); self.assertFalse(bundle['immediate_action_verified'])
        self.assertNotIn('effective_score', bundle); self.assertNotIn('priority', bundle)
        self.assertEqual(self.selection, selection); self.assertEqual(self.snapshot(), before)
        self.assertFalse(any(value.lstrip().upper().startswith(('INSERT','UPDATE','DELETE')) for value in statements))

    def test_immediate_words_periodic_adoption_and_matching_model_are_not_semantic_confirmation(self):
        bundle = self.read()['bundles'][0]
        self.assertIn('immediately', bundle['manufacturer']['rule']['source_quote'])
        self.assertEqual(bundle['manufacturer']['adoption']['status'], 'eligible')
        self.assertFalse(bundle['condition_match_verified']); self.assertFalse(bundle['immediate_action_verified'])
        self.assertNotEqual(bundle['manufacturer']['knowledge']['part_name'], bundle['observation']['target'])

    def test_forged_original_bytes_or_quote_flags_are_not_trusted(self):
        self.document.original_data = original_pdf('An unrelated original without urgency.'); self.db.session.commit()
        self.assertEqual(self.read()['bundles'], [])
        self.document.original_data = self.raw; self.db.session.commit()
        self.rule['source_quote'] = 'Inspect 30 days and immediately invented words.'; self.save_rule()
        self.selection['rule_key'] = _rule_key(self.knowledge.id, self.document_id, self.document.checksum, self.rule)
        self.assertEqual(self.read()['bundles'], [])

    def test_semantic_evidence_quote_must_really_exist_in_original(self):
        self.rule['semantic_review']['evidence'][0]['source_quote'] = 'This fabricated scope is absent.'; self.save_rule()
        self.assertEqual(self.read()['bundles'], [])

    def test_numeric_token_must_really_exist_in_original(self):
        self.rule['criteria'][0]['value'] = 31; self.save_rule()
        self.selection['rule_key'] = _rule_key(self.knowledge.id, self.document_id, self.document.checksum, self.rule)
        self.assertEqual(self.read()['bundles'], [])

    def test_public_version_review_scope_or_adoption_change_hold_current_bundle(self):
        for value in ('uncertain', 'contradicted'):
            self.rule['semantic_review']['status'] = value; self.save_rule()
            self.assertEqual(self.read()['bundles'], [])
        self.rule['semantic_review']['status'] = 'supported'; self.save_rule()
        self.public.available = False; self.db.session.commit()
        self.assertEqual(self.read()['bundles'], [])
        self.public.available = True; self.knowledge.status = 'retired'; self.db.session.commit()
        self.assertEqual(self.read()['bundles'], [])

    def test_foreign_vehicle_knowledge_and_forged_observation_never_partially_join(self):
        other = self.models.Vehicle.query.filter_by(company_code='B').one()
        self.assertEqual(read_manufacturer_priority_evidence(other, [self.selection], as_of=self.day)['bundles'], [])
        bad = {**self.selection, 'knowledge_source_id': 'knowledge:999999'}
        self.assertEqual(self.read([self.selection, bad])['bundles'], [])
        bad = {**self.selection, 'observation_input_ref': self.refs()[0][:-1] + 'z'}
        self.assertEqual(self.read([bad])['bundles'], [])

    def test_existing_repairs_and_rechecks_are_original_observations_not_current_conditions(self):
        before = self.read()['bundles'][0]['fingerprint']
        self.repair_priority(); self.recheck()
        result = self.read()['bundles'][0]
        self.assertTrue(result['observation']['resolved_after_repair_and_recheck'])
        self.assertEqual([value['kind'] for value in result['observation']['transitions']], ['repair', 'recheck'])
        self.assertFalse(result['condition_match_verified']); self.assertNotEqual(result['fingerprint'], before)
        self.assertEqual(self.read([{**self.selection, 'expected_fingerprint': before}])['bundles'], [])

    def test_expected_fingerprint_rejects_vehicle_or_source_rebinding(self):
        digest = self.read()['bundles'][0]['fingerprint']
        self.assertEqual(len(self.read([{**self.selection, 'expected_fingerprint': digest}])['bundles']), 1)
        self.vehicle.model_code = 'OTHER-FICTIONAL'; self.db.session.commit()
        self.assertEqual(self.read([{**self.selection, 'expected_fingerprint': digest}])['bundles'], [])

    def test_invalid_selection_limits_dirty_session_and_missing_original_fail_closed(self):
        for selections in ([], [self.selection]*2, [self.selection]*21,
                [{**self.selection, 'expected_fingerprint': None}], [{**self.selection, 'immediate': True}]):
            self.assertEqual(self.read(selections)['bundles'], [])
        self.vehicle.model_code = 'UNSAVED'
        self.assertEqual(self.read()['bundles'], []); self.assertIn(self.vehicle, self.db.session.dirty)
        self.db.session.rollback()
        with patch('dkss_app.priority_manufacturer_evidence.MAX_DOCUMENT_BYTES', 1):
            self.assertEqual(self.read()['bundles'], [])
        self.db.session.delete(self.document); self.db.session.commit()
        self.assertEqual(self.read()['bundles'], [])


    def confirmation_selection(self):
        return {**self.selection, 'condition_quote': 'If abnormal motion is observed',
            'action_quote': 'inspect the affected component immediately.'}

    def preview(self, selection=None, as_of=None):
        return preview_manufacturer_confirmation(self.vehicle,
            self.confirmation_selection() if selection is None else selection, as_of=as_of or self.day)

    def test_options_use_existing_adopted_rules_and_unselected_means_no_fact(self):
        options = manufacturer_confirmation_options(self.vehicle, self.refs()[0], as_of=self.day)
        self.assertEqual(options['missing_conditions'], [])
        self.assertEqual(len(options['bundles']), 1)
        self.assertEqual(options['bundles'][0]['manufacturer']['rule_key'], self.selection['rule_key'])
        with self.assertRaisesRegex(ValueError, '選択'):
            self.preview({})
        with patch('dkss_app.priority_manufacturer_evidence.MAX_KNOWLEDGE_OPTIONS', 0):
            self.assertEqual(manufacturer_confirmation_options(self.vehicle, self.refs()[0], as_of=self.day)['bundles'], [])

    def test_preview_records_exact_source_ranges_and_four_separate_statements(self):
        preview = self.preview()
        self.assertEqual(preview['kind'], 'manufacturer_immediate')
        self.assertEqual(preview['subject'], self.read()['bundles'][0]['observation']['target'])
        self.assertEqual(preview['source_ids'], [f'inspection:{self.row.id}', f'knowledge:{self.knowledge.id}'])
        self.assertEqual([value['key'] for value in preview['statements']], [key for key, _ in STATEMENTS])
        self.assertEqual(preview['sources']['selected_quotes']['condition_quote']['source_pages'], [1])
        self.assertFalse(preview['sources']['bundle']['condition_match_verified'])
        self.assertNotIn('effective_score', preview)
        self.assertEqual(len(preview['display_sources']), 4)
        self.assertIn('登録型式: FICTIONAL-ONLY', preview['display_sources'][2]['text'])
        self.assertIn('/vehicle/knowledge-documents/', preview['display_sources'][0]['url'])
        self.assertIn('/vehicle/checklists/', preview['display_sources'][3]['url'])
        self.assertEqual(preview, self.preview())

    def test_preview_rejects_invented_paraphrase_unknown_fields_and_blank_ranges(self):
        for key, value in [('condition_quote', '異音が確認された'), ('action_quote', ''),
                ('actual_observation_confirmed', True), ('action_quote', 'immediately' * 300)]:
            with self.subTest(key=key, value=str(value)[:20]), self.assertRaises(ValueError):
                self.preview({**self.confirmation_selection(), key: value})

    def test_original_quoted_full_sentence_can_be_selected_without_inferred_meaning(self):
        preview = self.preview({**self.confirmation_selection(), 'condition_quote': QUOTE, 'action_quote': QUOTE})
        self.assertEqual(preview['selection']['condition_quote'], QUOTE)
        self.assertEqual(preview['selection']['action_quote'], QUOTE)
        self.assertFalse(preview['sources']['bundle']['immediate_action_verified'])

    def test_trusted_confirmation_mapper_applies_only_approved_high_floor(self):
        from vehicle_priority_assessment import Candidate, assess_priority
        inputs = manufacturer_confirmation_inputs(self.preview(), event_id=111, confirmed_on=self.day)
        candidate = Candidate('same-original-proposal', inputs['scope'], inputs['event_id'],
            facts=inputs['facts'], missing_conditions=inputs['missing_conditions'], input_is_current=True)
        result = assess_priority(candidate, inputs['evidence'], inputs['references'], as_of=self.day)
        self.assertEqual((result['label'], result['base_score'], result['effective_score']), ('高', 0, 60))
        self.assertEqual(result['operation_decision'], 'human_only')
        self.assertEqual(result['applied_floors'][0]['code'], 'manufacturer_immediate_condition')
        self.assertEqual([value['points'] for value in result['factors']], [None, None, None])
        self.assertEqual(self.state()['status'], '運行可')
        self.assertIn('priority_confirmation:111', result['source_ids'])

    def test_trusted_mapper_does_not_accept_modified_preview_or_pre_observation_time(self):
        changed = self.preview(); changed['subject'] = '別部品'
        with self.assertRaises(ValueError):
            manufacturer_confirmation_inputs(changed, event_id=111, confirmed_on=self.day)
        with self.assertRaises(ValueError):
            manufacturer_confirmation_inputs(self.preview(), event_id=True, confirmed_on=self.day)
        with self.assertRaises(ValueError):
            manufacturer_confirmation_inputs(self.preview(), event_id=111, confirmed_on=self.day-timedelta(days=1))

    def test_pending_recheck_or_resolved_observation_cannot_be_confirmed_as_current_condition(self):
        self.repair_priority()
        with self.assertRaisesRegex(ValueError, '現在の未解消'):
            self.preview()
        self.recheck()
        with self.assertRaisesRegex(ValueError, '現在の未解消'):
            self.preview()

    def test_checksum_knowledge_metadata_or_subject_changes_invalidate_preview_fingerprint(self):
        before = self.preview()['fingerprint']
        self.knowledge.confirmed_by = 'another reviewed actor'
        self.db.session.commit()
        self.assertNotEqual(self.preview()['fingerprint'], before)
        self.public.checksum = '0' * 64; self.db.session.commit()
        with self.assertRaises(ValueError): self.preview()


    def test_only_verified_same_original_resolution_can_suppress_confirmed_subject(self):
        preview = self.preview()
        self.assertIsNone(manufacturer_confirmation_terminal(self.vehicle, preview, as_of=self.day))
        self.repair_priority()
        self.assertIsNone(manufacturer_confirmation_terminal(self.vehicle, preview, as_of=self.day))
        self.recheck()
        terminal = manufacturer_confirmation_terminal(self.vehicle, preview, as_of=self.day)
        self.assertEqual(terminal['status'], 'resolved')
        self.assertEqual(terminal['sources']['observations'][0]['input_ref'], self.selection['observation_input_ref'])
        # Source retirement cannot resurrect a genuinely resolved subject.
        self.knowledge.status = 'retired'; self.db.session.commit()
        self.assertEqual(manufacturer_confirmation_terminal(self.vehicle, preview, as_of=self.day)['status'], 'resolved')
        other = self.models.Vehicle.query.filter_by(company_code='B').one()
        self.assertIsNone(manufacturer_confirmation_terminal(other, preview, as_of=self.day))
        self.models.ChecklistEvent.query.filter_by(event_type='解消').delete(); self.db.session.commit()
        self.assertIsNone(manufacturer_confirmation_terminal(self.vehicle, preview, as_of=self.day))

    def test_terminal_does_not_treat_abnormal_recheck_or_changed_ref_as_resolution(self):
        preview = self.preview(); self.repair_priority(); self.recheck('異常あり', '合成再確認で異常あり')
        self.assertIsNone(manufacturer_confirmation_terminal(self.vehicle, preview, as_of=self.day))
        changed = deepcopy(preview); changed['selection']['observation_input_ref'] = self.refs()[0][:-1] + 'z'
        self.assertIsNone(manufacturer_confirmation_terminal(self.vehicle, changed, as_of=self.day))


if __name__ == '__main__': unittest.main()
