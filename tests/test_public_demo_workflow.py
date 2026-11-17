import time
import unittest
from unittest.mock import patch
from test_q02_daily_inspection_flow import Q02DailyInspectionFlowTests as Base

class DemoWorkflowTests(Base):
    @classmethod
    def setUpClass(cls):
        from dkss_app import create_app, models
        from dkss_app.extensions import db, limiter
        cls.db,cls.models=db,models
        with patch.dict('os.environ',{'SECRET_KEY':'demo-workflow-test','RENDER':'','DATABASE_URL':'sqlite://','OPENAI_API_KEY':'','SMTP_HOST':'','S3_BUCKET_NAME':'','VAPID_PRIVATE_KEY':'','VAPID_PUBLIC_KEY':''}):
            cls.app=create_app({'TESTING':True,'SQLALCHEMY_DATABASE_URI':'sqlite://','WTF_CSRF_ENABLED':False,
                'PUBLIC_DEMO_CANDIDATE':True,'PUBLIC_DEMO_WORKFLOW':True,'PUBLIC_DEMO_COMPANY':'A',
                'PUBLIC_DEMO_USERNAME':'checker','PUBLIC_DEMO_DRIVER':'checker','PUBLIC_DEMO_MANAGER':'admin',
                'PUBLIC_DEMO_EPOCH':'test','PUBLIC_DEMO_UNTIL':int(time.time())+3600,'PUBLIC_DEMO_VEHICLE_ID':1,
                'PUBLIC_DEMO_CHECKLIST_ID':1,'PUBLIC_DEMO_DAY':'2026-10-23'})
        limiter.enabled=False
    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():cls.db.session.remove();cls.db.engine.dispose()
    def setUp(self):
        self.demo_active=False
        super().setUp()
        self.request('GET','/vehicle/checklists')
        self.app.config['PUBLIC_DEMO_CHECKLIST_ID']=self.models.Checklist.query.filter_by(company_code='A').one().id
        self.demo_active=True
    def login(self,username,company='A'):
        prior=None
        if hasattr(self,'client'):
            with self.client.session_transaction() as s:prior=s.get('demo_result_id')
        super().login(username,company)
        if self.demo_active:
            with self.client.session_transaction() as s:
                s.update(aonagi_readonly_demo=True,demo_role='manager' if username=='admin' else 'driver',
                    demo_epoch='test',demo_until=self.app.config['PUBLIC_DEMO_UNTIL'],public_demo_token='isolated-fixture-demo-session-token')
                if prior:s['demo_result_id']=prior
                from dkss_app.public_demo_sessions import issue
                issue(s)
    def begin(self,defect=False):
        import json
        self.login('checker')
        self.checklist=self.models.Checklist.query.filter_by(company_code='A').one()
        items=json.loads(self.checklist.items_json)
        self.check_count=sum(item['item_type']=='check' for item in items)
        self.form={'vehicle_record_id':1,'year':'2026','month':'10','day':'23'}
        import html,re
        page=self.request('GET',f'/vehicle/checklists/{self.checklist.id}',query_string={**self.form,'active_day':'23'})
        self.form['csrf_token']=html.unescape(re.search(r'name="csrf_token" value="([^"]+)"',page.get_data(as_text=True))[1])
        for no in range(self.check_count):self.save(no,'×' if defect and no==0 else '✓')
        self.row=self.models.VehicleChecklistResult.query.filter_by(company_code='A').one()
        self.complete()
        self.db.session.refresh(self.row)
        self.assertEqual(self.row.status,'承認待ち')
        return self.row
    def test_demo_actions_follow_mobile_navigation_inside_main(self):
        # The menu is fixed at the viewport top. The demo notice must not
        # precede the shell: only content below its opaque sticky top bar
        # is protected from the menu, including during document scrolling.
        self.app.config['PUBLIC_DEMO_SHARED_COMPANY'] = True
        self.addCleanup(self.app.config.pop, 'PUBLIC_DEMO_SHARED_COMPANY', None)
        self.login('admin')
        for path in ('/', '/safety/driving-reports', '/vehicle/checklists'):
            with self.subTest(path=path):
                page = self.request('GET', path, follow_redirects=True)
                self.assertEqual(page.status_code, 200)
                html = page.get_data(as_text=True)
                main = html.index('<main class="main-content">')
                top_bar = html.index('<div class="top-bar', main)
                notice = html.index('class="alert public-demo-notice"')
                self.assertLess(main, top_bar)
                self.assertLess(top_bar, notice)
                self.assertLess(notice, html.index('</main>', main))
                self.assertEqual(html.count('class="alert public-demo-notice"'), 1)
                self.assertEqual(html.count('action="/demo/role"'), 1)
                self.assertIn('運転者役で見る', html[notice:])
                self.assertIn('管理者役で確認する', html[notice:])

    def test_demo_real_input_to_judgment_no_external_delivery(self):
        from dkss_app.extensions import limiter
        limiter.enabled=True;limiter.reset()
        self.addCleanup(setattr,limiter,'enabled',False)
        self.app.config['WTF_CSRF_ENABLED']=True
        self.addCleanup(self.app.config.update, WTF_CSRF_ENABLED=False)
        with patch('dkss_app.notifications_delivery.send_web_push_notification') as push, patch('dkss_app.notifications_delivery.send_email_notification') as mail:
            self.begin(defect=True)
            with self.client.session_transaction() as s:self.assertEqual(s['demo_result_id'],self.row.id)
            import html,re
            page=self.request('GET',f'/vehicle/checklists/{self.checklist.id}',query_string={**self.form,'active_day':'23'})
            token=html.unescape(re.search(r'name="csrf_token" value="([^"]+)"',page.get_data(as_text=True))[1])
            switched=self.request('POST','/demo/role',data={'role':'manager','csrf_token':token})
            self.assertEqual(switched.status_code,302)
            with self.client.session_transaction() as state:self.assertEqual(state['username'],'admin')
            response=self.request('POST',f'/vehicle/checklist-results/{self.row.id}/operation-judgment',data={**self.decision_data('運行不可'),'csrf_token':token})
            self.assertEqual(response.status_code,302)
            self.assertEqual(self.state()['status'],'運行不可')
            self.assertTrue(self.models.Notification.query.filter_by(company_code='A',target_username='checker',title='車両の運行判断：運行不可').first())
            push.assert_not_called();mail.assert_not_called()
    def test_release_window_and_fixed_principal_identities(self):
        import html,re
        driver=self.models.User.query.filter_by(company_code='A',username='checker').one()
        manager=self.models.User.query.filter_by(company_code='A',username='admin').one()
        settings={'PUBLIC_DEMO_SHARED_COMPANY':True,'PUBLIC_DEMO_RELEASE':True,'PUBLIC_DEMO_FROM':int(time.time())+100,
            'PUBLIC_DEMO_DRIVER_IDENTITY':driver.account_identity,'PUBLIC_DEMO_MANAGER_IDENTITY':manager.account_identity}
        self.app.config.update(settings)
        for key in settings:self.addCleanup(self.app.config.pop,key,None)
        self.client=self.app.test_client()
        self.assertEqual(self.request('GET','/demo').status_code,404)
        self.app.config['PUBLIC_DEMO_FROM']=int(time.time())-1
        self.assertEqual(self.request('GET','/demo').location,'/')
        page=self.request('GET','/')
        token=html.unescape(re.search(r'name="csrf_token" value="([^\"]+)"',page.get_data(as_text=True))[1])
        self.app.config['PUBLIC_DEMO_MANAGER_IDENTITY']='wrong-person'
        self.assertEqual(self.request('POST','/demo/role',data={'role':'manager','csrf_token':token}).status_code,404)
        self.app.config['PUBLIC_DEMO_MANAGER_IDENTITY']=manager.account_identity
        self.assertEqual(self.request('POST','/demo/role',data={'role':'manager','csrf_token':token}).status_code,302)

    def test_shared_company_uses_normal_dates_vehicles_and_unbound_role_switch(self):
        import html,re
        self.app.config['PUBLIC_DEMO_SHARED_COMPANY']=True
        self.addCleanup(self.app.config.pop,'PUBLIC_DEMO_SHARED_COMPANY',None)
        self.client=self.app.test_client()
        self.assertEqual(self.request('GET','/demo').location,'/')
        self.assertEqual(self.request('GET','/').status_code,200)
        self.assertEqual(self.request('GET','/vehicle/checklists',follow_redirects=True).status_code,200)
        index=self.app.config['PUBLIC_DEMO_CHECKLIST_ID']
        form={'vehicle_record_id':1,'year':'2026','month':'10','day':'24','item_no':'0','value':'✓'}
        response=self.request('POST',f'/vehicle/checklists/{index}/save-one',data=form)
        self.assertEqual(response.status_code,302)
        row=self.models.VehicleChecklistResult.query.filter_by(company_code='A').one()
        self.assertEqual(int(row.day),24)
        page=self.request('GET',f'/vehicle/checklists/{index}',query_string={**form,'active_day':24})
        self.assertEqual(page.status_code,200)
        token=html.unescape(re.search(r'name="csrf_token" value="([^\"]+)"',page.get_data(as_text=True))[1])
        self.assertEqual(self.request('POST','/demo/role',data={'role':'manager','csrf_token':token}).status_code,302)
        self.assertEqual(self.request('GET','/vehicle/karte/2').status_code,404)
        self.assertEqual(self.request('GET','/itc').status_code,403)
        self.assertEqual(self.request('POST','/settings',data={}).status_code,403)
        self.assertIn(self.request('POST','/switch-user',data={}).status_code,(403,404))
        for method,path in [('GET','/master/drivers/new'),('POST','/master/drivers/1/edit'),('POST','/master/drivers/1/delete'),('GET','/master/registration'),('POST','/settings/email/verify'),('POST','/notifications/email-test'),('POST','/api/push/test')]:
            self.assertEqual(self.request(method,path,data={}).status_code,403,path)
        from dkss_app.notifications_delivery import send_email_notification,send_web_push_notification
        with self.app.test_request_context('/'):
            from flask import session
            session['aonagi_readonly_demo']=True
            self.assertFalse(send_email_notification(object(),'test','test',require_opt_in=False))
            self.assertFalse(send_web_push_notification(object(),'test','test'))


    def test_next_visitor_reuses_only_fixed_shared_result_and_cleanup(self):
        self.begin()
        row_id=self.row.id
        self.client=self.app.test_client()
        self.assertEqual(self.request('GET','/demo').status_code,302)
        with self.client.session_transaction() as state:
            self.assertEqual(state['demo_result_id'],row_id)
        for field,value in [('checked_by_identity','another-owner'),('day',24),('vehicle_record_id',2),('company_code','B'),('status','入力中')]:
            original=getattr(self.row,field)
            setattr(self.row,field,value);self.db.session.commit()
            self.assertEqual(self.request('GET','/demo').status_code,302)
            with self.client.session_transaction() as state:
                self.assertNotIn('demo_result_id',state,field)
            setattr(self.row,field,original);self.db.session.commit()
        self.db.session.delete(self.row);self.db.session.commit()
        self.client=self.app.test_client()
        self.assertEqual(self.request('GET','/demo').status_code,302)
        with self.client.session_transaction() as state:
            self.assertNotIn('demo_result_id',state)

    def test_real_ui_async_completion_binds_result(self):
        def async_complete():
            proof=Base.selection_proof(self)
            response=self.request('POST',f'/vehicle/checklists/{self.checklist.id}/complete',
                data={**self.form,'approval_notify_users_0':'admin',**proof},headers={'X-DKSS-Final-Submit':'1'})
            self.assertEqual(response.status_code,200)
            self.assertTrue(response.get_json()['success'])
        with patch.object(self,'complete',async_complete):
            self.begin()
        with self.client.session_transaction() as state:
            self.assertEqual(state['demo_result_id'],self.row.id)

    def test_demo_rejects_other_vehicle_day_and_recipient(self):
        self.login('checker');index=self.app.config['PUBLIC_DEMO_CHECKLIST_ID']
        base={'vehicle_record_id':'1','year':'2026','month':'10','day':'23','item_no':'0','value':'✓'}
        for patch_data in [{'vehicle_record_id':'2'},{'day':'24'},{'value':'injected'}]:
            response=self.request('POST',f'/vehicle/checklists/{index}/save-one',data={**base,**patch_data})
            self.assertEqual(response.status_code,403)
        response=self.request('POST',f'/vehicle/checklists/{index}/complete',data={**base,'approval_notify_users_0':'outsider'})
        self.assertEqual(response.status_code,403)
        self.assertEqual(self.models.VehicleChecklistResult.query.count(),0)
    def test_role_switch_rejects_old_password_generation(self):
        import html,re
        self.login('checker')
        page=self.request('GET','/vehicle/karte/1')
        token=html.unescape(re.search(r'name="csrf_token" value="([^"]+)"',page.get_data(as_text=True))[1])
        with self.client.session_transaction() as state:state['password_changed_at']='old-generation'
        response=self.request('POST','/demo/role',data={'role':'driver','csrf_token':token})
        self.assertEqual(response.status_code,302)
        self.assertIn('/login',response.location)
        with self.client.session_transaction() as state:self.assertNotIn('username',state)
    def test_failed_active_issue_never_leaves_an_ordinary_authenticated_cookie(self):
        self.client=self.app.test_client()
        class BrokenStore:
            def set(self,*args,**kwargs):raise ConnectionError('isolated failure')
        with patch('dkss_app.public_demo_sessions._store',return_value=BrokenStore()):
            self.assertEqual(self.request('GET','/demo').status_code,503)
        with self.client.session_transaction() as state:
            self.assertNotIn('username',state)
        self.assertIn('/login',self.request('GET','/vehicle/karte/1').location)

    def test_missing_or_unavailable_demo_active_state_fails_closed(self):
        with self.client.session_transaction() as state:state.clear()
        self.assertEqual(self.request('GET','/demo').status_code,302)
        self.app.extensions['public_demo_active_sessions'].clear()
        self.assertEqual(self.request('GET','/vehicle/karte/1').status_code,410)
        self.assertEqual(self.request('GET','/demo').status_code,302)
        class BrokenStore:
            def get(self,key):raise ConnectionError('isolated failure')
        with patch('dkss_app.public_demo_sessions._store',return_value=BrokenStore()):
            self.assertEqual(self.request('GET','/vehicle/karte/1').status_code,503)

    def test_role_switch_rejects_logged_out_demo_cookie(self):
        import html,re
        with self.client.session_transaction() as state:state.clear()
        self.assertEqual(self.request('GET','/demo').status_code,302)
        page=self.request('GET','/vehicle/karte/1')
        token=html.unescape(re.search(r'name="csrf_token" value="([^\"]+)"',page.get_data(as_text=True))[1])
        copy=self.app.test_client();name=self.app.config['SESSION_COOKIE_NAME']
        copy.set_cookie(name,self.client.get_cookie(name).value)
        self.assertEqual(self.request('POST','/logout',data={'csrf_token':token}).status_code,302)
        self.assertEqual(copy.post('/demo/role',data={'role':'driver','csrf_token':token}).status_code,410)

    def test_role_switch_requires_csrf(self):
        self.login('checker')
        self.assertEqual(self.request('POST','/demo/role',data={'role':'manager'}).status_code,400)
        self.assertEqual(self.request('GET','/demo/role').status_code,405)

# Only new demo tests; inherited Base tests retain ordinary assumptions.
for name in list(vars(Base)):
    if name.startswith('test_') and name not in DemoWorkflowTests.__dict__:
        setattr(DemoWorkflowTests,name,None)
if __name__=='__main__':unittest.main()
