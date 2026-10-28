"""Master changes versus new/edited history; both commit orders, real routes."""
from q04_pg_helpers import PrivatePostgresCase


class HistoryMasterLinkTests(PrivatePostgresCase):
    def setUp(self):
        super().setUp()
        self.master_ids = {}
        self.master_ids['offices'] = self.ids['offices']
        with self.app.app_context():
            for company in (self.company, self.other):
                self.db.session.add(self.m.User(company_code=company, username='driver',
                    last_name='Synthetic', role='user', password='unused', office='Office-A', password_changed_at=self.stamp))
                for kind, model, name in (
                    ('delivery-places', self.m.DeliveryPlace, 'Place-A'),
                    ('patrol-content-types', self.m.PatrolContentType, 'Content-A')):
                    row = model(company_code=company, name=name)
                    self.db.session.add(row)
                    self.db.session.flush()
                    if company == self.company:
                        self.master_ids[kind] = row.id
                self.db.session.add(self.m.DeliveryPlace(company_code=company, name='Stable-Place'))
                row = self.m.PatrolResult(company_code=company, target_type='delivery_place',
                    delivery_place='Stable-Place' if company == self.company else 'Place-A',
                    content_type='' if company == self.company else 'Content-A',
                    created_by_username='admin', date='2026-10-01', category='品質',
                    content='Synthetic before', approval_status='未対応')
                self.db.session.add(row)
                self.db.session.flush()
                if company == self.company:
                    self.patrol_id = row.id
            self.db.session.commit()
        self.foreign_before = self.snapshot(self.other)

    def related_action(self, kind, writer):
        data = {'target_type': 'delivery_place', 'delivery_place': 'Place-A' if kind == 'delivery-places' else 'Stable-Place',
                'content_type': 'Content-A' if kind == 'patrol-content-types' else '',
                'date': '2026-10-02', 'category': '品質', 'content': 'Synthetic after'}
        if kind == 'offices':
            data.update(target_type='user', target_user='driver', delivery_place='')
        return self.action('/pointouts/new' if writer == 'new' else f'/pointouts/{self.patrol_id}/edit', data)

    def check_history_race(self, kind, writer, operation, master_first):
        table = {'delivery-places': 'delivery_place', 'patrol-content-types': 'patrol_content_type', 'offices': 'office'}[kind]
        column = {'delivery-places': 'delivery_place', 'patrol-content-types': 'content_type', 'offices': 'office'}[kind]
        name = {'delivery-places': 'Place-A', 'patrol-content-types': 'Content-A', 'offices': 'Office-A'}[kind]
        if kind == 'offices':
            with self.app.app_context():
                row = self.db.session.get(self.m.PatrolResult, self.patrol_id)
                row.target_type, row.target_username, row.office = 'user', 'driver', ''
                self.db.session.commit()
        mutation = self.action(f'/master/{kind}/{self.master_ids[kind]}/{operation}',
                               {'name': 'Renamed'} if operation == 'edit' else {})
        related = self.related_action(kind, writer)
        before = self.snapshot(self.company)
        actions = (mutation, related) if master_first else (related, mutation)
        results, waited = self.schedule(*actions, 'driver' if kind == 'offices' else table,
            first_table='patrol_result' if master_first else None)
        master, saved = results if master_first else reversed(results)
        state = self.snapshot(self.company)
        if master_first or kind == 'offices':
            self.assertEqual(master.get('status'), 302, repr(results))
            self.assertEqual(saved.get('status'), 400, repr(results))
            self.assertEqual(state['patrol_result'], before['patrol_result'], 'Rejected save changed history')
            row = next((r for r in state[table] if r['id'] == self.master_ids[kind]), None)
            if operation == 'edit':
                self.assertEqual(row['name'], 'Renamed')
            else:
                self.assertIsNone(row)
        else:
            self.assertEqual(saved.get('status'), 302, repr(results))
            self.assertEqual(master.get('status'), 409, repr(results))
            self.assertEqual(state[table], before[table], 'Used historical master was changed')
            written = next(r for r in state['patrol_result'] if r['content'] == 'Synthetic after')
            self.assertEqual(written[column], name)
            self.assertEqual(len(state['patrol_result']), len(before['patrol_result']) + (writer == 'new'))
        if master_first or kind != 'offices':
            self.assertTrue(waited, 'The competing request must wait on the real master row')
        self.assertEqual(self.snapshot(self.other), self.foreign_before)

    def test_normal_new_and_edit_controls(self):
        for writer in ('new', 'edit'):
            response = self.post('A', self.related_action('delivery-places', writer))
            self.assertEqual(response.get('status'), 302, repr(response))
        self.assertEqual(self.snapshot(self.other), self.foreign_before)

    def test_office_copied_from_driver_new_and_edit_controls(self):
        with self.app.app_context():
            row = self.db.session.get(self.m.PatrolResult, self.patrol_id)
            row.target_type, row.target_username = 'user', 'driver'
            self.db.session.commit()
        for writer in ('new', 'edit'):
            self.assertEqual(self.post('A', self.related_action('offices', writer)).get('status'), 302)
        self.assertEqual(self.snapshot(self.other), self.foreign_before)

    def test_new_failure_does_not_leave_partial_patrol_or_notifications(self):
        self.assert_failed_save_is_atomic(self.related_action('delivery-places', 'new'), 'insert into patrol_result ')

    def test_edit_failure_does_not_leave_partial_patrol_or_notifications(self):
        self.assert_failed_save_is_atomic(self.related_action('delivery-places', 'edit'), 'update patrol_result ')


def case(kind, writer, operation, master_first):
    def check(self):
        self.check_history_race(kind, writer, operation, master_first)
    return check


for _kind in ('delivery-places', 'patrol-content-types', 'offices'):
    for _writer in ('new', 'edit'):
        for _operation in ('edit', 'delete'):
            for _first in (False, True):
                setattr(HistoryMasterLinkTests,
                    'test_' + _kind.replace('-', '_') + '_' + _writer + '_' + _operation
                    + ('_master_first' if _first else '_history_first'),
                    case(_kind, _writer, _operation, _first))
