"""Q02: company, live office and role boundaries of recipient directories.

Real Flask requests and disposable SQLite. Sessions are seeded test cookies;
this is not a browser login, delivery test or PostgreSQL concurrency test.
"""
import json
import unittest

import test_q02_access_revocation as fixtures


class Q02DirectoryBoundaryTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.Q02AccessRevocationTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.Q02AccessRevocationTests.tearDownClass.__func__)
    tearDown = fixtures.Q02AccessRevocationTests.tearDown
    login = fixtures.Q02AccessRevocationTests.login
    user = fixtures.Q02AccessRevocationTests.user

    def setUp(self):
        fixtures.Q02AccessRevocationTests.setUp(self)
        m = self.models
        self.user().role = 'user'
        for company in ('A', 'B'):
            self.db.session.add_all([
                m.Office(company_code=company, name='east'),
                m.Office(company_code=company, name='west'),
                m.Office(company_code=company, name=company + '_ONLY_OFFICE'),
            ])
            for name, role, office in [('approver', 'admin', 'east'),
                                       ('west-approver', 'admin', 'west'),
                                       ('reader', 'user', 'east'),
                                       ('support', 'itc', 'east')]:
                self.db.session.add(m.User(
                    company_code=company, username=name, role=role, office=office,
                    password='unused', last_name=company + '_ONLY_' + name,
                    password_changed_at='2026-10-27 10:00:00'))
        self.db.session.commit()

    def actor(self, company='A', role='admin', office='east'):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(company_code=company, username='same', role=role, office=office,
                           password_changed_at='2026-10-27 10:00:00')

    def request(self, path, **args):
        response = self.client.get(path, query_string=args)
        self.addCleanup(response.close)
        return response

    def directory(self, path, key, **args):
        response = self.request(path, **args)
        self.assertEqual(response.status_code, 200)
        return response.json[key]

    def snapshot(self):
        self.db.session.expire_all()
        models = (self.models.Company, self.models.User, self.models.Office,
                  self.models.Manual, self.models.Notification)
        return [tuple(tuple(getattr(row, col.name) for col in model.__table__.columns)
                      for row in model.query.order_by(*model.__table__.primary_key.columns).all())
                for model in models]

    def test_general_user_approval_candidates_ignore_forged_company_office_and_role(self):
        before = self.snapshot()
        self.actor(role='itc', office='west')
        rows = self.directory('/api/approval-candidates', 'users',
            company_code='B', office='west', role='itc', username='support')
        self.assertEqual(rows, [{'name': 'A_ONLY_approver', 'username': 'approver', 'office': 'east'}])
        with self.client.session_transaction() as session:
            self.assertEqual((session['role'], session['office']), ('user', 'east'))
        self.assertEqual(self.snapshot(), before)

    def test_office_move_and_unassignment_refresh_candidates_despite_old_cookie(self):
        self.assertEqual(self.directory('/api/approval-candidates', 'users')[0]['username'], 'approver')
        for office, expected in [('west', ['west-approver']), ('', [])]:
            with self.subTest(office=office):
                self.user().office = office
                self.db.session.commit()
                before = self.snapshot()
                self.actor(office='east')
                rows = self.directory('/api/approval-candidates', 'users', office='east', company_code='B')
                self.assertEqual([row['username'] for row in rows], expected)
                self.assertEqual(self.snapshot(), before)

    def test_candidate_demotion_is_reflected_without_using_foreign_same_username(self):
        self.assertEqual(len(self.directory('/api/approval-candidates', 'users')), 1)
        candidate = self.models.User.query.filter_by(company_code='A', username='approver').one()
        candidate.role = 'user'
        self.db.session.commit()
        before = self.snapshot()
        self.assertEqual(self.directory('/api/approval-candidates', 'users'), [])
        self.assertEqual(self.models.User.query.filter_by(company_code='B', username='approver').one().role, 'admin')
        self.assertEqual(self.snapshot(), before)

    def test_itc_company_office_and_user_targets_stay_in_authenticated_company(self):
        self.user().role = 'itc'
        self.models.User.query.filter_by(company_code='B', username='same').one().role = 'itc'
        self.db.session.commit()
        before = self.snapshot()
        for company, other in [('A', 'B'), ('B', 'A')]:
            self.actor(company)
            for kind, expected in [('company', {company}),
                                    ('office', {'east', 'west', company + '_ONLY_OFFICE'}),
                                    ('user', {'approver', 'west-approver', 'reader'})]:
                with self.subTest(company=company, kind=kind):
                    rows = self.directory('/api/news-targets', 'results', type=kind, company_code=other)
                    self.assertEqual({row['id'] for row in rows}, expected)
                    self.assertNotIn(other + '_ONLY', json.dumps(rows))
                    self.assertEqual(self.directory('/api/news-targets', 'results',
                        type=kind, q=other + '_ONLY', company_code=other), [])
                    self.assertEqual(self.snapshot(), before)

    def test_revoked_itc_cannot_reuse_target_search_with_stale_role(self):
        self.user().role = 'itc'
        self.db.session.commit()
        self.assertTrue(self.directory('/api/news-targets', 'results', type='user'))
        self.user().role = 'admin'
        self.db.session.commit()
        before = self.snapshot()
        for kind in ('company', 'office', 'user'):
            with self.subTest(kind=kind):
                self.actor(role='itc')
                response = self.request('/api/news-targets', type=kind, company_code='B')
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json, {'results': []})
                self.assertEqual(self.snapshot(), before)

    def test_mentions_exact_lookup_and_approval_scopes_do_not_cross_company(self):
        before = self.snapshot()
        exact = self.directory('/api/mention-users', 'users', q='approver',
                               exact_username='1', company_code='B')
        self.assertEqual(exact, [{'name': 'A_ONLY_approver', 'username': 'approver',
                                 'office': 'east', 'role': 'admin'}])
        for scope, expected in [('admin', {'approver', 'west-approver'}),
                                 ('admin_user', {'approver', 'west-approver', 'reader'}),
                                 ('', {'approver', 'west-approver', 'reader', 'support'})]:
            with self.subTest(scope=scope):
                rows = self.directory('/api/mention-users', 'users', q='A_ONLY',
                                      approval_scope=scope, company_code='B')
                self.assertEqual({row['username'] for row in rows}, expected)
                self.assertNotIn('B_ONLY', json.dumps(rows))
        self.assertEqual(self.directory('/api/mention-users', 'users', q='B_ONLY', company_code='B'), [])
        self.assertEqual(self.snapshot(), before)

    def test_locked_itc_loses_all_directory_access_with_cookie_restored_for_each_url(self):
        self.user().role = 'itc'
        self.db.session.commit()
        paths = [('/api/approval-candidates', 'users', {}),
                 ('/api/mention-users', 'users', {'q': 'approver'}),
                 ('/api/news-targets', 'results', {'type': 'user'})]
        for path, key, args in paths:
            self.assertTrue(self.directory(path, key, **args))
        self.user().login_locked = True
        self.db.session.commit()
        before = self.snapshot()
        for path, _, args in paths:
            with self.subTest(path=path):
                self.actor(role='itc')
                response = self.request(path, **args)
                self.assertEqual(response.status_code, 401)
                self.assertNotIn('A_ONLY', response.get_data(as_text=True))
                self.assertNotIn('B_ONLY', response.get_data(as_text=True))
                with self.client.session_transaction() as session:
                    self.assertNotIn('username', session)
                self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
