"""Real review GET -> independent answer update -> stale approval POST."""
import os
import json
import unittest
from html.parser import HTMLParser
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

import test_q03_form_generation as forms


class Forms(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.forms = []
        self.current = None
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.current = {'action': attrs.get('action', ''), 'data': {}}
            self.forms.append(self.current)
        elif tag == 'input' and self.current is not None and attrs.get('type') == 'hidden' and attrs.get('name'):
            self.current['data'][attrs['name']] = attrs.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'form':
            self.current = None


class ApprovalVersionTests(unittest.TestCase):
    setUpClass = classmethod(forms.FormGenerationTests.setUpClass.__func__)
    tearDownClass = classmethod(forms.FormGenerationTests.tearDownClass.__func__)
    setUp = forms.FormGenerationTests.setUp
    tearDown = forms.FormGenerationTests.tearDown
    login = forms.FormGenerationTests.login
    request = forms.FormGenerationTests.request
    record = forms.FormGenerationTests.record
    _vehicle = forms.FormGenerationTests._vehicle
    _snapshot = forms.FormGenerationTests._snapshot

    def get_form(self, page, action):
        response = self.request('GET', page)
        self.assertEqual(response.status_code, 200)
        found = [f for f in Forms(response.get_data(as_text=True)).forms if f['action'] == action or (page == action and not f['action'])]
        self.assertEqual(len(found), 1, (page, action))
        return dict(found[0]['data'])

    def setup_record(self, kind):
        if kind == 'safety':
            row = self.record((True,))
            page = f'/safety/checklist-results/{row.id}'
        else:
            row, page = self._vehicle()
        self.login('reviewer')
        path = f'/{"safety" if kind == "safety" else "vehicle"}/checklist-results/{row.id}/approve/0'
        return row, page, path

    def change_answers(self, kind, row):
        self.login('checker')
        if kind == 'safety':
            path = f'/safety/checklist-results/{row.id}/edit'
            proof = self.get_form(path, path)
            response = self.request('POST', path, data={**proof, 'answer_0': 'NEW_ANSWER_FROM_OTHER_OPERATION'})
            self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[:500])
        else:
            self.login('admin')
            self.assertEqual(self.request('POST', f'/vehicle/checklist-results/{row.id}/reject', data={'reject_reason': 'correct answer'}).status_code, 302)
            self.login('checker')
            response = self.request('POST', f'/vehicle/checklists/{row.checklist_id}/save-one', data={
                'vehicle_record_id': row.vehicle_record_id, 'year': '2026', 'month': '10', 'day': '23',
                'item_no': '0', 'value': 'NEW_ANSWER_FROM_OTHER_OPERATION'})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(self.request('POST', f'/vehicle/checklists/{row.checklist_id}/complete', data={
                'vehicle_record_id': row.vehicle_record_id, 'year': '2026', 'month': '10', 'day': '23'}).status_code, 302)
        self.db.session.refresh(row)
        self.assertIn('NEW_ANSWER_FROM_OTHER_OPERATION', row.answers_json)
        self.assertEqual(row.status, '承認待ち')
        self.login('reviewer')

    def stale_case(self, kind):
        row, page, path = self.setup_record(kind)
        old = self.get_form(page, path)
        self.change_answers(kind, row)
        before = self._snapshot()
        response = self.request('POST', path, data=old)
        self.assertEqual(response.status_code, 409, 'Review of old answers must not approve unseen new answers')
        self.assertEqual(self._snapshot(), before)
        fresh = self.get_form(page, path)
        self.assertEqual(self.request('POST', path, data=fresh).status_code, 302)
        self.db.session.refresh(row)
        self.assertEqual(row.status, '承認済み')
        approval = json.loads(row.approvals_json)[0]
        actor = self.models.User.query.filter_by(company_code='A', username='reviewer').one()
        self.assertEqual(approval['approved_by_identity'], actor.account_identity)
        events = self.models.ChecklistEvent.query.filter_by(
            company_code='A', result_type=kind, result_id=row.id, event_type='承認').all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].actor_identity, actor.account_identity)

    def proof_case(self, kind):
        row, page, path = self.setup_record(kind)
        proof = self.get_form(page, path)
        self.assertEqual(len(proof['approval_version']), 64)
        before = self._snapshot()
        for value in ('', 'forged', 'f' * 64):
            self.assertEqual(self.request('POST', path, data={**proof, 'approval_version': value}).status_code, 409)
            self.assertEqual(self._snapshot(), before)
        # Missing form evidence, including a JSON API payload, cannot bypass it.
        from flask.testing import FlaskClient
        response = FlaskClient.open(self.client, path, method='POST', data={})
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self._snapshot(), before)
        self.assertEqual(self.request('POST', path, json={'approval_version': proof['approval_version']}).status_code, 409)
        self.assertEqual(self._snapshot(), before)

    def foreign_case(self, kind):
        row, page, path = self.setup_record(kind)
        proof = self.get_form(page, path)
        self.login('reviewer', 'B')
        before = self._snapshot()
        self.assertEqual(self.request('POST', path, data=proof).status_code, 302)
        self.assertEqual(self._snapshot(), before)

    def normal_case(self, kind, actor):
        row, page, path = self.setup_record(kind)
        self.login(actor)
        proof = self.get_form(page, path)
        self.assertEqual(self.request('POST', path, data=proof).status_code, 302)
        self.db.session.refresh(row)
        self.assertEqual(row.status, '承認済み')
        before = self._snapshot()
        self.assertEqual(self.request('POST', path, data=proof).status_code, 302)
        self.assertEqual(self._snapshot(), before, 'Already-approved replay creates no history/notification')

    def held_case(self, kind):
        row, page, path = self.setup_record(kind)
        proof = self.get_form(page, path)
        from dkss_app import checklists
        original = checklists.validate_approval_version
        seen = []

        def validate(*args):
            error = original(*args)
            self.assertIsNone(error)
            with self.db.engine.connect() as writer:
                with self.assertRaises(OperationalError) as caught:
                    with writer.begin():
                        if writer.dialect.name == 'postgresql':
                            writer.execute(text("SET LOCAL lock_timeout='100ms'"))
                        else:
                            writer.exec_driver_sql('PRAGMA busy_timeout=100')
                        writer.execute(text(f'UPDATE {row.__table__.name} SET answers_json=:answers WHERE id=:id'),
                                       {'answers': '[{"value":"UNSEEN_RACE"}]', 'id': row.id})
                if writer.dialect.name == 'postgresql':
                    self.assertEqual(caught.exception.orig.pgcode, '55P03')
                else:
                    self.assertIn('database is locked', str(caught.exception))
                seen.append(True)
            return error

        with patch.object(checklists, 'validate_approval_version', side_effect=validate):
            self.assertEqual(self.request('POST', path, data=proof).status_code, 302)
        self.assertEqual(seen, [True])
        self.db.session.refresh(row)
        self.assertNotIn('UNSEEN_RACE', row.answers_json)

    def event_case(self, kind):
        row, page, path = self.setup_record(kind)
        proof = self.get_form(page, path)
        original = tuple(getattr(row, c.name) for c in row.__table__.columns)
        event = self.models.ChecklistEvent(company_code='A', result_type=kind, result_id=row.id,
            event_type='修正', actor_username='checker', actor_name='Test checker',
            detail_json='{"changes":[]}', created_at='2026-10-29 10:00:00')
        self.db.session.add(event)
        self.db.session.commit()
        self.assertEqual(tuple(getattr(row, c.name) for c in row.__table__.columns), original)
        before = self._snapshot()
        self.assertEqual(self.request('POST', path, data=proof).status_code, 409)
        self.assertEqual(self._snapshot(), before)
        fresh = self.get_form(page, path)
        self.assertNotEqual(proof['approval_version'], fresh['approval_version'])
        self.assertEqual(self.request('POST', path, data=fresh).status_code, 302)

    def test_safety_stale_answer_review_rejected(self):
        self.stale_case('safety')

    def test_vehicle_stale_answer_review_rejected(self):
        self.stale_case('vehicle')


def case(method, *args):
    def run(self):
        getattr(self, method)(*args)
    return run


for _kind in ('safety', 'vehicle'):
    for _method in ('proof', 'foreign', 'held', 'event'):
        setattr(ApprovalVersionTests, f'test_{_kind}_{_method}', case(_method + '_case', _kind))
    for _actor in ('admin', 'outsider'):
        setattr(ApprovalVersionTests, f'test_{_kind}_normal_{_actor}', case('normal_case', _kind, _actor))


@unittest.skipUnless(os.environ.get('Q03_POSTGRES_TEST_URL'), 'explicit disposable PostgreSQL required')
class PostgresApprovalVersionTests(ApprovalVersionTests):
    setUpClass = classmethod(forms.PostgresFormGenerationTests.setUpClass.__func__)
    tearDownClass = classmethod(forms.PostgresFormGenerationTests.tearDownClass.__func__)
