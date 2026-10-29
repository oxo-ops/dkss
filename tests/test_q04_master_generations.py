"""Real rendered master forms, forced ID reuse and unchanged business history."""
import json
from html.parser import HTMLParser
import unittest

from flask.testing import FlaskClient

import test_q04_master_rename as baseline_fixture


KINDS = {'offices': 'Office', 'vehicle-types': 'VehicleType',
         'delivery-places': 'DeliveryPlace', 'license-types': 'LicenseType',
         'patrol-content-types': 'PatrolContentType'}


class FormInputs(HTMLParser):
    def __init__(self, html, path):
        super().__init__(convert_charrefs=True)
        self.path, self.current, self.forms = path, None, {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'form':
            self.current = values.get('action') or self.path
            self.forms.setdefault(self.current, {})
        elif tag == 'input' and self.current and values.get('type') == 'hidden':
            self.forms[self.current][values.get('name')] = values.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'form': self.current = None


class GenerationCases:
    force_id_reuse = False

    def model(self, kind):
        return getattr(self.models, KINDS[kind])

    def foreign_controls(self):
        with self.app.app_context():
            for kind in KINDS:
                model = self.model(kind)
                if model.query.filter_by(company_code=self.other).first() is None:
                    self.db.session.add(model(company_code=self.other, name='Foreign-generation-control'))
            self.db.session.commit()

    def plain_client(self, company=None):
        # Deliberately bypass any fresh-form adapter used by older route tests.
        company = company or self.company
        client = FlaskClient(self.app, use_cookies=True)
        with self.app.app_context():
            user = self.models.User.query.filter_by(company_code=company, username='admin').one()
            state = dict(company_code=company, username='admin', role='admin',
                         account_identity=user.account_identity, password_changed_at=user.password_changed_at)
        with client.session_transaction() as session: session.update(state)
        return client

    def form(self, client, kind, ident, operation):
        path = f'/master/{kind}/{ident}/edit' if operation == 'edit' else f'/master/{kind}'
        response = client.get(path)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        inputs = FormInputs(response.get_data(as_text=True), path).forms
        response.close()
        target = path if operation == 'edit' else f'/master/{kind}/{ident}/delete'
        return dict(inputs.get(target, {}))

    def post(self, client, kind, ident, operation, data):
        response = client.post(f'/master/{kind}/{ident}/{operation}', data=data)
        self.addCleanup(response.close)
        return response

    def create(self, client, kind, name):
        response = client.post(f'/master/{kind}/new', data={'name': name})
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))
        with self.app.app_context():
            return self.model(kind).query.filter_by(company_code=self.company, name=name).one().id

    def snapshot_all(self):
        with self.app.app_context():
            self.db.session.expire_all()
            return {t.name: [tuple(r) for r in self.db.session.execute(t.select().order_by(*t.primary_key.columns))]
                    for t in self.db.metadata.sorted_tables}

    def protect_history(self):
        m = self.models
        with self.app.app_context():
            vehicle = m.Vehicle.query.filter_by(company_code=self.company).first()
            self.db.session.add(m.VehicleMaintenanceRecord(company_code=self.company,
                vehicle_record_id=vehicle.id, entry_date='2026-10-01', total_cost=100,
                invoice_number='GEN-HISTORY-INVOICE', invoice_date='2026-10-01',
                invoice_details_json=json.dumps({'schema_version': 1,
                    'cost_attribution': {'office': 'Historical-only', 'basis': 'user_confirmed'},
                    'source': {'draft_id': 'synthetic-generation-history', 'record_index': 0}})))
            self.db.session.add(m.News(company_code=self.company, title='Historical notice',
                message='Preserve', target_type='all', target_value='', files_json='[]'))
            self.db.session.add(m.Notification(company_code=self.company, title='Historical notification',
                message='Preserve', target_user='Synthetic admin', target_username='admin'))
            self.db.session.add(m.PatrolResult(company_code=self.company, office='Office-A', content='Preserve'))
            definition = m.Checklist(company_code=self.company, name='Generation history', target='vehicle')
            self.db.session.add(definition)
            self.db.session.flush()
            self.db.session.add(m.ChecklistResult(company_code=self.company, checklist_id=definition.id,
                target_type='office', target_office='Office-A', status='approved',
                answers_json='[{"answer":"historical"}]', checklist_snapshot_json='{"preserve":true}'))
            self.db.session.add(m.VehicleChecklistResult(company_code=self.company, checklist_id=definition.id,
                vehicle_record_id=vehicle.id, year='2026', month='10', day='1', status='approved',
                answers_json='[{"answer":"historical"}]', checklist_snapshot_json='{"preserve":true}'))
            self.db.session.commit()

    def stale_case(self, kind, operation):
        client = self.plain_client()
        name = 'Generation-Probe'
        old = self.create(client, kind, name)
        stale = self.form(client, kind, old, operation)
        fresh_delete = self.form(client, kind, old, 'delete')
        self.assertEqual(self.post(client, kind, old, 'delete', fresh_delete).status_code, 302)
        new = self.create(client, kind, name)
        with self.app.app_context():
            model = self.model(kind)
            if self.force_id_reuse and new != old:
                # Synthetic restore/sequence-fault condition; PostgreSQL normally allocates a new ID.
                self.db.session.execute(model.__table__.update().where(model.id == new).values(id=old))
                self.db.session.commit()
                new = old
            self.assertEqual(new, old, 'This case must actually reuse the primary key')
            if kind == 'offices':
                for model in (self.models.Vehicle, self.models.User, self.models.Driver):
                    model.query.filter_by(company_code=self.company).update({'office': name})
            elif kind == 'vehicle-types':
                self.models.Vehicle.query.filter_by(company_code=self.company).update({'type': name})
                self.db.session.add(self.models.VehicleTypeImportMapping(company_code=self.company,
                    excel_value='New generation mapping', vehicle_type_name=name))
            elif kind == 'license-types' and operation == 'edit':
                self.models.Driver.query.filter_by(company_code=self.company).update(
                    {'licenses_json': json.dumps([{'type': name, 'expiry': '2030-01-01'}])})
            self.db.session.commit()
        self.protect_history()
        before = self.snapshot_all()
        if operation == 'edit': stale['name'] = 'Stale-Edit'
        response = self.post(client, kind, old, operation, stale)
        self.assertEqual(response.status_code, 409, response.get_data(as_text=True))
        self.assertEqual(self.snapshot_all(), before, 'Old form changed replacement or related/history rows')
        self.assertIn('再読み込み', response.get_data(as_text=True))

    def test_current_forms_still_edit_delete_and_reregister_all_five(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                client = self.plain_client()
                ident = self.create(client, kind, 'Current-Probe')
                with self.app.app_context():
                    initial_generation = self.model(kind).query.filter_by(id=ident).one().master_generation
                data = self.form(client, kind, ident, 'edit')
                self.assertTrue(data.get('master_token'), 'Use a real rendered signed form')
                data['name'] = 'Current-Renamed'
                self.assertEqual(self.post(client, kind, ident, 'edit', data).status_code, 302)
                data = self.form(client, kind, ident, 'delete')
                with self.app.app_context():
                    generation = self.model(kind).query.filter_by(id=ident).one().master_generation
                    self.assertEqual(generation, initial_generation, 'Rename must preserve record generation')
                self.assertEqual(self.post(client, kind, ident, 'delete', data).status_code, 302)
                with self.app.app_context():
                    action = self.model(kind).__tablename__ + '_deleted'
                    audit = self.models.AuditLog.query.filter_by(company_code=self.company, action=action,
                        target_id=str(ident)).order_by(self.models.AuditLog.id.desc()).first()
                    self.assertIsNotNone(audit)
                    self.assertIn('master_generation=' + generation, audit.detail)
                replacement = self.create(client, kind, 'Current-Renamed')
                with self.app.app_context():
                    self.assertNotEqual(self.model(kind).query.filter_by(id=replacement).one().master_generation,
                                        initial_generation, 'Reregister must create a different record generation')

    def test_unsigned_and_tampered_forms_never_write(self):
        client = self.plain_client()
        for kind in KINDS:
            ident = self.create(client, kind, 'Unsigned-Probe')
            for operation in ('edit', 'delete'):
                before = self.snapshot_all()
                for token in ('', 'not-a-valid-signed-token'):
                    data = {'name': 'Unauthorized-Change', 'master_token': token}
                    self.assertEqual(self.post(client, kind, ident, operation, data).status_code, 409)
                    self.assertEqual(self.snapshot_all(), before)

    def test_token_binds_company_kind_id_generation_and_operation(self):
        from dkss_app.master_generations import issue_token, verify_token, MasterFormConflict
        from types import SimpleNamespace
        client = self.plain_client()
        ident = self.create(client, 'offices', 'Bound-Probe')
        with self.app.app_context():
            row = self.models.Office.query.filter_by(id=ident).one()
            generation = row.master_generation
            values = ['offices', self.company, ident, generation, 'edit']
            variants = [(0, 'vehicle-types'), (1, self.other), (2, ident + 1000),
                        (3, 'e3786538-ce35-485b-bb24-ef7724cbb35e'), (4, 'delete')]
            tokens = []
            for index, changed in variants:
                payload = list(values); payload[index] = changed
                tokens.append(issue_token(*payload))
            with self.assertRaises(MasterFormConflict):
                verify_token(SimpleNamespace(__tablename__='office', company_code=self.company,
                    id=ident, master_generation=None), 'edit', issue_token(*values))
        before = self.snapshot_all()
        for token in tokens:
            self.assertEqual(self.post(client, 'offices', ident, 'edit',
                {'name': 'Wrong context', 'master_token': token}).status_code, 409)
            self.assertEqual(self.snapshot_all(), before)

    def test_foreign_records_are_unchanged_even_with_valid_foreign_form_signatures(self):
        from dkss_app.master_generations import issue_token
        client = self.plain_client()
        for kind in KINDS:
            for operation in ('edit', 'delete'):
                with self.app.app_context():
                    row = self.model(kind).query.filter_by(company_code=self.other).first()
                    ident = row.id
                    token = issue_token(kind, self.other, ident, row.master_generation, operation)
                before = self.snapshot_all()
                # Preserve the existing non-disclosing redirect for unavailable tenant rows.
                self.assertEqual(self.post(client, kind, ident, operation,
                    {'name': 'Foreign-Overwrite', 'master_token': token}).status_code, 302)
                self.assertEqual(self.snapshot_all(), before)

    def test_failed_valid_edit_rolls_back_related_changes_and_retries_with_same_generation(self):
        from sqlalchemy import event
        client = self.plain_client()
        ident = self.create(client, 'offices', 'Rollback-Probe')
        with self.app.app_context():
            for model in (self.models.Vehicle, self.models.User, self.models.Driver):
                model.query.filter_by(company_code=self.company).update({'office': 'Rollback-Probe'})
            self.db.session.commit()
            engine = self.db.engine
        self.protect_history()
        form = self.form(client, 'offices', ident, 'edit')
        form['name'] = 'Rollback-Renamed'
        before = self.snapshot_all()
        def fail(connection, cursor, statement, parameters, context, executemany):
            if statement.lower().startswith('update office '):
                raise RuntimeError('Synthetic failure after related updates')
        event.listen(engine, 'before_cursor_execute', fail)
        try:
            self.assertEqual(self.post(client, 'offices', ident, 'edit', form).status_code, 500)
        finally:
            event.remove(engine, 'before_cursor_execute', fail)
        self.assertEqual(self.snapshot_all(), before)
        self.assertEqual(self.post(client, 'offices', ident, 'edit', form).status_code, 302)
        with self.app.app_context():
            for model in (self.models.Vehicle, self.models.User, self.models.Driver):
                self.assertTrue(all(r.office == 'Rollback-Renamed'
                    for r in model.query.filter_by(company_code=self.company)))

    def test_recovery_key_change_invalidates_old_forms_without_rotating_master_generations(self):
        client = self.plain_client()
        ident = self.create(client, 'offices', 'Recovery-Probe')
        old_form = self.form(client, 'offices', ident, 'edit')
        old_form['name'] = 'Stale-Recovery-Edit'
        before = self.snapshot_all()
        old_key = self.app.secret_key
        try:
            self.app.secret_key = 'q04-isolated-recovery-key'
            client = self.plain_client()  # New login cookie; test the form signature independently.
            self.assertEqual(self.post(client, 'offices', ident, 'edit', old_form).status_code, 409)
            self.assertEqual(self.snapshot_all(), before)
            fresh = self.form(client, 'offices', ident, 'edit')
            fresh['name'] = 'Recovery-Current'
            self.assertEqual(self.post(client, 'offices', ident, 'edit', fresh).status_code, 302)
        finally:
            self.app.secret_key = old_key


    def test_unmigrated_and_unassigned_legacy_rows_fail_closed_until_explicit_upgrade(self):
        from sqlalchemy import inspect, text
        from dkss_app.master_generations import upgrade_storage
        client = self.plain_client()
        ident = self.create(client, 'offices', 'Legacy-Probe')
        data = self.form(client, 'offices', ident, 'edit')
        data['name'] = 'Unsafe-Legacy-Edit'
        with self.app.app_context():
            engine = self.db.engine
            # Test-owned schema only: reproduce a pre-release master table.
            self.db.session.execute(text('ALTER TABLE office DROP COLUMN master_generation'))
            self.db.session.commit()
        self.assertEqual(self.post(client, 'offices', ident, 'edit', data).status_code, 409)
        self.assertNotIn('master_generation', [c['name'] for c in inspect(engine).get_columns('office')])
        with engine.connect() as c:
            self.assertEqual(c.scalar(text('SELECT name FROM office WHERE id=:id'), {'id': ident}), 'Legacy-Probe')
        upgrade_storage(engine)
        fresh = self.form(client, 'offices', ident, 'edit')
        fresh['name'] = 'Unsafe-Unknown-Edit'
        with engine.begin() as c:
            c.execute(text('UPDATE office SET master_generation=NULL WHERE id=:id'), {'id': ident})
        self.assertEqual(self.post(client, 'offices', ident, 'edit', fresh).status_code, 409)
        with engine.connect() as c:
            self.assertIsNone(c.scalar(text('SELECT master_generation FROM office WHERE id=:id'), {'id': ident}))
            self.assertEqual(c.scalar(text('SELECT name FROM office WHERE id=:id'), {'id': ident}), 'Legacy-Probe')
        upgrade_storage(engine)
        current = self.form(client, 'offices', ident, 'edit')
        current['name'] = 'Explicitly-Migrated'
        self.assertEqual(self.post(client, 'offices', ident, 'edit', current).status_code, 302)

def stale_case(kind, operation):
    def run(self): self.stale_case(kind, operation)
    return run


for _kind in KINDS:
    for _operation in ('edit', 'delete'):
        setattr(GenerationCases, 'test_stale_' + _kind.replace('-', '_') + '_' + _operation,
                stale_case(_kind, _operation))


class SQLiteMasterGenerationTests(GenerationCases, unittest.TestCase):
    setUpClass = classmethod(baseline_fixture.MasterRenameIntegrityTests.setUpClass.__func__)
    tearDownClass = classmethod(baseline_fixture.MasterRenameIntegrityTests.tearDownClass.__func__)
    tearDown = baseline_fixture.MasterRenameIntegrityTests.tearDown

    def setUp(self):
        baseline_fixture.MasterRenameIntegrityTests.setUp(self)
        baseline_fixture.MasterRenameIntegrityTests.seed(self)
        from dkss_app import models
        self.models, self.db, self.app = models, self.m.db, self.m.app
        self.company, self.other = 'TEST', 'OTHER'
        self.foreign_controls()

    def test_replacement_after_form_validation_cannot_commit_related_updates(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from unittest.mock import patch
        from dkss_app import masters
        client_a, client_b = self.plain_client(), self.plain_client()
        ident = self.create(client_a, 'offices', 'Race-Probe')
        edit = self.form(client_a, 'offices', ident, 'edit')
        edit['name'] = 'Stale-Race-Edit'
        delete = self.form(client_b, 'offices', ident, 'delete')
        verified, release = Event(), Event()
        real_verify = masters.verify_token
        def gate(row, operation, token):
            real_verify(row, operation, token)
            if operation == 'edit' and not verified.is_set():
                verified.set()
                if not release.wait(15): raise RuntimeError('Race did not release')
        with patch.object(masters, 'verify_token', side_effect=gate), ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.post, client_a, 'offices', ident, 'edit', edit)
            try:
                self.assertTrue(verified.wait(10))
                self.assertEqual(self.post(client_b, 'offices', ident, 'delete', delete).status_code, 302)
                self.assertEqual(self.create(client_b, 'offices', 'Race-Probe'), ident)
                with self.app.app_context():
                    self.models.Vehicle.query.filter_by(company_code=self.company).update({'office': 'Race-Probe'})
                    self.db.session.commit()
                before = self.snapshot_all()
            finally:
                release.set()
            self.assertEqual(pending.result(timeout=15).status_code, 409)
        self.assertEqual(self.snapshot_all(), before)
