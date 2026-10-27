"""QP-20261027 Q02-NOTIFY-02: real request/DB ownership checks.

Synthetic temporary SQLite only. These tests do not establish PostgreSQL
locking guarantees, MFA correctness, production deployment or full Q02 coverage.
"""
import json
import os
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class Q02NotificationBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='dkss-q02-notifications-')
        from dkss_app import create_app, models
        from dkss_app.extensions import db, limiter
        cls.db, cls.models = db, models
        env = {'SECRET_KEY': 'isolated-q02-notifications', 'RENDER': '',
               'DATABASE_URL': 'sqlite:///' + str(Path(cls.temp.name)/'test.db'),
               'OPENAI_API_KEY': '', 'SMTP_HOST': '', 'S3_BUCKET_NAME': '',
               'VAPID_PRIVATE_KEY': '', 'VAPID_PUBLIC_KEY': '',
               'AWS_EC2_METADATA_DISABLED': 'true'}
        with patch.dict(os.environ, env):
            cls.app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False})
        limiter.enabled = False

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            cls.db.session.remove()
            cls.db.engine.dispose()
        cls.temp.cleanup()

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.db.drop_all()
        self.db.create_all()
        m = self.models
        self.db.session.add_all([
            m.Company(company_code=c, company_name=c, active=True) for c in ('A','B')
        ])
        for company, username in [('A','same'),('A','other'),('B','same')]:
            self.db.session.add(m.User(company_code=company, username=username,
                password='unused', role='user', last_name='Test', first_name='User',
                password_changed_at='2026-10-27 10:00:00'))
        self.rows = []
        self.stamp = datetime(2026,10,27,1,0,0)
        for company, username, title, deleted in [
            ('A','same','OWN_VISIBLE',False), ('A','same','OWN_DELETED',True),
            ('A','other','OTHER_RECIPIENT_SECRET',False),
            ('B','same','OTHER_COMPANY_SECRET',False),
            ('A','other','OTHER_RECIPIENT_DELETED_SECRET',True),
            ('B','same','OTHER_COMPANY_DELETED_SECRET',True),
        ]:
            row=m.Notification(company_code=company,target_user='Test',
                target_username=username,title=title,message=title,link='/notifications',
                read=False,created_at='2026-10-27 10:00:00',
                workflow_context_json=json.dumps({'action':'q02_test_unknown'}),
                deleted_at=self.stamp if deleted else None)
            self.db.session.add(row)
            self.rows.append(row)
        self.db.session.commit()
        self.own,self.deleted,self.other,self.foreign,self.other_deleted,self.foreign_deleted=self.rows
        self.client=self.app.test_client()
        with self.client.session_transaction() as session:
            session.update(company_code='A',username='same',role='user',
                           password_changed_at='2026-10-27 10:00:00')

    def tearDown(self):
        self.app.config['WTF_CSRF_ENABLED']=False
        self.db.session.remove()
        self.ctx.pop()

    def request(self, method, url, **kwargs):
        response=self.client.open(url,method=method,**kwargs)
        self.addCleanup(response.close)
        return response

    def snapshot(self):
        self.db.session.expire_all()
        return [(r.id,r.read,r.deleted_at) for r in
                self.models.Notification.query.order_by(self.models.Notification.id).all()]

    def assert_secrets_absent(self,response):
        for title in ('OTHER_RECIPIENT_SECRET','OTHER_COMPANY_SECRET',
                      'OTHER_RECIPIENT_DELETED_SECRET','OTHER_COMPANY_DELETED_SECRET'):
            self.assertNotIn(title,response.get_data(as_text=True))

    def test_recent_and_count_only_include_current_recipient(self):
        r=self.request('GET','/api/notifications/recent')
        self.assertEqual(r.status_code,200)
        self.assertEqual([x['id'] for x in r.json['notifications']],[self.own.id])
        self.assertEqual(r.json['unread_count'],1)
        self.assertIn('no-store',r.headers['Cache-Control'])
        r=self.request('GET','/api/notifications/unread-count?include_action=1')
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json['unread_count'],1)
        self.assertEqual(set(r.json['workflow_states']),{str(self.own.id)})

    def test_all_list_views_hide_other_recipient_and_company(self):
        for view in ('inbox','unread','action','deleted'):
            with self.subTest(view=view):
                r=self.request('GET','/notifications?view='+view)
                self.assertEqual(r.status_code,200)
                self.assert_secrets_absent(r)

    def test_direct_panel_and_open_deny_foreign_ids_without_mutation(self):
        before=self.snapshot()
        for row in (self.other,self.foreign):
            for suffix in ('','?panel=1','/open'):
                with self.subTest(id=row.id,suffix=suffix):
                    r=self.request('GET',f'/notifications/{row.id}{suffix}')
                    self.assertEqual(r.status_code,404 if suffix=='?panel=1' else 302)
                    self.assert_secrets_absent(r)
                    self.assertEqual(self.snapshot(),before)

    def test_panel_preview_does_not_mark_own_notification_read(self):
        r=self.request('GET',f'/notifications/{self.own.id}?panel=1')
        self.assertEqual(r.status_code,200)
        self.assertFalse(self.snapshot()[0][1])

    def test_own_detail_redirects_to_panel_without_implicit_read(self):
        before=self.snapshot()
        r=self.request('GET',f'/notifications/{self.own.id}')
        self.assertEqual(r.status_code,302)
        from urllib.parse import urlparse, parse_qs
        target=urlparse(r.location)
        self.assertEqual(target.path,'/notifications')
        self.assertEqual(parse_qs(target.query)['notification'],[str(self.own.id)])
        self.assertEqual(self.snapshot(),before)

    def test_read_api_denies_other_recipient_and_company(self):
        before=self.snapshot()
        for row in (self.other,self.foreign):
            with self.subTest(id=row.id):
                self.assertEqual(self.request('POST',f'/api/notifications/{row.id}/read').status_code,404)
                self.assertEqual(self.snapshot(),before)

    def test_read_api_accepts_own_and_rejects_deleted(self):
        self.assertEqual(self.request('POST',f'/api/notifications/{self.own.id}/read').status_code,200)
        self.assertEqual(self.request('POST',f'/api/notifications/{self.deleted.id}/read').status_code,409)
        self.assertTrue(self.snapshot()[0][1])
        self.assertFalse(self.snapshot()[1][1])

    def test_delete_and_restore_apis_deny_other_recipient_and_company(self):
        before=self.snapshot()
        for row in (self.other,self.foreign,self.other_deleted,self.foreign_deleted):
            for action in ('delete','undo-delete'):
                with self.subTest(id=row.id,action=action):
                    r=self.request('POST',f'/api/notifications/{row.id}/{action}',
                        json={'deleted_at':self.stamp.isoformat()})
                    self.assertEqual(r.status_code,404)
                    self.assertEqual(self.snapshot(),before)

    def test_own_delete_undo_requires_exact_deletion_version(self):
        r=self.request('POST',f'/api/notifications/{self.own.id}/delete')
        self.assertEqual(r.status_code,200)
        stamp=r.json['deleted_at']
        r=self.request('POST',f'/api/notifications/{self.own.id}/undo-delete',
            json={'deleted_at':'2000-01-01T00:00:00'})
        self.assertEqual(r.status_code,409)
        self.assertIsNotNone(self.snapshot()[0][2])
        r=self.request('POST',f'/api/notifications/{self.own.id}/undo-delete',json={'deleted_at':stamp})
        self.assertEqual(r.status_code,200)
        self.assertIsNone(self.snapshot()[0][2])

    def test_html_delete_and_restore_cannot_modify_foreign_ids(self):
        before=self.snapshot()
        for row in (self.other,self.foreign,self.other_deleted,self.foreign_deleted):
            for action in ('delete','restore'):
                with self.subTest(id=row.id,action=action):
                    self.assertEqual(self.request('POST',f'/notifications/{row.id}/{action}').status_code,302)
                    self.assertEqual(self.snapshot(),before)

    def test_bulk_all_actions_only_mutate_own_selected_rows(self):
        protected=self.snapshot()[2:]
        for action in ('read','unread','delete','restore'):
            with self.subTest(action=action):
                r=self.request('POST','/notifications/bulk',data={
                    'action':action,'notification_ids':[str(x.id) for x in self.rows]})
                self.assertEqual(r.status_code,302)
                states=self.snapshot()
                self.assertEqual(states[2:],protected)
                if action=='read':
                    self.assertTrue(states[0][1]); self.assertFalse(states[1][1])
                elif action=='unread':
                    self.assertTrue(all(not s[1] and s[2] is None for s in states[:2]))
                elif action=='delete':
                    self.assertTrue(all(s[2] is not None for s in states[:2]))
                else:
                    self.assertTrue(all(s[2] is None for s in states[:2]))

    def test_read_all_excludes_deleted_other_recipient_and_company(self):
        self.assertEqual(self.request('POST','/notifications/read-all').status_code,302)
        states=self.snapshot()
        self.assertTrue(states[0][1]); self.assertTrue(all(not s[1] for s in states[1:]))

    def test_undo_by_shared_timestamp_only_restores_own_rows(self):
        before=self.snapshot()
        self.assertEqual(self.request('POST','/notifications/undo-delete',
            data={'deleted_at':self.stamp.isoformat()}).status_code,302)
        states=self.snapshot()
        self.assertIsNone(states[1][2]); self.assertEqual(states[2:],before[2:])

    def test_invalid_bulk_ids_leave_every_record_unchanged(self):
        before=self.snapshot()
        for ids in (['invalid'],['0'],['-1'],['2147483648'],[]):
            with self.subTest(ids=ids):
                self.assertEqual(self.request('POST','/notifications/bulk',
                    data={'action':'delete','notification_ids':ids}).status_code,302)
                self.assertEqual(self.snapshot(),before)

    def test_csrf_rejects_missing_token_and_accepts_valid_token(self):
        self.app.config['WTF_CSRF_ENABLED']=True
        before=self.snapshot()
        r=self.request('POST',f'/api/notifications/{self.own.id}/read')
        self.assertEqual(r.status_code,400)
        self.assertEqual(self.snapshot(),before)
        token=self.request('GET','/login/csrf-token').json['csrf_token']
        r=self.request('POST',f'/api/notifications/{self.own.id}/read',headers={'X-CSRFToken':token})
        self.assertEqual(r.status_code,200)
        self.assertTrue(self.snapshot()[0][1])

    def test_external_notification_links_cannot_redirect_off_site(self):
        for link in ('https://example.invalid/secret','//example.invalid/secret','/\\example.invalid/secret'):
            with self.subTest(link=link):
                self.own.link=link
                self.db.session.commit()
                r=self.request('GET',f'/notifications/{self.own.id}/open')
                self.assertEqual(r.status_code,302)
                self.assertTrue(r.location.startswith('/notifications'))
                self.assertFalse(self.snapshot()[0][1])

    def test_foreign_notification_query_id_does_not_mark_read(self):
        before=self.snapshot()
        for row in (self.other,self.foreign):
            with self.subTest(id=row.id):
                self.assertEqual(self.request('GET',f'/notifications?_notification_id={row.id}').status_code,200)
                self.assertEqual(self.snapshot(),before)


if __name__=='__main__':
    unittest.main()
