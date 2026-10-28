"""Q02: ITC news mutation, recipient fan-out and attachment isolation.

Real Flask/temporary SQLite/local synthetic files. External notification
dispatch alone is mocked and recorded. No real mail, push, S3 or browser.
"""
from identity_fixture import identity_for
from io import BytesIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_q02_access_revocation as fixtures


class Q02NewsBoundaryTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.Q02AccessRevocationTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.Q02AccessRevocationTests.tearDownClass.__func__)
    login = fixtures.Q02AccessRevocationTests.login
    user = fixtures.Q02AccessRevocationTests.user

    def setUp(self):
        fixtures.Q02AccessRevocationTests.setUp(self)
        from dkss_app import notifications_delivery
        self.dispatch = self.enterContext(patch.object(notifications_delivery, 'dispatch_external_notification'))
        self.app.config['UPLOAD_FOLDER'] = str(self.files / 'uploads')
        m = self.models
        self.ids = {}
        for company in ('A', 'B'):
            m.User.query.filter_by(company_code=company, username='same').one().role = 'itc'
            for name, role, office in [('reader', 'user', 'east'),
                                       ('east-admin', 'admin', 'east'),
                                       ('west-admin', 'admin', 'west')]:
                self.db.session.add(m.User(company_code=company, username=name, role=role,
                    office=office, password='unused', last_name=company + '_' + name,
                    password_changed_at='2026-10-27 10:00:00'))
            self.db.session.add(m.Office(company_code=company, name='east'))
            self.db.session.add(m.Office(company_code=company, name=company + '-only-office'))
            news = m.News(company_code=company, title=company + '_PRIVATE_NEWS',
                message=company + '_PRIVATE_BODY', target_type='all', target_value='',
                files_json=json.dumps(['evidence.pdf']))
            self.db.session.add(news)
            self.db.session.flush()
            self.ids[company] = news.id
        self.db.session.add(m.User(company_code='B', username='B-only-user', role='user',
            password='unused', last_name='B_ONLY_USER', password_changed_at='2026-10-27 10:00:00'))
        self.db.session.commit()

    def tearDown(self):
        self.app.config['WTF_CSRF_ENABLED'] = False
        fixtures.Q02AccessRevocationTests.tearDown(self)

    def actor(self, company='A'):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(account_identity=identity_for(company, 'same', app=(self.client).application), company_code=company, username='same', role='itc', office='east',
                           password_changed_at='2026-10-27 10:00:00')

    def request(self, method, path, **kwargs):
        self.db.session.remove()
        self.ctx.pop()
        try:
            response = self.client.open(path, method=method, **kwargs)
        finally:
            self.ctx = self.app.app_context()
            self.ctx.push()
        self.addCleanup(response.close)
        return response

    def edit(self, company='A'):
        return f'/itc/news/{self.ids[company]}/edit'

    def delete(self, company='A'):
        return f'/itc/news/{self.ids[company]}/delete'

    def form(self, kind='all', value='', title='Synthetic new news'):
        return {'title': title, 'message': 'Synthetic text without mentions',
                'target_type': kind, 'target_value': value, 'company_code': 'B',
                'created_by': 'forged', 'username': 'B-only-user'}

    def db_rows(self, company=None):
        self.db.session.expire_all()
        result = []
        for model in (self.models.News, self.models.Notification, self.models.AuditLog):
            query = model.query
            if company:
                query = query.filter_by(company_code=company)
            result.append(tuple(tuple(getattr(row, col.name) for col in model.__table__.columns)
                                for row in query.order_by(*model.__table__.primary_key.columns).all()))
        return result

    def files_snapshot(self, company=None):
        root = self.files / 'uploads'
        if company:
            root = root / company
        return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*') if path.is_file()}

    def snapshot(self):
        return self.db_rows(), self.files_snapshot()

    def test_itc_recipient_fanout_uses_current_company_for_every_target_kind(self):
        before_b = self.db_rows('B'), self.files_snapshot('B')
        cases = [('all', '', {'same', 'reader', 'east-admin', 'west-admin'}),
                 ('company', 'A', {'same', 'reader', 'east-admin', 'west-admin'}),
                 ('admins', '', {'east-admin', 'west-admin'}),
                 ('office', 'east', {'same', 'reader', 'east-admin'}),
                 ('user', 'reader', {'reader'})]
        for index, (kind, value, expected) in enumerate(cases):
            with self.subTest(kind=kind):
                self.actor()
                self.dispatch.reset_mock()
                title = 'Synthetic fanout ' + str(index)
                response = self.request('POST', '/itc/news/new', data=self.form(kind, value, title))
                self.assertEqual((response.status_code, response.location), (302, '/itc'))
                news = self.models.News.query.filter_by(title=title).one()
                self.assertEqual((news.company_code, news.target_type, news.target_value), ('A', kind, value))
                notices = self.models.Notification.query.filter_by(title=title).all()
                self.assertEqual({(row.company_code, row.target_username) for row in notices},
                                 {('A', name) for name in expected})
                self.assertEqual(len(notices), len(expected))
                # Actual delivery is disabled; prove every attempted call has the
                # matching company and resolved user, not the forged POST actor.
                self.assertEqual({(call.args[0].company_code, call.args[0].username)
                                  for call in self.dispatch.call_args_list},
                                 {('A', name) for name in expected})
                self.assertEqual(self.dispatch.call_count, len(expected))
                audit = self.models.AuditLog.query.filter_by(action='news_created', target_id=str(news.id)).one()
                self.assertEqual((audit.company_code, audit.username), ('A', 'same'))
                self.assertEqual((self.db_rows('B'), self.files_snapshot('B')), before_b)

    def test_foreign_recipient_values_are_rejected_before_file_save_or_dispatch(self):
        from dkss_app import storage
        before = self.snapshot()
        with patch.object(storage, 'save_uploaded_file') as save:
            for path in ('/itc/news/new', self.edit()):
                for kind, value in [('company', 'B'), ('office', 'B-only-office'), ('user', 'B-only-user')]:
                    with self.subTest(path=path, kind=kind):
                        data = self.form(kind, value)
                        data['files'] = (BytesIO(b'%PDF-1.4 synthetic'), 'not-saved.pdf')
                        response = self.request('POST', path, data=data)
                        self.assertEqual(response.status_code, 403)
                        self.assertEqual(self.snapshot(), before)
                        save.assert_not_called()
                        self.dispatch.assert_not_called()

    def test_foreign_same_username_cannot_read_edit_or_delete_another_company_news(self):
        self.actor('B')
        response = self.request('GET', self.edit('B'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('B_PRIVATE_NEWS', response.get_data(as_text=True))
        before = self.snapshot()
        for method, path, kwargs in [('GET', self.edit(), {}),
                                    ('POST', self.edit(), {'data': self.form()}),
                                    ('POST', self.delete(), {})]:
            with self.subTest(method=method, path=path):
                response = self.request(method, path, **kwargs)
                self.assertEqual((response.status_code, response.location), (302, '/itc'))
                self.assertNotIn('A_PRIVATE_BODY', response.get_data(as_text=True))
                self.assertEqual(self.snapshot(), before)
                self.dispatch.assert_not_called()

    def test_itc_demotion_after_form_open_blocks_new_edit_delete_with_old_cookie(self):
        self.assertEqual(self.request('GET', '/itc/news/new').status_code, 200)
        self.assertEqual(self.request('GET', self.edit()).status_code, 200)
        self.user().role = 'admin'
        self.db.session.commit()
        before = self.snapshot()
        for path in ('/itc/news/new', self.edit(), self.delete()):
            self.actor()
            response = self.request('POST', path, data=self.form())
            self.assertEqual((response.status_code, response.location), (302, '/'))
            self.assertEqual(self.snapshot(), before)
            self.dispatch.assert_not_called()

    def test_locked_itc_cannot_reuse_open_forms_or_delete_attachment(self):
        self.assertEqual(self.request('GET', self.edit()).status_code, 200)
        self.user().login_locked = True
        self.db.session.commit()
        before = self.snapshot()
        for path in ('/itc/news/new', self.edit(), self.delete()):
            self.actor()
            response = self.request('POST', path, data=self.form())
            self.assertEqual((response.status_code, response.location), (302, '/login'))
            self.assertEqual(self.snapshot(), before)
            self.dispatch.assert_not_called()

    def test_own_edit_delete_and_local_cleanup_preserve_foreign_same_filename(self):
        before_b = self.db_rows('B'), self.files_snapshot('B')
        response = self.request('POST', self.edit(), data=self.form('user', 'reader', 'Own revised news'))
        self.assertEqual((response.status_code, response.location), (302, '/itc'))
        own = self.db.session.get(self.models.News, self.ids['A'])
        self.assertEqual((own.company_code, own.title, own.target_value), ('A', 'Own revised news', 'reader'))
        own_file = Path(self.app.config['UPLOAD_FOLDER']) / 'A/evidence.pdf'
        self.assertTrue(own_file.is_file())
        response = self.request('POST', self.delete())
        self.assertEqual((response.status_code, response.location), (302, '/itc'))
        self.assertIsNone(self.db.session.get(self.models.News, self.ids['A']))
        self.assertFalse(own_file.exists())
        self.assertEqual((self.db_rows('B'), self.files_snapshot('B')), before_b)
        for action in ('news_updated', 'news_deleted'):
            audit = self.models.AuditLog.query.filter_by(action=action, target_id=str(self.ids['A'])).one()
            self.assertEqual((audit.company_code, audit.username), ('A', 'same'))
        self.dispatch.assert_not_called()

    def test_csrf_missing_or_foreign_token_blocks_news_mutations_and_file_cleanup(self):
        self.app.config['WTF_CSRF_ENABLED'] = True
        other = self.app.test_client()
        response = other.get('/login/csrf-token')
        self.addCleanup(response.close)
        wrong = response.json['csrf_token']
        valid = self.request('GET', '/login/csrf-token').json['csrf_token']
        before = self.snapshot()
        for path in ('/itc/news/new', self.edit(), self.delete()):
            for token in (None, wrong):
                with self.subTest(path=path, token='missing' if token is None else 'foreign'):
                    data = self.form()
                    if token:
                        data['csrf_token'] = token
                    self.assertEqual(self.request('POST', path, data=data).status_code, 400)
                    self.assertEqual(self.snapshot(), before)
                    self.dispatch.assert_not_called()
        response = self.request('POST', self.delete(), data={'csrf_token': valid})
        self.assertEqual((response.status_code, response.location), (302, '/itc'))
        self.assertIsNone(self.db.session.get(self.models.News, self.ids['A']))


if __name__ == '__main__':
    unittest.main()
