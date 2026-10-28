"""Combined-PR security and additive migration acceptance; no production DB."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import test_q03_person_identity as identity
import test_q03_postgres_person_identity as postgres


class CombinedIdentityTests(unittest.TestCase):
    setUpClass = classmethod(identity.Q03PersonIdentityTests.setUpClass.__func__)
    tearDownClass = classmethod(identity.Q03PersonIdentityTests.tearDownClass.__func__)
    setUp = identity.Q03PersonIdentityTests.setUp
    tearDown = identity.Q03PersonIdentityTests.tearDown
    login = identity.Q03PersonIdentityTests.login
    request = identity.Q03PersonIdentityTests.request
    record = identity.Q03PersonIdentityTests.record
    url = identity.Q03PersonIdentityTests.url
    future_candidate = identity.Q03PersonIdentityTests.future_candidate
    replace_candidate = identity.Q03PersonIdentityTests.replace_candidate

    def test_new_generation_cannot_inherit_candidate_even_when_generated_user_id_reuses(self):
        a = self.models.User(company_code='A', username='last-candidate', role='user',
            password='unused', last_name='Original A', password_changed_at='same-stamp')
        self.db.session.add(a)
        self.db.session.commit()
        old_id, old_uuid = a.id, a.account_identity
        self.db.session.add(self.models.Driver(company_code='A', employee_id='last-candidate', name='Original A'))
        self.db.session.commit()
        row = self.record((False, True), {'approval_notify_users_1': 'last-candidate'})
        row.answers_json = json.dumps([{'files': ['combined-private.pdf']}])
        notice = self.models.Notification(company_code='A', target_username='last-candidate',
            target_user='Original A', title='OLD_A_NOTICE', message='OLD_A_PRIVATE')
        self.db.session.add(notice)
        self.db.session.commit()
        from flask import session
        from dkss_app.audit import add_audit_log
        with self.app.test_request_context():
            session.update(company_code='A', username='last-candidate', role='user', account_identity=old_uuid)
            add_audit_log(action='integration_original_actor', company_code='A', username='last-candidate')
            event = self.models.ChecklistEvent(company_code='A', result_type='safety', result_id=row.id,
                event_type='integration original actor', actor_username='last-candidate',
                actor_name='Original A', created_at='2026-10-28 10:00:00')
            self.db.session.add(event)
            self.db.session.commit()
        event_id = event.id
        driver = self.models.Driver.query.filter_by(company_code='A', employee_id='last-candidate').one()
        self.assertEqual(self.request('POST', f'/master/drivers/{driver.id}/delete').status_code, 302)
        self.assertEqual(self.request('POST', '/master/drivers/new', data={
            'employee_id': 'last-candidate', 'last_name': 'Replacement B',
            'password': 'Synthetic-Only-742!', 'role': 'user'}).status_code, 302)
        b = self.models.User.query.filter_by(company_code='A', username='last-candidate').one()
        self.assertNotEqual(old_uuid, b.account_identity)
        if self.db.engine.dialect.name == 'sqlite':
            self.assertEqual(old_id, b.id, 'fixture must exercise automatic SQLite rowid reuse')
        else:
            self.assertNotEqual(old_id, b.id)
        self.login('last-candidate')
        evidence = {'database': self.db.engine.dialect.name, 'A_id': old_id, 'B_id': b.id,
            'A_uuid': old_uuid, 'B_uuid': b.account_identity,
            'Q03_actor_id': self.db.session.get(self.models.ChecklistEvent, event_id).actor_user_id,
            'Q03_actor_identity': self.db.session.get(self.models.ChecklistEvent, event_id).actor_identity}
        (Path(__file__).resolve().parents[2] / ('q03-q08-pk-evidence-' + evidence['database'] + '.json')).write_text(
            json.dumps(evidence, indent=2), encoding='utf8')
        audit = self.models.AuditLog.query.filter_by(action='integration_original_actor').one()
        with self.subTest(boundary='Q08 audit actor'):
            self.assertEqual(audit.actor_identity, old_uuid)
            self.assertNotEqual(audit.actor_identity, b.account_identity)
        with self.subTest(boundary='Q03 event actor identity'):
            self.assertEqual(self.db.session.get(self.models.ChecklistEvent, event_id).actor_identity, old_uuid)
            self.assertNotEqual(self.db.session.get(self.models.ChecklistEvent, event_id).actor_identity, b.account_identity)
        with self.subTest(boundary='Q08 notification'):
            self.assertNotIn('OLD_A_PRIVATE', self.request('GET', '/notifications').get_data(as_text=True))
        for suffix in ('', '/excel'):
            with self.subTest(boundary='Q03 result' + suffix):
                self.assertEqual(self.request('GET', self.url(row, suffix)).status_code, 302)
        with self.subTest(boundary='Q03 attachment'):
            self.assertEqual(self.request('GET', '/files/uploads/combined-private.pdf').status_code, 404)
        before = identity.Q03PersonIdentityTests.snapshot(self)
        for suffix in ('/approve/0', '/approve/1', '/reject', '/edit', '/delete'):
            with self.subTest(boundary='Q03 JSON mutation ' + suffix):
                self.request('POST', self.url(row, suffix), json={
                    'approved_by_username': 'last-candidate', 'company_code': 'A', 'reject_reason': 'forged'})
                self.assertEqual(identity.Q03PersonIdentityTests.snapshot(self), before)

    def test_advancing_to_retired_candidate_does_not_notify_replacement(self):
        row = self.future_candidate()
        original_id, replacement_id = self.replace_candidate()
        b = self.models.User.query.filter_by(company_code='A', username='reviewer').one()
        identity_b = b.account_identity
        self.login('admin')
        self.assertEqual(self.request('POST', self.url(row, '/approve/0')).status_code, 302)
        self.db.session.refresh(row)
        self.assertEqual(json.loads(row.approvals_json)[1]['candidate_user_ids'], [original_id])
        self.assertNotEqual(original_id, replacement_id)
        self.login('reviewer')
        # B's independent general-stage permission is still legitimate.
        self.assertEqual(self.request('GET', self.url(row)).status_code, 200)
        received = self.models.Notification.query.filter_by(company_code='A', owner_identity=identity_b).all()
        (Path(__file__).resolve().parents[2] / ('q03-q08-notice-evidence-' + self.db.engine.dialect.name + '.json')).write_text(
            json.dumps({'original_candidate_id': original_id, 'replacement_id': replacement_id,
                'replacement_uuid': identity_b, 'notification_owners': [n.owner_identity for n in received],
                'titles': [n.title for n in received]}, ensure_ascii=False, indent=2), encoding='utf8')
        self.assertEqual(received, [], 'A preserved candidate must not be rebound to B by the notification writer')

    def _migration_order(self, first):
        from sqlalchemy import text
        from dkss_app.account_identity import upgrade_account_identity
        from dkss_app.safety_identity import IDENTITY_FIELDS, GENERATION_FIELDS, upgrade_storage
        self.db.session.remove()
        self.db.drop_all()
        self.db.create_all()
        q08_columns = {'user': ['account_identity'], 'notification': ['owner_identity'],
            'news': ['owner_identity'], 'push_subscription': ['owner_identity'],
            'audit_log': ['actor_identity', 'actor_name'],
            'vehicle_maintenance_record_event': ['actor_identity', 'actor_name']}
        with self.db.engine.begin() as c:
            for index in ('uq_user_account_identity', 'ix_notification_owner_identity', 'ix_push_owner_identity'):
                c.execute(text(f'DROP INDEX IF EXISTS {index}'))
            for table, columns in q08_columns.items():
                for column in columns:
                    c.execute(text(f'ALTER TABLE "{table}" DROP COLUMN {column}'))
            for table, fields in IDENTITY_FIELDS.items():
                for column in list(fields.values()) + [GENERATION_FIELDS[f] for f in fields.values()]:
                    c.execute(text(f'ALTER TABLE "{table}" DROP COLUMN {column}'))
            for table in ('checklist_result', 'vehicle_checklist_result'):
                c.execute(text(f'ALTER TABLE "{table}" DROP COLUMN notification_identities_json'))
            c.execute(text('INSERT INTO "user" (id,company_code,username,password,last_name,role,'
                'password_history_json,failed_login_count,login_locked,timezone,email_notify_enabled) '
                "VALUES (91,'A','retired','unused','Old A','user','[]',0,false,'Asia/Tokyo',false)"))
            c.execute(text("INSERT INTO notification (id,company_code,target_user,target_username,title,message) "
                "VALUES (91,'A','Old A','retired','legacy notice','KEEP_NOTICE')"))
            c.execute(text("INSERT INTO audit_log (id,company_code,username,action,detail,created_at) "
                "VALUES (91,'A','retired','legacy','KEEP_AUDIT','2026-10-01')"))
            c.execute(text("INSERT INTO checklist_result (id,company_code,checklist_id,target_type,target_user,"
                "target_username,checked_by,checked_by_username,approved_by,approved_by_username,approved_date,"
                "status,approvals_json) VALUES (91,'A',91,'user','Old A','retired','Old A','retired',"
                "'Historical Approver','retired','2026-10-01 10:00','承認済み',:approvals)"),
                {'approvals': '[{"candidate_usernames":["retired"],"approved_by":"Historical Approver"}]'})
        repo = Path(__file__).resolve().parents[1]
        db_url = self.db.engine.url.render_as_string(hide_password=False)
        env = dict(os.environ, DATABASE_URL=db_url, Q03_MIGRATION_DATABASE_URL=db_url,
            SECRET_KEY='integration-migration-only', RENDER='', S3_BUCKET_NAME='',
            DOCUMENT_IMPORT_WORKER_ENABLED='0', PYTHONUTF8='1')
        def cli(kind):
            command = ([sys.executable, 'tools/upgrade_safety_identities.py'] if kind == 'Q03' else
                [sys.executable, '-m', 'flask', '--app', 'app', 'upgrade-account-identity'])
            result = subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True, encoding='utf8')
            self.assertEqual(result.returncode, 0, result.stderr)
        operations = [lambda: cli('Q03'), lambda: cli('Q08')] if first == 'Q03' else [lambda: cli('Q08'), lambda: cli('Q03')]
        for operation in operations:
            operation()
        with self.db.engine.connect() as c:
            assigned_uuid = c.scalar(text('SELECT account_identity FROM "user" WHERE id=91'))
            saved = c.execute(text('SELECT target_user_id,checked_by_user_id,approved_by_user_id,approved_by,'
                'approved_date,approvals_json FROM checklist_result WHERE id=91')).one()
            self.assertEqual(saved[:5], (None,None,None,'Historical Approver','2026-10-01 10:00'))
            self.assertNotIn('candidate_user_ids', json.loads(saved[5])[0])
            self.assertTrue(assigned_uuid)
            self.assertEqual(c.execute(text('SELECT target_identity,checked_by_identity,approved_by_identity,'
                'notification_identities_json FROM checklist_result WHERE id=91')).one(), (None,None,None,None))
            self.assertEqual(c.execute(text('SELECT message,owner_identity FROM notification WHERE id=91')).one(),('KEEP_NOTICE',None))
            self.assertEqual(c.execute(text('SELECT detail,actor_identity FROM audit_log WHERE id=91')).one(),('KEEP_AUDIT',None))
        for operation in operations + list(reversed(operations)):
            operation()
        with self.db.engine.connect() as c:
            self.assertEqual(c.scalar(text('SELECT account_identity FROM "user" WHERE id=91')), assigned_uuid)
            self.assertEqual(tuple(c.execute(text('SELECT target_user_id,checked_by_user_id,approved_by_user_id,approved_by,'
                'approved_date,approvals_json FROM checklist_result WHERE id=91')).one()), tuple(saved))
            # Old-code predicates would expose these rows; a plain code rollback is unsafe.
            self.assertEqual(c.scalar(text("SELECT count(*) FROM notification WHERE company_code='A' AND target_username='retired'")),1)
            self.assertEqual(c.scalar(text("SELECT count(*) FROM notification WHERE owner_identity=:id"),{'id':assigned_uuid}),0)

    def test_migration_q08_then_q03_preserves_and_quarantines_legacy(self):
        self._migration_order('Q08')

    def test_migration_q03_then_q08_preserves_and_quarantines_legacy(self):
        self._migration_order('Q03')

    def test_numeric_only_q03_references_are_not_promoted_to_current_generation(self):
        from dkss_app.safety_identity import upgrade_storage
        row = self.future_candidate()
        approvals = json.loads(row.approvals_json)
        for approval in approvals:
            approval.pop('candidate_identities', None)
            approval.pop('approved_by_identity', None)
        # Keep the old numeric evidence intact, as in an existing #283 database.
        original_ids = approvals[1]['candidate_user_ids'][:]
        row.approvals_json = json.dumps(approvals)
        self.db.session.commit()
        upgrade_storage()
        upgrade_storage()
        self.login('reviewer')
        self.assertEqual(self.request('GET', self.url(row)).status_code, 302)
        self.login('admin')
        self.assertEqual(self.request('GET', self.url(row)).status_code, 200)
        self.db.session.refresh(row)
        self.assertEqual(json.loads(row.approvals_json)[1]['candidate_user_ids'], original_ids)
        self.assertNotIn('candidate_identities', json.loads(row.approvals_json)[1])

    def test_same_generation_rename_unlock_and_company_boundary_match_both_permissions(self):
        row = self.future_candidate()
        a = self.models.User.query.filter_by(company_code='A', username='reviewer').one()
        original_id, original_uuid = a.id, a.account_identity
        notice = self.models.Notification(company_code='A', target_username='reviewer',
            target_user='Original A', title='SAME_GENERATION_NOTICE', message='SAME_GENERATION_MESSAGE')
        self.db.session.add(notice)
        self.db.session.commit()
        a.login_locked = True
        self.db.session.commit()
        self.login('reviewer')
        self.assertEqual(self.request('GET', self.url(row)).status_code, 302)
        a.login_locked = False
        a.last_name = 'Renamed A'
        self.db.session.commit()
        self.login('reviewer')
        self.assertEqual((a.id, a.account_identity), (original_id, original_uuid))
        self.assertEqual(self.request('GET', self.url(row)).status_code, 200)
        self.assertIn('SAME_GENERATION_MESSAGE', self.request('GET', '/notifications').get_data(as_text=True))
        self.login('reviewer', 'B')
        self.assertEqual(self.request('GET', self.url(row)).status_code, 302)
        self.assertEqual(self.request('POST', f'/api/notifications/{notice.id}/read').status_code, 404)

    def test_legacy_unknown_references_stay_unbound_and_admin_keeps_review(self):
        from sqlalchemy import text
        row = self.future_candidate()
        approvals = json.loads(row.approvals_json)
        for approval in approvals:
            approval.pop('candidate_user_ids', None)
            approval.pop('candidate_identities', None)
            approval.pop('approved_by_user_id', None)
            approval.pop('approved_by_identity', None)
        row.approvals_json = json.dumps(approvals)
        self.db.session.execute(text('INSERT INTO notification (company_code,target_user,target_username,title,message,owner_identity) '
            "VALUES ('A','Old unknown','reviewer','LEGACY_UNKNOWN','LEGACY_PRIVATE',NULL)"))
        self.db.session.commit()
        before = row.approvals_json
        self.login('reviewer')
        self.assertEqual(self.request('GET', self.url(row)).status_code, 302)
        self.assertNotIn('LEGACY_PRIVATE', self.request('GET', '/notifications').get_data(as_text=True))
        self.login('admin')
        self.assertEqual(self.request('GET', self.url(row)).status_code, 200)
        self.db.session.refresh(row)
        self.assertEqual(row.approvals_json, before)
        self.assertIsNone(self.models.Notification.query.filter_by(title='LEGACY_UNKNOWN').one().owner_identity)


@unittest.skipUnless(os.environ.get('Q03_POSTGRES_TEST_URL'), 'explicit local integration PostgreSQL URL required')
class CombinedPostgresIdentityTests(CombinedIdentityTests):
    setUpClass = classmethod(postgres.Q03PostgresPersonIdentityTests.setUpClass.__func__)
    tearDownClass = classmethod(postgres.Q03PostgresPersonIdentityTests.tearDownClass.__func__)
