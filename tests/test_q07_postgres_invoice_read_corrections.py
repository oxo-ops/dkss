"""Reuse the marked, owned-schema PostgreSQL fixture; no existing DBs are accepted."""
from q10_postgres_support import PostgresFixture
import test_q07_invoice_read_corrections as cases
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import event, text


class PostgresInvoiceReadCorrectionTests(PostgresFixture, cases.InvoiceReadCorrectionTests):
    def race(self, first):
        row, _, _ = self.imported()
        old, _ = self.additional(row)
        self.assertEqual(self.review(old).status_code, 302)
        replacement, _ = self.additional(row, '20')
        forms = {'edit': self.read_form(row, 'primary:', '110'),
                 'replace': {'confirm_correction': '1', 'expected_total': '130.00',
                             'replaces_document_id': old.id}}
        paths = {'edit': f'/vehicle/karte/{self.vehicle.id}/maintenance/{row.id}/edit',
                 'replace': f'/master/vehicles/invoice-reviews/{replacement.id}/correction'}
        actor = self.m.User.query.filter_by(company_code='TEST', username='admin').one()
        clients = {}
        for name in forms:
            client = self.m.app.test_client()
            with client.session_transaction() as state:
                state.update(company_code='TEST', username='admin', role='admin',
                             account_identity=actor.account_identity, password_changed_at=actor.password_changed_at)
            clients[name] = client
        engine = self.m.db.engine
        local, acquired, release = threading.local(), threading.Event(), threading.Event()
        pids = {}

        def before(conn, cursor, statement, parameters, context, many):
            who = getattr(local, 'who', None)
            if who and 'from company' in statement.lower() and 'for update' in statement.lower():
                pids[who] = conn.connection.driver_connection.get_backend_pid()

        def after(conn, cursor, statement, parameters, context, many):
            if (getattr(local, 'who', None) == first and 'from company' in statement.lower()
                    and 'for update' in statement.lower() and not acquired.is_set()):
                acquired.set()
                if not release.wait(8):
                    raise AssertionError('The real first company lock was not released')

        def post(name):
            local.who = name
            with clients[name] as client:
                response = client.post(paths[name], data=forms[name],
                                       headers={'X-DKSS-Final-Submit': '1'})
                try:
                    return response.status_code
                finally:
                    response.close()

        event.listen(engine, 'before_cursor_execute', before)
        event.listen(engine, 'after_cursor_execute', after)
        second = 'replace' if first == 'edit' else 'edit'
        try:
            with ThreadPoolExecutor(2) as pool:
                a = pool.submit(post, first)
                try:
                    self.assertTrue(acquired.wait(5))
                    b = pool.submit(post, second)
                    waiting = False
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        pid = pids.get(second)
                        if pid:
                            with engine.connect() as c:
                                waiting = c.scalar(text(
                                    "SELECT wait_event_type='Lock' FROM pg_stat_activity WHERE pid=:pid"),
                                    {'pid': pid}) is True
                            if waiting:
                                break
                        time.sleep(.02)
                    self.assertTrue(waiting, 'The second HTTP request must wait on a real PostgreSQL lock')
                finally:
                    release.set()
                self.assertEqual(a.result(10), 302)
                self.assertEqual(b.result(10), 400 if first == 'edit' else 409)
        finally:
            release.set()
            event.remove(engine, 'before_cursor_execute', before)
            event.remove(engine, 'after_cursor_execute', after)
        self.m.db.session.expire_all()
        if first == 'edit':
            self.assert_cost(row, 140)
            self.assertEqual(self.review(replacement, 'correction', old).status_code, 302)
        else:
            self.assert_cost(row, 120)
            self.assertEqual(self.read(row, 'primary:', '110').status_code, 302)
        self.assert_cost(row, 130)
        self.assertEqual((old.financial_status, replacement.financial_status), ('superseded', 'confirmed'))

    def test_parallel_read_then_replacement_rejects_stale_total_and_retries(self):
        self.race('edit')

    def test_parallel_replacement_then_read_rejects_stale_source_version_and_retries(self):
        self.race('replace')
