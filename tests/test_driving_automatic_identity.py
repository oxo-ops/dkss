"""Automatic account matching must remain unambiguous and company scoped."""
import json
import unittest
from flask import session
from dkss_app import driving_access as access
from dkss_app.models import Driver, DrivingReportReader
from driving_report_data import payload
import test_driving_report_readership as readership_tests

class AutomaticIdentityTests(unittest.TestCase):
    setUpClass=classmethod(readership_tests.DrivingReadershipTests.setUpClass.__func__)
    tearDownClass=classmethod(readership_tests.DrivingReadershipTests.tearDownClass.__func__)
    setUp=readership_tests.DrivingReadershipTests.setUp
    tearDown=readership_tests.DrivingReadershipTests.tearDown
    save=readership_tests.DrivingReadershipTests.save
    login=readership_tests.DrivingReadershipTests.login
    grant=readership_tests.DrivingReadershipTests.grant

    def master(self, code='one', name='同姓 同名', company='TEST'):
        row=Driver(company_code=company,employee_id=code,name=name,office='別の営業所')
        self.m.db.session.add(row);self.m.db.session.commit();return row

    def test_employee_account_and_report_match_without_manual_grants(self):
        self.master();own=self.save(code='one',name='同姓　同名')
        self.login()
        for suffix in [f'/{own.id}','?scope=self&period=all','/export.csv?scope=self&period=all','/export.csv?scope=self&period=all&view=comparison']:
            r=self.client.get('/safety/driving-reports'+suffix)
            self.assertEqual(r.status_code,200)
            self.assertIn('同姓',r.get_data(as_text=True))
        self.assertEqual(DrivingReportReader.query.count(),0,'GET never creates an ACL or calls paid AI')

    def test_name_alone_wrong_code_duplicate_master_and_name_conflict_stay_private(self):
        row=self.save(code='one',name='同姓同名');self.login()
        self.assertEqual(self.client.get(f'/safety/driving-reports/{row.id}').status_code,404)
        master=self.master(name='別人')
        self.assertEqual(self.client.get(f'/safety/driving-reports/{row.id}').status_code,404)
        master.name='同姓同名';self.m.db.session.commit();duplicate=self.master()
        self.assertEqual(self.client.get(f'/safety/driving-reports/{row.id}').status_code,404)
        self.m.db.session.delete(duplicate);self.m.db.session.commit()
        wrong=self.save(2,code='TEST-SHIOKAWA-01',name='同姓同名')
        self.assertEqual(self.client.get(f'/safety/driving-reports/{wrong.id}').status_code,404)

    def test_other_company_master_or_other_account_cannot_grant_access(self):
        own=self.save(code='one',name='同姓同名');self.master(company='OTHER');self.login()
        self.assertEqual(self.client.get(f'/safety/driving-reports/{own.id}').status_code,404)
        self.master();self.login('two')
        self.assertEqual(self.client.get(f'/safety/driving-reports/{own.id}').status_code,404)

    def test_confirmed_correspondence_reused_only_for_same_identity_from_start_date(self):
        old=self.save(day='2026-10-10');self.grant(old)
        later=self.save(2,day='2026-10-11');earlier=self.save(3,day='2026-10-09')
        source=self.save(4,day='2026-10-11',source_system='OTHER');name=self.save(5,day='2026-10-11',name='別人')
        self.login()
        self.assertEqual(self.client.get(f'/safety/driving-reports/{later.id}').status_code,200)
        for row in [earlier,source,name]:self.assertEqual(self.client.get(f'/safety/driving-reports/{row.id}').status_code,404)

    def test_conflicting_confirmations_do_not_choose_an_account(self):
        first=self.save();self.grant(first)
        second=self.save(2);self.grant(second,'two')
        next_row=self.save(3);self.login()
        self.assertEqual(self.client.get(f'/safety/driving-reports/{next_row.id}').status_code,404)

    def test_stale_explicit_grant_and_withdrawal_override_automatic_match(self):
        self.master();row=self.save(code='one',name='同姓同名');self.grant(row)
        p=payload(row);p['driver_name']='同姓 同名';row.details_json=json.dumps(p);self.m.db.session.commit()
        self.login();self.assertEqual(self.client.get(f'/safety/driving-reports/{row.id}').status_code,404)
        self.login('admin','admin');self.grant(row,'');self.login()
        self.assertEqual(self.client.get(f'/safety/driving-reports/{row.id}').status_code,404)

    def test_admin_self_is_automatic_without_changing_management_permission(self):
        self.master(code='admin',name='検証管理者');row=self.save(code='admin',name='検証 管理者')
        self.assertEqual(self.client.get('/safety/driving-reports?scope=self&period=all').status_code,200)
        with self.m.app.test_request_context():
            session.update(company_code='TEST',username='admin',role='admin')
            self.assertEqual([r.id for r in access.visible([row],personal=True)],[row.id])
        self.assertEqual(self.client.get('/safety/driving-reports?scope=company&period=all').status_code,200)
