"""Vehicle selections use rendered proofs, never a test-client proof adapter.

Fresh synthetic SQLite only. PostgreSQL lock execution and browser JavaScript
are separate acceptance checks, not simulated by these route tests.
"""
from html.parser import HTMLParser
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flask.testing import FlaskClient


class Form(HTMLParser):
    def __init__(self, html, action=None):
        super().__init__(convert_charrefs=True)
        self.forms = []
        self.current = None
        self.select = None
        self.feed(html)
        matches = [f for f in self.forms if action is None or f['action'] == action]
        self.values = dict(matches[-1]['values']) if matches else {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.current = {'action': attrs.get('action', ''), 'values': {}}
            self.forms.append(self.current)
        elif self.current is not None:
            if tag == 'input' and attrs.get('name') and attrs.get('type') != 'file':
                self.current['values'][attrs['name']] = attrs.get('value', '')
            elif tag == 'select':
                self.select = attrs.get('name')
            elif tag == 'option' and self.select and 'selected' in attrs:
                self.current['values'][self.select] = attrs.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'select':
            self.select = None
        elif tag == 'form':
            self.current = None


class VehicleMasterSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='q04-selection-')
        self.database_path = Path(self.temp.name) / 'selection.sqlite3'
        from dkss_app import create_app, models
        from dkss_app.extensions import db
        self.m, self.db = models, db
        with patch.dict(os.environ, {'RENDER': '', 'S3_BUCKET_NAME': '',
                'AWS_EC2_METADATA_DISABLED': 'true', 'DOCUMENT_IMPORT_WORKER_ENABLED': '0'}):
            self.app = create_app({'SECRET_KEY': 'synthetic-selection-tests-only',
                'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(self.database_path),
                'TESTING': True, 'WTF_CSRF_ENABLED': True, 'MFA_ENABLED': False,
                'RATELIMIT_ENABLED': False, 'UPLOAD_FOLDER': str(Path(self.temp.name) / 'uploads')})
        self.app.test_client_class = FlaskClient
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        m = models
        for company in ('A', 'B'):
            db.session.add(m.Company(company_code=company, company_name=company,
                                     active=True, vehicle_limit=20))
            for username in ('admin', 'other-admin'):
                db.session.add(m.User(company_code=company, username=username,
                    password='unused', role='admin', last_name='Synthetic', first_name='Admin',
                    password_changed_at='2026-11-12 00:00:00'))
            for model in (m.Office, m.VehicleType):
                db.session.add_all([model(company_code=company, name='Shared'),
                                    model(company_code=company, name='Other')])
            db.session.add(m.Vehicle(company_code=company, chassis_number=company + '-CHASSIS',
                office='Shared', type='Shared', manufacturer='Original',
                gross_vehicle_weight=100, max_payload=10, inspection_expiry=''))
        db.session.add(m.Vehicle(company_code='A', chassis_number='SECOND',
                                office='Other', type='Other'))
        db.session.commit()
        self.own = m.Vehicle.query.filter_by(chassis_number='A-CHASSIS').one().id
        self.second = m.Vehicle.query.filter_by(chassis_number='SECOND').one().id
        self.foreign = m.Vehicle.query.filter_by(chassis_number='B-CHASSIS').one().id
        self.client = self.client_for('A')
        self.path = f'/master/vehicles/{self.own}/edit'

    def tearDown(self):
        self.db.session.remove()
        self.db.engine.dispose()
        self.ctx.pop()
        self.temp.cleanup()

    def client_for(self, company, username='admin'):
        client = self.app.test_client()
        actor = self.m.User.query.filter_by(company_code=company, username=username).one()
        with client.session_transaction() as state:
            state.update(company_code=company, username=username, role='admin',
                account_identity=actor.account_identity,
                password_changed_at=actor.password_changed_at)
        return client

    def snapshot(self):
        self.db.session.remove()
        return {t.name: list(self.db.session.execute(t.select().order_by(*t.primary_key.columns)))
                for t in self.db.metadata.sorted_tables}

    def get_form(self, path=None, client=None):
        response = (client or self.client).get(path or self.path)
        self.assertEqual(response.status_code, 200)
        return Form(response.get_data(as_text=True)).values

    def post(self, values, path=None, client=None, expected=200, headers=None):
        response = (client or self.client).post(path or self.path, data=values, headers=headers)
        self.assertEqual(response.status_code, expected, response.get_data(as_text=True)[:500])
        return response

    def confirm(self, values=None, path=None, client=None):
        path = path or self.path
        values = values or self.get_form(path, client)
        response = self.post(values, path, client)
        return Form(response.get_data(as_text=True), path).values

    def assert_rejected(self, values, path=None, client=None):
        before = self.snapshot()
        self.post(values, path, client, expected=409)
        self.assertEqual(self.snapshot(), before)

    def replace_master(self, kind):
        model = self.m.Office if kind == 'offices' else self.m.VehicleType
        old = model.query.filter_by(company_code='A', name='Shared').one()
        old_identity = (old.id, old.master_generation)
        listing = self.client.get('/master/' + kind)
        delete = f'/master/{kind}/{old.id}/delete'
        self.post(Form(listing.get_data(as_text=True), delete).values, delete, expected=302)
        path = f'/master/{kind}/new'
        values = self.get_form(path)
        values['name'] = 'Shared'
        self.post(values, path, expected=302)
        self.db.session.remove()
        new = model.query.filter_by(company_code='A', name='Shared').one()
        self.assertNotEqual((new.id, new.master_generation), old_identity)

    def test_edit_confirm_back_change_save_and_double_submit(self):
        before = self.snapshot()
        values = self.get_form()
        values['manufacturer'] = 'Changed'
        confirm = self.confirm(values)
        self.assertEqual(self.snapshot(), before)
        response = self.post(dict(confirm, vehicle_form_action='back'))
        returned = Form(response.get_data(as_text=True)).values
        self.assertEqual(returned['manufacturer'], 'Changed')
        returned.update(office='Other', type='Other')
        confirm = self.confirm(returned)
        self.post(dict(confirm, vehicle_form_action='save'), expected=302)
        state = self.snapshot()
        self.post(dict(confirm, vehicle_form_action='save'), expected=302)
        self.assertEqual(self.snapshot(), state)
        row = self.db.session.get(self.m.Vehicle, self.own)
        self.assertEqual((row.office, row.type, row.manufacturer), ('Other', 'Other', 'Changed'))
        self.assertEqual(before['office'], state['office'])
        self.assertEqual(before['vehicle_type'], state['vehicle_type'])

    def test_new_confirm_back_save_and_duplicate_submit(self):
        path = '/master/vehicles/new'
        values = self.get_form(path)
        self.assertEqual((values['office'], values['type']), ('', ''))
        values.update(chassis_number='NEW', office='Shared', type='Other')
        confirm = self.confirm(values, path)
        back = self.post(dict(confirm, vehicle_form_action='back'), path)
        confirm = self.confirm(Form(back.get_data(as_text=True)).values, path)
        self.post(dict(confirm, vehicle_form_action='save'), path, expected=302)
        before = self.snapshot()
        self.post(dict(confirm, vehicle_form_action='save'), path, expected=409)
        self.assertEqual(self.snapshot(), before)

    def test_blank_choices_remain_supported(self):
        values = self.get_form()
        values.update(office='', type='')
        self.post(dict(self.confirm(values), vehicle_form_action='save'), expected=302)
        row = self.db.session.get(self.m.Vehicle, self.own)
        self.assertEqual((row.office, row.type), ('', ''))

    def test_legacy_unknown_names_do_not_select_first_master(self):
        row = self.db.session.get(self.m.Vehicle, self.own)
        row.office, row.type = 'Unknown office', 'Unknown type'
        self.db.session.commit()
        before = self.snapshot()
        values = self.get_form()
        self.assertEqual((values['office'], values['type']), ('', ''))
        self.assertEqual(self.snapshot(), before)

    def test_missing_proof_even_with_blank_choices_is_rejected(self):
        values = self.get_form()
        values.pop('vehicle_master_selection')
        values.update(office='', type='', vehicle_form_action='save')
        self.assert_rejected(values)

    def test_tampered_proof_is_rejected(self):
        values = self.get_form()
        values['vehicle_master_selection'] += 'tampered'
        self.assert_rejected(values)

    def test_unsigned_confirmation_from_before_deployment_is_rejected(self):
        values = self.confirm()
        values.pop('vehicle_master_selection')
        self.assert_rejected(dict(values, vehicle_form_action='save'))

    def test_foreign_same_name_catalogue_is_rejected(self):
        foreign = self.client_for('B')
        values = self.get_form()
        values['vehicle_master_selection'] = self.get_form(
            f'/master/vehicles/{self.foreign}/edit', foreign)['vehicle_master_selection']
        self.assert_rejected(values)

    def test_other_actor_same_company_catalogue_is_rejected(self):
        values = self.get_form()
        other = self.client_for('A', 'other-admin')
        values['vehicle_master_selection'] = self.get_form(client=other)['vehicle_master_selection']
        self.assert_rejected(values)

    def test_other_vehicle_catalogue_is_rejected(self):
        values = self.get_form()
        values['vehicle_master_selection'] = self.get_form(
            f'/master/vehicles/{self.second}/edit')['vehicle_master_selection']
        self.assert_rejected(values)

    def test_new_catalogue_cannot_be_used_to_edit(self):
        values = self.get_form()
        values['vehicle_master_selection'] = self.get_form('/master/vehicles/new')['vehicle_master_selection']
        self.assert_rejected(values)

    def test_edit_catalogue_cannot_be_used_to_create(self):
        values = self.get_form('/master/vehicles/new')
        values.update(chassis_number='NEW', vehicle_master_selection=self.get_form()['vehicle_master_selection'])
        self.assert_rejected(values, '/master/vehicles/new')

    def test_master_management_token_is_not_a_vehicle_proof(self):
        values = self.get_form()
        listing = self.client.get('/master/offices')
        row = self.m.Office.query.filter_by(company_code='A', name='Shared').one()
        proof = Form(listing.get_data(as_text=True), f'/master/offices/{row.id}/delete').values['master_token']
        values['vehicle_master_selection'] = proof
        self.assert_rejected(values)

    def test_confirmation_cannot_change_to_an_unconfirmed_master(self):
        values = self.confirm()
        values.update(office='Other', vehicle_form_action='save')
        self.assert_rejected(values)

    def test_signed_wrong_generation_id_and_kind_are_rejected(self):
        from dkss_app.vehicle_master_selection import _serializer
        values = self.get_form()
        original = _serializer().loads(values['vehicle_master_selection'])
        for mutation in ('generation', 'id', 'kind'):
            import copy
            payload = copy.deepcopy(original)
            if mutation == 'generation':
                payload['office'][0][2] = '00000000-0000-4000-8000-000000000001'
            elif mutation == 'id':
                payload['office'][0][1] += 10000
            else:
                payload['office'], payload['type'] = payload['type'], payload['office']
            with self.subTest(mutation=mutation):
                self.assert_rejected(dict(values, vehicle_master_selection=_serializer().dumps(payload)))

    def test_signed_malformed_payloads_are_rejected_without_server_errors(self):
        from dkss_app.vehicle_master_selection import _serializer
        values = self.get_form()
        payload = _serializer().loads(values['vehicle_master_selection'])
        for entries in (None, {}, [['Shared']], [['Shared', True, 'bad']]):
            with self.subTest(entries=entries):
                bad = dict(payload, office=entries)
                self.assert_rejected(dict(values, vehicle_master_selection=_serializer().dumps(bad)))

    def test_invalid_actor_identity_cannot_issue_or_use_proof(self):
        from dkss_app import vehicle_master_selection as selection
        from flask import session
        with self.app.test_request_context():
            session.update(company_code='A', account_identity='not-a-uuid')
            self.assertEqual(selection.form_context()['vehicle_master_selection'], '')
            self.assertTrue(selection.validate({'office': '', 'type': '', 'vehicle_master_selection': 'x'}))

    def test_renamed_master_invalidates_old_confirmation(self):
        values = self.confirm()
        row = self.m.Office.query.filter_by(company_code='A', name='Shared').one()
        path = f'/master/offices/{row.id}/edit'
        rename = self.get_form(path)
        rename['name'] = 'Renamed'
        self.post(rename, path, expected=302)
        self.assert_rejected(dict(values, vehicle_form_action='save'))

    def test_catalogue_is_compacted_before_confirmation_and_cookie_recovery(self):
        # Simulate an ordinary large catalogue before any request. No per-option
        # signed tokens and no full catalogue copied into the session cookie.
        self.db.session.add_all(self.m.Office(company_code='A', name=f'Office {i:04}')
                                for i in range(1000))
        self.db.session.commit()
        values = self.get_form()
        full_size = len(values['vehicle_master_selection'])
        confirm = self.confirm(values)
        self.assertLess(len(confirm['vehicle_master_selection']), 1024)
        self.assertGreater(full_size, 20000)
        values['gross_vehicle_weight'] = '-1'
        response = self.post(values, expected=302, headers={'Accept': 'text/html'})
        self.assertTrue(all(len(value) < 4093 for value in response.headers.getlist('Set-Cookie')))
        with self.client.session_transaction() as state:
            self.assertLess(len(state['vehicle_edit_form_data']['vehicle_master_selection']), 1024)

    def test_postgresql_compilation_keeps_identity_predicate_in_share_lock_query(self):
        # Compilation only, not a PostgreSQL lock/concurrency execution claim.
        from sqlalchemy import event
        from sqlalchemy.dialects import postgresql
        queries = []
        def capture(conn, clause, multiparams, params, options):
            if getattr(clause, '_for_update_arg', None) is not None:
                queries.append(str(clause.compile(dialect=postgresql.dialect())))
        values = self.get_form()
        event.listen(self.db.engine, 'before_execute', capture)
        try:
            self.confirm(values)
        finally:
            event.remove(self.db.engine, 'before_execute', capture)
        for table in ('office', 'vehicle_type'):
            matches = [sql for sql in queries if 'FROM ' + table + ' ' in sql.replace('\n', ' ')]
            self.assertEqual(len(matches), 1)
            self.assertIn('FOR SHARE', matches[0])
            where = matches[0].split('WHERE')[1]
            for column in ('company_code', 'id', 'master_generation', 'name'):
                self.assertIn(f'{table}.{column} = ', where)

    def test_edit_stale_recovery_clears_only_stale_choice_and_keeps_other_inputs(self):
        values = self.get_form()
        values['manufacturer'] = 'Keep this edit'
        confirm = self.confirm(values)
        self.replace_master('offices')
        before = self.snapshot()
        self.post(dict(confirm, vehicle_form_action='save'), expected=302,
                  headers={'Accept': 'text/html'})
        recovered = self.get_form()
        self.assertEqual(recovered['office'], '')
        self.assertEqual(recovered['type'], 'Shared')
        self.assertEqual(recovered['manufacturer'], 'Keep this edit')
        self.assertEqual(self.snapshot(), before)
        # A second save without deliberate reselection does not reattach.
        self.post(dict(self.confirm(recovered), vehicle_form_action='save'), expected=302)
        self.assertEqual(self.db.session.get(self.m.Vehicle, self.own).office, '')
        recovered = self.get_form()
        recovered['office'] = 'Shared'
        self.post(dict(self.confirm(recovered), vehicle_form_action='save'), expected=302)
        self.assertEqual(self.db.session.get(self.m.Vehicle, self.own).office, 'Shared')

    def test_error_session_from_another_vehicle_cannot_rebind_choices(self):
        values = self.get_form()
        values['gross_vehicle_weight'] = '-1'
        self.post(values, expected=302, headers={'Accept': 'text/html'})
        recovered = self.get_form(f'/master/vehicles/{self.second}/edit')
        self.assertEqual((recovered['office'], recovered['type']), ('', ''))

    def test_valid_error_recovery_retains_selection(self):
        values = self.get_form()
        values.update(gross_vehicle_weight='-1', office='Other', manufacturer='Retained')
        self.post(values, expected=302, headers={'Accept': 'text/html'})
        recovered = self.get_form()
        self.assertEqual((recovered['office'], recovered['type']), ('Other', 'Shared'))
        self.assertEqual(recovered['manufacturer'], 'Retained')

    def test_certificate_entry_has_new_context_proof_without_external_reading(self):
        with self.app.test_request_context():
            from flask import url_for
            path = url_for('vehicle_registration_method')
        page = self.client.get(path)
        form = Form(page.get_data(as_text=True), '').values
        # The page has several forms, so locate the certificate form explicitly.
        token = next(f['values']['vehicle_master_selection'] for f in Form(page.get_data(as_text=True)).forms
                     if 'vehicle_master_selection' in f['values'])
        values = self.get_form('/master/vehicles/new')
        values.update(chassis_number='CERTIFICATE', office='Shared', type='Shared', vehicle_master_selection=token)
        response = self.post(values, '/master/vehicles/new', headers={'X-DKSS-Validation-Only': '1'})
        self.assertEqual(response.json, {'ok': True})
        confirm = self.confirm(values, '/master/vehicles/new')
        self.post(dict(confirm, vehicle_form_action='save'), '/master/vehicles/new', expected=302)


def stale_case(kind, stage, mode):
    def test(self):
        path = self.path if mode == 'edit' else '/master/vehicles/new'
        values = self.get_form(path)
        if mode == 'new':
            values.update(chassis_number='HELD-NEW', office='Shared', type='Shared')
        if stage != 'form':
            values = self.confirm(values, path)
            values['vehicle_form_action'] = 'back' if stage == 'back' else 'save'
        self.replace_master(kind)
        self.assert_rejected(values, path)
    return test


for _kind in ('offices', 'vehicle-types'):
    for _stage in ('form', 'confirm', 'back'):
        for _mode in ('new', 'edit'):
            setattr(VehicleMasterSelectionTests, f'test_stale_{_kind.replace("-", "_")}_{_stage}_{_mode}',
                    stale_case(_kind, _stage, _mode))


if __name__ == '__main__':
    unittest.main()
