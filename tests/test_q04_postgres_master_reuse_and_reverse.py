"""Previously uncovered commit order and same-name replacement for offices/types."""
import json

import test_q04_postgres_related_writes as related
from q04_pg_helpers import PrivatePostgresCase


class ReverseRelatedWriteTests(PrivatePostgresCase):
    setUp = related.RelatedMasterWriteTests.setUp
    related_request = related.RelatedMasterWriteTests.related_request
    target_rows = related.RelatedMasterWriteTests.target_rows
    orphans = related.RelatedMasterWriteTests.orphans

    def check_reverse(self, writer, kind, operation):
        before = self.target_rows(writer)
        path, data = self.related_request(writer, kind)
        master = self.action(f'/master/{kind}/{self.ids[kind]}/{operation}',
            {'name': 'Renamed'} if operation == 'edit' else {})
        results, waited = self.schedule(master, self.action(path, data),
            'office' if kind == 'offices' else 'vehicle_type')
        self.assertEqual(results[0].get('status'), 302, repr(results))
        self.assertEqual(results[1].get('status'), 400, repr(results))
        self.assertTrue(waited)
        self.assertEqual(self.target_rows(writer), before, 'Rejected request left partial User/Driver/Vehicle changes')
        self.assertEqual(self.orphans(), [])
        self.assertEqual(self.snapshot(self.other), self.foreign_before)


def reverse_case(writer, kind, operation):
    def check(self):
        self.check_reverse(writer, kind, operation)
    return check


for _writer in ('vehicle_new', 'vehicle_edit', 'driver_new', 'driver_edit'):
    for _kind in (('offices', 'vehicle-types') if _writer.startswith('vehicle_') else ('offices',)):
        for _operation in ('edit', 'delete'):
            setattr(ReverseRelatedWriteTests,
                'test_' + _writer + '_' + _kind.replace('-', '_') + '_' + _operation,
                reverse_case(_writer, _kind, _operation))


class MasterNameReuseTests(PrivatePostgresCase):
    def check_reuse(self, kind):
        model = self.m.Office if kind == 'offices' else self.m.VehicleType
        table, column, name = (('office', 'office', 'Office-A') if kind == 'offices'
                               else ('vehicle_type', 'type', 'Type-A'))
        foreign = self.snapshot(self.other)
        old_id = self.ids[kind]
        delete = self.action(f'/master/{kind}/{old_id}/delete')
        self.assertEqual(self.post('A', delete).get('status'), 302)
        self.assertEqual(self.post('A', self.action(f'/master/{kind}/new', {'name': name})).get('status'), 302)
        state = self.snapshot(self.company)
        self.assertNotEqual(state[table][0]['id'], old_id)
        self.assertEqual(state['vehicle'][0][column], '', 'Re-registering a name must not restore old assignments')
        if kind == 'offices':
            self.assertEqual(state['user'][0]['office'], '')
            self.assertEqual(state['driver'][0]['office'], '')
        else:
            self.assertEqual(state['vehicle_type_import_mapping'], [])
        for action in (delete, self.action(f'/master/{kind}/{old_id}/edit', {'name': 'Stale'})):
            self.assertEqual(self.post('A', action).get('status'), 302)
            self.assertEqual(self.snapshot(self.company), state)
        saved = next(r for r in state['master_display_order'] if r['kind'] == kind)
        self.assertNotIn(old_id, json.loads(saved['ordered_ids_json']))
        self.assertEqual(self.snapshot(self.other), foreign)

    def test_office_same_name_replacement_does_not_rebind_old_references(self):
        self.check_reuse('offices')

    def test_vehicle_type_same_name_replacement_does_not_rebind_old_references(self):
        self.check_reuse('vehicle-types')
