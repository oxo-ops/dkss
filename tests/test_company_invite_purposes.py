"""Two reusable invitations: isolated synthetic data only."""
import unittest
import test_company_invites as acceptance
from dkss_app import company_invites as service
from dkss_app.extensions import db
from dkss_app.models import CompanyRegistrationApplication as Application, User


class TwoInvitePurposes(unittest.TestCase):
    setUp = acceptance.CompanyInviteAcceptance.setUp
    tearDown = acceptance.CompanyInviteAcceptance.tearDown
    make_user = acceptance.CompanyInviteAcceptance.make_user
    sign_in = acceptance.CompanyInviteAcceptance.sign_in
    issue = acceptance.CompanyInviteAcceptance.issue
    submit = acceptance.CompanyInviteAcceptance.submit
    approve = acceptance.CompanyInviteAcceptance.approve
    def typed(self, purpose):
        with self.app.test_request_context():
            return service.issue_invite('FICTION', self.actor, purpose=purpose)

    def test_two_types_reusable_independent_rotation(self):
        _, admin = self.typed('admin')
        _, general = self.typed('user')
        admins = [self.submit(admin, 'admin' + str(i)) for i in range(2)]
        users = [self.submit(general, 'user' + str(i)) for i in range(2)]
        self.typed('user')
        self.assertEqual([db.session.get(Application, x.id).status for x in admins], ['pending'] * 2)
        self.assertEqual([db.session.get(Application, x.id).status for x in users], ['revoked'] * 2)
        with self.app.test_request_context():
            service.validate_invite(admin)
            with self.assertRaises(service.InviteError):
                service.validate_invite(general)

    def test_general_cannot_bootstrap_or_escalate(self):
        _, token = self.typed('user')
        row = self.submit(token)
        self.assertEqual(self.approve(row).status_code, 403)
        self.assertIsNone(User.query.filter_by(company_code='FICTION', username='manager').first())
        manager = self.make_user('FICTION', 'approved_manager', 'admin')
        self.sign_in(manager)
        self.assertEqual(self.client.post('/master/registration', data=dict(action='approve', application_id=row.id, role='admin')).status_code, 403)
        self.assertLess(self.client.post('/master/registration', data=dict(action='approve', application_id=row.id, role='user')).status_code, 400)

    def test_multiple_admins_need_confirmed_first_admin_then_company(self):
        _, token = self.typed('admin')
        first, second = self.submit(token, 'first'), self.submit(token, 'second')
        self.assertLess(self.approve(first).status_code, 400)
        self.assertEqual(self.approve(second).status_code, 403)
        self.sign_in(User.query.filter_by(company_code='FICTION', username='first').one())
        self.assertLess(self.client.post('/master/registration', data=dict(action='approve', application_id=second.id, role='admin')).status_code, 400)

    def test_ui_two_buttons_and_untrusted_kind_rejected(self):
        body = self.client.get(self.url).get_data(as_text=True)
        self.assertIn('管理者用登録URLを発行', body)
        self.assertIn('一般利用者用登録URLを発行', body)
        self.assertEqual(self.client.post(self.url, data=dict(action='issue', purpose='legacy')).status_code, 400)
        self.assertEqual(self.client.post(self.url, data=dict(action='issue', purpose='itc')).status_code, 400)

    def test_rotation_preserves_legacy_pending(self):
        _, old = self.issue()
        row = self.submit(old, 'legacy')
        self.typed('admin')
        self.typed('user')
        self.assertEqual(db.session.get(Application, row.id).status, 'pending')

    def test_additive_migration_is_idempotent_and_preserves_old_rows(self):
        from sqlalchemy import text, inspect
        db.session.remove()
        with db.engine.begin() as connection:
            connection.execute(text("DROP TABLE company_registration_application"))
            connection.execute(text("DROP TABLE company_registration_invite"))
            connection.execute(text("CREATE TABLE company_registration_invite (id INTEGER PRIMARY KEY, company_code VARCHAR(50), token_hash VARCHAR(64), created_at DATETIME, expires_at DATETIME, revoked_at DATETIME, created_by VARCHAR(36))"))
            connection.execute(text("INSERT INTO company_registration_invite (id, company_code, token_hash) VALUES (1, 'FICTION', 'synthetic')"))
        service.upgrade_invite_schema()
        service.upgrade_invite_schema()
        with db.engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT purpose FROM company_registration_invite WHERE id=1")).scalar(), 'legacy')
            self.assertIn('purpose', {c['name'] for c in inspect(connection).get_columns('company_registration_invite')})

    def test_expire_or_revoke_one_type_does_not_affect_other(self):
        from datetime import datetime, timedelta
        admin, admin_token = self.typed('admin')
        general, general_token = self.typed('user')
        admin.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()
        with self.app.test_request_context():
            with self.assertRaises(service.InviteError):
                service.validate_invite(admin_token)
            service.validate_invite(general_token)
            service.revoke_invite(general.id, self.actor)
            with self.assertRaises(service.InviteError):
                service.validate_invite(general_token)

    def test_admin_application_cannot_be_approved_as_general(self):
        self.make_user('FICTION', 'manager', 'admin')
        self.sign_in(User.query.filter_by(company_code='FICTION', username='manager').one())
        _, token = self.typed('admin')
        row = self.submit(token, 'candidate')
        response = self.client.post('/master/registration', data=dict(action='approve', application_id=row.id, role='user'))
        self.assertEqual(response.status_code, 403)
