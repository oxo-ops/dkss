"""Two-connection invitation races in the guarded, disposable CI service only."""
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import patch

import test_bootstrap_postgres as bootstrap
from dkss_app import create_app, company_invites as service
from dkss_app.extensions import db
from dkss_app.models import (Company, User, Driver, CompanyRegistrationInvite as Invite,
                             CompanyRegistrationApplication as Application)


class CompanyInvitePostgresRaces(unittest.TestCase):
    setUpClass = classmethod(bootstrap.PostgreSQLBootstrapAcceptance.setUpClass.__func__)

    def setUp(self):
        bootstrap.PostgreSQLBootstrapAcceptance.setUp(self)
        self.app = create_app({'SECRET_KEY': 'synthetic-only', 'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': self.url_value, 'WTF_CSRF_ENABLED': False,
            'RATELIMIT_ENABLED': False, 'MFA_ENABLED': False, 'S3_BUCKET_NAME': ''})
        with self.app.test_request_context('/'):
            db.create_all()
            db.session.add_all([
                Company(company_code='ITC', company_name='ITC', active=True),
                Company(company_code='FICTION', company_name='架空運送', active=True, vehicle_limit=3)])
            actor = User(company_code='ITC', username='itc', last_name='管理',
                         role='itc', password='unused')
            db.session.add(actor)
            db.session.commit()
            self.actor_id = actor.id
            invite, self.token = service.issue_invite('FICTION', actor)
            self.invite_id = invite.id
        self.addCleanup(self.dispose)

    def dispose(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def form(self, username):
        return {'employee_id': username, 'last_name': '朝日', 'first_name': '太郎',
                'password': 'Synthetic9!Only'}

    def prepare_applications(self):
        with self.app.test_request_context('/'):
            return [service.submit_application(self.token, self.form(username)).id
                    for username in ('one', 'two')]

    def approve(self, app_id):
        return service.approve_application(app_id, db.session.get(User, self.actor_id),
            role='admin', verification_reason='契約時に確認済みの責任者へ電話し本人確認した')

    def revoke(self):
        return service.revoke_invite(self.invite_id, db.session.get(User, self.actor_id))

    def race(self, first, second):
        first_locked = threading.Event()
        second_attempt = threading.Event()
        second_locked = threading.Event()
        release = threading.Event()
        context = threading.local()
        original = service.lock_company

        def controlled_lock(*args, **kwargs):
            if context.position == 2:
                second_attempt.set()
            company = original(*args, **kwargs)
            if context.position == 1:
                first_locked.set()
                if not release.wait(10):
                    raise AssertionError('First writer was never released')
            else:
                second_locked.set()
            return company

        def perform(position, operation):
            context.position = position
            with self.app.test_request_context('/'):
                try:
                    operation()
                    return 200
                except service.InviteError as exc:
                    return exc.status

        with patch('dkss_app.company_invites.lock_company', side_effect=controlled_lock), ThreadPoolExecutor(2) as pool:
            one = pool.submit(perform, 1, first)
            try:
                self.assertTrue(first_locked.wait(10), 'First connection did not acquire lock')
                two = pool.submit(perform, 2, second)
                self.assertTrue(second_attempt.wait(10), 'Second connection did not attempt lock')
                self.assertFalse(second_locked.wait(.3), 'Second connection bypassed company row lock')
            finally:
                release.set()
            codes = (one.result(timeout=15), two.result(timeout=15))
        return codes

    def test_shared_invite_accepts_two_concurrent_people_without_creating_users(self):
        self.assertEqual(self.race(
            lambda: service.submit_application(self.token, self.form('one')),
            lambda: service.submit_application(self.token, self.form('two'))), (200, 200))
        with self.app.app_context():
            self.assertEqual(Application.query.filter_by(status='pending').count(), 2)
            self.assertEqual(User.query.filter_by(company_code='FICTION').count(), 0)
            self.assertIsNone(db.session.get(Invite, self.invite_id).revoked_at)

    def test_duplicate_username_is_not_admitted_twice(self):
        self.assertEqual(self.race(
            lambda: service.submit_application(self.token, self.form('same')),
            lambda: service.submit_application(self.token, self.form('same'))), (200, 409))
        with self.app.app_context():
            self.assertEqual(Application.query.filter_by(status='pending').count(), 1)
            self.assertEqual(User.query.filter_by(company_code='FICTION').count(), 0)

    def test_competing_first_admin_approvals_create_exactly_one(self):
        first, second = self.prepare_applications()
        self.assertEqual(self.race(lambda: self.approve(first), lambda: self.approve(second)), (200, 403))
        with self.app.app_context():
            self.assertEqual(User.query.filter_by(company_code='FICTION', role='admin').count(), 1)
            self.assertEqual(Driver.query.filter_by(company_code='FICTION', role='admin').count(), 1)
            self.assertEqual(Application.query.filter_by(status='approved').count(), 1)
            self.assertEqual(Application.query.filter_by(status='pending').count(), 1)

    def test_revoke_wins_before_approval_and_erases_pending_hashes(self):
        first, _ = self.prepare_applications()
        self.assertEqual(self.race(self.revoke, lambda: self.approve(first)), (200, 409))
        with self.app.app_context():
            self.assertEqual(User.query.filter_by(company_code='FICTION').count(), 0)
            self.assertEqual(Application.query.filter_by(status='revoked', password_hash=None).count(), 2)

    def test_approval_wins_before_revoke_without_deleting_approved_account(self):
        first, _ = self.prepare_applications()
        self.assertEqual(self.race(lambda: self.approve(first), self.revoke), (200, 200))
        with self.app.app_context():
            self.assertEqual(User.query.filter_by(company_code='FICTION', role='admin').count(), 1)
            self.assertEqual(Driver.query.filter_by(company_code='FICTION', role='admin').count(), 1)
            self.assertEqual(Application.query.filter_by(status='approved', password_hash=None).count(), 1)
            self.assertEqual(Application.query.filter_by(status='revoked', password_hash=None).count(), 1)
