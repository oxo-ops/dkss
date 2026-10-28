"""Organization navigation, aggregate provenance, privacy and async AI lifecycle."""
from identity_fixture import identity_for
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from urllib.parse import urlencode
from flask import template_rendered
import test_workflow_regressions as workflow
import test_driving_report_insights as insight_tests
from driving_report_data import payload, version
from driving_report_insights import digest, driver_keys
from driving_report_reflection import validate_result
from dkss_app.models import Office, Driver, DrivingReportReflection, DrivingReportReader


class WorkspaceTests(unittest.TestCase):
    setUpClass=classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass=classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    tearDown=workflow.WorkflowRegressionTests.tearDown
    save=insight_tests.DrivingInsightRouteTests.save

    def setUp(self):
        workflow.WorkflowRegressionTests.setUp(self)
        self.m.User.query.filter_by(username='admin').one().office='安城'
        for company,name in [('TEST','安城'),('TEST','小山'),('OTHER','秘密営業所')]:
            self.m.db.session.add(Office(company_code=company,name=name))
        for code,name,office in [('A','乗務員A','安城'),('B','乗務員B','小山'),('C','記録なしの人','安城')]:
            self.m.db.session.add(Driver(company_code='TEST',employee_id=code,name=name,office=office))
        self.m.db.session.commit()
        self.a=self.save(1,distance='20',count='1')
        self.b=self.save(2,distance='100',count='2',code='B',name='小山の人',office_name='小山')
        self.secret=self.save(3,name='他社の秘密',code='X',office_name='秘密営業所')
        self.secret.company_code='OTHER';self.m.db.session.commit()
        self.base='/safety/driving-reports?period=all'

    def render(self,url):
        contexts=[]
        def capture(sender,template,context,**extra):contexts.append(context)
        template_rendered.connect(capture,self.m.app)
        try:response=self.client.get(url)
        finally:template_rendered.disconnect(capture,self.m.app)
        self.assertEqual(response.status_code,200,response.get_data(as_text=True))
        return response,contexts[-1]

    def test_default_office_roster_and_company_drilldown(self):
        response,context=self.render(self.base)
        self.assertEqual(context['insights']['scope_name'],'安城')
        self.assertEqual(context['insights']['summary']['count'],1)
        html=response.get_data(as_text=True)
        self.assertIn('記録なしの人',html);self.assertNotIn('小山の人',html);self.assertNotIn('秘密営業所',html)
        response,context=self.render(self.base+'&scope=company')
        self.assertIn('営業所別の分析',response.get_data(as_text=True))
        self.assertEqual(context['insights']['summary']['distance'],120)
        self.assertEqual(context['insights']['highlights'][0]['current']['display'],'2.5')
        response,context=self.render(self.base+'&scope=office&office='+digest(['office','小山']))
        self.assertEqual(context['insights']['summary']['count'],1)
        self.assertIn('小山の人',response.get_data(as_text=True));self.assertNotIn('乗務員A',response.get_data(as_text=True))

    def test_unknown_office_fails_closed_and_invalid_office_is_rejected(self):
        self.m.User.query.filter_by(username='admin').one().office=None;self.m.db.session.commit()
        response,context=self.render(self.base)
        self.assertTrue(context['insights']['scope_missing']);self.assertEqual(context['total'],0)
        self.assertNotIn('乗務員A',response.get_data(as_text=True))
        self.assertEqual(self.client.get(self.base+'&office=秘密営業所').status_code,400)

    def test_focus_filters_report_list_and_every_export(self):
        key=driver_keys([self.a])[0][self.a.id]
        response,context=self.render(self.base+'&scope=company&focus='+key)
        self.assertEqual([r.id for r in context['insights']['reader_rows']],[self.a.id])
        self.assertEqual(context['total'],1)
        # A company-level person detail may show other recorded users of the same vehicle.
        # The person's report list and exports must still contain only that person's records.
        self.assertNotIn('小山の人',response.get_data(as_text=True).split('id="report-list"')[-1])
        for suffix in ['','&view=comparison']:
            response=self.client.get('/safety/driving-reports/export.csv?period=all&scope=company&focus='+key+suffix)
            self.assertEqual(response.status_code,200);self.assertNotIn('小山の人',response.data.decode('utf-8-sig'))
        response=self.client.get('/safety/driving-reports/export.csv?period=all&office=小山')
        self.assertNotIn('乗務員A',response.data.decode('utf-8-sig'));self.assertIn('小山の人',response.data.decode('utf-8-sig'))

    def test_ai_get_is_free_and_pending_is_deduplicated(self):
        response,context=self.render(self.base)
        form=dict(context['filters'],input_key=context['reflection']['key'])
        executor=self.m.app.extensions['driving_reflection_executor']
        with patch('driving_report_reflection.generate',side_effect=AssertionError('GET never generates')):
            self.assertEqual(self.client.get('/safety/driving-reports/reflection?period=all').status_code,200)
        with patch.dict('os.environ',{'OPENAI_API_KEY':'test-only'}),patch.object(executor,'submit') as submit:
            self.assertEqual(self.client.post('/safety/driving-reports/reflection',data=form).status_code,202)
            self.assertEqual(self.client.post('/safety/driving-reports/reflection',data=form).status_code,202)
            submit.assert_called_once()
            work,args=submit.call_args.args[0],submit.call_args.args[1:]
            document=args[-1]
            self.assertNotIn('小山の人',json.dumps(document,ensure_ascii=False))
            self.assertNotIn('他社',json.dumps(document,ensure_ascii=False))
        with patch('driving_report_reflection.generate',return_value={'items':[{'evidence_id':'0','action':'review_context'}]}):
            with ThreadPoolExecutor(max_workers=1) as worker:worker.submit(work,*args).result(timeout=10)
        self.m.db.session.expire_all()
        state=self.client.get('/safety/driving-reports/reflection?period=all').json
        self.assertEqual(state['status'],'completed');self.assertEqual(len(state['items']),1)
        old_key=state['key'];self.a=self.m.VehicleDrivingReportRecord.query.get(self.a.id)
        p=payload(self.a);p['distance']='25';self.a.details_json=json.dumps(p);self.m.db.session.commit()
        state=self.client.get('/safety/driving-reports/reflection?period=all').json
        self.assertEqual(state['status'],'new');self.assertNotEqual(state['key'],old_key)
        with patch.dict('os.environ',{'OPENAI_API_KEY':'test-only'}),patch('driving_report_reflection.generate',side_effect=AssertionError('GET never generates')):
            refreshed=self.client.get('/safety/driving-reports/reflection?period=all').json
            self.assertTrue(refreshed['auto_refresh'])
            # A different scope has no subscription and needs an explicit first request.
            other=self.client.get('/safety/driving-reports/reflection?period=all&scope=company').json
            self.assertFalse(other['auto_refresh'])
        self.assertEqual(self.client.post('/safety/driving-reports/reflection',data=form).status_code,409)

    def test_failed_generation_and_invalid_evidence_are_not_success(self):
        _,context=self.render(self.base);form=dict(context['filters'],input_key=context['reflection']['key'])
        executor=self.m.app.extensions['driving_reflection_executor']
        with patch.dict('os.environ',{'OPENAI_API_KEY':'test-only'}),patch.object(executor,'submit') as submit:
            self.client.post('/safety/driving-reports/reflection',data=form)
        work,*args=submit.call_args.args
        with patch('driving_report_reflection.generate',return_value={'items':[{'evidence_id':'other-company','action':'maintenance'}]}):
            with ThreadPoolExecutor(max_workers=1) as worker:worker.submit(work,*args).result(timeout=10)
        self.m.db.session.expire_all()
        self.assertEqual(self.client.get('/safety/driving-reports/reflection?period=all').json['status'],'failed')

    def test_user_ai_input_and_cached_results_remain_private_after_revocation(self):
        self.m.db.session.add(self.m.User(company_code='TEST',username='one',role='user',password='unused',last_name='本人',password_changed_at='stamp'))
        self.m.db.session.commit()
        from dkss_app import driving_access
        from flask import session
        with self.m.app.test_request_context():
            session.update(account_identity=identity_for('TEST', 'admin'), company_code='TEST',username='admin',role='admin')
            driving_access.assign([self.a],'one','admin');self.m.db.session.commit()
        with self.client.session_transaction() as state:state.update(account_identity=identity_for(state.get('company_code'), 'one', app=(self.client).application), username='one',role='user',password_changed_at='stamp')
        _,context=self.render(self.base+'&scope=company&office=小山')
        self.assertEqual(context['filters']['scope'],'self')
        self.assertEqual(context['total'],1)
        state=self.client.get('/safety/driving-reports/reflection?period=all&scope=company').json
        self.assertEqual(state['status'],'new');self.assertNotIn('小山の人',str(state))
        grant=DrivingReportReader.query.one();self.m.db.session.delete(grant);self.m.db.session.commit()
        state=self.client.get('/safety/driving-reports/reflection?period=all').json
        self.assertEqual(state['status'],'empty')

    def test_missing_key_is_actionable_and_does_not_queue(self):
        _,context=self.render(self.base)
        with patch.dict('os.environ',{'OPENAI_API_KEY':''}):
            response=self.client.post('/safety/driving-reports/reflection',data=dict(context['filters'],input_key=context['reflection']['key']))
        self.assertEqual(response.status_code,503);self.assertEqual(DrivingReportReflection.query.count(),0)

    def test_duplicate_source_cannot_supply_a_different_offices_values(self):
        old=payload(self.a);old['office_name']='小山';old['distance']='999'
        self.a.details_json=json.dumps(old);self.m.db.session.commit()
        self.save(9,report_number='R1',distance='20',count='1',office_name='安城')
        _,context=self.render(self.base)
        self.assertEqual(context['insights']['summary']['distance'],20)
        self.assertEqual(context['insights']['summary']['count'],1)

    def test_ai_cannot_invent_an_evidence_id_or_choose_unsupported_action(self):
        document={'evidence':[{'id':'source-1','allowed_actions':['verify_data'],'finding':'原本値','reports':[1]}]}
        for item in [{'evidence_id':'missing','action':'verify_data'}, {'evidence_id':'source-1','action':'maintenance'}]:
            with self.assertRaises(ValueError):validate_result({'items':[item]},document)
        result=validate_result({'items':[{'evidence_id':'source-1','action':'verify_data','finding':'架空の数値'}]},document)
        self.assertEqual(result['items'][0]['finding'],'原本値')


if __name__=='__main__':unittest.main()
