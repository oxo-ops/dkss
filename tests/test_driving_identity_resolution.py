"""Identity follows real report fields; fixtures are not evidence about manufacturers."""
from identity_fixture import identity_for
import json
import unittest
from unittest.mock import patch
from flask import session, template_rendered

import test_workflow_regressions as workflow
from dkss_app import driving_access
from dkss_app.models import DrivingReportReader
from driving_report_data import payload, version
from driving_identity_resolution import resolver, AUTO


class DrivingIdentityTests(unittest.TestCase):
    setUpClass=classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass=classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    tearDown=workflow.WorkflowRegressionTests.tearDown
    upload_driving_report=workflow.WorkflowRegressionTests.upload_driving_report
    inspection_form=workflow.WorkflowRegressionTests.inspection_form

    def setUp(self):
        workflow.WorkflowRegressionTests.setUp(self)
        self.person=self.add_user('78678','塩川','万帆')

    def add_user(self,username,last,first='',company='TEST'):
        u=self.m.User(company_code=company,username=username,role='user',password='unused',
            last_name=last,first_name=first,office='安城',password_changed_at='stamp')
        self.m.db.session.add(u);self.m.db.session.commit();return u

    def save(self,day='2026-10-23',name='塩川 万帆',code='TEST-SHIOKAWA-01',source='sample-system',company='TEST',**extra):
        data=dict(driver_name=name,driver_code=code,source_system=source,record_date=day,
                  distance='100',report_items=[],report_scope='daily',driver_office='安城',**extra)
        r=self.m.VehicleDrivingReportRecord(company_code=company,vehicle_record_id=self.vehicle.id,
            operation_date=day,content='fixture',details_json=json.dumps(data,ensure_ascii=False),
            source_draft_id='identity-fixture-'+str(self.m.VehicleDrivingReportRecord.query.count()),source_record_index=0,created_by_username='admin')
        self.m.db.session.add(r);self.m.db.session.commit();return r

    def resolve(self,r):
        with self.m.app.test_request_context():
            session.update(account_identity=identity_for('TEST', 'admin'), company_code='TEST',username='admin',role='admin')
            return resolver().resolve(r)

    def login(self,user):
        with self.client.session_transaction() as s:
            s.update(account_identity=identity_for(s.get('company_code'), user.username, app=(self.client).application), username=user.username,role=user.role,password_changed_at=user.password_changed_at)

    def context(self,url):
        contexts=[]
        def capture(sender,template,context,**kw):contexts.append(context)
        template_rendered.connect(capture,self.m.app)
        try:r=self.client.get(url)
        finally:template_rendered.disconnect(capture,self.m.app)
        self.assertEqual(r.status_code,200,r.get_data(as_text=True))
        return r,contexts[-1]

    def test_existing_report_shows_own_results_without_settings_or_get_writes(self):
        r=self.save();before=r.details_json
        self.login(self.person)
        response,ctx=self.context('/safety/driving-reports?period=all')
        self.assertEqual(ctx['total'],1);self.assertEqual(ctx['insights']['summary']['distance'],100)
        self.assertEqual(DrivingReportReader.query.count(),0);self.assertEqual(r.details_json,before)
        self.assertNotIn('乗務員を選択',response.get_data(as_text=True))
        self.assertEqual(self.client.get(f'/safety/driving-reports/{r.id}').status_code,200)

    def test_name_normalization_does_not_require_report_code_to_match_login(self):
        for n in ['塩川万帆','塩川　万帆',' 塩川 万帆 ']:
            r=self.save(name=n);u,b=self.resolve(r)
            self.assertEqual(u.id,self.person.id);self.assertEqual(b,'name')

    def test_missing_code_and_unknown_source_still_resolve_unique_full_name(self):
        r=self.save(code='',source='');self.assertEqual(self.resolve(r)[0].id,self.person.id)

    def test_duplicate_names_require_selection_even_with_matching_office(self):
        self.add_user('duplicate','塩川','万帆');r=self.save()
        self.assertIsNone(self.resolve(r)[0])
        with self.m.app.test_request_context():
            session.update(account_identity=identity_for('TEST', 'admin'), company_code='TEST',username='admin',role='admin')
            driving_access.resolve_import(r,self.person.username);self.m.db.session.commit()
        self.assertEqual(self.resolve(r)[0].id,self.person.id)
        later=self.save(day='2026-10-24');self.assertEqual(self.resolve(later)[0].id,self.person.id)
        earlier=self.save(day='2026-10-22');self.assertIsNone(self.resolve(earlier)[0])

    def test_other_company_same_name_cannot_grant_access(self):
        other=self.add_user('external','塩川','万帆',company='OTHER')
        r=self.save(company='OTHER')
        self.assertIsNone(self.resolve(r)[0])
        local=self.save();self.assertEqual(self.resolve(local)[0].id,self.person.id)
        self.login(self.person);self.assertEqual(self.client.get(f'/safety/driving-reports/{r.id}').status_code,404)

    def test_code_equals_username_without_matching_name_is_not_identity(self):
        r=self.save(name='別人',code=self.person.username);self.assertIsNone(self.resolve(r)[0])

    def test_unknown_or_partial_name_never_uses_uploader_vehicle_or_office(self):
        for n in ['', '塩川', 'シオカワ マホ']:
            self.assertIsNone(self.resolve(self.save(name=n))[0])

    def test_reused_code_with_different_names_stops_automatic_resolution(self):
        r=self.save();self.add_user('different','別人');self.save(name='別人')
        self.assertIsNone(self.resolve(r)[0])
        clean=self.save(source='another-system');self.assertEqual(self.resolve(clean)[0].id,self.person.id)

    def test_explicit_revocation_is_not_undone_by_automatic_name_resolution(self):
        r=self.save()
        self.client.post(f'/safety/driving-reports/{r.id}/reader',data={'version':version(r),'reader_username':''})
        self.assertIsNone(self.resolve(r)[0])
        self.login(self.person);self.assertEqual(self.client.get(f'/safety/driving-reports/{r.id}').status_code,404)

    def test_changed_identity_invalidates_explicit_grant(self):
        r=self.save()
        self.client.post(f'/safety/driving-reports/{r.id}/reader',data={'version':version(r),'reader_username':self.person.username})
        p=payload(r);p['driver_code']='changed';r.details_json=json.dumps(p);self.m.db.session.commit()
        self.assertIsNone(self.resolve(r)[0])

    def test_locked_and_removed_accounts_cannot_receive_automatic_access(self):
        r=self.save();self.person.login_locked=True;self.m.db.session.commit()
        self.assertIsNone(self.resolve(r)[0])
        self.person.login_locked=False;self.person.role='unsupported';self.m.db.session.commit()
        self.assertIsNone(self.resolve(r)[0])

    def test_new_duplicate_invalidates_automatic_grant(self):
        r=self.save()
        with self.m.app.test_request_context():
            session.update(account_identity=identity_for('TEST', 'admin'), company_code='TEST',username='admin',role='admin')
            driving_access.resolve_import(r);self.m.db.session.commit()
        self.assertEqual(DrivingReportReader.query.one().confirmed_by,AUTO)
        self.add_user('duplicate','塩川','万帆')
        self.assertIsNone(self.resolve(r)[0])

    def test_multiple_crew_is_not_automatically_given_whole_trip(self):
        r=self.save(duties=[{'driver_code':'different'}]);self.assertIsNone(self.resolve(r)[0])

    def import_matching(self,choice=None):
        self.upload_driving_report();draft=self.m.VehicleDocumentImportDraft.query.one()
        form=self.inspection_form(draft);key=draft.id+'_0'
        form['driver_name_'+key]='塩川 万帆'
        if choice is not None:form['driving_account_'+key]=choice
        response=self.client.post(f'/vehicle/data-import/{draft.batch_id}/confirm',data=form)
        return response,self.m.VehicleDrivingReportRecord.query.first(),draft

    def test_normal_import_automatically_persists_identity_with_no_extra_field(self):
        response,r,draft=self.import_matching();self.assertEqual(response.status_code,302)
        grant=DrivingReportReader.query.filter_by(report_id=r.id).one()
        self.assertEqual(grant.user_id,self.person.id);self.assertEqual(grant.confirmed_by,AUTO)
        self.assertIn('identity_resolution',payload(r))

    def test_exception_can_be_selected_inside_existing_import(self):
        self.add_user('duplicate','塩川','万帆')
        response,r,draft=self.import_matching(self.person.username)
        self.assertEqual(response.status_code,302)
        self.assertEqual(DrivingReportReader.query.one().user_id,self.person.id)

    def test_forged_cross_company_selection_is_rejected_without_registering(self):
        self.add_user('external','外部',company='OTHER')
        response,r,draft=self.import_matching('external')
        self.assertEqual(response.status_code,400);self.assertIsNone(r)

    def test_hold_saves_report_without_personal_access(self):
        response,r,draft=self.import_matching('__hold__')
        self.assertEqual(response.status_code,302);self.assertIsNone(self.resolve(r)[0])

    def test_registered_report_can_be_resolved_in_existing_readback(self):
        self.add_user('duplicate','塩川','万帆')
        response,r,draft=self.import_matching()
        self.assertIsNone(self.resolve(r)[0])
        form=self.inspection_form(draft);form.update(record_version=version(r))
        form['driving_account_'+draft.id+'_0']=self.person.username
        response=self.client.post(f'/safety/driving-reports/{r.id}/edit',data=form)
        self.assertEqual(response.status_code,302,response.get_data(as_text=True))
        self.assertEqual(self.resolve(r)[0].id,self.person.id)
        self.assertEqual(self.m.VehicleDrivingReportRecord.query.count(),1)

    def test_same_account_rows_merge_and_exports_remain_personal(self):
        self.save();self.save(day='2026-10-24',code='another-code')
        self.save(name='他人',code='other',day='2026-10-25')
        self.login(self.person)
        _,ctx=self.context('/safety/driving-reports?period=all&scope=company')
        self.assertEqual(ctx['total'],2);self.assertEqual(len(ctx['insights']['drivers']),1)
        self.assertEqual(ctx['insights']['summary']['distance'],200)
        data=self.client.get('/safety/driving-reports/export.csv?period=all&scope=company').data.decode('utf-8-sig')
        self.assertIn('塩川',data);self.assertNotIn('他人',data)
        with patch('driving_report_management.export_pdf',return_value=b'%PDF-test') as pdf:
            self.assertEqual(self.client.get('/safety/driving-reports/export.pdf?period=all&scope=self').status_code,200)
            self.assertNotIn('他人',str(pdf.call_args))

    def test_admin_self_ten_reports_and_master_are_one_person_without_setup(self):
        from dkss_app.models import Driver
        self.person.role='admin'
        self.m.db.session.add(Driver(company_code='TEST',name='塩川万帆',employee_id='78678',office='安城'))
        self.m.db.session.commit()
        for day in [f'2026-09-{d}' for d in range(26,31)]+[f'2026-10-{d}' for d in range(23,28)]:
            self.save(day=day)
        self.login(self.person)
        _,all_ctx=self.context('/safety/driving-reports?scope=self&period=all')
        self.assertEqual(all_ctx['total'],10);self.assertEqual(all_ctx['insights']['summary']['distance'],1000)
        _,month=self.context('/safety/driving-reports?scope=self&period=custom&start=2026-10-01&end=2026-10-31')
        self.assertEqual(month['total'],5);self.assertEqual(month['insights']['summary']['distance'],500)
        _,company=self.context('/safety/driving-reports?scope=company&period=all')
        self.assertEqual(len(company['insights']['drivers']),1)
        self.assertEqual(DrivingReportReader.query.count(),0)


if __name__=='__main__':unittest.main()
