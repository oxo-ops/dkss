"""Actual two-connection races, only in the marked disposable CI service."""
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from unittest.mock import patch

from test_bootstrap_postgres import PostgreSQLBootstrapAcceptance
from dkss_app import create_app, initial_admin
from dkss_app.extensions import db
from dkss_app.models import Company, User, Driver


class InitialAdminPostgresRaces(unittest.TestCase):
    setUpClass = classmethod(PostgreSQLBootstrapAcceptance.setUpClass.__func__)

    def setUp(self):
        PostgreSQLBootstrapAcceptance.setUp(self)
        self.app = create_app({'SECRET_KEY':'synthetic-only', 'TESTING':True,
            'SQLALCHEMY_DATABASE_URI':self.url_value, 'WTF_CSRF_ENABLED':False,
            'RATELIMIT_ENABLED':False, 'MFA_ENABLED':False, 'S3_BUCKET_NAME':''})
        with self.app.app_context():
            db.create_all()
            company=Company(company_code='FICTION',company_name='架空運送',active=True,vehicle_limit=3)
            actor=User(company_code='ITC',username='itc',last_name='管理',role='itc',password='unused',
                       password_changed_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            db.session.add_all([company,actor]);db.session.commit()
            self.url=f'/itc/companies/{company.id}/initial-admin'
            self.session=dict(company_code='ITC',username='itc',role='itc',
                              account_identity=actor.account_identity,password_changed_at=actor.password_changed_at)
        self.form=dict(employee_id='manager',last_name='朝日',first_name='太郎',password='Synthetic9!Only')
        self.addCleanup(self.dispose)

    def dispose(self):
        with self.app.app_context():
            db.session.remove();db.engine.dispose()

    def race(self, first_kind, second_kind):
        first_locked=threading.Event();second_attempt=threading.Event()
        second_locked=threading.Event();release=threading.Event()
        context=threading.local(); original=initial_admin.lock_company
        def controlled_lock(*args,**kwargs):
            if context.position == 2:
                second_attempt.set()
            company=original(*args,**kwargs)
            if context.position == 1:
                first_locked.set()
                if not release.wait(10):
                    raise AssertionError('first writer never released')
            else:
                second_locked.set()
            return company
        def submit(position,kind):
            context.position=position
            client=self.app.test_client()
            with client.session_transaction() as session:
                session.update(self.session)
            data=self.form|{'employee_id':f'person{position}'}
            return client.post(self.url if kind=='admin' else '/register?company_code=FICTION',data=data).status_code
        with patch('dkss_app.initial_admin.lock_company',side_effect=controlled_lock), ThreadPoolExecutor(2) as pool:
            one=pool.submit(submit,1,first_kind)
            try:
                self.assertTrue(first_locked.wait(10))
                two=pool.submit(submit,2,second_kind)
                self.assertTrue(second_attempt.wait(10))
                self.assertFalse(second_locked.wait(.3),'second connection bypassed row lock')
            finally:
                release.set()
            codes=(one.result(timeout=15),two.result(timeout=15))
        with self.app.app_context():
            users=User.query.filter_by(company_code='FICTION').all()
            roles=sorted(user.role for user in users)
            self.assertEqual(Driver.query.filter_by(company_code='FICTION').count(),len(users))
        return codes,roles

    def test_public_registration_first_blocks_bootstrap(self):
        self.assertEqual(self.race('public','admin'),((302,409),['user']))

    def test_bootstrap_first_allows_subsequent_ordinary_user(self):
        self.assertEqual(self.race('admin','public'),((302,302),['admin','user']))

    def test_two_bootstraps_create_only_one_admin(self):
        self.assertEqual(self.race('admin','admin'),((302,409),['admin']))
