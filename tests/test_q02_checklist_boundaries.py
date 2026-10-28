"""Q02 safety checklist authorization and export regression coverage.

Real Flask routes, disposable SQLite and synthetic users only. Candidate lists
select notification recipients; they do not restrict an allow_general slot.
Does not validate PostgreSQL locking, browser CSRF or live deployment.
"""
from identity_fixture import identity_for, PersonSelectionClient
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class Q02ChecklistBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='dkss-q02-checklist-')
        from dkss_app import create_app, models
        from dkss_app.extensions import db, limiter
        cls.db, cls.models = db, models
        env = {'SECRET_KEY': 'q02-checklist-test-only', 'RENDER': '',
               'DATABASE_URL': 'sqlite:///' + str(Path(cls.temp.name) / 'test.db'),
               'OPENAI_API_KEY': '', 'SMTP_HOST': '', 'S3_BUCKET_NAME': '',
               'VAPID_PRIVATE_KEY': '', 'VAPID_PUBLIC_KEY': '',
               'AWS_EC2_METADATA_DISABLED': 'true'}
        with patch.dict(os.environ, env):
            cls.app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False})
        cls.app.test_client_class = PersonSelectionClient
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
        for company in ('A', 'B'):
            self.db.session.add(m.Company(company_code=company, company_name=company, active=True))
            for username, role in [('admin', 'admin'), ('checker', 'user'),
                                   ('reviewer', 'user'), ('outsider', 'user'), ('support', 'itc')]:
                self.db.session.add(m.User(company_code=company, username=username, role=role,
                    password='unused', last_name='Test', first_name=username,
                    password_changed_at='2026-10-27 10:00:00'))
        self.db.session.commit()
        self.client = self.app.test_client()
        self.login('admin')

    def tearDown(self):
        self.db.session.remove()
        self.ctx.pop()

    def login(self, username, company='A'):
        user = self.models.User.query.filter_by(company_code=company, username=username).one()
        with self.client.session_transaction() as session:
            session.clear()
            session.update(account_identity=identity_for(company, username, app=(self.client).application), company_code=company, username=username, role=user.role,
                name='Test ' + username, password_changed_at=user.password_changed_at)

    def request(self, method, url, **kwargs):
        response = self.client.open(url, method=method, **kwargs)
        self.addCleanup(response.close)
        return response

    def record(self, approvals=(False, False), candidates=None, company='A'):
        m = self.models
        items = [{'item_type': 'check', 'category': '点検', 'content': company + '-CHECK-SECRET',
                  'input_type': 'text', 'answer_required': False}]
        items += [{'item_type': 'approval', 'approval_label': '確認' + str(i),
                   'approval_allow_general': allow} for i, allow in enumerate(approvals)]
        checklist = m.Checklist(company_code=company, name=company + '-CHECKLIST-SECRET',
            target='安全管理', frequency_unit='day', display_type='month', active=True,
            items_json=json.dumps(items, ensure_ascii=False))
        self.db.session.add(checklist)
        self.db.session.commit()
        self.login('checker', company)
        before = {r.id for r in m.ChecklistResult.query.all()}
        response = self.request('POST', f'/safety/checklists/{checklist.id}/new',
            data={'answer_0': company + '-ANSWER-SECRET', **(candidates or {})})
        self.assertEqual(response.status_code, 302)
        rows = [r for r in m.ChecklistResult.query.all() if r.id not in before]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, '承認待ち')
        self.login('admin')
        return rows[0]

    def url(self, row, suffix=''):
        return f'/safety/checklist-results/{row.id}' + suffix

    def snapshot(self):
        self.db.session.expire_all()
        return tuple(tuple(tuple(getattr(row, col.name) for col in model.__table__.columns)
                           for row in model.query.order_by(model.id).all())
                     for model in (self.models.ChecklistResult, self.models.ChecklistEvent,
                                   self.models.Notification, self.models.AuditLog))

    def approve(self, row, index=0, **data):
        return self.request('POST', self.url(row, f'/approve/{index}'), data=data)

    def reject(self, row, reason='再確認'):
        return self.request('POST', self.url(row, '/reject'), data={'reject_reason': reason})

    def assert_readable(self, row):
        self.assertEqual(self.request('GET', self.url(row)).status_code, 200)
        response = self.request('GET', self.url(row, '/excel'))
        self.assertEqual(response.status_code, 200)
        from openpyxl import load_workbook
        book = load_workbook(io.BytesIO(response.data), read_only=True)
        try:
            cells = [str(value) for sheet in book for values in sheet.values for value in values]
            self.assertIn(row.company_code + '-ANSWER-SECRET', cells)
            self.assertNotIn(('B' if row.company_code == 'A' else 'A') + '-ANSWER-SECRET', cells)
        finally:
            book.close()

    def test_foreign_same_username_cannot_read_detail_or_excel(self):
        row = self.record(company='B')
        before = self.snapshot()
        for suffix in ('', '/excel', '/edit'):
            with self.subTest(suffix=suffix):
                response = self.request('GET', self.url(row, suffix))
                self.assertEqual(response.status_code, 302)
                self.assertNotIn(b'B-ANSWER-SECRET', response.data)
        self.assertEqual(self.snapshot(), before)

    def test_foreign_same_username_cannot_approve_reject_edit_or_delete(self):
        row = self.record(company='B')
        before = self.snapshot()
        for suffix, data in [('/approve/0', {}), ('/reject', {'reject_reason': 'bad'}),
                             ('/edit', {'answer_0': 'bad'}), ('/delete', {})]:
            with self.subTest(suffix=suffix):
                self.assertEqual(self.request('POST', self.url(row, suffix), data=data).status_code, 302)
                self.assertEqual(self.snapshot(), before)

    def test_unrelated_user_cannot_read_admin_only_result(self):
        row = self.record()
        self.login('outsider')
        before = self.snapshot()
        for suffix in ('', '/excel', '/edit'):
            self.assertEqual(self.request('GET', self.url(row, suffix)).status_code, 302)
        self.assertEqual(self.snapshot(), before)

    def test_unrelated_user_cannot_approve_reject_or_manage_admin_only_result(self):
        row = self.record()
        self.login('outsider')
        before = self.snapshot()
        for suffix in ('/approve/0', '/reject', '/edit', '/delete'):
            self.assertEqual(self.request('POST', self.url(row, suffix),
                data={'reject_reason': 'bad', 'answer_0': 'bad'}).status_code, 302)
            self.assertEqual(self.snapshot(), before)

    def test_author_can_read_excel_but_cannot_approve_admin_only_slot(self):
        row = self.record()
        self.login('checker')
        self.assert_readable(row)
        before = self.snapshot()
        self.approve(row)
        self.reject(row)
        self.assertEqual(self.snapshot(), before)

    def test_admin_approval_uses_server_actor_and_preserves_other_tenant(self):
        row = self.record((False,))
        foreign = self.record((False,), company='B')
        foreign_before = foreign.approvals_json
        self.approve(row, company_code='B', username='reviewer', approved_by_username='reviewer',
                     status='差し戻し', approval_index='99')
        self.db.session.refresh(row)
        self.db.session.refresh(foreign)
        self.assertEqual(row.status, '承認済み')
        self.assertEqual(json.loads(row.approvals_json)[0]['approved_by_username'], 'admin')
        self.assertEqual(foreign.approvals_json, foreign_before)
        event = self.models.ChecklistEvent.query.filter_by(result_id=row.id, event_type='承認').one()
        self.assertEqual((event.company_code, event.actor_username), ('A', 'admin'))

    def test_admin_cannot_skip_approval_order(self):
        row = self.record()
        before = self.snapshot()
        self.approve(row, 1)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_approval_index_does_not_write(self):
        row = self.record()
        before = self.snapshot()
        self.approve(row, 999)
        self.assertEqual(self.snapshot(), before)

    def test_repeated_partial_approval_does_not_duplicate_events_or_notices(self):
        row = self.record(candidates={'approval_notify_users_1': 'admin'})
        self.approve(row)
        before = self.snapshot()
        self.approve(row)
        self.assertEqual(self.snapshot(), before)

    def test_completed_result_rejects_approval_and_rejection_replays(self):
        row = self.record((False,))
        self.approve(row)
        self.db.session.refresh(row)
        self.assertEqual(row.status, '承認済み')
        before = self.snapshot()
        self.approve(row)
        self.reject(row)
        self.assertEqual(self.snapshot(), before)

    def test_general_slot_allows_user_without_candidate_selection(self):
        row = self.record((True,))
        self.login('outsider')
        self.assert_readable(row)
        self.approve(row)
        self.db.session.refresh(row)
        self.assertEqual(row.status, '承認済み')
        self.assertEqual(row.approved_by_username, 'outsider')

    def test_future_general_candidate_can_read_but_cannot_approve_out_of_order(self):
        row = self.record((False, True), {'approval_notify_users_1': 'reviewer'})
        self.login('reviewer')
        self.assert_readable(row)
        before = self.snapshot()
        self.approve(row, 1)
        self.reject(row)
        self.assertEqual(self.snapshot(), before)

    def test_general_approver_does_not_gain_edit_or_delete_rights(self):
        row = self.record((True,))
        self.login('reviewer')
        before = self.snapshot()
        for method, suffix in [('GET', '/edit'), ('POST', '/edit'), ('POST', '/delete')]:
            self.assertEqual(self.request(method, self.url(row, suffix), data={'answer_0': 'bad'}).status_code, 302)
            self.assertEqual(self.snapshot(), before)

    def test_revoked_admin_cannot_submit_stale_approval_or_rejection(self):
        row = self.record()
        self.assert_readable(row)
        self.models.User.query.filter_by(company_code='A', username='admin').one().role = 'user'
        self.db.session.commit()
        before = self.snapshot()
        self.approve(row)
        self.reject(row)
        self.assertEqual(self.snapshot(), before)

    def test_itc_can_read_but_cannot_approve_admin_or_general_slots(self):
        for allowed in (False, True):
            row = self.record((allowed,))
            self.login('support')
            self.assert_readable(row)
            before = self.snapshot()
            self.approve(row)
            self.reject(row)
            self.assertEqual(self.snapshot(), before)

    def test_rejection_resets_partial_approval_and_replay_has_no_effect(self):
        row = self.record()
        self.approve(row)
        self.reject(row)
        self.db.session.refresh(row)
        self.assertEqual(row.status, '差し戻し')
        self.assertEqual(row.reject_reason, '再確認')
        self.assertTrue(all(not item.get('approved_by_username') for item in json.loads(row.approvals_json)))
        event = self.models.ChecklistEvent.query.filter_by(result_id=row.id, event_type='差し戻し').one()
        self.assertEqual(event.actor_username, 'admin')
        before = self.snapshot()
        self.reject(row)
        self.approve(row)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_reject_reason_preserves_approval_and_has_no_side_effects(self):
        row = self.record()
        self.approve(row)
        before = self.snapshot()
        for reason in ('   ', 'x' * 5001):
            response = self.request('POST', self.url(row, '/reject'),
                data={'reject_reason': reason}, headers={'X-DKSS-Final-Submit': '1'})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(self.snapshot(), before)

    def test_deleted_account_cannot_use_open_approval_page(self):
        row = self.record((True,))
        self.login('reviewer')
        self.assert_readable(row)
        self.db.session.delete(self.models.User.query.filter_by(company_code='A', username='reviewer').one())
        self.db.session.commit()
        before = self.snapshot()
        self.approve(row)
        self.reject(row)
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
