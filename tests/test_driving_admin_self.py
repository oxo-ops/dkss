"""Managers retain authority while requesting a strictly personal report scope."""
from identity_fixture import identity_for
import json
import unittest
from unittest.mock import patch

from flask import session, template_rendered
import test_workflow_regressions as workflow
import test_driving_report_insights as insight_tests
from dkss_app import driving_access
from dkss_app.models import DrivingReportReader, VehicleChecklistResult


class AdminSelfTests(unittest.TestCase):
    setUpClass=classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass=classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    tearDown=workflow.WorkflowRegressionTests.tearDown
    save=insight_tests.DrivingInsightRouteTests.save

    def setUp(self):
        workflow.WorkflowRegressionTests.setUp(self)
        self.admin=self.m.User.query.filter_by(username='admin').one();self.admin.office='安城'
        self.other=self.m.User(company_code='TEST',username='two',role='user',password='unused',last_name='他人',password_changed_at='stamp')
        self.itc=self.m.User(company_code='TEST',username='support',role='itc',password='unused',last_name='兼務者',password_changed_at='stamp')
        self.m.db.session.add_all([self.other,self.itc]);self.m.db.session.commit()
        self.own=self.save(1,name='管理者本人の運行',distance='20',count='1')
        self.theirs=self.save(2,name='他人の運行秘密',code='B',distance='100',count='2')
        self.support=self.save(3,name='兼務者の運行',code='C',distance='50',count='1')
        self.bind(self.own,'admin');self.bind(self.theirs,'two');self.bind(self.support,'support')
        self.base='/safety/driving-reports?period=all'

    def bind(self,row,username):
        with self.m.app.test_request_context():
            session.update(account_identity=identity_for('TEST', 'admin'), company_code='TEST',username='admin',role='admin')
            driving_access.assign([row],username,'admin');self.m.db.session.commit()

    def render(self,url):
        contexts=[]
        def capture(sender,template,context,**kw):contexts.append(context)
        template_rendered.connect(capture,self.m.app)
        try:response=self.client.get(url)
        finally:template_rendered.disconnect(capture,self.m.app)
        self.assertEqual(response.status_code,200,response.get_data(as_text=True))
        return response,contexts[-1]

    def test_admin_self_has_only_confirmed_own_records_and_keeps_scope_switch(self):
        response,ctx=self.render(self.base+'&scope=self&focus='+driving_access.account_key(DrivingReportReader.query.filter_by(user_id=self.other.id).one()))
        self.assertEqual(ctx['total'],1)
        self.assertEqual(ctx['insights']['summary']['distance'],20)
        self.assertEqual(ctx['filters']['scope'],'self')
        self.assertTrue(ctx['driving_can_manage']);self.assertFalse(ctx['driving_is_admin'])
        self.assertEqual(ctx['vehicle_history'],[])
        self.assertEqual(ctx['driving_vehicles']['user_id'],self.admin.id)
        html=response.get_data(as_text=True)
        self.assertIn('自分の運転実績',html);self.assertIn('自分の実績</a>',html)
        self.assertIn('管理画面</a>',html);self.assertNotIn('他人の運行秘密',html)
        self.assertNotIn('id="driver-comparison"',html)
        self.assertEqual(ctx['insights']['shared_vehicle_usage'],{})
        with self.client.session_transaction() as state:self.assertEqual(state['role'],'admin')

    def test_default_office_and_company_access_are_preserved(self):
        _,ctx=self.render(self.base)
        self.assertEqual(ctx['filters']['scope'],'office');self.assertEqual(ctx['total'],3)
        _,ctx=self.render(self.base+'&office=__self__')
        self.assertEqual(ctx['total'],1)
        _,ctx=self.render(self.base+'&scope=self&office=__company__')
        self.assertEqual(ctx['filters']['scope'],'company');self.assertEqual(ctx['total'],3)
        self.assertEqual(self.client.get(f'/safety/driving-reports/{self.theirs.id}').status_code,200)

    def test_readership_setting_accepts_admin_and_itc_without_role_change(self):
        from driving_report_data import version
        response=self.client.post(f'/safety/driving-reports/{self.own.id}/reader',data={
            'version':version(self.own),'reader_username':'admin'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(DrivingReportReader.query.filter_by(report_id=self.own.id).one().user_id,self.admin.id)
        html=self.client.get(f'/safety/driving-reports/{self.own.id}').get_data(as_text=True)
        self.assertIn('value="admin"',html);self.assertIn('value="support"',html)
        self.assertEqual(self.admin.role,'admin')

    def test_exports_csv_comparison_and_pdf_use_personal_scope(self):
        for suffix in ['','&view=comparison']:
            response=self.client.get('/safety/driving-reports/export.csv?period=all&scope=self'+suffix)
            self.assertEqual(response.status_code,200)
            text=response.data.decode('utf-8-sig')
            self.assertIn('管理者本人の運行',text);self.assertNotIn('他人の運行秘密',text)
            self.assertNotIn('兼務者の運行',text)
        with patch('driving_report_management.export_pdf',return_value=b'%PDF-fixture') as pdf:
            response=self.client.get('/safety/driving-reports/export.pdf?period=all&scope=self')
            self.assertEqual(response.status_code,200)
            args=str(pdf.call_args)
            self.assertIn('管理者本人の運行',args);self.assertNotIn('他人の運行秘密',args)

    def test_ai_scope_cache_and_evidence_are_distinct_from_manager_view(self):
        _,own=self.render(self.base+'&scope=self')
        _,company=self.render(self.base+'&scope=company')
        self.assertNotEqual(own['reflection']['key'],company['reflection']['key'])
        executor=self.m.app.extensions['driving_reflection_executor']
        form=dict(own['filters'],input_key=own['reflection']['key'])
        with patch.dict('os.environ',{'OPENAI_API_KEY':'isolated-only'}),patch.object(executor,'submit') as submit:
            response=self.client.post('/safety/driving-reports/reflection',data=form)
            self.assertEqual(response.status_code,202)
            document=submit.call_args.args[-1]
            self.assertEqual(document['role'],'self');self.assertEqual(document['scope'],'自分')
            self.assertNotIn('他人の運行秘密',json.dumps(document,ensure_ascii=False))
            self.assertEqual(document['current_affiliations'],[])

    def test_revoked_own_binding_clears_self_but_preserves_manager_rights(self):
        grant=DrivingReportReader.query.filter_by(report_id=self.own.id).one()
        self.m.db.session.delete(grant);self.m.db.session.commit()
        _,ctx=self.render(self.base+'&scope=self')
        self.assertEqual(ctx['total'],0);self.assertEqual(ctx['reflection']['status'],'empty')
        _,ctx=self.render(self.base+'&scope=company');self.assertEqual(ctx['total'],3)

    def test_general_user_cannot_widen_scope_or_assign_a_reader(self):
        with self.client.session_transaction() as state:state.update(account_identity=identity_for(state.get('company_code'), 'two', app=(self.client).application), username='two',role='user',password_changed_at='stamp')
        _,ctx=self.render(self.base+'&scope=company&office=__company__')
        self.assertEqual(ctx['total'],1);self.assertEqual(ctx['filters']['scope'],'self')
        self.assertFalse(ctx['driving_can_manage'])
        self.assertEqual(self.client.post(f'/safety/driving-reports/{self.theirs.id}/reader',data={}).status_code,403)

    def test_itc_self_uses_own_account_and_personal_candidates(self):
        with self.client.session_transaction() as state:state.update(account_identity=identity_for(state.get('company_code'), 'support', app=(self.client).application), username='support',role='itc',password_changed_at='stamp')
        _,ctx=self.render(self.base+'&scope=self')
        self.assertEqual(ctx['total'],1);self.assertEqual(ctx['insights']['summary']['distance'],50)
        with self.m.app.test_request_context():
            session.update(account_identity=identity_for('TEST', 'support'), company_code='TEST',username='support',role='itc')
            self.m.db.session.add(VehicleChecklistResult(company_code='TEST',checklist_id=1,
                vehicle_record_id=self.vehicle.id,year='2026',month='10',day='20',status='点検完了',
                checked_by_username='support',answers_json='[]',
                checklist_snapshot_json=json.dumps({'fixed_template_code':'daily_inspection_truck_trailer'})))
            self.m.db.session.commit()
        _,ctx=self.render(self.base+'&scope=self')
        self.assertEqual(ctx['driving_vehicles']['user_id'],self.itc.id)
        self.assertEqual(len(ctx['driving_vehicles']['candidates']),1)
        item=ctx['driving_vehicles']['candidates'][0]
        response=self.client.post('/safety/driving-reports/vehicle-candidates',data=dict(
            ctx['filters'],inspection_id=item['inspection_id'],revision=item['revision'],
            evidence_key=item['evidence_key'],action='exclude'))
        self.assertEqual(response.status_code,302);self.assertIn('scope=self',response.location)


    def test_one_click_links_keep_conditions_and_restore_company_view(self):
        url='/safety/driving-reports?period=custom&start=2026-10-01&end=2026-10-27&scope=company&vehicle='+str(self.vehicle.id)+'&category=economy&compare=custom&compare_start=2026-09-01&compare_end=2026-09-30'
        _,manager=self.render(url)
        response,own=self.render(manager['driving_view_navigation']['self'])
        self.assertEqual(own['total'],1)
        self.assertNotIn('data-office-select',response.get_data(as_text=True))
        for name in ['period','vehicle','category','compare','compare_start','compare_end']:
            self.assertEqual(own['filters'][name],manager['filters'][name])
        _,back=self.render(own['driving_view_navigation']['manager'])
        self.assertEqual(back['filters']['scope'],'company');self.assertEqual(back['total'],3)
        for name in ['period','vehicle','category','compare','compare_start','compare_end']:
            self.assertEqual(back['filters'][name],manager['filters'][name])

    def test_one_click_restores_office_and_people_search(self):
        _,manager=self.render(self.base+'&driver=他人&listing=people')
        _,own=self.render(manager['driving_view_navigation']['self'])
        self.assertEqual(own['total'],1)
        _,back=self.render(own['driving_view_navigation']['manager'])
        self.assertEqual(back['total'],1);self.assertEqual(back['reports'][0]['row'].id,self.theirs.id)
        self.assertEqual(back['filters']['office'],manager['filters']['office'])
        self.assertEqual(back['filters']['driver'],'他人');self.assertEqual(back['filters']['listing'],'people')

    def test_direct_self_link_returns_to_default_office(self):
        _,own=self.render(self.base+'&scope=self')
        _,back=self.render(own['driving_view_navigation']['manager'])
        self.assertEqual(back['filters']['scope'],'office');self.assertEqual(back['insights']['scope_name'],'安城')

    def test_stale_or_other_account_memory_does_not_change_default(self):
        for memory in [
            {'owner':['OTHER','admin'],'filters':{'scope':'company','driver':'秘密'}},
            {'owner':['TEST','other'],'filters':{'scope':'company','driver':'秘密'}},
            {'owner':['TEST','admin'],'filters':{'scope':'office','office':'removed','driver':'秘密'}},
        ]:
            with self.client.session_transaction() as state:state['driving_manager_view']=memory
            _,own=self.render(self.base+'&scope=self')
            _,back=self.render(own['driving_view_navigation']['manager'])
            self.assertEqual(back['filters']['scope'],'office');self.assertNotIn('秘密',back['filters'].values())

    def test_regular_user_has_no_management_switch(self):
        with self.client.session_transaction() as state:state.update(account_identity=identity_for(state.get('company_code'), 'two', app=(self.client).application), username='two',role='user',password_changed_at='stamp')
        response,ctx=self.render(self.base)
        self.assertIsNone(ctx['driving_view_navigation']);self.assertNotIn('class="driving-view-switch"',response.get_data(as_text=True))


if __name__=='__main__':unittest.main()
