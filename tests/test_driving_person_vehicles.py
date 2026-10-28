"""Personal vehicle provenance and corrections use an isolated SQLite database."""
from identity_fixture import identity_for
import json
import unittest
from unittest.mock import patch

from flask import session, template_rendered
from sqlalchemy import event

import test_workflow_regressions as workflow
import test_driving_report_insights as insight_tests
from dkss_app import driving_access
from dkss_app.driving_vehicle_links import DrivingVehicleCorrection, ORIGIN
from dkss_app.models import ChecklistEvent, Driver, DrivingReportReader


class PersonalVehicleTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    tearDown = workflow.WorkflowRegressionTests.tearDown
    save = insight_tests.DrivingInsightRouteTests.save

    def setUp(self):
        workflow.WorkflowRegressionTests.setUp(self)
        self.user = self.m.User(company_code='TEST', username='one', role='user', password='unused',
                                last_name='本人', password_changed_at='stamp')
        self.other = self.m.User(company_code='OTHER', username='secret', role='user', password='unused',
                                 last_name='他社', password_changed_at='stamp')
        self.b = self.m.Vehicle(company_code='TEST', chassis_number='SECOND-CAR')
        self.watch = self.m.Vehicle(company_code='TEST', chassis_number='WATCH-ONLY')
        self.foreign = self.m.Vehicle(company_code='OTHER', chassis_number='SECRET-CAR')
        self.m.db.session.add_all([self.user, self.other, self.b, self.watch, self.foreign])
        self.m.db.session.flush()
        self.m.db.session.add(Driver(company_code='TEST', employee_id='one', name='本人', vehicles_json=json.dumps([str(self.watch.id)])))
        self.m.db.session.commit()
        self.login()
        self.url = '/safety/driving-reports?period=all'

    def login(self, name='one', role='user', stamp='stamp'):
        with self.client.session_transaction() as state:
            state.update(account_identity=identity_for(state.get('company_code'), name, app=(self.client).application), username=name, role=role, password_changed_at=stamp)

    def inspection(self, vehicle=None, day='10', username='one', origin=True, status='点検完了', template='daily_inspection_truck_trailer'):
        record = self.m.VehicleChecklistResult(company_code='TEST', checklist_id=1,
            vehicle_record_id=(vehicle or self.vehicle).id, year='2026', month='10', day=day,
            checked_by_username=username, checked_date='2026-11-20 23:59', status=status,
            checklist_snapshot_json=json.dumps({'fixed_template_code':template}), answers_json='[]')
        if origin:
            with self.m.app.test_request_context():
                session.update(account_identity=identity_for('TEST', username), company_code='TEST', username=username, role='user')
                self.m.db.session.add(record);self.m.db.session.commit()
        else:
            self.m.db.session.add(record);self.m.db.session.commit()
        return record

    def grant(self, row):
        with self.m.app.test_request_context():
            session.update(account_identity=identity_for('TEST', 'admin'), company_code='TEST', username='admin', role='admin')
            driving_access.assign([row], 'one', 'admin');self.m.db.session.commit()

    def render(self, url=None):
        contexts=[]
        def capture(sender,template,context,**kw):contexts.append(context)
        template_rendered.connect(capture,self.m.app)
        try:response=self.client.get(url or self.url)
        finally:template_rendered.disconnect(capture,self.m.app)
        self.assertEqual(response.status_code,200,response.get_data(as_text=True))
        return response,contexts[-1]

    def form(self, item, action='exclude', **kw):
        return dict(period='all', inspection_id=item['inspection_id'], revision=item['revision'],
                    evidence_key=item['evidence_key'], action=action, **kw)

    def post(self, form):
        return self.client.post('/safety/driving-reports/vehicle-candidates',data=form)

    def test_multiple_report_vehicles_without_watch_list_or_candidates_in_totals(self):
        a=self.save(1);b=self.save(2,day='2026-10-11');b.vehicle_record_id=self.b.id;self.m.db.session.commit()
        self.grant(a);self.grant(b);self.inspection(self.watch)
        _,ctx=self.render();panel=ctx['driving_vehicles']
        self.assertEqual({v['id'] for v in panel['trips']},{self.vehicle.id,self.b.id})
        self.assertEqual(len(panel['candidates']),1)
        self.assertEqual(ctx['insights']['summary']['count'],2)
        self.assertEqual(ctx['insights']['summary']['distance'],200)
        self.assertNotIn(self.foreign.id,{v['id'] for v in panel['choices']})

    def test_origin_survives_later_editor_and_uses_target_not_entry_day(self):
        record=self.inspection();record.checked_by_username='admin';self.m.db.session.commit()
        response,ctx=self.render()
        self.assertEqual(ctx['driving_vehicles']['candidates'][0]['day'],'2026-10-10')
        self.assertIn('点検から推定',response.get_data(as_text=True))
        self.assertEqual(ctx['insights']['summary']['count'],0)
        self.assertIsNone(ctx['insights']['summary']['distance'])
        self.assertEqual(DrivingReportReader.query.count(),0)

    def test_legacy_incomplete_and_periodic_inspections_do_not_invent_origin(self):
        self.inspection(origin=False);self.inspection(day='11',status='入力中')
        self.inspection(day='12',template='periodic');self.inspection(day='13',username='admin')
        _,ctx=self.render();self.assertEqual(ctx['driving_vehicles']['candidates'],[])

    def test_reused_username_cannot_inherit_previous_accounts_inspections(self):
        self.inspection();self.user.username='old';self.m.db.session.commit()
        replacement=self.m.User(company_code='TEST',username='one',role='user',password='unused',password_changed_at='stamp',last_name='別人')
        self.m.db.session.add(replacement);self.m.db.session.commit()
        # The old signed session must be rejected before testing the new person's
        # independent authenticated view. Keep the original no-inheritance check.
        self.assertEqual(self.client.get(self.url).location,'/login')
        with self.client.session_transaction() as state:
            state.update(company_code='TEST',username='one',role='user',password_changed_at='stamp',
                         account_identity=replacement.account_identity)
        _,ctx=self.render();self.assertEqual(ctx['driving_vehicles']['candidates'],[])

    def test_exclude_reset_and_replace_preserve_sources_and_append_history(self):
        record=self.inspection();before=record.answers_json
        _,ctx=self.render();item=ctx['driving_vehicles']['candidates'][0]
        self.assertEqual(self.post(self.form(item)).status_code,302)
        _,ctx=self.render();self.assertEqual(ctx['driving_vehicles']['candidates'],[])
        edit=ctx['driving_vehicles']['corrections'][0]
        self.assertEqual(self.post(self.form(edit,'replace',vehicle_id=self.b.id)).status_code,302)
        _,ctx=self.render();item=ctx['driving_vehicles']['candidates'][0]
        self.assertEqual(item['vehicle_id'],self.b.id)
        self.assertEqual(self.post(self.form(item,'reset')).status_code,302)
        _,ctx=self.render();self.assertEqual(ctx['driving_vehicles']['candidates'][0]['vehicle_id'],self.vehicle.id)
        self.assertEqual(DrivingVehicleCorrection.query.count(),3)
        self.assertEqual(record.answers_json,before)
        self.assertEqual(record.vehicle_record_id,self.vehicle.id)
        self.assertEqual(Driver.query.filter_by(employee_id='one').one().vehicles_json,json.dumps([str(self.watch.id)]))
        self.assertEqual(DrivingReportReader.query.count(),0)

    def test_stale_replay_and_cross_company_replacement_are_rejected(self):
        self.inspection();_,ctx=self.render();item=ctx['driving_vehicles']['candidates'][0]
        form=self.form(item,'replace',vehicle_id=self.foreign.id)
        self.assertEqual(self.post(form).status_code,404)
        form=self.form(item);self.assertEqual(self.post(form).status_code,302)
        self.assertEqual(self.post(form).status_code,409)
        self.assertEqual(DrivingVehicleCorrection.query.count(),1)

    def test_other_account_cannot_correct_candidate_even_with_forged_subject(self):
        self.inspection(username='admin');own=self.inspection(day='11')
        _,ctx=self.render();item=ctx['driving_vehicles']['candidates'][0]
        self.login('admin','admin',self.m.User.query.filter_by(username='admin').one().password_changed_at)
        self.assertEqual(self.post(self.form(item,user_id=self.user.id)).status_code,404)
        self.assertEqual(DrivingVehicleCorrection.query.count(),0)

    def test_later_report_collapses_only_same_vehicle_day_not_other_car(self):
        self.inspection();self.inspection(self.b)
        a=self.save();self.grant(a)
        _,ctx=self.render();panel=ctx['driving_vehicles']
        self.assertEqual(len(panel['trips']),1)
        self.assertEqual([i['vehicle_id'] for i in panel['candidates']],[self.b.id])
        self.assertEqual(ctx['insights']['summary']['distance'],100)

    def test_report_and_different_day_candidate_share_one_vehicle_row(self):
        self.inspection(day='11');a=self.save();self.grant(a)
        _,ctx=self.render();panel=ctx['driving_vehicles']
        self.assertEqual(len(panel['groups']),1)
        self.assertIsNotNone(panel['groups'][0]['trip'])
        self.assertEqual(panel['groups'][0]['candidates'][0]['day'],'2026-10-11')

    def test_real_cell_save_preserves_initial_account_and_approval_does_not_replace_it(self):
        checklist=workflow.WorkflowRegressionTests.workflow_checklist(self,'車両管理',[])
        items=json.loads(checklist.items_json);items[0]['fixed_template_code']='daily_inspection_truck_trailer'
        checklist.items_json=json.dumps(items);self.m.db.session.commit()
        response=self.client.post(f'/vehicle/checklists/{checklist.id}/save-one',data=dict(
            vehicle_record_id=self.vehicle.id,year='2026',month='10',day='10',item_no='0',value='確認済み'))
        self.assertEqual(response.status_code,302,response.get_data(as_text=True))
        record=self.m.VehicleChecklistResult.query.one()
        origin=ChecklistEvent.query.filter_by(result_id=record.id,event_type=ORIGIN).one()
        self.assertEqual(json.loads(origin.detail_json)['user_id'],self.user.id)
        record.checked_by_username='admin';record.status='点検完了';self.m.db.session.commit()
        _,ctx=self.render();self.assertEqual(len(ctx['driving_vehicles']['candidates']),1)

    def test_admin_person_focus_reuses_confirmed_account_but_company_view_has_no_candidates(self):
        self.inspection();a=self.save();self.grant(a)
        self.login('admin','admin',self.m.User.query.filter_by(username='admin').one().password_changed_at)
        _,ctx=self.render(self.url+'&scope=company')
        self.assertIsNone(ctx['driving_vehicles']['user_id'])
        key=driving_access.account_key(DrivingReportReader.query.one())
        _,ctx=self.render(self.url+'&scope=company&focus='+key)
        self.assertEqual(ctx['driving_vehicles']['user_id'],self.user.id)

    def test_date_vehicle_and_metadata_filters_apply_to_candidates(self):
        self.inspection();self.inspection(self.b,day='20')
        _,ctx=self.render('/safety/driving-reports?period=custom&start=2026-10-01&end=2026-10-12')
        self.assertEqual(len(ctx['driving_vehicles']['candidates']),1)
        _,ctx=self.render(self.url+'&vehicle='+str(self.b.id))
        self.assertEqual([i['vehicle_id'] for i in ctx['driving_vehicles']['candidates']],[self.b.id])

    def test_changed_target_or_missing_origin_evidence_invalidates_candidate(self):
        record=self.inspection();record.day='15';self.m.db.session.commit()
        _,ctx=self.render();self.assertEqual(ctx['driving_vehicles']['candidates'],[])

    def test_csrf_required_and_get_never_creates_schema_or_runs_ai(self):
        self.inspection();_,ctx=self.render();item=ctx['driving_vehicles']['candidates'][0]
        self.m.app.config['WTF_CSRF_ENABLED']=True
        try:self.assertEqual(self.post(self.form(item)).status_code,400)
        finally:self.m.app.config['WTF_CSRF_ENABLED']=False
        statements=[]
        def observe(conn,cursor,sql,*args):statements.append(sql.lstrip().upper())
        event.listen(self.m.db.engine,'before_cursor_execute',observe)
        try:
            with patch('driving_report_reflection.generate',side_effect=AssertionError('GET AI')):self.render()
        finally:event.remove(self.m.db.engine,'before_cursor_execute',observe)
        self.assertFalse(any(s.startswith(('CREATE','ALTER','INSERT','UPDATE','DELETE')) for s in statements))

    def test_missing_correction_schema_is_read_only_until_explicit_initialization(self):
        self.inspection();DrivingVehicleCorrection.__table__.drop(self.m.db.engine)
        _,ctx=self.render();panel=ctx['driving_vehicles']
        self.assertFalse(panel['ready']);self.assertEqual(len(panel['candidates']),1)
        self.assertEqual(self.post(self.form(panel['candidates'][0])).status_code,503)
        driving_access.initialize_driving_access(self.m.app);driving_access.initialize_driving_access(self.m.app)
        _,ctx=self.render();self.assertTrue(ctx['driving_vehicles']['ready'])


if __name__=='__main__':unittest.main()
