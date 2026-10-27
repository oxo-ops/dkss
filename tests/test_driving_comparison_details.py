"""Compare real authorized routes and exports, without inventing compatible metrics."""
import csv
import io
import json
import unittest
from driving_report_data import payload, version
from driving_report_insights import driver_keys
import test_driving_workspace as workspace_tests
from dkss_app.models import DrivingReportReader


class ComparisonDetailTests(unittest.TestCase):
    setUpClass=classmethod(workspace_tests.WorkspaceTests.setUpClass.__func__)
    tearDownClass=classmethod(workspace_tests.WorkspaceTests.tearDownClass.__func__)
    setUp=workspace_tests.WorkspaceTests.setUp
    tearDown=workspace_tests.WorkspaceTests.tearDown
    save=workspace_tests.WorkspaceTests.save
    render=workspace_tests.WorkspaceTests.render

    def test_same_vehicle_uses_paired_rates_and_scoped_export(self):
        # Both drivers use this vehicle, but their offices remain distinct.
        url=self.base+'&scope=company&breakdown=vehicle&vehicle='+str(self.a.vehicle_record_id)
        _,context=self.render(url)
        rows=context['insights']['comparison']['rows']
        self.assertEqual(sorted(r['current']['display'] for r in rows),['2','5'])
        self.assertEqual(sorted(r['coverage'] for r in rows),['100','100'])
        self.assertNotIn('他社の秘密',str(rows))
        response=self.client.get(url.replace('/safety/driving-reports?','/safety/driving-reports/export.csv?')+'&view=breakdown')
        exported=list(csv.reader(io.StringIO(response.data.decode('utf-8-sig'))))
        self.assertEqual(len(exported),3)
        self.assertIn('小山の人',response.data.decode('utf-8-sig'))
        _,context=self.render(self.base+'&breakdown=vehicle&vehicle='+str(self.a.vehicle_record_id))
        self.assertEqual(len(context['insights']['comparison']['rows']),1)

    def test_single_person_vehicle_comparison_never_adds_peer(self):
        v=self.m.Vehicle(company_code='TEST',chassis_number='comparison-second')
        self.m.db.session.add(v);self.m.db.session.flush()
        second=self.save(8,distance='80',count='4');second.vehicle_record_id=v.id
        self.m.db.session.commit()
        key=driver_keys([self.a])[0][self.a.id]
        _,context=self.render(self.base+'&scope=company&breakdown=vehicles&focus='+key)
        rows=context['insights']['comparison']['rows']
        self.assertEqual(len(rows),2)
        self.assertEqual(sum(r['current']['count'] for r in rows),2)
        self.assertNotIn('小山の人',str(rows))

    def test_incompatible_or_missing_metrics_do_not_become_zero(self):
        p=payload(self.b);p['definition_version']='v2';self.b.details_json=json.dumps(p)
        self.m.db.session.commit()
        _,context=self.render(self.base+'&scope=company&breakdown=offices')
        rows=context['insights']['comparison']['rows']
        missing=[r for r in rows if r['current']['metric_count']==0 and r['current']['count']]
        self.assertEqual(len(missing),1)
        self.assertEqual(missing[0]['current']['display'],'—')
        self.assertEqual(missing[0]['coverage'],'0')
        self.assertIsNone(missing[0]['change'])
        _,context=self.render(self.base+'&scope=company&breakdown=vehicle')
        self.assertFalse(context['insights']['comparison']['ready'])
        self.assertEqual(context['insights']['comparison']['rows'],[])

    def test_period_comparison_discloses_vehicle_change(self):
        v=self.m.Vehicle(company_code='TEST',chassis_number='previous-vehicle')
        self.m.db.session.add(v);self.m.db.session.flush()
        old=self.save(9,day='2026-09-10',distance='30',count='3');old.vehicle_record_id=v.id
        self.m.db.session.commit()
        _,context=self.render('/safety/driving-reports?period=custom&start=2026-10-01&end=2026-10-26&breakdown=people')
        row=context['insights']['comparison']['rows'][0]
        self.assertEqual(row['current']['display'],'5')
        self.assertEqual(row['previous']['display'],'10')
        self.assertEqual(row['change'],'-5')
        self.assertTrue(row['conditions_changed'])

    def test_completion_is_independent_from_improvement_and_history_preserved(self):
        endpoint='/safety/driving-reports/'+str(self.a.id)+'/review'
        result=self.client.post(endpoint,data={'version':version(self.a),'state':'completed','action':'早めの減速'})
        self.assertEqual(result.status_code,302)
        self.m.db.session.refresh(self.a)
        self.assertEqual(payload(self.a)['review']['outcome'],'')
        result=self.client.post(endpoint,data={'version':version(self.a),'state':'completed','outcome':'improved'})
        self.assertEqual(result.status_code,400)
        result=self.client.post(endpoint,data={'version':version(self.a),'state':'completed','outcome':'continue','comparison_note':'道路条件が異なるため継続確認'})
        self.assertEqual(result.status_code,302)
        key=driver_keys([self.a])[0][self.a.id]
        _,context=self.render(self.base+'&focus='+key)
        item=context['insights']['followups'][0]
        self.assertEqual(item['review']['outcome'],'continue')
        self.assertEqual(len(item['events']),2)
        self.assertEqual(item['events'][1]['action'],'早めの減速')

    def test_general_user_cannot_request_other_driver_comparison(self):
        from dkss_app import driving_access
        from flask import session
        self.m.db.session.add(self.m.User(company_code='TEST',username='one',role='user',password='unused',last_name='本人',password_changed_at='stamp'))
        self.m.db.session.commit()
        with self.m.app.test_request_context():
            session.update(company_code='TEST',username='admin',role='admin')
            driving_access.assign([self.a],'one','admin');self.m.db.session.commit()
        with self.client.session_transaction() as state:state.update(username='one',role='user',password_changed_at='stamp')
        _,context=self.render(self.base+'&scope=company&breakdown=vehicle&vehicle='+str(self.a.vehicle_record_id))
        comparison=context['insights']['comparison']
        self.assertEqual(comparison['mode'],'vehicles')
        self.assertEqual(len(comparison['rows']),1)
        self.assertNotIn('小山の人',str(comparison))
        grant=DrivingReportReader.query.one();self.m.db.session.delete(grant);self.m.db.session.commit()
        _,context=self.render(self.base+'&scope=company&breakdown=offices')
        self.assertEqual(context['insights']['comparison']['rows'],[])


if __name__=='__main__':unittest.main()
