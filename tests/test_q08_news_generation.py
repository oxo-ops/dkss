"""Additional acceptance after 288261d: form-time personal news ownership.

Real routes, signed GET forms, FK-enabled disposable databases and local PDF.
Explicit proof (including empty proof) bypasses no production validation.
"""
from html import unescape
from io import BytesIO
import json
import re
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from pypdf import PdfWriter
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
import test_q02_news_boundaries as fixtures


def foreign_keys(connection, record):
    connection.execute('PRAGMA foreign_keys=ON')


class NewsGenerationTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.Q02NewsBoundaryTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.Q02NewsBoundaryTests.tearDownClass.__func__)
    login = fixtures.Q02NewsBoundaryTests.login
    user = fixtures.Q02NewsBoundaryTests.user
    actor = fixtures.Q02NewsBoundaryTests.actor
    request = fixtures.Q02NewsBoundaryTests.request
    edit = fixtures.Q02NewsBoundaryTests.edit
    db_rows = fixtures.Q02NewsBoundaryTests.db_rows
    files_snapshot = fixtures.Q02NewsBoundaryTests.files_snapshot
    snapshot = fixtures.Q02NewsBoundaryTests.snapshot
    tearDown = fixtures.Q02NewsBoundaryTests.tearDown

    def setUp(self):
        fixtures.Q02NewsBoundaryTests.setUp(self)
        self.actor()
        self.app.config['WTF_CSRF_ENABLED'] = True
        if self.db.engine.dialect.name == 'sqlite':
            self.db.session.remove()
            self.db.engine.dispose()
            engine = self.db.engine
            event.listen(engine, 'connect', foreign_keys)
            self.addCleanup(event.remove, engine, 'connect', foreign_keys)
            self.assertEqual(self.db.session.scalar(text('PRAGMA foreign_keys')), 1)

    def person(self, company='A'):
        return self.models.User.query.filter_by(company_code=company, username='reader').one()

    def replace(self):
        old = self.person()
        old_id, old_identity = old.id, old.account_identity
        self.db.session.delete(old)
        self.db.session.commit()
        new = self.models.User(id=old_id, company_code='A', username='reader',
            last_name='Different person B', password='unused', role='user', office='east',
            password_changed_at='2026-10-27 10:00:00')
        self.db.session.add(new)
        self.db.session.commit()
        self.assertEqual(new.id, old_id)
        self.assertNotEqual(new.account_identity, old_identity)
        return old_identity, new.account_identity

    def form(self, path, kind='user', value='reader'):
        response = self.request('GET', path)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        def hidden(name):
            match = re.search(r'name="' + name + r'"\s+value="([^"]*)"', html)
            return unescape(match.group(1)) if match else ''
        return dict(title='Q08 private form', message='Private intended recipient',
            target_type=kind, target_value=value, csrf_token=hidden('csrf_token'),
            person_selection_token=hidden('person_selection_token'))

    def attachment(self, data):
        pdf = PdfWriter()
        pdf.add_blank_page(width=100, height=100)
        stream = BytesIO()
        pdf.write(stream)
        return dict(data, files=(BytesIO(stream.getvalue()), 'q08-proof.pdf'))

    def reject(self, path, data, status=409):
        from dkss_app import storage
        before = self.snapshot()
        with patch.object(storage, 'save_uploaded_file', wraps=storage.save_uploaded_file) as save:
            response = self.request('POST', path, data=self.attachment(data))
            self.assertEqual(response.status_code, status)
            save.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        self.dispatch.assert_not_called()

    def test_stale_new_person_reused_username_and_id_is_rejected(self):
        path = '/itc/news/new'
        data = self.form(path)
        self.replace()
        self.reject(path, data)

    def test_stale_edit_person_reused_username_and_id_is_rejected(self):
        path = self.edit()
        data = self.form(path)
        self.replace()
        self.reject(path, data)

    def test_missing_or_tampered_evidence_is_rejected_without_partial_writes(self):
        for path in ('/itc/news/new', self.edit()):
            data = self.form(path)
            for proof in ('', data['person_selection_token'] + 'tampered'):
                with self.subTest(path=path, proof=bool(proof)):
                    self.reject(path, dict(data, person_selection_token=proof))

    def test_foreign_company_proof_and_foreign_target_are_rejected(self):
        self.actor('B')
        foreign_proof = self.form('/itc/news/new')['person_selection_token']
        self.actor('A')
        for path in ('/itc/news/new', self.edit()):
            data = self.form(path)
            self.reject(path, dict(data, person_selection_token=foreign_proof))
            self.reject(path, dict(data, target_value='B-only-user'), 403)

    def test_fresh_b_selection_saves_with_uuid_and_edit_still_sends_no_notification(self):
        _, identity = self.replace()
        for path in ('/itc/news/new', self.edit()):
            self.dispatch.reset_mock()
            data = self.form(path)
            response = self.request('POST', path, data=self.attachment(data))
            self.assertEqual((response.status_code, response.location), (302, '/itc'))
            news = self.models.News.query.filter_by(title=data['title']).order_by(self.models.News.id.desc()).first()
            if path != '/itc/news/new':
                news = self.db.session.get(self.models.News, self.ids['A'])
            self.assertEqual(news.owner_identity, identity)
            if path == '/itc/news/new':
                notice = self.models.Notification.query.filter_by(title=data['title']).one()
                self.assertEqual(notice.owner_identity, identity)
                self.assertEqual(self.dispatch.call_count, 1)
            else:
                self.dispatch.assert_not_called()
                self.assertEqual(self.models.Notification.query.count(), 1)
            audit = self.models.AuditLog.query.filter_by(target_type='news', target_id=str(news.id)).one()
            self.assertEqual(audit.actor_identity, self.user().account_identity)
            self.assertNotEqual(audit.actor_identity, identity)
            filename = json.loads(news.files_json)[-1]
            with self.client.session_transaction() as state:
                state.update(company_code='A', username='reader', role='user', account_identity=identity)
            self.assertEqual(self.request('GET', '/static/uploads/' + filename, buffered=True).status_code, 200)
            foreign = self.person('B').account_identity
            with self.client.session_transaction() as state:
                state.update(company_code='B', username='reader', role='user', account_identity=foreign)
            self.assertEqual(self.request('GET', '/static/uploads/' + filename, buffered=True).status_code, 404)
            self.actor()

    def test_same_uuid_name_change_preserves_selection(self):
        for path in ('/itc/news/new', self.edit()):
            data = self.form(path)
            before = self.person().account_identity
            self.person().last_name = 'Renamed same person'
            self.db.session.commit()
            response = self.request('POST', path, data=data)
            self.assertEqual(response.status_code, 302)
            row = self.models.News.query.filter_by(title=data['title']).order_by(self.models.News.id.desc()).first()
            self.assertEqual(row.owner_identity, before)

    def test_removed_locked_or_role_changed_selection_is_rejected(self):
        for change in ('locked', 'role', 'missing'):
            data = self.form('/itc/news/new')
            person = self.person()
            if change == 'locked':
                person.login_locked = True
            elif change == 'role':
                person.role = 'admin'
            else:
                self.db.session.delete(person)
            self.db.session.commit()
            self.reject('/itc/news/new', data, 403 if change == 'missing' else 409)

    def test_legacy_unknown_uuid_is_not_resolved_by_username(self):
        person_id = self.person().id
        self.db.session.execute(self.models.User.__table__.update()
            .where(self.models.User.id == person_id).values(account_identity=None))
        self.db.session.commit()
        for path in ('/itc/news/new', self.edit()):
            self.reject(path, self.form(path))

    def after_validation_race(self, path):
        """A real second connection must not replace A between check and commit.

        The competing transaction must roll back on the actual DB lock. Then
        allow the valid A save, replace A after commit, and prove B is denied.
        """
        from dkss_app import person_selection
        data = self.form(path)
        person_id, identity = self.person().id, self.person().account_identity
        engine, table = self.db.engine, self.models.User.__table__
        observed = []

        def competing_replacement():
            try:
                with engine.begin() as connection:
                    if engine.dialect.name == 'postgresql':
                        connection.exec_driver_sql("SET LOCAL lock_timeout = '200ms'")
                    else:
                        connection.exec_driver_sql('PRAGMA busy_timeout=200')
                    connection.execute(table.delete().where(table.c.id == person_id))
                    raise AssertionError('Selected account was deleted while the news transaction was open')
            except OperationalError as error:
                if engine.dialect.name == 'postgresql':
                    self.assertEqual(error.orig.pgcode, '55P03')
                else:
                    self.assertIn(error.orig.sqlite_errorcode & 255, (5, 6))
                return 'replacement blocked and rolled back'

        validate = person_selection.validate
        with ThreadPoolExecutor(max_workers=1) as pool:
            def checked(*args, **kwargs):
                result = validate(*args, **kwargs)
                if result is None:
                    observed.append(pool.submit(competing_replacement).result(timeout=5))
                return result
            with patch.object(person_selection, 'validate', side_effect=checked):
                response = self.request('POST', path, data=self.attachment(data))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(observed, ['replacement blocked and rolled back'])
        news = (self.models.News.query.filter_by(title=data['title']).one() if path == '/itc/news/new'
                else self.db.session.get(self.models.News, self.ids['A']))
        self.assertEqual(news.owner_identity, identity)
        files = json.loads(news.files_json)
        _, successor_identity = self.replace()
        with self.client.session_transaction() as state:
            state.update(company_code='A', username='reader', role='user', account_identity=successor_identity)
        for filename in files:
            self.assertEqual(self.request('GET', '/static/uploads/' + filename, buffered=True).status_code, 404)
        self.assertNotIn(data['title'], self.request('GET', '/notifications').get_data(as_text=True))
        for notification in self.models.Notification.query.filter_by(title=data['title']).all():
            self.assertEqual(notification.owner_identity, identity)
            self.assertEqual(self.request('GET', f'/notifications/{notification.id}?panel=1').status_code, 404)

    def test_new_recipient_replacement_after_validation_is_locked_until_commit(self):
        self.after_validation_race('/itc/news/new')

    def test_edit_recipient_replacement_after_validation_is_locked_until_commit(self):
        self.after_validation_race(self.edit())

    def test_existing_content_edit_never_rebinds_a_saved_old_owner(self):
        path = '/itc/news/new'
        data = self.form(path)
        self.assertEqual(self.request('POST', path, data=data).status_code, 302)
        saved = self.models.News.query.filter_by(title=data['title']).one()
        saved_id, old_identity = saved.id, saved.owner_identity
        self.replace()
        path = f'/itc/news/{saved_id}/edit'
        data = self.form(path)
        data['message'] = 'Content update only'
        self.assertEqual(self.request('POST', path, data=data).status_code, 302)
        self.assertEqual(self.db.session.get(self.models.News, saved_id).owner_identity, old_identity)
        self.assertEqual(self.models.Notification.query.one().owner_identity, old_identity)

    def test_dynamic_scopes_preserve_fanout_and_edit_semantics(self):
        for kind, value, expected in [('all','',4), ('admins','',2), ('company','A',4), ('office','east',3)]:
            with self.subTest(kind=kind):
                before = self.models.Notification.query.count()
                data = self.form('/itc/news/new', kind, value)
                self.assertEqual(self.request('POST', '/itc/news/new', data=data).status_code, 302)
                self.assertEqual(self.models.Notification.query.count() - before, expected)
                self.dispatch.reset_mock()
                edit_data = self.form(self.edit(), kind, value)
                self.assertEqual(self.request('POST', self.edit(), data=edit_data).status_code, 302)
                self.assertEqual(self.models.Notification.query.count() - before, expected)
                self.dispatch.assert_not_called()
