"""Unknown or conflicting identities are operations, never invented people."""
import csv
import io
import json
import unittest
from driving_report_data import payload
from dkss_app import driving_access
from flask import session
import test_driving_workspace as workspace_tests


class IdentityCountTests(unittest.TestCase):
    setUpClass=classmethod(workspace_tests.WorkspaceTests.setUpClass.__func__)
    tearDownClass=classmethod(workspace_tests.WorkspaceTests.tearDownClass.__func__)
    setUp=workspace_tests.WorkspaceTests.setUp
    tearDown=workspace_tests.WorkspaceTests.tearDown
    save=workspace_tests.WorkspaceTests.save
    render=workspace_tests.WorkspaceTests.render

    def unknown(self,row):
        data=payload(row);data['driver_code']=None;row.details_json=json.dumps(data);self.m.db.session.commit()

    def assign(self,rows,username):
        with self.m.app.test_request_context():
            session.update(company_code='TEST',username='admin',role='admin')
            driving_access.assign(rows,username,'admin');self.m.db.session.commit()

    def test_unknown_same_names_are_not_counted_as_people_in_office_or_export(self):
        self.unknown(self.a);self.save(8,code=None,name='乗務員A',distance='80')
        response,context=self.render(self.base+'&scope=company')
        office=next(o for o in context['insights']['office_summaries'] if o['name']=='安城')
        self.assertEqual((office['driver_count'],office['unidentified_count'],office['summary']['count']),(0,2,2))
        self.assertEqual(office['summary']['distance'],100)
        self.assertEqual(context['insights']['identity_counts']['driver_count'],1)
        self.assertNotIn('0人',response.get_data(as_text=True))
        response=self.client.get('/safety/driving-reports/export.csv?period=all&scope=company&breakdown=offices&view=breakdown')
        rows=list(csv.DictReader(io.StringIO(response.data.decode('utf-8-sig'))))
        row=next(r for r in rows if r['対象']=='安城')
        self.assertEqual(row['識別できた乗務員数'],'0');self.assertEqual(row['乗務員未確認の運行数'],'2')
        self.assertNotIn('他社の秘密',response.data.decode('utf-8-sig'))

    def test_conflicting_names_remain_unknown_until_explicit_account_confirmation(self):
        second=self.save(8,code='A',name='異なる氏名')
        _,context=self.render(self.base)
        self.assertEqual(context['insights']['identity_counts']['driver_count'],0)
        self.assertEqual(context['insights']['identity_counts']['unidentified_count'],2)
        self.m.db.session.add(self.m.User(company_code='TEST',username='one',role='user',password='unused',last_name='本人',password_changed_at='stamp'))
        self.m.db.session.commit();self.assign([self.a,second],'one')
        _,context=self.render(self.base)
        self.assertEqual(context['insights']['identity_counts']['driver_count'],1)
        self.assertEqual(context['insights']['identity_counts']['unidentified_count'],0)
        data=payload(second);data['office_name']='小山';second.details_json=json.dumps(data);self.m.db.session.commit()
        _,company=self.render(self.base+'&scope=company')
        self.assertEqual(company['insights']['identity_counts']['driver_count'],2)
        self.assertEqual(sum(o['driver_count'] for o in company['insights']['office_summaries']),3)
        data['office_name']='安城';second.details_json=json.dumps(data);self.m.db.session.commit()
        self.assign([self.a,second],'')
        _,context=self.render(self.base)
        self.assertEqual(context['insights']['identity_counts']['driver_count'],0)

    def test_cancelled_unknown_records_and_no_report_roster_never_inflate_counts(self):
        self.unknown(self.a);cancelled=self.save(8,code=None,name='取消の人')
        data=payload(cancelled);data['lifecycle']='cancelled';cancelled.details_json=json.dumps(data);self.m.db.session.commit()
        _,context=self.render(self.base)
        counts=context['insights']['identity_counts']
        self.assertEqual((counts['driver_count'],counts['unidentified_count']),(0,1))
        self.assertTrue(any(not p['has_records'] for p in context['insights']['drivers']))
        _,empty=self.render('/safety/driving-reports?period=custom&start=2030-01-01&end=2030-01-02')
        self.assertEqual(empty['insights']['identity_counts']['identity_display'],'記録なし')

    def test_user_company_query_does_not_expand_counts_or_office_candidates(self):
        self.unknown(self.a)
        self.m.db.session.add(self.m.User(company_code='TEST',username='one',role='user',password='unused',last_name='本人',password_changed_at='stamp'))
        self.m.db.session.commit();self.assign([self.a],'one')
        with self.client.session_transaction() as state:state.update(username='one',role='user',password_changed_at='stamp')
        response,context=self.render(self.base+'&scope=company')
        self.assertEqual(context['insights']['identity_counts']['driver_count'],1)
        self.assertEqual(context['insights']['identity_counts']['unidentified_count'],0)
        self.assertNotIn('小山の人',response.get_data(as_text=True))
        self.assertEqual(context['insights']['office_choices'],[])


if __name__=='__main__':unittest.main()
