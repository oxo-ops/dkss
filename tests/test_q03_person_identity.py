"""Account reuse must not inherit a selected future approver's personal access.

Candidates and role-based permission are tested separately: existing general
approval stages allow an unselected user when that stage becomes current.
"""
import json
import unittest

import test_q02_checklist_boundaries as boundaries


class Q03PersonIdentityTests(unittest.TestCase):
    setUpClass = classmethod(boundaries.Q02ChecklistBoundaryTests.setUpClass.__func__)
    tearDownClass = classmethod(boundaries.Q02ChecklistBoundaryTests.tearDownClass.__func__)
    setUp = boundaries.Q02ChecklistBoundaryTests.setUp
    tearDown = boundaries.Q02ChecklistBoundaryTests.tearDown
    login = boundaries.Q02ChecklistBoundaryTests.login
    request = boundaries.Q02ChecklistBoundaryTests.request
    record = boundaries.Q02ChecklistBoundaryTests.record
    url = boundaries.Q02ChecklistBoundaryTests.url
    snapshot = boundaries.Q02ChecklistBoundaryTests.snapshot

    def future_candidate(self):
        row = self.record((False, True), {'approval_notify_users_1': 'reviewer'})
        row.answers_json = json.dumps([{'files': ['q03-person-evidence.pdf']}])
        self.db.session.add(self.models.Driver(company_code='A', employee_id='reviewer', name='Testreviewer'))
        self.db.session.commit()
        self.login('reviewer')
        self.assertEqual(self.request('GET', self.url(row)).status_code, 200)
        self.login('admin')
        return row

    def replace_candidate(self):
        old = self.models.User.query.filter_by(company_code='A', username='reviewer').one()
        old_id = old.id
        driver = self.models.Driver.query.filter_by(company_code='A', employee_id='reviewer').one()
        self.assertEqual(self.request('POST', f'/master/drivers/{driver.id}/delete').status_code, 302)
        self.assertIsNone(self.db.session.get(self.models.User, old_id))
        other = self.models.User(company_code='A', username='reviewer', role='user',
            password='unused', last_name='Different person', password_changed_at='new-account')
        self.db.session.add(other)
        self.db.session.commit()
        self.assertNotEqual(other.id, old_id)
        self.login('reviewer')
        return old_id, other.id

    def test_reused_login_cannot_inherit_future_candidate_detail_or_export(self):
        row = self.future_candidate()
        self.replace_candidate()
        for suffix in ('', '/excel', '/edit'):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.request('GET', self.url(row, suffix)).status_code, 302)

    def test_reused_login_cannot_inherit_future_candidate_attachment(self):
        self.future_candidate()
        self.replace_candidate()
        from flask import session
        from dkss_app.storage import file_belongs_to_current_company
        with self.app.test_request_context():
            session.update(company_code='A', username='reviewer', role='user')
            self.assertFalse(file_belongs_to_current_company('q03-person-evidence.pdf'))
        # Both serving paths must deny before generating a URL or touching storage.
        for url in ('/files/uploads/q03-person-evidence.pdf', '/static/uploads/q03-person-evidence.pdf'):
            response = self.request('GET', url)
            self.assertEqual(response.status_code, 404)

    def test_reused_login_cannot_skip_approval_or_mutate_via_json_post(self):
        row = self.future_candidate()
        self.replace_candidate()
        before = self.snapshot()
        for suffix in ('/approve/1', '/reject', '/edit', '/delete'):
            self.request('POST', self.url(row, suffix), json={
                'approved_by_username': 'reviewer', 'company_code': 'A', 'reject_reason': 'forged'})
            self.assertEqual(self.snapshot(), before)

    def test_foreign_same_login_does_not_inherit_candidate(self):
        row = self.future_candidate()
        self.login('reviewer', 'B')
        before = self.snapshot()
        for suffix in ('', '/excel'):
            self.assertEqual(self.request('GET', self.url(row, suffix)).status_code, 302)
        self.request('POST', self.url(row, '/approve/1'))
        self.assertEqual(self.snapshot(), before)

    def test_same_account_unlock_keeps_candidate_and_history(self):
        row = self.future_candidate()
        actor = self.models.User.query.filter_by(company_code='A', username='reviewer').one()
        old_id = actor.id
        actor.login_locked = True
        self.db.session.commit()
        self.login('reviewer')
        self.assertEqual(self.request('GET', self.url(row)).status_code, 302)
        actor.login_locked = False
        actor.last_name = 'Renamed'
        self.db.session.commit()
        self.login('reviewer')
        self.assertEqual(actor.id, old_id)
        self.assertEqual(self.request('GET', self.url(row)).status_code, 200)

    def test_general_role_remains_available_under_new_accounts_own_identity(self):
        row = self.future_candidate()
        original_id, replacement_id = self.replace_candidate()
        self.login('admin')
        self.request('POST', self.url(row, '/approve/0'))
        self.login('reviewer')
        self.assertEqual(self.request('GET', self.url(row)).status_code, 200)
        self.request('POST', self.url(row, '/approve/1'))
        self.db.session.refresh(row)
        approval = json.loads(row.approvals_json)[1]
        self.assertEqual(row.status, '承認済み')
        self.assertEqual(approval['candidate_user_ids'], [original_id])
        self.assertEqual(approval['approved_by_user_id'], replacement_id)
        self.assertEqual(row.approved_by_user_id, replacement_id)

    def test_unresolved_legacy_candidate_stays_unresolved_on_reads_and_unrelated_update(self):
        row = self.future_candidate()
        legacy = json.loads(row.approvals_json)
        for approval in legacy:
            approval.pop('candidate_user_ids', None)
            approval.pop('candidate_identities', None)
            approval.pop('approved_by_user_id', None)
            approval.pop('approved_by_identity', None)
        row.approvals_json = json.dumps(legacy)
        row.checked_by_user_id = None
        row.checked_by_identity = None
        self.db.session.commit()
        old_json = row.approvals_json
        self.login('reviewer')
        self.assertEqual(self.request('GET', self.url(row)).status_code, 302)
        self.db.session.refresh(row)
        self.assertEqual(row.approvals_json, old_json)
        self.login('admin')
        self.assertEqual(self.request('GET', self.url(row)).status_code, 200)
        row.reject_reason = 'unrelated edit'
        self.db.session.commit()
        self.assertEqual(row.approvals_json, old_json)

    def test_approval_history_and_excel_keep_original_actor_after_out_of_band_deletion(self):
        import io
        from openpyxl import load_workbook
        row = self.record((True, False), {'approval_notify_users_0': 'reviewer'})
        original = self.models.User.query.filter_by(company_code='A', username='reviewer').one()
        original_id = original.id
        self.login('reviewer')
        self.request('POST', self.url(row, '/approve/0'))
        self.login('admin')
        self.request('POST', self.url(row, '/approve/1'))
        self.db.session.refresh(row)
        before = row.approvals_json
        events = [(e.actor_name, e.actor_user_id, e.detail_json, e.created_at)
            for e in self.models.ChecklistEvent.query.filter_by(result_id=row.id).all()]
        d = self.models.Driver(company_code='A', employee_id='reviewer', name='Testreviewer')
        self.db.session.add(d)
        self.db.session.commit()
        self.assertEqual(self.request('POST', f'/master/drivers/{d.id}/delete').status_code, 409)
        # Simulate an external historic account removal, not a relaxed delete route.
        self.db.session.delete(original)
        self.db.session.commit()
        b = self.models.User(company_code='A', username='reviewer', role='user',
            password='unused', last_name='B-DIFFERENT-SECRET', password_changed_at='new')
        self.db.session.add(b)
        self.db.session.commit()
        self.assertNotEqual(b.id, original_id)
        self.login('reviewer')
        self.assertEqual(self.request('GET', self.url(row)).status_code, 302)
        self.request('POST', self.url(row, '/approve/0'))
        self.login('admin')
        response = self.request('GET', self.url(row, '/excel'))
        self.assertEqual(response.status_code, 200)
        book = load_workbook(io.BytesIO(response.data), read_only=True)
        try:
            cells = '\n'.join(str(v) for sheet in book for values in sheet.values for v in values)
        finally:
            book.close()
        self.assertNotIn('B-DIFFERENT-SECRET', cells)
        self.assertIn('Testreviewer', cells)
        self.db.session.refresh(row)
        self.assertEqual(row.approvals_json, before)
        self.assertEqual(json.loads(before)[0]['approved_by_user_id'], original_id)
        self.assertEqual(events, [(e.actor_name, e.actor_user_id, e.detail_json, e.created_at)
            for e in self.models.ChecklistEvent.query.filter_by(result_id=row.id).all()])

    def test_target_and_checker_identity_cannot_follow_reused_username(self):
        row = self.record((False,))
        a = self.models.User.query.filter_by(company_code='A', username='reviewer').one()
        row.target_type = 'user'
        row.target_username, row.target_user = a.username, 'Original subject'
        row.target_user_id = a.id
        row.target_identity = a.account_identity
        self.db.session.commit()
        self.login('reviewer')
        self.assertEqual(self.request('GET', self.url(row)).status_code, 200)
        # Login rename via the UI remains forbidden; this simulates external reuse.
        a.username = 'retained-original-account'
        self.db.session.add(self.models.User(company_code='A', username='reviewer', role='user',
            password='unused', last_name='Other person', password_changed_at='new'))
        self.db.session.commit()
        self.login('reviewer')
        self.assertEqual(self.request('GET', self.url(row)).status_code, 302)
        self.login('retained-original-account')
        self.assertEqual(self.request('GET', self.url(row)).status_code, 200)

    def test_patrol_creator_and_subject_do_not_follow_reused_login(self):
        row = self.models.PatrolResult(company_code='A', created_by_username='reviewer',
            created_by_name='Original author', target_type='user', target_username='reviewer',
            target_user='Original subject', content='Q03-PATROL-SECRET', category='Good',
            files_json=json.dumps(['q03-patrol-evidence.pdf']))
        self.db.session.add(row)
        self.db.session.commit()
        a = self.models.User.query.filter_by(company_code='A', username='reviewer').one()
        self.assertEqual(row.created_by_user_id, a.id)
        self.assertEqual(row.target_user_id, a.id)
        a.username = 'retained-original-account'
        self.db.session.add(self.models.User(company_code='A', username='reviewer', role='user',
            password='unused', last_name='Other person', password_changed_at='new'))
        self.db.session.commit()
        self.login('reviewer')
        url = f'/pointouts/{row.id}'
        self.assertEqual(self.request('GET', url).status_code, 302)
        self.assertNotIn('Q03-PATROL-SECRET', self.request('GET', '/').get_data(as_text=True))
        self.assertEqual(self.request('GET', '/files/uploads/q03-patrol-evidence.pdf').status_code, 404)
        before = (row.content, row.countermeasure, row.target_user_id)
        for suffix in ('/countermeasure', '/delete', '/edit'):
            self.request('POST', url + suffix, json={'content': 'forged'})
            self.db.session.refresh(row)
            self.assertEqual((row.content, row.countermeasure, row.target_user_id), before)
        self.login('retained-original-account')
        self.assertEqual(self.request('GET', url).status_code, 200)

    def test_upgrade_preserves_legacy_evidence_without_username_backfill(self):
        from sqlalchemy import text, inspect
        from dkss_app.safety_identity import IDENTITY_FIELDS, upgrade_storage
        row = self.future_candidate()
        record_id, original_json = row.id, row.approvals_json
        # Construct an actual pre-change schema rather than merely assigning NULL.
        self.db.session.remove()
        with self.db.engine.begin() as connection:
            for table, fields in IDENTITY_FIELDS.items():
                for column in fields.values():
                    connection.execute(text(f'ALTER TABLE {table} DROP COLUMN {column}'))
        import os
        import subprocess
        import sys
        from pathlib import Path
        script = Path(__file__).resolve().parents[1] / 'tools' / 'upgrade_safety_identities.py'
        env = dict(os.environ,
            Q03_MIGRATION_DATABASE_URL=self.db.engine.url.render_as_string(hide_password=False),
            DATABASE_URL='postgresql://invalid.example/do-not-use')
        completed = subprocess.run([sys.executable, str(script)], env=env,
            capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('SAFETY_IDENTITIES_UPGRADED', completed.stdout)
        upgrade_storage()
        columns = {c['name'] for c in inspect(self.db.engine).get_columns('checklist_result')}
        self.assertIn('target_user_id', columns)
        restored = self.db.session.get(self.models.ChecklistResult, record_id)
        self.assertIsNone(restored.checked_by_user_id)
        self.assertIsNone(restored.target_user_id)
        self.assertEqual(restored.approvals_json, original_json)
        self.login('admin')
        self.assertEqual(self.request('GET', self.url(restored)).status_code, 200)

    def test_admin_resubmission_does_not_rebind_unchanged_retired_candidate(self):
        row = self.future_candidate()
        original_id, replacement_id = self.replace_candidate()
        self.login('admin')
        from dkss_app.checklists import checklist_result_edit_version
        response = self.request('POST', self.url(row, '/edit'), data={
            'record_version': checklist_result_edit_version(row),
            'answer_0': 'Updated answer', 'approval_notify_users_1': 'reviewer'})
        self.assertEqual(response.status_code, 302)
        self.db.session.refresh(row)
        self.assertEqual(json.loads(row.approvals_json)[1]['candidate_user_ids'], [original_id])
        self.assertNotIn(replacement_id, json.loads(row.approvals_json)[1]['candidate_user_ids'])
        self.login('reviewer')
        self.assertEqual(self.request('GET', self.url(row)).status_code, 302)

    def test_legacy_candidate_resubmission_does_not_invent_identity(self):
        from dkss_app.safety_identity import selected_candidate_ids
        self.assertEqual(selected_candidate_ids('A', ['reviewer'],
            [{'candidate_usernames': ['reviewer']}]), [None])

    def test_migration_script_requires_its_explicit_database_url(self):
        import os
        import subprocess
        import sys
        from pathlib import Path
        env = dict(os.environ, DATABASE_URL='postgresql://invalid.example/do-not-use')
        env.pop('Q03_MIGRATION_DATABASE_URL', None)
        script = Path(__file__).resolve().parents[1] / 'tools' / 'upgrade_safety_identities.py'
        completed = subprocess.run([sys.executable, str(script)], env=env,
            capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(completed.returncode, 2)
        self.assertIn('explicit Q03_MIGRATION_DATABASE_URL', completed.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
