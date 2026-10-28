"""Excel finalization must hold office/type references through vehicle/mapping save."""
from q04_pg_helpers import PrivatePostgresCase


class VehicleBatchMasterLinkTests(PrivatePostgresCase):
    def setUp(self):
        super().setUp()
        with self.app.app_context():
            self.m.Company.query.filter_by(company_code=self.company).update({'vehicle_limit': 100})
            self.db.session.commit()
        self.foreign_before = self.snapshot(self.other)

    def batch(self, writer):
        return self.action('/master/vehicles/import/confirm', {
            'vehicle_type_code': 'Gap-Code', 'vehicle_type': 'Type-A',
            'plate_area': '', 'plate_class': '', 'plate_kana': '', 'plate_number': '',
            'gross_vehicle_weight': '1000', 'max_payload': '500',
            'chassis_number': self.company if writer == 'edit' else self.company + '-BATCH',
            'model_code': '', 'first_registration_date': '', 'inspection_expiry': '',
            'vehicle_name': '', 'body_type': '', 'office': 'Office-A', 'active_status': '有効'})

    def check_race(self, writer, kind, operation, master_first):
        table, column = ('office', 'office') if kind == 'offices' else ('vehicle_type', 'type')
        mutation = self.action(f'/master/{kind}/{self.ids[kind]}/{operation}',
            {'name': 'Renamed'} if operation == 'edit' else {})
        before = self.snapshot(self.company)
        actions = (mutation, self.batch(writer)) if master_first else (self.batch(writer), mutation)
        results, waited = self.schedule(*actions, table)
        mutated, saved = results if master_first else reversed(results)
        state = self.snapshot(self.company)
        self.assertEqual(mutated.get('status'), 302, repr(results))
        if master_first:
            self.assertEqual(saved.get('status'), 400, repr(results))
            self.assertEqual([r['chassis_number'] for r in state['vehicle']],
                             [r['chassis_number'] for r in before['vehicle']])
            self.assertFalse(any(r['excel_value'] == 'Gap-Code' for r in state['vehicle_type_import_mapping']))
        else:
            self.assertEqual(saved.get('status'), 200, repr(results))
            chassis = self.company if writer == 'edit' else self.company + '-BATCH'
            row = next(r for r in state['vehicle'] if r['chassis_number'] == chassis)
            self.assertEqual(row[column], 'Renamed' if operation == 'edit' else '')
            if kind == 'vehicle-types':
                mappings = [r for r in state['vehicle_type_import_mapping'] if r['excel_value'] == 'Gap-Code']
                self.assertEqual([r['vehicle_type_name'] for r in mappings], ['Renamed'] if operation == 'edit' else [])
        self.assertTrue(waited, 'Finalization must share-lock its selected masters')
        self.assertEqual(self.snapshot(self.other), self.foreign_before)

    def test_controls_new_and_update_use_real_batch_route(self):
        for writer in ('new', 'edit'):
            self.assertEqual(self.post('A', self.batch(writer)).get('status'), 200)
        self.assertEqual(self.snapshot(self.other), self.foreign_before)


def case(writer, kind, operation, first):
    def check(self):
        self.check_race(writer, kind, operation, first)
    return check


for _writer in ('new', 'edit'):
    for _kind in ('offices', 'vehicle-types'):
        for _operation in ('edit', 'delete'):
            for _first in (False, True):
                setattr(VehicleBatchMasterLinkTests,
                    'test_' + _writer + '_' + _kind.replace('-', '_') + '_' + _operation
                    + ('_master_first' if _first else '_import_first'),
                    case(_writer, _kind, _operation, _first))
