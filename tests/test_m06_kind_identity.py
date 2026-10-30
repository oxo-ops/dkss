"""Independent kind contract boundaries; no DB/schema writes."""
import copy
import json
import unittest
from types import SimpleNamespace

from inspection_kind_identity import document_kind_identity, new_storage_kind, stored_kind_identity


class KindIdentityTests(unittest.TestCase):
    def setUp(self):
        self.record = SimpleNamespace(id=17, company_code='A', vehicle_record_id=9,
            inspection_type='12month', source_draft_id='draft-A', source_record_index=0,
            details_json=json.dumps({'inspection_type': '12month', 'inspection_type_raw': '12か月定期点検',
                                     'vehicle_record_id': 9}))
        self.draft = SimpleNamespace(id='draft-A', company_code='A', document_type='inspection', status='completed',
            preview_json=json.dumps({'original_records': [{'inspection_type': '12month', 'inspection_type_raw': '12か月定期点検'}]}),
            result_json=json.dumps({'records': [{'record_index': 0, 'record_id': 17, 'vehicle_record_id': 9,
                                                'document_type': 'inspection'}]}))

    def identity(self):
        return document_kind_identity(self.record, self.draft, company_code='A', vehicle_id=9)

    def test_new_kinds_are_distinct_without_changing_legacy_values(self):
        self.assertNotEqual(new_storage_kind('12month'), new_storage_kind('vehicle_inspection'))
        self.assertEqual(stored_kind_identity(new_storage_kind('12month')).kind, '12month')
        self.assertEqual(stored_kind_identity('vehicle_inspection').kind, 'vehicle_inspection')
        self.assertIsNone(stored_kind_identity('12month').kind)
        self.assertEqual(self.record.inspection_type, '12month')

    def test_existing_confirmed_periodic_does_not_need_a_new_marker(self):
        before = copy.deepcopy((vars(self.record), vars(self.draft)))
        result = self.identity()
        self.assertEqual((result.kind, result.basis), ('12month', 'confirmed_document'))
        self.assertEqual(before, (vars(self.record), vars(self.draft)))

    def test_legacy_storage_with_explicit_confirmed_car_values_is_read_without_reclassification(self):
        details = json.loads(self.record.details_json)
        details.update(inspection_type='vehicle_inspection', inspection_type_raw='車検')
        self.record.details_json = json.dumps(details)
        self.draft.preview_json = json.dumps({'original_records': [
            {'inspection_type': 'vehicle_inspection', 'inspection_type_raw': '車検'}]})
        self.assertEqual(self.identity().kind, 'vehicle_inspection')
        self.assertEqual(self.record.inspection_type, '12month')

    def test_conflicting_original_does_not_get_inferred_as_a_car_inspection(self):
        for label in ('車検', '車検／12か月点検', '区分不明', None, [], {}):
            with self.subTest(label=label):
                self.record.details_json = json.dumps({'inspection_type': '12month',
                    'inspection_type_raw': label, 'vehicle_record_id': 9})
                self.draft.preview_json = json.dumps({'original_records': [{'inspection_type': '12month',
                    'inspection_type_raw': label}]})
                self.assertFalse(self.identity().confirmed)
                self.assertEqual(self.record.inspection_type, '12month')

    def test_company_vehicle_source_and_registration_boundaries(self):
        mutations = [(self.record, 'company_code', 'B'), (self.record, 'vehicle_record_id', 10),
            (self.draft, 'company_code', 'B'), (self.record, 'source_draft_id', 'foreign'),
            (self.record, 'source_record_index', True), (self.record, 'source_record_index', -1),
            (self.draft, 'status', 'preview'), (self.draft, 'document_type', 'certificate'),
            (self.record, 'details_json', '[]'), (self.draft, 'preview_json', '{'),
            (self.draft, 'result_json', json.dumps({'records': []}))]
        for obj, field, value in mutations:
            with self.subTest(field=field, value=value):
                original = getattr(obj, field)
                setattr(obj, field, value)
                self.assertFalse(self.identity().confirmed)
                setattr(obj, field, original)

    def test_conflicting_registration_at_same_source_index_is_not_ignored(self):
        result = json.loads(self.draft.result_json)
        result['records'].append({**result['records'][0], 'record_id': 999})
        self.draft.result_json = json.dumps(result)
        self.assertFalse(self.identity().confirmed)

    def test_unknown_new_input_is_rejected_instead_of_aliasing_to_annual(self):
        for raw in (None, [], {}, 'annual', 'periodic_12month'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                new_storage_kind(raw)
