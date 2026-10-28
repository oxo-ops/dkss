"""Delivery-place integrity, re-registration and rollback on private PostgreSQL."""
import json
import os
from unittest.mock import patch

from sqlalchemy import event, inspect, text

from q04_pg_helpers import PrivatePostgresCase


class DeliveryIntegrityTests(PrivatePostgresCase):
    def setUp(self):
        super().setUp()
        with self.app.app_context():
            for company in (self.company, self.other):
                row = self.m.DeliveryPlace(company_code=company, name='Place-A')
                self.db.session.add(row)
                self.db.session.flush()
                if company == self.company:
                    self.place_id = row.id
                self.db.session.add(self.m.MasterDisplayOrder(company_code=company,
                    kind='delivery-places', ordered_ids_json=json.dumps([row.id])))
            self.db.session.commit()
            # Bootstrap the normal per-company defaults before migration snapshots.
            from dkss_app.database import init_db
            with patch.dict(os.environ, {'ITC_INITIAL_PASSWORD': 'Q04-Disposable-Only-742!'}):
                init_db()
        self.foreign_before = self.snapshot(self.other)

    def mutation(self, operation, name='Place-B', ident=None):
        return self.action('/master/delivery-places/' + str(ident or self.place_id) + '/' + operation,
                           {'name': name} if operation == 'edit' else {})

    def test_schema_enforces_company_name_on_fresh_database(self):
        with self.app.app_context():
            indices = inspect(self.engine).get_indexes('delivery_place')
        self.assertTrue(any(x['unique'] and x['column_names'] == ['company_code', 'name']
                            for x in indices), repr(indices))

    def test_same_company_concurrent_create_rejects_one_request(self):
        action = self.action('/master/delivery-places/new', {'name': 'Concurrent'})
        responses, _ = self.schedule(action, action, 'delivery_place', 'insert into delivery_place ')
        self.assertCountEqual([x.get('status') for x in responses], [302, 409])
        self.assertEqual(sum(x['name'] == 'Concurrent' for x in self.snapshot(self.company)['delivery_place']), 1)
        self.assertEqual(self.snapshot(self.other), self.foreign_before)

    def test_other_companies_can_concurrently_use_the_same_name(self):
        responses, _ = self.schedule(
            self.action('/master/delivery-places/new', {'name': 'Concurrent'}),
            self.action('/master/delivery-places/new', {'name': 'Concurrent'}, self.other),
            'delivery_place', 'insert into delivery_place ')
        self.assertEqual([x.get('status') for x in responses], [302, 302])
        for company in (self.company, self.other):
            self.assertEqual(sum(x['name'] == 'Concurrent' for x in self.snapshot(company)['delivery_place']), 1)

    def test_import_racing_manual_create_is_atomic(self):
        manual = self.action('/master/delivery-places/new', {'name': 'Concurrent'})
        batch = self.action('/master/delivery-places/import/confirm',
            {'delivery_place_name': ['Batch-only', 'Concurrent']})
        responses, _ = self.schedule(manual, batch, 'delivery_place', 'insert into delivery_place ')
        self.assertIn([r.get('status') for r in responses], ([302, 409], [409, 200]))
        names = [r['name'] for r in self.snapshot(self.company)['delivery_place']]
        self.assertEqual(names.count('Concurrent'), 1)
        self.assertEqual(names.count('Batch-only'), int(responses[1]['status'] == 200),
                         'A conflicting import must roll back its other insertions')
        self.assertEqual(self.snapshot(self.other), self.foreign_before)

    def test_two_imports_with_one_shared_name_roll_back_the_losing_batch(self):
        actions = [self.action('/master/delivery-places/import/confirm',
                   {'delivery_place_name': ['Batch-' + label, 'Concurrent']}) for label in ('A', 'B')]
        responses, _ = self.schedule(*actions, 'delivery_place', 'insert into delivery_place ')
        self.assertCountEqual([r.get('status') for r in responses], [200, 409])
        names = [r['name'] for r in self.snapshot(self.company)['delivery_place']]
        self.assertEqual(names.count('Concurrent'), 1)
        for label, response in zip(('A', 'B'), responses):
            self.assertEqual(names.count('Batch-' + label), int(response['status'] == 200))
        self.assertEqual(self.snapshot(self.other), self.foreign_before)

    def test_invalid_later_import_name_does_not_save_earlier_names(self):
        before = self.snapshot(self.company)
        response = self.post('A', self.action('/master/delivery-places/import/confirm',
            {'delivery_place_name': ['Must-not-survive', 'x' * 101]}))
        self.assertEqual(response.get('status'), 400)
        self.assertEqual(self.snapshot(self.company), before)
        self.assertEqual(self.snapshot(self.other), self.foreign_before)

    def test_disjoint_rows_cannot_concurrently_rename_to_one_name(self):
        with self.app.app_context():
            second = self.m.DeliveryPlace(company_code=self.company, name='Second')
            self.db.session.add(second)
            self.db.session.commit()
            ident = second.id
        responses, _ = self.schedule(self.mutation('edit', 'Concurrent'),
            self.mutation('edit', 'Concurrent', ident), 'delivery_place', 'update delivery_place ')
        self.assertCountEqual([x.get('status') for x in responses], [302, 409])
        self.assertEqual(sum(x['name'] == 'Concurrent' for x in self.snapshot(self.company)['delivery_place']), 1)
        self.assertEqual(self.snapshot(self.other), self.foreign_before)

    def race_mutations(self, first, second):
        responses, waited = self.schedule(self.mutation(first), self.mutation(second, 'Place-C'), 'delivery_place')
        self.assertEqual([x.get('status') for x in responses], [302, 302])
        self.assertTrue(waited, 'Master mutations must serialize on the same row')
        state = self.snapshot(self.company)
        if first == second == 'edit':
            self.assertEqual([x['name'] for x in state['delivery_place']], ['Place-C'])
        else:
            self.assertEqual(state['delivery_place'], [])
            self.assertEqual(sum(x['action'] == 'delivery_place_deleted' for x in state['audit_log']), 1)
            saved = next(x for x in state['master_display_order'] if x['kind'] == 'delivery-places')
            self.assertNotIn(self.place_id, json.loads(saved['ordered_ids_json']))
        self.assertEqual(self.snapshot(self.other), self.foreign_before)

    def test_rename_then_rename(self):
        self.race_mutations('edit', 'edit')

    def test_rename_then_delete(self):
        self.race_mutations('edit', 'delete')

    def test_delete_then_rename(self):
        self.race_mutations('delete', 'edit')

    def test_delete_then_delete_has_one_audit(self):
        self.race_mutations('delete', 'delete')

    def test_delete_reregister_and_stale_id_do_not_affect_replacement(self):
        self.assertEqual(self.post('A', self.mutation('delete'))['status'], 302)
        self.assertEqual(self.post('A', self.action('/master/delivery-places/new', {'name': 'Place-A'}))['status'], 302)
        before = self.snapshot(self.company)
        self.assertNotEqual(before['delivery_place'][0]['id'], self.place_id)
        for operation in ('edit', 'delete'):
            self.assertEqual(self.post('A', self.mutation(operation))['status'], 302)
            self.assertEqual(self.snapshot(self.company), before)
        self.assertEqual(self.snapshot(self.other), self.foreign_before)

    def test_foreign_ids_and_invalid_names_leave_all_data_unchanged(self):
        foreign_id = self.foreign_before['delivery_place'][0]['id']
        before = self.snapshot(self.company)
        for operation in ('edit', 'delete'):
            self.assertEqual(self.post('A', self.mutation(operation, ident=foreign_id))['status'], 302)
        for name in ('', ' ', 'x' * 101):
            self.assertEqual(self.post('A', self.mutation('edit', name))['status'], 400)
        self.assertEqual(self.snapshot(self.company), before)
        self.assertEqual(self.snapshot(self.other), self.foreign_before)

    def test_delete_failure_rolls_back_master_order_and_audit_then_retry_succeeds(self):
        before = self.snapshot(self.company)
        reached = []
        def fail_after_delete(connection, cursor, statement, parameters, context, executemany):
            if statement.lower().startswith('delete from delivery_place '):
                reached.append(True)
                raise RuntimeError('Q04_DELIVERY_AFTER_DELETE')
        event.listen(self.engine, 'after_cursor_execute', fail_after_delete)
        try:
            response = self.post('A', self.mutation('delete'))
        finally:
            event.remove(self.engine, 'after_cursor_execute', fail_after_delete)
        self.assertEqual(reached, [True])
        self.assertTrue(response.get('error') or response.get('status') == 500, repr(response))
        self.assertEqual(self.snapshot(self.company), before)
        self.assertEqual(self.snapshot(self.other), self.foreign_before)
        self.assertEqual(self.post('A', self.mutation('delete'))['status'], 302)
        self.assertEqual(sum(x['action'] == 'delivery_place_deleted'
                             for x in self.snapshot(self.company)['audit_log']), 1)

    def test_legacy_upgrade_is_repeatable_and_preserves_company_data(self):
        from dkss_app.database import init_db
        with self.app.app_context():
            self.db.session.execute(text('DROP INDEX IF EXISTS uq_delivery_place_company_name'))
            self.db.session.commit()
        before = self.snapshot(self.company), self.snapshot(self.other)
        with self.app.app_context(), patch.dict(os.environ, {'ITC_INITIAL_PASSWORD': 'Q04-Disposable-Only-742!'}):
            init_db()
            init_db()
        self.assertEqual((self.snapshot(self.company), self.snapshot(self.other)), before)
        self.test_schema_enforces_company_name_on_fresh_database()

    def test_legacy_duplicates_stop_upgrade_without_rewriting_or_partial_index(self):
        from dkss_app.database import init_db
        with self.app.app_context():
            self.db.session.execute(text('DROP INDEX IF EXISTS uq_delivery_place_company_name'))
            self.db.session.add(self.m.DeliveryPlace(company_code=self.company, name='Place-A'))
            self.db.session.commit()
        before = self.snapshot(self.company), self.snapshot(self.other)
        try:
            with self.app.app_context(), patch.dict(os.environ, {'ITC_INITIAL_PASSWORD': 'Q04-Disposable-Only-742!'}):
                with self.assertRaisesRegex(RuntimeError, '納入先'):
                    init_db()
            self.assertEqual((self.snapshot(self.company), self.snapshot(self.other)), before)
            with self.app.app_context():
                self.assertNotIn('uq_delivery_place_company_name',
                    [x['name'] for x in inspect(self.engine).get_indexes('delivery_place')])
        finally:
            # Restore this class's schema for the following test, not request state.
            with self.app.app_context():
                rows = self.m.DeliveryPlace.query.filter_by(company_code=self.company).order_by(self.m.DeliveryPlace.id).all()
                self.db.session.delete(rows[-1])
                self.db.session.commit()
            with self.app.app_context(), patch.dict(os.environ, {'ITC_INITIAL_PASSWORD': 'Q04-Disposable-Only-742!'}):
                init_db()
