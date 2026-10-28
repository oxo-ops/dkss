"""Current registry filters and recorded shared usage preserve scope and evidence."""
from identity_fixture import identity_for
import unittest
from driving_report_conditions import value, usage
from driving_report_insights import digest, driver_keys
from driving_report_data import payload
from types import SimpleNamespace
import json
import test_driving_workspace as workspace_tests


class VehicleConditionTests(unittest.TestCase):
    setUpClass=classmethod(workspace_tests.WorkspaceTests.setUpClass.__func__)
    tearDownClass=classmethod(workspace_tests.WorkspaceTests.tearDownClass.__func__)
    setUp=workspace_tests.WorkspaceTests.setUp
    tearDown=workspace_tests.WorkspaceTests.tearDown
    save=workspace_tests.WorkspaceTests.save
    render=workspace_tests.WorkspaceTests.render

    def registry(self):
        self.vehicle.manufacturer='日野';self.vehicle.model_code='MODEL-A'
        self.vehicle.body_type='平ボデー';self.vehicle.first_registration_date='2020-04'
        second=self.m.Vehicle(company_code='TEST',chassis_number='SECOND',manufacturer='いすゞ',model_code='MODEL-B')
        foreign=self.m.Vehicle(company_code='OTHER',chassis_number='SECRET',manufacturer='他社限定メーカー')
        self.m.db.session.add_all([second,foreign]);self.m.db.session.flush()
        self.b.vehicle_record_id=second.id;self.m.db.session.commit()
        return second

    def test_filter_applies_to_current_previous_exports_and_ai(self):
        second=self.registry();old=self.save(8,day='2026-09-10',distance='30')
        old_other=self.save(9,day='2026-09-11',code='B',name='小山の人',office_name='小山')
        old_other.vehicle_record_id=second.id;self.m.db.session.commit()
        query='period=custom&start=2026-10-01&end=2026-10-26&scope=company&vehicle_make='+digest(['vehicle_make','日野'])
        response,context=self.render('/safety/driving-reports?'+query)
        board=context['insights'];self.assertEqual(context['total'],1)
        self.assertEqual(board['summary']['distance'],20)
        self.assertEqual(board['previous']['count'],1)
        self.assertNotIn('他社限定メーカー',response.get_data(as_text=True))
        for suffix in ['', '&view=comparison','&view=breakdown']:
            exported=self.client.get('/safety/driving-reports/export.csv?'+query+suffix)
            self.assertEqual(exported.status_code,200)
            text=exported.data.decode('utf-8-sig');self.assertIn('メーカー：日野',text);self.assertNotIn('小山の人',text)
        self.assertEqual(self.client.get('/safety/driving-reports/export.pdf?'+query).status_code,200)
        first=self.client.get('/safety/driving-reports/reflection?'+query).json['key']
        self.vehicle.model_code='MODEL-CHANGED';self.m.db.session.commit()
        second_key=self.client.get('/safety/driving-reports/reflection?'+query).json['key']
        self.assertNotEqual(first,second_key)

    def test_unknown_year_and_invalid_or_foreign_choices(self):
        self.registry()
        for raw,expected in [('2020-04','2020'),('2020年4月','2020'),('不明',None),('令和2年',None),('',None)]:
            self.assertEqual(value(SimpleNamespace(first_registration_date=raw),'vehicle_year'),expected)
        _,context=self.render(self.base+'&scope=company&vehicle_year='+digest(['vehicle_year',None]))
        self.assertEqual(context['total'],1)
        for key in ['garbage',digest(['vehicle_make','他社限定メーカー'])]:
            self.assertEqual(self.client.get(self.base+'&vehicle_make='+key).status_code,400)

    def test_shared_usage_respects_office_period_and_lifecycle(self):
        old=self.save(8,day='2025-10-10',code='OLD',name='期間外の人')
        cancelled=self.save(9,code='CANCEL',name='取消の人')
        data=payload(cancelled);data['lifecycle']='cancelled';cancelled.details_json=json.dumps(data);self.m.db.session.commit()
        key=driver_keys([self.a])[0][self.a.id]
        query='period=custom&start=2026-10-01&end=2026-10-26&focus='+key
        _,context=self.render('/safety/driving-reports?'+query)
        users=context['insights']['shared_vehicle_usage'][self.vehicle.id]
        self.assertEqual([u['name'] for u in users],['乗務員A'])
        _,context=self.render('/safety/driving-reports?'+query+'&scope=company')
        users=context['insights']['shared_vehicle_usage'][self.vehicle.id]
        self.assertEqual({u['name'] for u in users},{'乗務員A','小山の人'})
        self.assertTrue(all(u['recorded_days']==1 for u in users))
        self.assertTrue(all(u['summary']['count']==1 for u in users))

    def test_user_sees_only_granted_vehicle_conditions_and_no_shared_users(self):
        self.registry()
        self.m.db.session.add(self.m.User(company_code='TEST',username='one',role='user',password='unused',last_name='本人',password_changed_at='stamp'))
        self.m.db.session.commit()
        from dkss_app import driving_access
        from flask import session
        with self.m.app.test_request_context():
            session.update(account_identity=identity_for('TEST', 'admin'), company_code='TEST',username='admin',role='admin')
            driving_access.assign([self.a],'one','admin');self.m.db.session.commit()
        with self.client.session_transaction() as state:state.update(account_identity=identity_for(state.get('company_code'), 'one', app=(self.client).application), username='one',role='user',password_changed_at='stamp')
        response,context=self.render(self.base+'&scope=company')
        html=response.get_data(as_text=True)
        self.assertNotIn('いすゞ',html);self.assertNotIn('小山の人',html)
        self.assertEqual(context['insights']['shared_vehicle_usage'],{})
        self.assertEqual(self.client.get(self.base+'&vehicle_make='+digest(['vehicle_make','いすゞ'])).status_code,400)


if __name__=='__main__':unittest.main()
