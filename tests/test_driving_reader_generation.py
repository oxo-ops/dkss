"""Real form evidence and atomic reader saves; synthetic isolated databases only."""
import re
import json
import unittest
from html import unescape
from unittest.mock import patch
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from flask import session

from dkss_app import driving_access, person_selection
from driving_report_data import version
from driving_report_insights import driver_keys
from driving_identity_fixture import DrivingIdentityFixture
from test_q08_postgres_identity import DisposablePostgres
import test_workflow_regressions as workflow


class ReaderGenerationTests(DrivingIdentityFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.m.User.query.filter_by(username='admin').one()
        self.a = self.person()
        self.row = self.save()
        self.login(self.admin)
        self.m.app.config['WTF_CSRF_ENABLED'] = True

    def snapshot(self):
        self.m.db.session.flush()
        return {t.name: sorted((tuple(map(repr, r)) for r in self.m.db.session.execute(select(t))), key=repr)
                for t in self.m.db.metadata.sorted_tables}

    def form(self, bulk=False):
        path = f'/safety/driving-reports/{self.row.id}'
        if bulk:
            focus = driver_keys([self.row])[0][self.row.id]
            path = self.url + '&scope=company&focus=' + focus
        page = self.client.get(path)
        self.assertEqual(page.status_code, 200)
        action = '/safety/driving-reports/readers' if bulk else path + '/reader'
        form = re.search(r'<form\b[^>]*action="' + re.escape(action) + r'"[^>]*>(.*?)</form>',
                         page.get_data(as_text=True), re.S)
        self.assertIsNotNone(form)
        data = {name: unescape(value) for name, value in re.findall(
            r'<input\b[^>]*name="([^"]+)"[^>]*value="([^"]*)"', form.group(1))}
        data.update(reader_username=self.a.username)
        # Keep missing proofs explicit: the legacy fixture must not supply one.
        data.setdefault('person_selection_token', '')
        return action, data

    def replace(self):
        ident, old_uuid = self.a.id, self.a.account_identity
        self.m.db.session.delete(self.a)
        self.m.db.session.commit()
        self.a = self.person(ident=ident)
        self.assertNotEqual(old_uuid, self.a.account_identity)
        return old_uuid

    def current_person_status(self):
        client = self.m.app.test_client()
        with client.session_transaction() as state:
            state.update(company_code='TEST', username=self.a.username, role='user',
                         account_identity=self.a.account_identity, password_changed_at='stamp')
        return client.get(f'/safety/driving-reports/{self.row.id}').status_code

    def denied_to_b(self):
        self.assertEqual(self.current_person_status(), 404)

    def reject(self, action, data, status=409, check_person=True):
        before = self.snapshot()
        response = self.client.post(action, data=data)
        self.assertEqual(response.status_code, status,
            'unexpected reader POST; current person detail=' + str(self.current_person_status()))
        self.assertEqual(self.snapshot(), before)
        if check_person:self.denied_to_b()

    def test_individual_stale_selection_never_grants_replacement_and_keeps_a_evidence(self):
        with self.m.app.test_request_context():
            session.update(company_code='TEST', username=self.admin.username, role='admin',
                           account_identity=self.admin.account_identity)
            driving_access.assign([self.row], self.a.username, self.admin.username)
            self.m.db.session.commit()
        action, data = self.form()
        old_uuid = self.replace()
        self.assertEqual(data['version'], version(self.row))
        self.denied_to_b()
        self.reject(action, data)
        self.assertEqual(driving_access.DrivingReaderAccount.query.one().account_identity, old_uuid)

    def test_bulk_stale_selection_never_partially_saves(self):
        self.save(2)
        action, data = self.form(True)
        self.replace()
        self.reject(action, data)

    def test_missing_and_tampered_evidence_are_rejected_on_both_routes(self):
        for bulk in (False, True):
            action, data = self.form(bulk)
            for proof in ('', data['person_selection_token'] + 'tampered'):
                with self.subTest(bulk=bulk, proof=bool(proof)):
                    self.reject(action, dict(data, person_selection_token=proof))

    def test_fresh_selection_same_uuid_rename_and_explicit_revoke(self):
        for bulk in (False, True):
            action, data = self.form(bulk)
            self.a.last_name = '改姓'; self.m.db.session.commit()
            self.assertEqual(self.client.post(action, data=data).status_code, 302)
            self.assertEqual(driving_access.reader(self.row).user_id, self.a.id)
            action, data = self.form(False)
            data['reader_username'] = ''
            self.assertEqual(self.client.post(action, data=data).status_code, 302)
            self.assertIsNone(driving_access.reader(self.row))

    def test_fresh_b_reselection_after_rejection_is_allowed(self):
        action, data = self.form(); self.replace(); self.reject(action, data)
        action, data = self.form()
        self.assertEqual(self.client.post(action, data=data).status_code, 302)
        self.assertEqual(driving_access.DrivingReaderAccount.query.one().account_identity, self.a.account_identity)

    def test_report_version_is_checked_independently_of_person_proof(self):
        for bulk in (False, True):
            action, data = self.form(bulk)
            self.row.details_json = self.row.details_json[:-1] + ',"concurrent_edit":true}'; self.m.db.session.commit()
            self.reject(action, data)

    def test_validation_locks_person_until_save_and_delete_rolls_back(self):
        for bulk in (False, True):
            action, data = self.form(bulk)
            self.m.db.session.commit()
            original = person_selection.validate
            def guarded(**kwargs):
                result = original(**kwargs)
                if result is None:
                    with self.m.db.engine.connect() as other:
                        tx = other.begin()
                        try:
                            if other.dialect.name == 'sqlite':
                                other.exec_driver_sql('PRAGMA busy_timeout=100')
                            else:
                                other.execute(text("SET LOCAL lock_timeout='100ms'"))
                            with self.assertRaises(OperationalError):
                                other.execute(text('DELETE FROM "user" WHERE id=:id'), {'id': self.a.id})
                        finally:
                            tx.rollback()
                return result
            with patch.object(person_selection, 'validate', side_effect=guarded) as validation:
                self.assertEqual(self.client.post(action, data=data).status_code, 302)
            self.assertTrue(validation.called)
            self.assertEqual(driving_access.reader(self.row).user_id, self.a.id)
            action, data = self.form(); data['reader_username'] = ''
            self.assertEqual(self.client.post(action, data=data).status_code, 302)

    def test_foreign_company_proof_and_unknown_person_are_rejected(self):
        from dkss_app.person_selection import _signer
        action, data = self.form()
        with self.m.app.test_request_context():
            evidence = _signer().loads(data['person_selection_token'])
            evidence['company'] = 'OTHER'
            forged = _signer().dumps(evidence)
        self.reject(action, dict(data, person_selection_token=forged))
        self.reject(action, dict(data, reader_username='foreign-only'), 400)

    def test_bulk_failure_after_first_row_update_rolls_back_every_table(self):
        self.save(2)
        action, data = self.form(True)
        before = self.snapshot()
        original = driving_access.assign
        def fail(*args, **kwargs):
            original(*args, **kwargs)
            self.m.db.session.flush()
            raise RuntimeError('synthetic save failure')
        with patch.object(driving_access, 'assign', side_effect=fail):
            self.assertEqual(self.client.post(action, data=data).status_code, 500)
        self.assertEqual(self.snapshot(), before)
        self.denied_to_b()

    def import_form(self, vehicle=True):
        self.m.app.config['WTF_CSRF_ENABLED'] = False
        try:
            self.assertEqual(workflow.WorkflowRegressionTests.upload_driving_report(self).status_code, 302)
        finally:
            self.m.app.config['WTF_CSRF_ENABLED'] = True
        draft = self.m.VehicleDocumentImportDraft.query.filter_by(status='preview').one()
        page = self.client.get(f'/vehicle/data-import/{draft.batch_id}/preview')
        self.assertEqual(page.status_code, 200)
        data = workflow.WorkflowRegressionTests.inspection_form(self, draft, vehicle=vehicle)
        for name in ('csrf_token', 'person_selection_token'):
            found = re.search(r'name="' + name + r'"\s+value="([^"]*)"', page.get_data(as_text=True))
            data[name] = unescape(found.group(1)) if found else ''
        data['driving_account_' + draft.id + '_0'] = self.a.username
        return draft, data

    def test_import_manual_stale_choice_and_missing_proof_do_not_save_preview_or_report(self):
        draft, data = self.import_form()
        self.replace()
        path = f'/vehicle/data-import/{draft.batch_id}/confirm'
        self.reject(path, data)
        self.reject(path, dict(data, person_selection_token=''))

    def test_registered_correction_stale_choice_does_not_save_json_or_audit(self):
        draft, data = self.import_form()
        path = f'/vehicle/data-import/{draft.batch_id}/confirm'
        self.assertEqual(self.client.post(path, data=data).status_code, 302)
        row = self.m.VehicleDrivingReportRecord.query.filter_by(source_draft_id=draft.id).one()
        path = f'/safety/driving-reports/{row.id}/edit'
        page = self.client.get(path).get_data(as_text=True)
        data = workflow.WorkflowRegressionTests.inspection_form(self, draft)
        for name in ('csrf_token', 'person_selection_token', 'record_version'):
            found = re.search(r'name="' + name + r'"\s+value="([^"]*)"', page)
            data[name] = unescape(found.group(1)) if found else ''
        data['driving_account_' + draft.id + '_0'] = self.a.username
        self.row = row
        self.replace()
        self.reject(path, data)

    def test_pending_manual_uuid_survives_and_replacement_is_rejected_atomically(self):
        draft, data = self.import_form(vehicle=False)
        self.assertEqual(self.client.post(f'/vehicle/data-import/{draft.batch_id}/confirm', data=data).status_code, 302)
        item = self.m.VehicleImportPendingRecord.query.one()
        identity = json.loads(item.payload_json).get('_driving_account_identity')
        old_uuid = self.a.account_identity
        self.replace()
        page = self.client.get(f'/master/vehicles/pending/{item.pending_id}').get_data(as_text=True)
        csrf = re.search(r'name="csrf_token"\s+value="([^"]*)"', page).group(1)
        self.reject(f'/master/vehicles/pending/{item.pending_id}',
                    dict(vehicle_record_id=str(self.vehicle.id), csrf_token=unescape(csrf)))
        self.assertEqual(identity, old_uuid)

    def test_new_pending_manual_selection_applies_with_original_uuid(self):
        draft, data = self.import_form(vehicle=False)
        self.assertEqual(self.client.post(f'/vehicle/data-import/{draft.batch_id}/confirm', data=data).status_code, 302)
        item = self.m.VehicleImportPendingRecord.query.one()
        page = self.client.get(f'/master/vehicles/pending/{item.pending_id}').get_data(as_text=True)
        csrf = re.search(r'name="csrf_token"\s+value="([^"]*)"', page).group(1)
        response = self.client.post(f'/master/vehicles/pending/{item.pending_id}',
            data=dict(vehicle_record_id=str(self.vehicle.id), csrf_token=unescape(csrf)))
        self.assertEqual(response.status_code, 302)
        row = self.m.VehicleDrivingReportRecord.query.filter_by(source_draft_id=draft.id).one()
        self.assertEqual(driving_access.reader(row).user_id, self.a.id)

    def test_missing_uuid_in_legacy_manual_pending_is_not_inferred(self):
        draft, data = self.import_form(vehicle=False)
        self.assertEqual(self.client.post(f'/vehicle/data-import/{draft.batch_id}/confirm', data=data).status_code, 302)
        item = self.m.VehicleImportPendingRecord.query.one()
        payload = json.loads(item.payload_json); payload.pop('_driving_account_identity')
        item.payload_json = json.dumps(payload, ensure_ascii=False)
        preview = json.loads(draft.preview_json); preview['records'][0] = payload
        draft.preview_json = json.dumps(preview, ensure_ascii=False)
        self.m.db.session.commit()
        page = self.client.get(f'/master/vehicles/pending/{item.pending_id}').get_data(as_text=True)
        csrf = re.search(r'name="csrf_token"\s+value="([^"]*)"', page).group(1)
        self.reject(f'/master/vehicles/pending/{item.pending_id}',
                    dict(vehicle_record_id=str(self.vehicle.id), csrf_token=unescape(csrf)))

    def test_selected_person_role_and_lock_change_require_reselection(self):
        for field, value in [('role', 'admin'), ('login_locked', True)]:
            action, data = self.form()
            old = getattr(self.a, field)
            setattr(self.a, field, value); self.m.db.session.commit()
            self.reject(action, data, check_person=False)
            setattr(self.a, field, old); self.m.db.session.commit()

    def test_assign_rechecks_expected_uuid_even_after_form_validation(self):
        action, data = self.form()
        original = driving_access.assign
        def changed(rows, username, actor, expected_identity=None):
            self.assertEqual(expected_identity, self.a.account_identity)
            return original(rows, username, actor, expected_identity='different-generation')
        with patch.object(driving_access, 'assign', side_effect=changed):
            self.reject(action, data)

    def test_import_revalidates_after_preview_commit_releases_person_lock(self):
        from dkss_app import import_owner as owner
        draft, data = self.import_form()
        original = owner.active_owner_username
        replaced = []
        before = self.row.details_json
        def entering_final(*args, **kwargs):
            if not replaced:
                replaced.append(self.replace())
            return original(*args, **kwargs)
        with patch.object(owner, 'active_owner_username', side_effect=entering_final):
            response = self.client.post(f'/vehicle/data-import/{draft.batch_id}/confirm', data=data)
        self.assertEqual(response.status_code, 409)
        self.assertTrue(replaced)
        self.assertEqual(self.m.VehicleDrivingReportRecord.query.count(), 1)
        self.assertEqual(self.row.details_json, before)
        self.assertEqual(driving_access.DrivingReaderAccount.query.count(), 0)
        self.assertEqual(self.m.db.session.get(self.m.VehicleDocumentImportDraft, draft.id).status, 'preview')
        self.denied_to_b()


class PostgresReaderGenerationTests(DisposablePostgres, ReaderGenerationTests):
    pass
