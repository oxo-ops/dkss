"""Single reminder setting per vehicle/checklist, using real concurrent HTTP."""
import json
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import event

import test_q03_form_generation as forms


class NotifySettingConcurrencyTests(unittest.TestCase):
    setUpClass = classmethod(forms.FormGenerationTests.setUpClass.__func__)
    tearDownClass = classmethod(forms.FormGenerationTests.tearDownClass.__func__)
    setUp = forms.FormGenerationTests.setUp
    tearDown = forms.FormGenerationTests.tearDown
    login = forms.FormGenerationTests.login
    request = forms.FormGenerationTests.request
    _vehicle = forms.FormGenerationTests._vehicle
    _page = forms.FormGenerationTests._page
    _replace = forms.FormGenerationTests._replace
    _snapshot = forms.FormGenerationTests._snapshot

    def prepare(self):
        row, page = self._vehicle()
        self.login('admin')
        path = f'/vehicle/checklists/{row.checklist_id}/reminder-notify-users'
        return row, page, path

    def concurrent(self, existing=False):
        row, page, path = self.prepare()
        payload = {'vehicle_record_id': row.vehicle_record_id, **self._page(page)}
        if existing:
            self.assertEqual(self.request('POST', path, data={**payload, 'reminder_notify_users': 'admin'}).status_code, 200)
        with self.client.session_transaction() as browser:
            claims = dict(browser)
        clients = [self.app.test_client(), self.app.test_client()]
        for client in clients:
            with client.session_transaction() as browser:
                browser.update(claims)
        start = threading.Barrier(2)
        both_read = threading.Event()
        lock = threading.Lock()
        reads = []
        pids = set()
        local = threading.local()

        def after_select(connection, cursor, statement, params, context, many):
            if (statement.lstrip().lower().startswith('select')
                    and 'from vehicle_checklist_notify_setting' in statement.lower()
                    and not getattr(local, 'seen', False)):
                local.seen = True
                with lock:
                    reads.append(True)
                    if connection.dialect.name == 'postgresql':
                        pids.add(connection.connection.driver_connection.get_backend_pid())
                    if len(reads) == 2:
                        both_read.set()
                # On a serialized implementation the second reader cannot enter
                # yet. The bounded rendezvous also exposes two empty reads before
                # either INSERT in the unprotected PostgreSQL implementation.
                both_read.wait(0.4)

        def post(pair):
            client, username = pair
            start.wait(10)
            with client.post(path, data={**payload, 'reminder_notify_users': username}) as response:
                return response.status_code

        engine = self.db.engine
        event.listen(engine, 'after_cursor_execute', after_select)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                statuses = list(pool.map(post, zip(clients, ('reviewer', 'outsider'))))
        finally:
            event.remove(engine, 'after_cursor_execute', after_select)
        self.assertEqual(statuses, [200, 200])
        if engine.dialect.name == 'postgresql':
            self.assertEqual(len(pids), 2, 'Two real database connections must execute')
        self.db.session.expire_all()
        settings = self.models.VehicleChecklistNotifySetting.query.filter_by(
            company_code='A', checklist_id=row.checklist_id, vehicle_record_id=row.vehicle_record_id).all()
        self.assertEqual(len(settings), 1, 'Parallel saves must not create duplicate setting parents')
        from dkss_app.checklist_notify_identity import VehicleChecklistNotifyAccount, resolved_notify_users
        history = VehicleChecklistNotifyAccount.query.filter_by(setting_id=settings[0].id).all()
        self.assertEqual(len(history), 3 if existing else 2)
        self.assertEqual({u.username for u in resolved_notify_users('A', row.checklist_id, row.vehicle_record_id)},
                         set(json.loads(settings[0].notify_users_json)))

    def test_parallel_initial_setting_has_one_parent(self):
        self.concurrent()

    def test_parallel_existing_setting_keeps_history(self):
        self.concurrent(existing=True)

    def test_other_company_cannot_save_setting(self):
        row, page, path = self.prepare()
        proof = self._page(page)
        self.login('admin', 'B')
        before = self._snapshot()
        self.assertEqual(self.request('POST', path, data={**proof, 'vehicle_record_id': row.vehicle_record_id,
                                                        'reminder_notify_users': 'reviewer'}).status_code, 404)
        self.assertEqual(self._snapshot(), before)

    def test_replaced_recipient_stays_rejected(self):
        row, page, path = self.prepare()
        proof = self._page(page)
        self._replace()
        before = self._snapshot()
        self.assertEqual(self.request('POST', path, data={**proof, 'vehicle_record_id': row.vehicle_record_id,
                                                        'reminder_notify_users': 'reviewer'}).status_code, 409)
        self.assertEqual(self._snapshot(), before)


@unittest.skipUnless(os.environ.get('Q03_POSTGRES_TEST_URL'), 'explicit disposable PostgreSQL required')
class PostgresNotifySettingConcurrencyTests(NotifySettingConcurrencyTests):
    setUpClass = classmethod(forms.PostgresFormGenerationTests.setUpClass.__func__)
    tearDownClass = classmethod(forms.PostgresFormGenerationTests.tearDownClass.__func__)
