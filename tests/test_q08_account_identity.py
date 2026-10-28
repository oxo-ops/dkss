"""Account reincarnation, legacy quarantine and immutable audit evidence. Synthetic DB only."""
import json
import unittest
from unittest.mock import patch

from test_workflow_regressions import WorkflowRegressionTests as Fixture
from identity_fixture import identity_for


class AccountIdentityTests(unittest.TestCase):
    setUpClass = classmethod(Fixture.setUpClass.__func__)
    tearDownClass = classmethod(Fixture.tearDownClass.__func__)
    setUp = Fixture.setUp
    tearDown = Fixture.tearDown

    def user(self, company='TEST', username='retired', name='Person A'):
        m = self.m
        user = m.User(company_code=company, username=username, last_name=name, role='user',
                      password=m.generate_password_hash('Synthetic-Only-742!'),
                      password_changed_at='2026-10-28 10:00:00')
        m.db.session.add(user)
        m.db.session.commit()
        return user

    def client_for(self, user):
        client = self.m.app.test_client()
        with client.session_transaction() as state:
            state.update(company_code=user.company_code, username=user.username, role=user.role,
                         password_changed_at=user.password_changed_at, account_identity=user.account_identity)
        return client

    def notice(self, user, deleted=False):
        from datetime import datetime
        row = self.m.Notification(company_code=user.company_code, target_user=user.last_name,
            target_username=user.username, title='Q08_PRIVATE_PERSON_A', message='Synthetic private message',
            files_json=json.dumps(['q08-private.pdf']), read=False,
            deleted_at=datetime(2026, 10, 1) if deleted else None,
            created_at='2026-10-01 00:00:00')
        self.m.db.session.add(row)
        self.m.db.session.commit()
        self.assertEqual(row.owner_identity, user.account_identity)
        return row

    def replace_person(self, user):
        m = self.m
        company, username, old_identity = user.company_code, user.username, user.account_identity
        driver = m.Driver(company_code=company, employee_id=username, name=user.last_name)
        m.db.session.add(driver)
        m.db.session.commit()
        response = self.client.post(f'/master/drivers/{driver.id}/delete')
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(m.User.query.filter_by(company_code=company, username=username).first())
        response = self.client.post('/master/drivers/new', data={'employee_id':username,
            'last_name':'Person B', 'password':'Synthetic-Only-742!', 'role':'user'})
        self.assertEqual(response.status_code, 302)
        replacement = m.User.query.filter_by(company_code=company, username=username).one()
        self.assertNotEqual(replacement.account_identity, old_identity)
        return replacement

    def test_reused_login_cannot_list_detail_open_or_preview_old_notifications(self):
        old = self.user()
        row = self.notice(old)
        replacement = self.replace_person(old)
        client = self.client_for(replacement)
        for path in ['/notifications', '/notifications?view=deleted', '/api/notifications/recent',
                     f'/notifications/{row.id}', f'/notifications/{row.id}/open']:
            response = client.get(path)
            self.assertNotIn('Q08_PRIVATE_PERSON_A', response.get_data(as_text=True), path)
        response = client.get('/api/notifications/unread-count')
        self.assertEqual(response.json['unread_count'], 0)
        self.assertEqual(self.m.Notification.query.count(), 1)

    def test_reused_login_cannot_mutate_or_restore_old_notifications(self):
        old = self.user()
        visible, deleted = self.notice(old), self.notice(old, deleted=True)
        client = self.client_for(self.replace_person(old))
        before = [(r.id, r.read, r.deleted_at) for r in self.m.Notification.query.order_by(self.m.Notification.id)]
        for row in [visible, deleted]:
            for action in ['read', 'delete', 'undo-delete']:
                response = client.post(f'/api/notifications/{row.id}/{action}',
                    json={'deleted_at':'2026-10-01T00:00:00'})
                self.assertEqual(response.status_code, 404, (row.id, action))
        self.m.db.session.expire_all()
        self.assertEqual([(r.id,r.read,r.deleted_at) for r in self.m.Notification.query.order_by(self.m.Notification.id)], before)

    def test_old_cookie_rejected_even_when_password_timestamp_matches_replacement(self):
        old = self.user()
        stale = self.client_for(old)
        replacement = self.replace_person(old)
        replacement.password_changed_at = '2026-10-28 10:00:00'
        self.m.db.session.commit()
        self.assertEqual(stale.get('/api/notifications/unread-count').status_code, 401)
        self.assertEqual(stale.get('/static/uploads/q08-private.pdf').status_code, 302)

    def test_legacy_cookie_without_account_identity_requires_login(self):
        with self.client.session_transaction() as state:
            state.pop('account_identity', None)
        self.assertEqual(self.client.get('/api/notifications/unread-count').status_code, 401)

    def test_same_person_lock_unlock_preserves_identity_and_history(self):
        user = self.user()
        row = self.notice(user)
        identity = user.account_identity
        client = self.client_for(user)
        user.login_locked = True
        self.m.db.session.commit()
        self.assertEqual(client.get('/api/notifications/unread-count').status_code, 401)
        user.login_locked = False
        self.m.db.session.commit()
        response = self.client_for(user).get('/notifications')
        self.assertIn('Q08_PRIVATE_PERSON_A', response.get_data(as_text=True))
        self.assertEqual((user.account_identity, row.owner_identity), (identity, identity))

    def test_rename_keeps_ownership_without_matching_username(self):
        user = self.user()
        row = self.notice(user)
        user.username = 'renamed'
        self.m.db.session.commit()
        self.assertEqual(self.client_for(user).post(f'/api/notifications/{row.id}/read').status_code, 200)

    def test_same_username_other_company_is_not_owner(self):
        old = self.user()
        row = self.notice(old)
        self.m.db.session.add(self.m.Company(company_code='OTHER',company_name='Other',active=True))
        self.m.db.session.commit()
        other = self.user(company='OTHER')
        self.assertEqual(self.client_for(other).post(f'/api/notifications/{row.id}/read').status_code, 404)

    def test_legacy_unbound_notification_is_preserved_and_hidden(self):
        user = self.user()
        row = self.notice(user)
        self.m.db.session.execute(self.m.db.text('UPDATE notification SET owner_identity=NULL WHERE id=:id'), {'id':row.id})
        self.m.db.session.commit()
        response = self.client_for(user).get('/notifications')
        self.assertNotIn('Q08_PRIVATE_PERSON_A', response.get_data(as_text=True))
        self.assertEqual(self.m.Notification.query.count(), 1)

    def test_old_attachment_is_not_authorized_through_notification(self):
        old = self.user()
        self.notice(old)
        new = self.replace_person(old)
        with self.m.app.test_request_context('/'):
            self.m.session.update(company_code='TEST', username=new.username,
                account_identity=new.account_identity, role='user')
            self.assertFalse(self.m.file_belongs_to_current_company('q08-private.pdf'))

    def test_personal_news_attachment_does_not_follow_reused_login(self):
        old = self.user()
        news = self.m.News(company_code='TEST',target_type='user',target_value=old.username,
            title='Synthetic private news',files_json=json.dumps(['q08-personal-news.pdf']))
        self.m.db.session.add(news)
        self.m.db.session.commit()
        self.assertEqual(news.owner_identity,old.account_identity)
        new = self.replace_person(old)
        with self.m.app.test_request_context('/'):
            self.m.session.update(company_code='TEST',username=new.username,role='user',account_identity=new.account_identity)
            self.assertFalse(self.m.file_belongs_to_current_company('q08-personal-news.pdf'))

    def test_mfa_pending_identity_is_not_transferable_even_if_other_fields_match(self):
        from dkss_app.auth import mfa_challenge_key
        old = self.user()
        identity = old.account_identity
        new = self.replace_person(old)
        new.mfa_code_hash = self.m.generate_password_hash('123456')
        new.mfa_code_expires_at = '2099-01-01 00:00:00'
        self.m.db.session.commit()
        client = self.m.app.test_client()
        with client.session_transaction() as state:
            state.update(mfa_pending_company_code='TEST',mfa_pending_username=new.username,
                mfa_account_identity=identity,mfa_password_changed_at=new.password_changed_at,
                mfa_pending_challenge=mfa_challenge_key(new))
        self.assertEqual(client.post('/mfa',data={'code':'123456'}).location,'/login')
        with client.session_transaction() as state:
            self.assertNotIn('username',state)

    def test_bulk_notification_actions_cannot_modify_retired_owner_rows(self):
        old = self.user()
        visible, deleted = self.notice(old), self.notice(old,deleted=True)
        client = self.client_for(self.replace_person(old))
        for action in ['read','delete','restore']:
            response = client.post('/notifications/bulk',data={'action':action,'notification_ids':[str(visible.id),str(deleted.id)]})
            self.assertEqual(response.status_code,302)
        self.assertEqual(client.post('/notifications/read-all').status_code,302)
        self.m.db.session.expire_all()
        self.assertFalse(visible.read)
        self.assertIsNone(visible.deleted_at)
        self.assertIsNotNone(deleted.deleted_at)

    def test_sender_and_direct_workflow_writer_bind_current_owner(self):
        user = self.user()
        with self.m.app.test_request_context('/'):
            self.m.session.update(company_code='TEST', username='admin',
                account_identity=identity_for('TEST','admin'))
            with patch('dkss_app.notifications_delivery.dispatch_external_notification'):
                self.m.add_notification(user.last_name,'New message','Synthetic',target_username=user.username)
        row = self.m.Notification.query.one()
        self.assertEqual(row.owner_identity, user.account_identity)
        self.assertEqual(self.client_for(user).post(f'/api/notifications/{row.id}/read').status_code, 200)

    def test_delayed_sender_never_resolves_selected_old_person_to_replacement(self):
        old = self.user()
        identity = old.account_identity
        self.replace_person(old)
        with self.m.app.test_request_context('/'):
            self.m.session.update(company_code='TEST',username='admin',account_identity=identity_for('TEST','admin'))
            with patch('dkss_app.notifications_delivery.dispatch_external_notification') as deliver:
                self.m.add_notification('Person A','Old message','Private synthetic text',
                    target_username='retired',target_identity=identity)
                deliver.assert_not_called()
        self.assertEqual(self.m.Notification.query.count(),0)

    def test_delayed_external_delivery_cannot_send_old_content_to_replacement(self):
        from dkss_app.notifications_delivery import dispatch_external_notification
        old = self.user()
        row = self.notice(old)
        new = self.replace_person(old)
        with patch('dkss_app.notifications_delivery.send_web_push_notification') as push, patch('dkss_app.notifications_delivery.send_email_notification') as mail:
            dispatch_external_notification(new,row.title,row.message,notification_id=row.id)
            push.assert_not_called()
            mail.assert_not_called()

    def test_news_commit_then_reregistration_does_not_retarget_selected_recipient(self):
        from dkss_app import notifications_delivery as delivery
        old = self.user()
        identity = old.account_identity
        admin = self.m.User.query.filter_by(username='admin').one()
        admin.role = 'itc'
        self.m.db.session.commit()
        save = delivery.add_news

        def save_then_replace(*args, **kwargs):
            result = save(*args, **kwargs)
            self.m.User.query.filter_by(account_identity=identity).delete(synchronize_session=False)
            self.m.db.session.commit()
            self.user(name='Person B')
            return result

        with patch.object(delivery,'add_news',side_effect=save_then_replace):
            response = self.client.post('/itc/news/new',data={'title':'Private old message',
                'message':'Synthetic private text','target_type':'user','target_value':'retired'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.m.News.query.one().owner_identity,identity)
        self.assertEqual(self.m.Notification.query.count(),0)

    def test_audit_actor_snapshot_never_resolves_to_replacement_person(self):
        from dkss_app.account_identity import audit_actor_label
        old = self.user()
        identity = old.account_identity
        with self.m.app.test_request_context('/'):
            self.m.session.update(company_code='TEST',username=old.username,account_identity=identity)
            self.m.add_audit_log('q08_history', detail='Synthetic action')
            self.m.db.session.commit()
        row = self.m.AuditLog.query.filter_by(action='q08_history').one()
        self.replace_person(old)
        self.assertEqual(row.actor_identity, identity)
        self.assertIn('Person A', audit_actor_label(row))
        self.assertNotIn('Person B', audit_actor_label(row))
        row.actor_identity = None
        row.actor_name = None
        self.m.db.session.commit()
        self.assertIn('本人未確認', audit_actor_label(row))

    def test_schema_bootstrap_preserves_old_audit_history(self):
        import os
        row = self.m.AuditLog(company_code='TEST',username='retired',action='old_history',
                              detail='Keep old evidence',created_at='2020-01-01 00:00:00')
        self.m.db.session.add(row)
        self.m.db.session.commit()
        with patch.dict(os.environ, {'ITC_INITIAL_PASSWORD':'Synthetic-Only-742!'}):
            self.m.init_db()
        self.assertEqual(self.m.AuditLog.query.filter_by(action='old_history').one().detail,'Keep old evidence')

    def test_failed_login_does_not_identify_the_target_account_as_the_actor(self):
        user = self.user()
        with self.m.app.test_request_context('/'):
            self.m.add_audit_log('login_failed',company_code='TEST',username=user.username)
            self.m.db.session.commit()
        log = self.m.AuditLog.query.filter_by(action='login_failed').one()
        self.assertIsNone(log.actor_identity)
        self.assertIsNone(log.actor_name)

    def test_cross_company_audit_keeps_authenticated_actor_not_namesake_in_target_company(self):
        admin = self.m.User.query.filter_by(company_code='TEST',username='admin').one()
        other = self.user(company='OTHER',username='admin',name='Other Person')
        with self.m.app.test_request_context('/'):
            self.m.session.update(company_code='TEST',username='admin',account_identity=admin.account_identity)
            self.m.add_audit_log('q08_cross_company',company_code='OTHER')
            self.m.db.session.commit()
        log = self.m.AuditLog.query.filter_by(action='q08_cross_company').one()
        self.assertEqual(log.actor_identity,admin.account_identity)
        self.assertNotEqual(log.actor_identity,other.account_identity)

    def test_audit_enrichment_leaves_pending_business_validation_to_callers_commit(self):
        from sqlalchemy.exc import IntegrityError
        self.m.db.session.add(self.m.Office(company_code='TEST',name=None))
        with self.m.app.test_request_context('/'):
            self.m.session.update(company_code='TEST',username='admin',account_identity=identity_for('TEST','admin'))
            self.m.add_audit_log('q08_pending_business_write')
        # The caller can still catch its own commit failure and roll back both.
        with self.assertRaises(IntegrityError):
            self.m.db.session.commit()
        self.m.db.session.rollback()
        self.assertEqual(self.m.AuditLog.query.filter_by(action='q08_pending_business_write').count(),0)

    def test_registration_audit_binds_new_account_without_premature_flush(self):
        user = self.m.User(company_code='TEST',username='new-person',password='unused',last_name='New Person')
        self.m.db.session.add(user)
        with self.m.app.test_request_context('/'):
            self.m.add_audit_log('user_registered',company_code='TEST',username='new-person')
        self.assertIsNone(user.id)
        self.m.db.session.commit()
        log = self.m.AuditLog.query.filter_by(action='user_registered').one()
        self.assertTrue(user.account_identity)
        self.assertEqual(log.actor_identity,user.account_identity)
        self.assertEqual(log.actor_name,'New Person')

    def test_maintenance_event_preserves_actor_snapshot_after_reregistration(self):
        from dkss_app.maintenance import add_vehicle_maintenance_record_event
        from dkss_app.vehicle_karte import get_vehicle_maintenance_record_events
        old = self.user()
        record = self.m.VehicleMaintenanceRecord(company_code='TEST',vehicle_record_id=self.vehicle.id,
            content='Synthetic maintenance',status='整備中')
        self.m.db.session.add(record)
        self.m.db.session.commit()
        with self.m.app.test_request_context('/'):
            self.m.session.update(company_code='TEST',username=old.username,account_identity=old.account_identity)
            add_vehicle_maintenance_record_event(record,'created')
            self.m.db.session.commit()
        self.replace_person(old)
        items = get_vehicle_maintenance_record_events(record)
        self.assertEqual(items[0]['actor'],'Person A')
        event = self.m.VehicleMaintenanceRecordEvent.query.one()
        self.m.db.session.execute(self.m.db.text('UPDATE vehicle_maintenance_record_event SET actor_identity=NULL, actor_name=NULL WHERE id=:id'),{'id':event.id})
        self.m.db.session.commit()
        self.m.db.session.expire_all()
        items = get_vehicle_maintenance_record_events(record)
        self.assertIn('本人未確認',items[0]['actor'])
        self.assertNotIn('Person B',items[0]['actor'])

    def test_document_uploader_is_not_relabelled_with_replacement_name(self):
        from dkss_app.vehicle_karte import build_vehicle_karte_documents_context
        old = self.user()
        self.replace_person(old)
        documents = [{'draft_id':'synthetic','filename':'history.pdf','created_by_username':'retired',
                      'document_type':'inspection','completed_at':None}]
        with self.m.app.test_request_context('/'):
            result = build_vehicle_karte_documents_context(self.vehicle,documents)
        label = result['document_page'].items[0]['uploader_label']
        self.assertIn('本人未確認',label)
        self.assertNotIn('Person B',label)

    def test_identity_and_notification_owner_cannot_be_reassigned(self):
        user = self.user()
        row = self.notice(user)
        user.account_identity = 'changed'
        with self.assertRaises(ValueError): self.m.db.session.flush()
        self.m.db.session.rollback()
        row.owner_identity = 'changed'
        with self.assertRaises(ValueError): self.m.db.session.flush()
        self.m.db.session.rollback()

    def test_push_to_replacement_does_not_use_retired_subscription(self):
        from dkss_app.notifications_delivery import send_web_push_notification
        old = self.user()
        self.m.db.session.add(self.m.PushSubscription(company_code='TEST',username=old.username,
            owner_identity=old.account_identity,endpoint='https://example.invalid/old',p256dh='synthetic',auth='synthetic',created_at='2026-10-01'))
        self.m.db.session.commit()
        new = self.replace_person(old)
        with patch.dict(self.m.app.config, VAPID_PRIVATE_KEY='synthetic', VAPID_PUBLIC_KEY='synthetic',VAPID_SUBJECT='mailto:a@example.invalid'), patch('dkss_app.common.webpush') as push:
            self.assertFalse(send_web_push_notification(new,'Synthetic','Message'))
            push.assert_not_called()


class IdentityMigrationTests(unittest.TestCase):
    def test_additive_idempotent_migration_does_not_guess_old_owners_or_delete_history(self):
        import os
        from dkss_app import create_app
        from dkss_app.extensions import db
        from dkss_app.account_identity import upgrade_account_identity
        with patch.dict(os.environ, {'SECRET_KEY':'q08-test','RENDER':'','S3_BUCKET_NAME':'','AWS_EC2_METADATA_DISABLED':'true'}):
            app = create_app({'TESTING':True,'SQLALCHEMY_DATABASE_URI':'sqlite:///:memory:'})
        with app.app_context():
            with db.engine.begin() as c:
                for sql in ['CREATE TABLE "user" (id INTEGER PRIMARY KEY, username TEXT)',
                    'CREATE TABLE news (id INTEGER PRIMARY KEY)',
                    'CREATE TABLE vehicle_maintenance_record_event (id INTEGER PRIMARY KEY)',
                    'CREATE TABLE notification (id INTEGER PRIMARY KEY, company_code TEXT, target_username TEXT, message TEXT)',
                    'CREATE TABLE push_subscription (id INTEGER PRIMARY KEY, company_code TEXT)',
                    'CREATE TABLE audit_log (id INTEGER PRIMARY KEY, username TEXT, detail TEXT)']:
                    c.execute(db.text(sql))
                c.execute(db.text('INSERT INTO "user" VALUES (1, \'reused\')'))
                c.execute(db.text("INSERT INTO notification VALUES (1, 'TEST', 'reused', 'OLD PRIVATE MESSAGE')"))
                c.execute(db.text("INSERT INTO audit_log VALUES (1, 'reused', 'OLD AUDIT')"))
            upgrade_account_identity()
            with db.engine.connect() as c:
                identity = c.scalar(db.text('SELECT account_identity FROM "user"'))
                self.assertTrue(identity)
                self.assertEqual(c.execute(db.text('SELECT message, owner_identity FROM notification')).one(), ('OLD PRIVATE MESSAGE',None))
                self.assertEqual(c.execute(db.text('SELECT detail, actor_identity FROM audit_log')).one(), ('OLD AUDIT',None))
            upgrade_account_identity()
            with db.engine.connect() as c:
                self.assertEqual(c.scalar(db.text('SELECT account_identity FROM "user"')), identity)
            db.session.remove()
            db.engine.dispose()
