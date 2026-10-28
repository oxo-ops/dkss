"""Q02: maintenance knowledge authority and original-document boundaries.

Synthetic data, real Flask requests, disposable SQLite. No external AI,
catalogue download, delivery, browser or PostgreSQL verification.
"""
import hashlib
import json
import unittest

import test_q02_access_revocation as fixtures
from test_inspection_document_ai import pdf_bytes


class Q02KnowledgeBoundaryTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.Q02AccessRevocationTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.Q02AccessRevocationTests.tearDownClass.__func__)
    login = fixtures.Q02AccessRevocationTests.login
    user = fixtures.Q02AccessRevocationTests.user

    def setUp(self):
        fixtures.Q02AccessRevocationTests.setUp(self)
        from dkss_app.maintenance_knowledge_import_models import get_models
        self.Document, self.Extraction = get_models(self.db)
        self.originals = {}
        self.ids = {}
        self.document_ids = {'A': '11111111-1111-4111-8111-111111111111',
                             'B': '22222222-2222-4222-8222-222222222222'}
        for company, width in [('A', 595), ('B', 612)]:
            source = pdf_bytes(width)
            self.originals[company] = source
            row = self.models.VehicleMaintenanceKnowledge(
                company_code=company, title=company + '_PRIVATE_KNOWLEDGE',
                part_name='Synthetic part', conditions='Synthetic condition',
                guidance=company + '_PRIVATE_GUIDANCE', source_kind='社内基準',
                source_reference='[knowledge-document:' + self.document_ids[company] + ']',
                provider='Synthetic provider', valid_from='2026-01-01', status='draft',
                created_by='same', created_at='2026/10/28 12:00')
            self.db.session.add(row)
            self.db.session.flush()
            self.ids[company] = row.id
            self.db.session.add(self.Document(
                id=self.document_ids[company], company_code=company,
                checksum=hashlib.sha256(source).hexdigest(), filename=company + '-source.pdf',
                original_data=source, mimetype='application/pdf',
                knowledge_ids_json=json.dumps([row.id]), extraction_json='{}',
                created_by='same', created_at='2026/10/28 12:00'))
        self.db.session.commit()

    def tearDown(self):
        self.app.config['WTF_CSRF_ENABLED'] = False
        fixtures.Q02AccessRevocationTests.tearDown(self)

    def actor(self, company='A'):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(company_code=company, username='same', role='admin', office='east',
                           password_changed_at='2026-10-27 10:00:00')

    def request(self, method, path, **kwargs):
        # A fresh request context also prevents Flask-WTF's g cache from making
        # CSRF tests accidentally reuse a token from an earlier request.
        self.db.session.remove()
        self.ctx.pop()
        try:
            response = self.client.open(path, method=method, **kwargs)
        finally:
            self.ctx = self.app.app_context()
            self.ctx.push()
        self.addCleanup(response.close)
        return response

    def row(self, company='A'):
        return self.db.session.get(self.models.VehicleMaintenanceKnowledge, self.ids[company])

    def snapshot(self, company=None):
        self.db.session.expire_all()
        result = []
        for model in (self.models.VehicleMaintenanceKnowledge, self.Document, self.Extraction):
            query = model.query
            if company:
                query = query.filter_by(company_code=company)
            result.append(tuple(tuple(getattr(row, c.name) for c in model.__table__.columns)
                                for row in query.order_by(*model.__table__.primary_key.columns).all()))
        return result

    def detail(self, company='A'):
        return '/vehicle/maintenance-knowledge/' + str(self.ids[company])

    def source(self, company='A'):
        return '/vehicle/knowledge-documents/' + self.document_ids[company] + '/source'

    def create_form(self):
        return {'action': 'create', 'title': 'Created through route', 'part_name': 'Part',
                'conditions': 'Synthetic applicability', 'guidance': 'Synthetic guidance',
                'source_kind': '社内基準', 'source_reference': 'Synthetic page 1',
                'provider': 'Synthetic provider', 'valid_from': '2026-01-01',
                'company_code': 'B', 'created_by': 'forged', 'confirmed_by': 'forged',
                'retired_by': 'forged', 'status': 'active'}

    def writes(self, company='A'):
        return [self.create_form(),
                {'action': 'confirm', 'knowledge_id': self.ids[company], 'reviewed': '1',
                 'company_code': 'B', 'confirmed_by': 'forged'},
                {'action': 'retire', 'knowledge_id': self.ids[company],
                 'retirement_reason': 'Synthetic withdrawal', 'company_code': 'B',
                 'retired_by': 'forged'}]

    def assert_reads_allowed(self, company='A'):
        response = self.request('GET', self.detail(company))
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn(company + '_PRIVATE_KNOWLEDGE', text)
        self.assertNotIn(('B' if company == 'A' else 'A') + '_PRIVATE_GUIDANCE', text)
        response = self.request('GET', self.source(company))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, self.originals[company])
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')

    def test_authorized_create_confirm_retire_use_server_company_actor_and_preserve_originals(self):
        foreign = self.snapshot('B')
        documents = self.Document.query.count()
        response = self.request('POST', '/master/maintenance-knowledge', data=self.create_form())
        self.assertEqual(response.status_code, 302)
        created = self.models.VehicleMaintenanceKnowledge.query.filter_by(title='Created through route').one()
        created_id = created.id
        self.assertEqual((created.company_code, created.created_by, created.status), ('A', 'same', 'draft'))
        self.assertIsNone(created.confirmed_by)
        for action, status, actor_field in [('confirm', 'active', 'confirmed_by'),
                                             ('retire', 'retired', 'retired_by')]:
            form = {'action': action, 'knowledge_id': created_id, 'reviewed': '1',
                    'retirement_reason': 'Synthetic withdrawal', 'company_code': 'B',
                    'confirmed_by': 'forged', 'retired_by': 'forged'}
            self.assertEqual(self.request('POST', '/master/maintenance-knowledge', data=form).status_code, 302)
            row = self.db.session.get(self.models.VehicleMaintenanceKnowledge, created_id)
            self.assertEqual((row.company_code, row.status, getattr(row, actor_field)), ('A', status, 'same'))
        self.assertEqual(self.snapshot('B'), foreign)
        self.assertEqual(self.Document.query.count(), documents)
        for company in ('A', 'B'):
            document = self.db.session.get(self.Document, self.document_ids[company])
            self.assertEqual(document.original_data, self.originals[company])
            self.assertEqual(hashlib.sha256(document.original_data).hexdigest(), document.checksum)

    def test_foreign_authenticated_same_username_cannot_read_original_or_confirm_or_retire(self):
        self.assert_reads_allowed()
        self.actor('B')
        self.assert_reads_allowed('B')
        before = self.snapshot()
        for method, path, kwargs in [('GET', self.detail(), {}), ('GET', self.source(), {})] + [
                ('POST', '/master/maintenance-knowledge', {'data': form}) for form in self.writes()[1:]]:
            with self.subTest(method=method, path=path, action=kwargs.get('data', {}).get('action')):
                response = self.request(method, path, **kwargs)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(self.originals['A'], response.data)
                self.assertNotIn('A_PRIVATE_GUIDANCE', response.get_data(as_text=True))
                self.assertEqual(self.snapshot(), before)

    def test_demoted_admin_keeps_same_company_read_but_cannot_create_confirm_or_retire(self):
        self.assert_reads_allowed()
        self.user().role = 'user'
        self.db.session.commit()
        before = self.snapshot()
        self.actor()
        self.assert_reads_allowed()
        for form in self.writes():
            self.actor()
            response = self.request('POST', '/master/maintenance-knowledge', data=form)
            self.assertEqual((response.status_code, response.location), (302, '/'))
            self.assertEqual(self.snapshot(), before)

    def check_revocation(self, reason):
        self.assert_reads_allowed()
        if reason == 'lock':
            self.user().login_locked = True
        elif reason == 'delete':
            self.db.session.delete(self.user())
        elif reason == 'password':
            self.user().password_changed_at = '2099-01-01 00:00:00'
        else:
            self.models.Company.query.filter_by(company_code='A').one().active = False
        self.db.session.commit()
        before = self.snapshot()
        paths = [('GET', self.detail(), {}), ('GET', self.source(), {})] + [
            ('POST', '/master/maintenance-knowledge', {'data': form}) for form in self.writes()]
        for method, path, kwargs in paths:
            with self.subTest(method=method, path=path, action=kwargs.get('data', {}).get('action')):
                self.actor()
                response = self.request(method, path, **kwargs)
                self.assertEqual((response.status_code, response.location), (302, '/login'))
                self.assertNotIn(self.originals['A'], response.data)
                with self.client.session_transaction() as session:
                    self.assertNotIn('username', session)
                self.assertEqual(self.snapshot(), before)

    def test_lock_revokes_detail_source_and_all_knowledge_writes(self):
        self.check_revocation('lock')

    def test_deleted_user_does_not_fall_back_to_foreign_same_username(self):
        self.check_revocation('delete')

    def test_password_change_revokes_detail_source_and_all_knowledge_writes(self):
        self.check_revocation('password')

    def test_company_stop_revokes_detail_source_and_all_knowledge_writes(self):
        self.check_revocation('company')

    def test_csrf_missing_or_other_session_cannot_create_confirm_or_retire(self):
        self.app.config['WTF_CSRF_ENABLED'] = True
        # Obtain a valid signed token belonging to a genuinely different session.
        other = self.app.test_client()
        response = other.get('/login/csrf-token')
        self.addCleanup(response.close)
        wrong = response.json['csrf_token']
        response = self.request('GET', '/login/csrf-token')
        self.assertEqual(response.status_code, 200)
        valid = response.json['csrf_token']
        before = self.snapshot()
        for form in self.writes():
            for token in (None, wrong):
                with self.subTest(action=form['action'], token='missing' if token is None else 'other-session'):
                    data = dict(form)
                    if token:
                        data['csrf_token'] = token
                    self.assertEqual(self.request('POST', '/master/maintenance-knowledge', data=data).status_code, 400)
                    self.assertEqual(self.snapshot(), before)
        # Prove that the same route succeeds with the current session's token.
        data = dict(self.writes()[1], csrf_token=valid)
        self.assertEqual(self.request('POST', '/master/maintenance-knowledge', data=data).status_code, 302)
        self.assertEqual((self.row().status, self.row().confirmed_by), ('active', 'same'))


if __name__ == '__main__':
    unittest.main()
