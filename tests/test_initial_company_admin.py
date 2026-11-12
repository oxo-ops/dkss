"""Synthetic in-memory coverage for the protected first-admin workflow."""
import unittest
from datetime import datetime
from unittest.mock import patch
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import check_password_hash
from dkss_app import create_app
from dkss_app.extensions import db
from dkss_app.models import Company, User, Driver, AuditLog


class InitialCompanyAdminTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'SECRET_KEY':'synthetic-only', 'TESTING':True,
            'SQLALCHEMY_DATABASE_URI':'sqlite:///:memory:', 'WTF_CSRF_ENABLED':False,
            'RATELIMIT_ENABLED':False, 'MFA_ENABLED':False, 'S3_BUCKET_NAME':''})
        self.ctx = self.app.app_context(); self.ctx.push()
        db.create_all()
        db.session.add_all([Company(company_code='ITC',company_name='ITC',active=True,vehicle_limit=0),
            Company(company_code='FICTION',company_name='架空運送',active=True,vehicle_limit=3)])
        self.actor=User(company_code='ITC',username='itc',last_name='管理',role='itc',
            password='not-a-login-hash',password_changed_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        db.session.add(self.actor);db.session.commit()
        self.company=Company.query.filter_by(company_code='FICTION').one()
        self.url=f'/itc/companies/{self.company.id}/initial-admin'
        self.client=self.app.test_client();self.sign_in()
        self.form={'employee_id':'manager','last_name':'朝日','first_name':'太郎','email_address':'', 'password':'Synthetic9!Only'}

    def sign_in(self, **overrides):
        with self.client.session_transaction() as session:
            session.update(company_code='ITC',username='itc',role='itc',
                account_identity=self.actor.account_identity,password_changed_at=self.actor.password_changed_at)
            session.update(overrides)

    def tearDown(self):
        db.session.remove();db.drop_all();self.ctx.pop()

    def test_create_atomic_admin_and_normal_identity(self):
        self.assertEqual(self.client.get(self.url).status_code,200)
        self.assertEqual(self.client.post(self.url,data=self.form).status_code,302)
        user=User.query.filter_by(company_code='FICTION').one()
        self.assertEqual(user.role,'admin');self.assertTrue(user.account_identity)
        self.assertTrue(check_password_hash(user.password,self.form['password']))
        self.assertEqual(user.password_history_json,'[]');self.assertTrue(user.password_changed_at)
        self.assertFalse(user.email_notify_enabled)
        self.assertEqual(Driver.query.filter_by(company_code='FICTION').one().role,'admin')
        audit=AuditLog.query.filter_by(action='initial_company_admin_created').one()
        self.assertNotIn(self.form['password'],audit.detail)
        self.assertEqual(self.client.post(self.url,data=self.form).status_code,409)

    def test_anonymous_and_forged_session_rejected(self):
        self.client=self.app.test_client()
        self.assertEqual(self.client.post(self.url,data=self.form).status_code,302)
        self.sign_in(account_identity='wrong')
        self.assertEqual(self.client.post(self.url,data=self.form).status_code,302)
        self.assertEqual(User.query.filter_by(company_code='FICTION').count(),0)

    def test_real_role_overrides_claimed_itc_role(self):
        for role in ('admin','user'):
            self.actor.role=role;db.session.commit();self.sign_in(role='itc')
            self.assertEqual(self.client.post(self.url,data=self.form).status_code,403)

    def test_expired_or_locked_account_rejected(self):
        self.sign_in(password_changed_at='stale')
        self.assertEqual(self.client.post(self.url,data=self.form).status_code,302)
        self.actor.password_changed_at='2000-01-01 00:00:00';db.session.commit();self.sign_in()
        self.assertEqual(self.client.post(self.url,data=self.form).status_code,302)
        self.actor.login_locked=True;db.session.commit();self.sign_in()
        self.assertEqual(self.client.post(self.url,data=self.form).status_code,302)

    def test_target_guards(self):
        self.assertEqual(self.client.get('/itc/companies/999/initial-admin').status_code,404)
        itc=Company.query.filter_by(company_code='ITC').one()
        self.assertEqual(self.client.get(f'/itc/companies/{itc.id}/initial-admin').status_code,409)
        self.company.active=False;db.session.commit()
        self.assertEqual(self.client.post(self.url,data=self.form).status_code,409)

    def test_either_user_or_driver_blocks_creation(self):
        for model, fields in ((User,dict(username='other',password='hash',last_name='架空')),
                              (Driver,dict(employee_id='other',name='架空'))):
            row=model(company_code='FICTION',**fields);db.session.add(row);db.session.commit()
            self.assertEqual(self.client.post(self.url,data=self.form).status_code,409)
            db.session.delete(row);db.session.commit()

    def test_tampering_and_invalid_password_never_echo_password(self):
        for values in ({'company_code':'ITC'},{'role':'itc'},{'company_id':'1'},{'password':'short'}):
            form=self.form|values
            response=self.client.post(self.url,data=form)
            self.assertEqual(response.status_code,400)
            self.assertNotIn(form['password'],response.get_data(as_text=True))
        self.assertEqual(User.query.filter_by(company_code='FICTION').count(),0)

    def test_mfa_email_requirement_without_notifications(self):
        self.app.config['MFA_ENABLED']=True
        self.assertEqual(self.client.post(self.url,data=self.form).status_code,400)
        self.assertEqual(self.client.post(self.url,data=self.form|{'email_address':'bad'}).status_code,400)
        self.assertEqual(self.client.post(self.url,data=self.form|{'email_address':'manager@example.invalid'}).status_code,302)

    def test_audit_failure_rolls_back_both_rows(self):
        with patch('dkss_app.initial_admin.add_audit_log',side_effect=SQLAlchemyError('secret-bound-value')):
            response=self.client.post(self.url,data=self.form)
        self.assertEqual(response.status_code,400)
        self.assertNotIn('secret-bound-value',response.get_data(as_text=True))
        self.assertEqual(User.query.filter_by(company_code='FICTION').count(),0)
        self.assertEqual(Driver.query.filter_by(company_code='FICTION').count(),0)

    def test_public_registration_remains_user_and_blocks_bootstrap(self):
        self.assertEqual(self.client.post('/register?company_code=FICTION',data=self.form).status_code,302)
        self.assertEqual(User.query.filter_by(company_code='FICTION').one().role,'user')
        self.assertEqual(self.client.post(self.url,data=self.form).status_code,409)

    def test_csrf_required_and_no_rows_written(self):
        self.app.config['WTF_CSRF_ENABLED']=True
        self.assertEqual(self.client.post(self.url,data=self.form).status_code,400)
        self.assertEqual(User.query.filter_by(company_code='FICTION').count(),0)

    def test_usage_failure_rolls_back_audit_and_accounts(self):
        with patch('dkss_app.initial_admin.update_company_usage_summary',side_effect=SQLAlchemyError('private')):
            self.assertEqual(self.client.post(self.url,data=self.form).status_code,400)
        self.assertEqual(User.query.filter_by(company_code='FICTION').count(),0)
        self.assertEqual(Driver.query.filter_by(company_code='FICTION').count(),0)
        self.assertEqual(AuditLog.query.filter_by(action='initial_company_admin_created').count(),0)

    def test_audit_attributes_itc_actor_not_new_admin(self):
        actor_identity=self.actor.account_identity
        self.client.post(self.url,data=self.form)
        audit=AuditLog.query.filter_by(action='initial_company_admin_created').one()
        self.assertEqual(audit.actor_identity,actor_identity)

    def test_mfa_creation_does_not_send_mail(self):
        self.app.config['MFA_ENABLED']=True
        with patch('dkss_app.auth.send_mfa_code_email') as send:
            response=self.client.post(self.url,data=self.form|{'email_address':'admin@example.invalid'})
        self.assertEqual(response.status_code,302)
        send.assert_not_called()
