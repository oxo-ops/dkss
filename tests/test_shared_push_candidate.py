"""Real push routes, synthetic DB and mocked transport; no real sends."""
import json
import unittest
from unittest.mock import patch
import test_session_authority_candidate as authority_tests


class SharedPushCandidateTests(unittest.TestCase):
    setUp = authority_tests.SessionAuthorityIntegration.setUp
    login = authority_tests.SessionAuthorityIntegration.login

    def prepare(self):
        from dkss_app.shared_push_candidate import PushAuthorityBinding
        self.app.config.update(SHARED_PUSH_CANDIDATE=True, VAPID_PRIVATE_KEY='synthetic',
            VAPID_PUBLIC_KEY='synthetic', VAPID_SUBJECT='mailto:test@example.invalid')
        PushAuthorityBinding.__table__.create(self.db.engine)
        self.login()
        self.user = self.models.User.query.filter_by(username='operator').one()
        self.data = {'endpoint':'https://push.example.invalid/synthetic',
            'keys':{'p256dh':'synthetic-key','auth':'synthetic-auth'}}

    def subscribe(self):
        return self.client.post('/api/push/subscribe', json=self.data)

    def send(self):
        from dkss_app import notifications_delivery, common
        with patch.object(common, 'webpush') as transport:
            result = notifications_delivery.send_web_push_notification(self.user,
                'PERSONAL TITLE', 'PERSONAL BODY', '/private/customer/123')
        return result, transport

    def test_active_authority_gets_only_generic_payload(self):
        self.prepare(); self.assertEqual(self.subscribe().status_code, 200)
        result, transport = self.send()
        self.assertTrue(result)
        data = json.loads(transport.call_args.kwargs['data'])
        self.assertEqual(data['link'], '/notifications')
        self.assertEqual(data['unread_count'], 0)
        self.assertEqual(data['title'], 'DKSS')
        self.assertNotIn('PERSONAL', transport.call_args.kwargs['data'])
        self.assertNotIn('customer', transport.call_args.kwargs['data'])

    def test_logout_keeps_row_but_stops_delivery(self):
        self.prepare(); self.subscribe(); self.client.post('/logout')
        self.assertEqual(self.models.PushSubscription.query.count(), 1)
        result, transport = self.send()
        self.assertFalse(result); transport.assert_not_called()

    def test_idle_or_absolute_expiry_stops_delivery(self):
        from dkss_app.session_authority_model import SessionAuthority
        for field in ('idle_until', 'absolute_until'):
            with self.subTest(field=field):
                if not hasattr(self, 'user'): self.prepare()
                else: self.client.post('/logout'); self.login()
                self.assertEqual(self.subscribe().status_code, 200)
                self.db.session.execute(self.db.update(SessionAuthority).values(**{field: 0}))
                self.db.session.commit()
                result, transport = self.send()
                self.assertFalse(result); transport.assert_not_called()

    def test_unbound_existing_subscription_is_not_sent(self):
        self.prepare()
        self.app.config['SHARED_PUSH_CANDIDATE'] = False
        self.subscribe()
        self.app.config['SHARED_PUSH_CANDIDATE'] = True
        result, transport = self.send()
        self.assertFalse(result); transport.assert_not_called()

    def test_new_same_user_session_does_not_inherit_binding(self):
        self.prepare(); self.subscribe(); self.client.post('/logout'); self.login()
        result, transport = self.send()
        self.assertFalse(result); transport.assert_not_called()
        self.assertEqual(self.subscribe().status_code, 200)
        self.assertTrue(self.send()[0])

    def test_old_copied_cookie_cannot_rebind(self):
        self.prepare(); self.subscribe()
        cookie = self.client.get_cookie(self.app.config['SESSION_COOKIE_NAME'])
        copied = self.app.test_client()
        copied.set_cookie(self.app.config['SESSION_COOKIE_NAME'], cookie.value)
        self.client.post('/logout')
        self.assertEqual(copied.post('/api/push/subscribe', json=self.data).status_code, 401)
        self.assertFalse(self.send()[0])

    def test_account_endpoint_cannot_be_taken_over(self):
        self.prepare(); self.subscribe()
        row = self.models.PushSubscription.query.one()
        row.owner_identity = 'different-generation'
        self.db.session.commit()
        self.assertEqual(self.subscribe().status_code, 409)
        self.assertFalse(self.send()[0])

    def test_company_mismatch_fails_closed(self):
        self.prepare(); self.subscribe()
        from dkss_app.shared_push_candidate import PushAuthorityBinding
        self.db.session.execute(self.db.update(PushAuthorityBinding).values(company_code='OTHER'))
        self.db.session.commit()
        self.assertFalse(self.send()[0])

    def test_legacy_ownerless_subscription_cannot_be_claimed(self):
        self.prepare(); self.subscribe()
        row = self.models.PushSubscription.query.one()
        row.owner_identity = None
        self.db.session.commit()
        self.assertEqual(self.subscribe().status_code, 409)
        self.assertFalse(self.send()[0])

    def test_reused_row_id_with_new_endpoint_does_not_inherit_binding(self):
        self.prepare(); self.subscribe()
        row = self.models.PushSubscription.query.one()
        row.endpoint = 'https://push.example.invalid/replaced'
        self.db.session.commit()
        self.assertFalse(self.send()[0])

    def test_real_person_switch_blocks_old_delivery_and_endpoint_takeover(self):
        from werkzeug.security import generate_password_hash
        self.prepare(); self.subscribe()
        queued = self.send()[1].call_args.kwargs['data']
        self.db.session.add(self.models.User(company_code='SYNTH', username='second',
            role='user', password=generate_password_hash(self.password),
            last_name='Test', first_name='Second', password_changed_at=self.user.password_changed_at))
        self.db.session.add(self.models.Notification(company_code='SYNTH',
            target_username='operator', target_user='Test', owner_identity=self.user.account_identity,
            title='FIRST_PERSON_SECRET', message='FIRST_PERSON_BODY', read=False,
            created_at='2026-11-15 12:00:00'))
        self.db.session.commit()
        self.assertEqual(self.client.post('/login', data={'company_code':'SYNTH',
            'username':'second', 'password':self.password}).status_code, 302)
        self.assertFalse(self.send()[0])
        self.assertEqual(self.subscribe().status_code, 409)
        # The generic queued click destination resolves only the new viewer's rows.
        response = self.client.get('/api/notifications/recent')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('FIRST_PERSON', response.get_data(as_text=True))
        self.assertEqual(response.json['notifications'], [])
        self.assertNotIn('PERSONAL', queued)
        self.assertEqual(json.loads(queued)['link'], '/notifications')
        # A fresh browser subscription can be bound to B, no shared credentials.
        self.data['endpoint'] += '-new'
        self.assertEqual(self.subscribe().status_code, 200)
        self.user = self.models.User.query.filter_by(username='second').one()
        self.assertTrue(self.send()[0])

    def test_provider_gone_removes_binding(self):
        from types import SimpleNamespace
        from dkss_app import notifications_delivery, common
        from dkss_app.shared_push_candidate import PushAuthorityBinding
        self.prepare(); self.subscribe()
        with patch.object(common, 'webpush', side_effect=common.WebPushException(
                'synthetic', response=SimpleNamespace(status_code=410))):
            self.assertFalse(notifications_delivery.send_web_push_notification(self.user, 'x', 'y'))
        self.assertEqual(self.models.PushSubscription.query.count(), 0)
        self.assertEqual(self.db.session.execute(self.db.select(PushAuthorityBinding)).all(), [])

    def test_unsubscribe_removes_binding(self):
        self.prepare(); self.subscribe()
        self.assertEqual(self.client.post('/api/push/unsubscribe', json=self.data).status_code, 200)
        from dkss_app.shared_push_candidate import PushAuthorityBinding
        self.assertEqual(self.db.session.execute(self.db.select(PushAuthorityBinding)).all(), [])
        self.assertFalse(self.send()[0])

    def test_disabled_candidate_preserves_existing_payload(self):
        self.prepare(); self.app.config['SHARED_PUSH_CANDIDATE'] = False
        self.subscribe()
        result, transport = self.send()
        self.assertTrue(result)
        self.assertEqual(json.loads(transport.call_args.kwargs['data'])['title'], 'PERSONAL TITLE')

    def test_production_flag_fails_closed(self):
        self.prepare(); self.app.config['TESTING'] = False
        self.assertEqual(self.subscribe().status_code, 500)
        self.assertEqual(self.models.PushSubscription.query.count(), 0)

    def test_candidate_table_not_in_normal_metadata(self):
        from dkss_app.shared_push_candidate import PushAuthorityBinding
        self.assertNotIn(PushAuthorityBinding.__tablename__, self.db.metadata.tables)
