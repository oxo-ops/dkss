"""Office rename/delete against safety checklist create/edit, not date semantics."""
import html
import re

from q04_pg_helpers import PrivatePostgresCase


class ChecklistOfficeLinkTests(PrivatePostgresCase):
    def setUp(self):
        super().setUp()
        with self.app.app_context():
            for company in (self.company, self.other):
                self.db.session.add(self.m.User(company_code=company, username='driver',
                    last_name='Synthetic', role='user', password='unused', office='Office-A', password_changed_at=self.stamp))
                vehicle = self.m.Vehicle.query.filter_by(company_code=company).one()
                if company == self.company:
                    self.target_vehicle_id = vehicle.id
                checklist = self.m.Checklist(company_code=company, name='Synthetic safety',
                    target='安全管理', items_json='[]', active=True)
                self.db.session.add(checklist)
                self.db.session.flush()
                row = self.m.ChecklistResult(company_code=company, checklist_id=checklist.id,
                    checked_by_username='admin', target_type='' if company == self.company else 'office',
                    target_office='' if company == self.company else 'Office-A',
                    status='点検完了', answers_json='[]', approvals_json='[]')
                self.db.session.add(row)
                self.db.session.flush()
                if company == self.company:
                    self.checklist_id, self.result_id = checklist.id, row.id
            self.db.session.commit()
        self.foreign_before = self.snapshot(self.other)

    def related_action(self, writer):
        writer, _, source = writer.partition('_')
        data = {'target_type': 'office', 'target_office': 'Office-A'}
        if source:
            data.update(target_type=source, target_user='driver', target_vehicle_record_id=self.target_vehicle_id)
        if writer == 'new':
            path=f'/safety/checklists/{self.checklist_id}/new'
        else:
            path=f'/safety/checklist-results/{self.result_id}/edit'
        # Capture the real form before either scheduled transaction starts.
        # Historical baseline templates have no token; keep that baseline runnable.
        with self.client() as client:
            response=client.get(path)
            try:
                self.assertEqual(response.status_code,200)
                match=re.search(r'name="person_selection_token"\s+value="([^"]+)"',response.get_data(as_text=True))
                if match:
                    data['person_selection_token']=html.unescape(match[1])
            finally:
                response.close()
        if writer == 'new':
            return self.action(path,data)
        from dkss_app.checklists import checklist_result_edit_version
        with self.app.app_context():
            data['record_version'] = checklist_result_edit_version(
                self.db.session.get(self.m.ChecklistResult, self.result_id))
        return self.action(f'/safety/checklist-results/{self.result_id}/edit', data)

    def check_race(self, writer, operation, master_first):
        source = writer.partition('_')[2]
        master = self.action(f'/master/offices/{self.ids["offices"]}/{operation}',
            {'name': 'Renamed'} if operation == 'edit' else {})
        related = self.related_action(writer)
        before = self.snapshot(self.company)
        actions = (master, related) if master_first else (related, master)
        table = {'user': 'driver', 'vehicle': 'vehicle'}.get(source, 'office')
        results, waited = self.schedule(*actions, table,
            first_table='checklist_result' if master_first else None)
        mutated, saved = results if master_first else reversed(results)
        state = self.snapshot(self.company)
        if master_first or source:
            self.assertEqual(mutated.get('status'), 302, repr(results))
            self.assertEqual(saved.get('status'), 400, repr(results))
            self.assertEqual(state['checklist_result'], before['checklist_result'])
            self.assertEqual(state['patrol_result'], before['patrol_result'])
        else:
            self.assertEqual(saved.get('status'), 302, repr(results))
            self.assertEqual(mutated.get('status'), 409, repr(results))
            self.assertEqual(state['office'], before['office'])
            self.assertEqual(sum(r['target_office'] == 'Office-A' for r in state['checklist_result']), 1)
        if master_first or not source:
            self.assertTrue(waited, 'History validation and master mutation must serialize')
        self.assertEqual(self.snapshot(self.other), self.foreign_before)

    def test_control_new_and_edit(self):
        for writer in ('new', 'edit', 'new_user', 'edit_user', 'new_vehicle', 'edit_vehicle'):
            self.assertEqual(self.post('A', self.related_action(writer)).get('status'), 302)
        self.assertEqual(self.snapshot(self.other), self.foreign_before)

    def test_new_failure_does_not_leave_partial_history_or_events(self):
        self.assert_failed_save_is_atomic(self.related_action('new'), 'insert into checklist_result ')

    def test_edit_failure_does_not_leave_partial_history_or_events(self):
        self.assert_failed_save_is_atomic(self.related_action('edit'), 'update checklist_result ')


def case(writer, operation, first):
    def check(self):
        self.check_race(writer, operation, first)
    return check


for _writer in ('new', 'edit', 'new_user', 'edit_user', 'new_vehicle', 'edit_vehicle'):
    for _operation in ('edit', 'delete'):
        for _first in (False, True):
            setattr(ChecklistOfficeLinkTests,
                'test_' + _writer + '_' + _operation + ('_master_first' if _first else '_history_first'),
                case(_writer, _operation, _first))
