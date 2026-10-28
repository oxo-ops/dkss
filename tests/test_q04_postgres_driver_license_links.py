"""Driver/User atomic saves versus license-type rename/delete, both orders."""
import json

from q04_pg_helpers import PrivatePostgresCase


class DriverLicenseLinkTests(PrivatePostgresCase):
    def setUp(self):
        super().setUp()
        with self.app.app_context():
            for company in (self.company, self.other):
                row = self.m.LicenseType(company_code=company, name='License-A')
                self.db.session.add(row)
                self.db.session.flush()
                if company == self.company:
                    self.license_id = row.id
                driver = self.m.Driver(company_code=company, employee_id='lic-edit', name='Synthetic',
                    office='Office-A', role='user', licenses_json='[]')
                self.db.session.add(driver)
                self.db.session.add(self.m.User(company_code=company, username='lic-edit', last_name='Synthetic',
                    password='unused', office='Office-A', role='user', password_changed_at=self.stamp))
                self.db.session.flush()
                if company == self.company:
                    self.driver_id = driver.id
            self.db.session.commit()
        self.foreign_before = self.snapshot(self.other)

    def related_action(self, writer):
        data = {'employee_id': 'lic-new' if writer == 'new' else 'lic-edit', 'last_name': 'Synthetic',
                'role': 'user', 'office': 'Office-A', 'license_type': 'License-A', 'license_expiry': '2027-10-01'}
        if writer == 'new':
            data['password'] = 'Q04-Disposable-Only-742!'
        return self.action('/master/drivers/new' if writer == 'new' else f'/master/drivers/{self.driver_id}/edit', data)

    def check_race(self, writer, operation, master_first):
        mutation = self.action(f'/master/license-types/{self.license_id}/{operation}',
            {'name': 'Renamed'} if operation == 'edit' else {})
        before = self.snapshot(self.company)
        related = self.related_action(writer)
        actions = (mutation, related) if master_first else (related, mutation)
        responses, waited = self.schedule(*actions, 'license_type', first_table='driver' if master_first else None)
        mutated, saved = responses if master_first else reversed(responses)
        state = self.snapshot(self.company)
        if master_first:
            self.assertEqual(mutated.get('status'), 302, repr(responses))
            self.assertEqual(saved.get('status'), 400, repr(responses))
            self.assertEqual(state['driver'], before['driver'])
            self.assertEqual(state['user'], before['user'], 'Rejected driver save partly changed its User')
        else:
            self.assertEqual(saved.get('status'), 302, repr(responses))
            self.assertEqual(mutated.get('status'), 302 if operation == 'edit' else 409, repr(responses))
            employee = 'lic-new' if writer == 'new' else 'lic-edit'
            row = next(r for r in state['driver'] if r['employee_id'] == employee)
            self.assertEqual(json.loads(row['licenses_json']),
                [{'type': 'Renamed' if operation == 'edit' else 'License-A', 'expiry': '2027-10-01'}])
            self.assertEqual(sum(r['username'] == employee for r in state['user']), 1)
        self.assertTrue(waited, 'License validation must protect the master until Driver/User commit')
        self.assertEqual(self.snapshot(self.other), self.foreign_before)

    def test_control_new_and_edit(self):
        for writer in ('new', 'edit'):
            self.assertEqual(self.post('A', self.related_action(writer)).get('status'), 302)
        self.assertEqual(self.snapshot(self.other), self.foreign_before)

    def test_new_failure_rolls_back_both_driver_and_user(self):
        self.assert_failed_save_is_atomic(self.related_action('new'), 'insert into "user" ')

    def test_edit_failure_rolls_back_both_driver_and_user(self):
        self.assert_failed_save_is_atomic(self.related_action('edit'), 'update driver ')

    def test_different_license_renames_do_not_overwrite_the_same_driver_license_list(self):
        with self.app.app_context():
            second = self.m.LicenseType(company_code=self.company, name='License-B')
            self.db.session.add(second)
            self.db.session.add(self.m.LicenseType(company_code=self.other, name='License-B'))
            licenses = [{'type': name, 'expiry': '2027-10-01'} for name in ('License-A', 'License-B')]
            first = self.db.session.get(self.m.Driver, self.driver_id)
            first.licenses_json = json.dumps(licenses)
            self.db.session.add(self.m.Driver(company_code=self.company, employee_id='lic-second',
                name='Synthetic', office='Office-A', licenses_json=json.dumps(list(reversed(licenses)))))
            self.db.session.commit()
            second_id = second.id
        foreign = self.snapshot(self.other)
        actions = [self.action(f'/master/license-types/{ident}/edit', {'name': name})
                   for ident, name in ((self.license_id, 'Renamed-A'), (second_id, 'Renamed-B'))]
        responses, waited = self.schedule(*actions, 'driver')
        self.assertEqual([r.get('status') for r in responses], [302, 302], repr(responses))
        state = self.snapshot(self.company)
        for employee in ('lic-edit', 'lic-second'):
            row = next(r for r in state['driver'] if r['employee_id'] == employee)
            self.assertCountEqual(json.loads(row['licenses_json']),
                [{'type': name, 'expiry': '2027-10-01'} for name in ('Renamed-A', 'Renamed-B')])
        self.assertEqual(self.snapshot(self.other), foreign)
        self.assertTrue(waited, 'Renames touching the same license list must serialize on its driver rows')


def case(writer, operation, first):
    def check(self):
        self.check_race(writer, operation, first)
    return check


for _writer in ('new', 'edit'):
    for _operation in ('edit', 'delete'):
        for _first in (False, True):
            setattr(DriverLicenseLinkTests,
                'test_' + _writer + '_' + _operation + ('_master_first' if _first else '_related_first'),
                case(_writer, _operation, _first))
