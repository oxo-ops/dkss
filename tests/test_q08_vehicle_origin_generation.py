"""No.11 account-generation boundaries, without weakening live foreign keys."""
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from flask import session
from sqlalchemy import event, inspect, text
from werkzeug.exceptions import Conflict, NotFound
from sqlalchemy.exc import IntegrityError

import test_driving_person_vehicles as vehicle_tests
from dkss_app.driving_vehicle_links import DrivingVehicleCorrection, ORIGIN, save_correction, build
from dkss_app.models import ChecklistEvent


def enable_sqlite_foreign_keys(connection, record):
    connection.execute('PRAGMA foreign_keys=ON')


class VehicleOriginGenerationTests(unittest.TestCase):
    setUpClass = classmethod(vehicle_tests.PersonalVehicleTests.setUpClass.__func__)
    tearDownClass = classmethod(vehicle_tests.PersonalVehicleTests.tearDownClass.__func__)
    login, inspection, render, form, post = (vehicle_tests.PersonalVehicleTests.login,
        vehicle_tests.PersonalVehicleTests.inspection, vehicle_tests.PersonalVehicleTests.render,
        vehicle_tests.PersonalVehicleTests.form, vehicle_tests.PersonalVehicleTests.post)

    def setUp(self):
        vehicle_tests.PersonalVehicleTests.setUp(self)
        self.m.db.session.add(self.m.Company(company_code='OTHER', company_name='Other', active=True))
        self.m.db.session.commit()
        if self.m.db.engine.dialect.name == 'sqlite':
            # Every pooled connection must enforce FKs, including inspector /
            # request connections opened after a commit releases the first one.
            self.m.db.engine.dispose()
            event.listen(self.m.db.engine, 'connect', enable_sqlite_foreign_keys)
            self.assertEqual(self.m.db.session.scalar(text('PRAGMA foreign_keys')), 1)

    def tearDown(self):
        self.m.db.session.rollback()
        engine = self.m.db.engine
        vehicle_tests.PersonalVehicleTests.tearDown(self)
        if engine.dialect.name == 'sqlite':
            event.remove(engine, 'connect', enable_sqlite_foreign_keys)
            engine.dispose()

    def replace(self):
        ident, identity = self.user.id, self.user.account_identity
        self.m.db.session.delete(self.user)
        self.m.db.session.commit()
        replacement = self.m.User(id=ident, company_code='TEST', username='one',
            role='user', password='unused', last_name='別人B', password_changed_at='stamp')
        self.m.db.session.add(replacement)
        self.m.db.session.commit()
        self.assertNotEqual(replacement.account_identity, identity)
        self.login()
        return replacement

    def test_deleted_account_numeric_id_reuse_cannot_inherit_candidate_or_write(self):
        row = self.inspection()
        _, context = self.render()
        form = self.form(context['driving_vehicles']['candidates'][0])
        original = row.answers_json
        origin = ChecklistEvent.query.filter_by(event_type=ORIGIN).one()
        old_identity = self.user.account_identity
        self.replace()
        _, context = self.render()
        self.assertEqual(context['driving_vehicles']['candidates'], [])
        self.assertEqual(self.post(form).status_code, 404)
        self.assertEqual(DrivingVehicleCorrection.query.count(), 0)
        self.assertEqual(row.answers_json, original)
        self.assertEqual(ChecklistEvent.query.filter_by(event_type=ORIGIN).count(), 1)
        self.assertEqual(origin.actor_identity, old_identity)
        self.assertEqual(origin.actor_name, '本人')
        self.assertEqual(row.checked_by_identity, old_identity)

    def test_current_correction_foreign_keys_prevent_physical_deletion(self):
        self.inspection()
        _, context = self.render()
        self.assertEqual(self.post(self.form(context['driving_vehicles']['candidates'][0])).status_code, 302)
        self.m.db.session.delete(self.user)
        with self.assertRaises(IntegrityError):
            self.m.db.session.commit()
        self.m.db.session.rollback()
        self.assertIsNotNone(self.m.db.session.get(self.m.User, self.user.id))
        self.assertEqual(DrivingVehicleCorrection.query.count(), 1)

    def test_deleted_account_numeric_id_reuse_rejects_old_correction_form(self):
        self.inspection()
        _, context = self.render()
        form = self.form(context['driving_vehicles']['candidates'][0])
        self.replace()
        self.assertEqual(self.post(form).status_code, 404)
        self.assertEqual(DrivingVehicleCorrection.query.count(), 0)

    def test_origin_captures_existing_q03_actor_uuid(self):
        self.inspection()
        origin = ChecklistEvent.query.filter_by(event_type=ORIGIN).one()
        self.assertEqual(origin.actor_identity, self.user.account_identity)
        self.assertEqual(origin.actor_user_id, self.user.id)
        self.assertEqual(json.loads(origin.detail_json)['user_id'], self.user.id)
        self.assertEqual(origin.actor_name, '本人')
        self.assertLessEqual(len(origin.created_at), 30)

    def test_normal_corrections_append_identity_and_audit_without_editing_origin(self):
        row = self.inspection()
        origin = ChecklistEvent.query.filter_by(event_type=ORIGIN).one()
        before = (row.answers_json, row.vehicle_record_id, origin.detail_json, origin.actor_identity)
        for action in ('exclude', 'reset', 'replace'):
            _, context = self.render()
            panel = context['driving_vehicles']
            item = (panel['corrections'] or panel['candidates'])[0]
            form = self.form(item, action, **({'vehicle_id': self.b.id} if action == 'replace' else {}))
            self.assertEqual(self.post(form).status_code, 302)
        edits = DrivingVehicleCorrection.query.order_by(DrivingVehicleCorrection.revision).all()
        self.assertEqual([e.revision for e in edits], [1, 2, 3])
        self.assertTrue(all(e.user_identity == self.user.account_identity
                            and e.actor_identity == self.user.account_identity and e.actor_name == '本人' for e in edits))
        audits = self.m.AuditLog.query.filter_by(action='driving_vehicle_candidate_corrected').all()
        self.assertEqual(len(audits), 3)
        self.assertTrue(all(a.actor_identity == self.user.account_identity and a.actor_name == '本人' for a in audits))
        self.assertEqual((row.answers_json, row.vehicle_record_id, origin.detail_json, origin.actor_identity), before)

    def test_admin_actor_is_distinct_from_subject_and_cannot_be_replaced_in_audit(self):
        from driving_report_insights import digest
        self.inspection()
        admin = self.m.User.query.filter_by(company_code='TEST', username='admin').one()
        with self.m.app.test_request_context():
            session.update(company_code='TEST', username='admin', role='admin', account_identity=admin.account_identity)
            panel = build({'personal_view':False, 'selected_driver':{'key':digest(['account','TEST',self.user.id])},
                           'period':{}}, [], {})
            save_correction(panel, admin, self.form(panel['candidates'][0]))
        edit = DrivingVehicleCorrection.query.one()
        self.assertEqual(edit.user_identity, self.user.account_identity)
        self.assertEqual(edit.actor_identity, admin.account_identity)
        self.assertNotEqual(edit.user_identity, edit.actor_identity)
        audit = self.m.AuditLog.query.filter_by(action='driving_vehicle_candidate_corrected').one()
        self.assertEqual(audit.actor_identity, admin.account_identity)
        self.assertEqual(json.loads(audit.detail)['subject_identity'], self.user.account_identity)
        admin.last_name = '改姓後管理者'
        self.m.db.session.commit()
        self.assertEqual(edit.actor_name, '検証管理者')
        self.assertEqual(audit.actor_name, '検証管理者')
        self.m.db.session.delete(admin)
        with self.assertRaises(IntegrityError):
            self.m.db.session.commit()
        self.m.db.session.rollback()

    def test_long_actor_name_fits_existing_q03_event_column(self):
        self.user.last_name = '名' * 100
        self.user.first_name = '姓' * 100
        self.m.db.session.commit()
        self.inspection()
        origin = ChecklistEvent.query.filter_by(event_type=ORIGIN).one()
        self.assertEqual(len(origin.actor_name), 100)
        self.assertEqual(origin.actor_identity, self.user.account_identity)

    def test_duplicate_origins_with_different_uuid_remain_ambiguous(self):
        row = self.inspection()
        origin = ChecklistEvent.query.filter_by(event_type=ORIGIN).one()
        self.m.db.session.execute(ChecklistEvent.__table__.insert().values(
            company_code='TEST', result_type='vehicle', result_id=row.id, event_type=ORIGIN,
            actor_username='one', actor_user_id=self.user.id, actor_identity=str(uuid4()),
            actor_name='別の旧起点', detail_json=origin.detail_json, created_at='2026-10-28T12:00:00+09:00'))
        self.m.db.session.commit()
        _, context = self.render()
        self.assertEqual(context['driving_vehicles']['candidates'], [])
        self.assertEqual(ChecklistEvent.query.filter_by(event_type=ORIGIN).count(), 2)

    def test_unique_revision_failure_rolls_back_correction_and_audit_together(self):
        self.inspection()
        _, context = self.render()
        panel = context['driving_vehicles']
        form = self.form(panel['candidates'][0])
        self.assertEqual(self.post(form).status_code, 302)
        with self.m.app.test_request_context():
            session.update(company_code='TEST', username='one', role='user', account_identity=self.user.account_identity)
            with self.assertRaises(Conflict):
                save_correction(panel, self.user, form)
        self.assertEqual(DrivingVehicleCorrection.query.count(), 1)
        self.assertEqual(self.m.AuditLog.query.filter_by(action='driving_vehicle_candidate_corrected').count(), 1)

    def test_rename_and_unlock_keep_same_uuid_and_original_actor_snapshot(self):
        self.inspection()
        _, context = self.render()
        self.assertEqual(self.post(self.form(context['driving_vehicles']['candidates'][0])).status_code, 302)
        identity = self.user.account_identity
        self.user.last_name = '改姓後'
        self.user.login_locked = True
        self.m.db.session.commit()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.user.login_locked = False
        self.m.db.session.commit()
        with self.client.session_transaction() as state:
            state['company_code'] = 'TEST'
        self.login()
        _, context = self.render()
        self.assertEqual(self.user.account_identity, identity)
        self.assertEqual(len(context['driving_vehicles']['corrections'][0]['history']), 1)
        self.assertEqual(DrivingVehicleCorrection.query.one().actor_name, '本人')
        self.assertEqual(ChecklistEvent.query.filter_by(event_type=ORIGIN).one().actor_name, '本人')

    def test_legacy_origin_is_not_backfilled_from_current_checker(self):
        row = self.inspection()
        _, context = self.render()
        form = self.form(context['driving_vehicles']['candidates'][0])
        origin = ChecklistEvent.query.filter_by(event_type=ORIGIN).one()
        origin.actor_identity = None
        origin.actor_user_id = None
        self.m.db.session.commit()
        before = origin.detail_json
        _, context = self.render()
        self.assertEqual(context['driving_vehicles']['candidates'], [])
        self.assertEqual(self.post(form).status_code, 404)
        self.assertEqual(row.checked_by_identity, self.user.account_identity)
        self.assertIsNone(origin.actor_identity)
        self.assertEqual(origin.detail_json, before)

    def test_unresolved_or_other_generation_correction_holds_without_rebinding(self):
        for identity in (None, str(uuid4())):
            with self.subTest(identity=identity):
                row = self.inspection(day='10' if identity is None else '11')
                _, context = self.render()
                item = next(i for i in context['driving_vehicles']['candidates'] if i['inspection_id'] == row.id)
                edit = DrivingVehicleCorrection(company_code='TEST', user_id=self.user.id,
                    inspection_id=row.id, evidence_key=item['evidence_key'], revision=1,
                    action='exclude', actor_user_id=self.user.id, user_identity=identity,
                    actor_identity=identity, actor_name='旧人物の記録', created_at='2026-10-28T12:00:00+09:00')
                self.m.db.session.add(edit)
                self.m.db.session.commit()
                _, context = self.render()
                self.assertEqual(context['driving_vehicles']['candidates'], [])
                self.assertEqual(context['driving_vehicles']['corrections'], [])
                self.assertEqual(self.post(self.form(item)).status_code, 404)
                self.assertEqual(edit.user_identity, identity)
                self.assertEqual(edit.actor_name, '旧人物の記録')

    def test_foreign_same_username_cannot_see_or_correct_origin(self):
        self.inspection()
        _, context = self.render()
        form = self.form(context['driving_vehicles']['candidates'][0])
        self.other.username = 'one'
        self.m.db.session.commit()
        with self.client.session_transaction() as state:
            state.update(company_code='OTHER', username='one', role='user',
                         account_identity=self.other.account_identity, password_changed_at='stamp')
        _, context = self.render()
        self.assertEqual(context['driving_vehicles']['candidates'], [])
        self.assertEqual(self.post(form).status_code, 404)

    def test_vehicle_attachment_is_company_shared_before_and_after_replacement(self):
        row = self.inspection()
        row.answers_json = json.dumps([{'files': ['q08-no11-private.pdf']}])
        self.m.db.session.commit()
        self.m.db.session.add(self.m.User(company_code='TEST', username='bystander', role='user',
            password='unused', last_name='無関係C', password_changed_at='stamp'))
        self.m.db.session.commit()
        with tempfile.TemporaryDirectory(prefix='q08-no11-attachment-') as folder:
            file = Path(folder, 'uploads', 'TEST', 'q08-no11-private.pdf')
            file.parent.mkdir(parents=True)
            file.write_bytes(b'%PDF-SYNTHETIC-Q08-NO11')
            with patch.object(self.m.app, '_static_folder', folder):
                self.login('bystander')
                with self.client.get('/static/uploads/q08-no11-private.pdf', buffered=True) as response:
                    self.assertEqual(response.data, b'%PDF-SYNTHETIC-Q08-NO11')
                self.replace()
                for url in ('/files/uploads/q08-no11-private.pdf', '/static/uploads/q08-no11-private.pdf'):
                    with self.subTest(url=url):
                        with self.client.get(url, follow_redirects=True, buffered=True) as response:
                            self.assertEqual(response.status_code, 200)
                            self.assertEqual(response.data, b'%PDF-SYNTHETIC-Q08-NO11')
                with self.client.session_transaction() as state:
                    state.update(company_code='OTHER', username='secret', role='user',
                        account_identity=self.other.account_identity, password_changed_at='stamp')
                self.assertEqual(self.client.get('/static/uploads/q08-no11-private.pdf').status_code, 404)
        self.assertEqual(json.loads(row.answers_json)[0]['files'], ['q08-no11-private.pdf'])

    def test_stale_subject_panel_is_rejected_after_account_replacement(self):
        self.inspection()
        _, context = self.render()
        panel = context['driving_vehicles']
        form = self.form(panel['candidates'][0])
        replacement = self.replace()
        with self.m.app.test_request_context():
            session.update(company_code='TEST', username='one', role='user', account_identity=replacement.account_identity)
            with self.assertRaises(NotFound):
                save_correction(panel, replacement, form)
        self.assertEqual(DrivingVehicleCorrection.query.count(), 0)

    def test_stale_actor_cookie_cannot_create_new_origin(self):
        identity = self.user.account_identity
        self.replace()
        with self.m.app.test_request_context():
            session.update(company_code='TEST', username='one', role='user', account_identity=identity)
            # B exists, but the authenticated request still names A's UUID.
            row = self.m.VehicleChecklistResult(company_code='TEST', checklist_id=1,
                vehicle_record_id=self.vehicle.id, year='2026', month='10', day='12',
                checked_by_username='one', status='点検完了',
                checklist_snapshot_json=json.dumps({'fixed_template_code':'daily_inspection_truck_trailer'}))
            self.m.db.session.add(row)
            self.m.db.session.commit()
        self.assertEqual(ChecklistEvent.query.filter_by(event_type=ORIGIN).count(), 0)

    def test_additive_migration_is_explicit_repeatable_and_preserves_old_constraints(self):
        from dkss_app.driving_access import initialize_driving_access
        from dkss_app.safety_identity import upgrade_storage
        row = self.inspection()
        _, context = self.render()
        form = self.form(context['driving_vehicles']['candidates'][0])
        db = self.m.db
        db.session.remove()
        table = DrivingVehicleCorrection.__tablename__
        pk = 'SERIAL PRIMARY KEY' if db.engine.dialect.name == 'postgresql' else 'INTEGER PRIMARY KEY'
        with db.engine.begin() as connection:
            DrivingVehicleCorrection.__table__.drop(connection)
            connection.execute(text(f'''CREATE TABLE {table} (
                id {pk}, company_code VARCHAR(50) NOT NULL,
                user_id INTEGER NOT NULL REFERENCES "user"(id), inspection_id INTEGER NOT NULL,
                evidence_key VARCHAR(64) NOT NULL, revision INTEGER NOT NULL, action VARCHAR(20) NOT NULL,
                vehicle_id INTEGER REFERENCES vehicle(id), actor_user_id INTEGER NOT NULL REFERENCES "user"(id),
                created_at VARCHAR(40) NOT NULL,
                CONSTRAINT uq_driving_vehicle_correction_revision UNIQUE (company_code,user_id,inspection_id,revision))'''))
            connection.execute(text(f'''INSERT INTO {table}
                (company_code,user_id,inspection_id,evidence_key,revision,action,actor_user_id,created_at)
                VALUES ('TEST',:uid,:iid,:key,1,'exclude',:uid,'2026-10-28T12:00:00+09:00')'''),
                {'uid':self.user.id, 'iid':row.id, 'key':form['evidence_key']})
        foreign_keys = inspect(db.engine).get_foreign_keys(table)
        unique = inspect(db.engine).get_unique_constraints(table)
        _, context = self.render()
        self.assertFalse(context['driving_vehicles']['ready'])
        self.assertEqual(self.post(form).status_code, 503)
        self.assertNotIn('user_identity', {c['name'] for c in inspect(db.engine).get_columns(table)})
        # Both initializer orders, reruns, and retained nullable legacy records.
        upgrade_storage()
        initialize_driving_access(self.m.app)
        upgrade_storage()
        initialize_driving_access(self.m.app)
        self.assertEqual(inspect(db.engine).get_foreign_keys(table), foreign_keys)
        self.assertEqual(inspect(db.engine).get_unique_constraints(table), unique)
        edit = DrivingVehicleCorrection.query.one()
        self.assertIsNone(edit.user_identity)
        self.assertIsNone(edit.actor_identity)
        self.assertEqual(edit.action, 'exclude')
        _, context = self.render()
        self.assertTrue(context['driving_vehicles']['ready'])
        self.assertEqual(context['driving_vehicles']['candidates'], [])
        self.assertEqual(context['driving_vehicles']['corrections'], [])
        self.assertEqual(self.post(form).status_code, 404)


if __name__ == '__main__':
    unittest.main()
