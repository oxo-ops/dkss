"""Current roster and historical operation offices remain separate facts."""
import csv
import io
import json
import unittest
from unittest.mock import patch
from driving_report_data import payload
from driving_report_insights import digest
from dkss_app.models import Driver, DrivingReportReader
import test_driving_workspace as workspace_tests


class OfficeMembershipTests(unittest.TestCase):
    setUpClass=classmethod(workspace_tests.WorkspaceTests.setUpClass.__func__)
    tearDownClass=classmethod(workspace_tests.WorkspaceTests.tearDownClass.__func__)
    setUp=workspace_tests.WorkspaceTests.setUp
    tearDown=workspace_tests.WorkspaceTests.tearDown
    save=workspace_tests.WorkspaceTests.save
    render=workspace_tests.WorkspaceTests.render

    def confirm(self):
        self.m.db.session.add(self.m.User(company_code='TEST',username='A',role='user',password='unused',last_name='本人',office='安城',password_changed_at='stamp'))
        self.m.db.session.commit()
        from dkss_app import driving_access
        from flask import session
        with self.m.app.test_request_context():
            session.update(company_code='TEST',username='admin',role='admin')
            driving_access.assign([self.a],'A','admin');self.m.db.session.commit()

    def people(self,context):
        return [p for p in context['insights']['drivers'] if p['has_records']]

    def test_transfer_preserves_historical_scope_and_current_roster(self):
        self.confirm()
        master=Driver.query.filter_by(company_code='TEST',employee_id='A').one()
        master.office='小山';self.m.db.session.commit()
        response,context=self.render(self.base)
        people=self.people(context);self.assertEqual(len(people),1)
        self.assertEqual(people[0]['offices'],['安城'])
        self.assertEqual((people[0]['current_office'],people[0]['affiliation_status']),('小山','other'))
        self.assertEqual(context['insights']['summary']['distance'],20)
        self.assertIn('他営業所所属・期間内の運行あり',response.get_data(as_text=True))
        _,context=self.render(self.base+'&office='+digest(['office','小山']))
        self.assertEqual(context['insights']['summary']['distance'],100)
        current=[p for p in context['insights']['drivers'] if p['master_id']==master.id]
        self.assertEqual(len(current),1);self.assertFalse(current[0]['has_records'])
        self.assertEqual(current[0]['current_office'],'小山')
        _,context=self.render(self.base+'&scope=company&listing=people')
        linked=[p for p in context['insights']['drivers'] if p['master_id']==master.id]
        self.assertEqual(len(linked),1);self.assertEqual(linked[0]['offices'],['安城'])
        self.assertEqual(payload(self.a)['office_name'],'安城')

    def test_source_name_or_code_never_links_current_master_without_confirmation(self):
        _,context=self.render(self.base)
        recorded=self.people(context)[0]
        self.assertEqual(recorded['affiliation_status'],'unknown')
        self.assertEqual(recorded['current_office'],'')
        self.assertIsNone(recorded['master_id'])
        self.assertEqual(DrivingReportReader.query.count(),0)
        self.assertTrue(any(not p['has_records'] and p['name']=='乗務員A' for p in context['insights']['drivers']))

    def test_ambiguous_employee_master_or_stale_binding_keeps_office_unknown(self):
        self.confirm()
        self.m.db.session.add(Driver(company_code='TEST',employee_id='A',name='別の台帳行',office='小山'))
        self.m.db.session.commit()
        _,context=self.render(self.base);self.assertEqual(self.people(context)[0]['affiliation_status'],'unknown')
        Driver.query.filter_by(name='別の台帳行').delete();self.m.db.session.commit()
        data=payload(self.a);data['driver_name']='原本の訂正後氏名'
        self.a.details_json=json.dumps(data);self.m.db.session.commit()
        _,context=self.render(self.base);self.assertEqual(self.people(context)[0]['affiliation_status'],'unknown')

    def test_unknown_historical_office_is_never_allocated_to_current_office(self):
        data=payload(self.a);data.pop('office_name',None);data.pop('driver_office',None)
        self.a.details_json=json.dumps(data);self.m.db.session.commit();self.confirm()
        _,context=self.render(self.base);self.assertEqual(context['total'],0)
        _,context=self.render(self.base+'&scope=company&listing=people')
        person=next(p for p in self.people(context) if p['name']=='乗務員A')
        self.assertEqual(person['offices'],['所属不明']);self.assertEqual(person['current_office'],'安城')
        self.assertEqual(person['affiliation_status'],'history_unknown')
        self.assertNotIn('他社の秘密',str(context['insights']['current_affiliations']))

    def test_comparison_export_and_ai_distinguish_current_and_historical_offices(self):
        self.confirm()
        url='/safety/driving-reports/reflection?period=all'
        before=self.client.get(url).json['key']
        Driver.query.filter_by(company_code='TEST',employee_id='A').one().office='小山'
        self.m.db.session.commit();self.assertNotEqual(before,self.client.get(url).json['key'])
        exported=self.client.get('/safety/driving-reports/export.csv?period=all&view=comparison')
        data=list(csv.DictReader(io.StringIO(exported.data.decode('utf-8-sig'))))
        person=next(row for row in data if row['乗務員']=='乗務員A')
        self.assertEqual(person['営業所'],'安城')
        self.assertEqual(person['現在所属（確認済み乗務員台帳）'],'小山')
        self.assertEqual(person['所属区分'],'他営業所所属・期間内の運行あり')
        with patch('driving_report_management.export_pdf',return_value=b'fake-pdf') as pdf:
            self.assertEqual(self.client.get('/safety/driving-reports/export.pdf?period=all').status_code,200)
            self.assertIn('現在所属 小山',str(pdf.call_args))
        with self.client.session_transaction() as state:state.update(username='A',role='user',password_changed_at='stamp')
        response,context=self.render(self.base+'&scope=company')
        self.assertEqual(context['insights']['current_affiliations'],[])
        self.assertNotIn('他営業所所属',response.get_data(as_text=True))
        self.assertNotIn('小山の人',response.get_data(as_text=True))

    def test_vehicle_or_due_filter_never_adds_unrelated_no_report_roster(self):
        self.vehicle.manufacturer='日野';self.m.db.session.commit()
        _,context=self.render(self.base+'&vehicle_make='+digest(['vehicle_make','日野']))
        self.assertTrue(all(p['has_records'] for p in context['insights']['drivers']))
        _,context=self.render(self.base+'&followup_due=due')
        self.assertEqual(context['insights']['drivers'],[])


if __name__=='__main__':unittest.main()
