"""Real GET -> account replacement -> POST races, with no production DB."""
import html
import json
import os
import re
import unittest

import test_q03_account_generations as identity
import test_q02_vehicle_workflow_boundaries as vehicle
import test_q03_postgres_person_identity as postgres


class FormGenerationTests(unittest.TestCase):
    setUpClass=classmethod(identity.CombinedIdentityTests.setUpClass.__func__)
    tearDownClass=classmethod(identity.CombinedIdentityTests.tearDownClass.__func__)
    setUp=identity.CombinedIdentityTests.setUp
    tearDown=identity.CombinedIdentityTests.tearDown
    login=identity.CombinedIdentityTests.login
    request=identity.CombinedIdentityTests.request
    record=identity.CombinedIdentityTests.record
    url=identity.CombinedIdentityTests.url
    def _page(self, url):
        response = self.request('GET', url)
        self.assertEqual(response.status_code, 200)
        content = response.get_data(as_text=True)
        match = re.search(r'name="person_selection_token"\s+value="([^"]+)"', content)
        return {'person_selection_token':html.unescape(match[1])} if match else {}

    def _replace(self, username='reviewer'):
        a=self.models.User.query.filter_by(company_code='A',username=username).one()
        old_id,old_uuid,role=a.id,a.account_identity,a.role
        self.db.session.delete(a)
        self.db.session.commit()
        b=self.models.User(id=old_id,company_code='A',username=username,role=role,
            password='unused',last_name='Replacement B',password_changed_at='same-stamp')
        self.db.session.add(b)
        self.db.session.commit()
        self.assertEqual(b.id,old_id)
        self.assertNotEqual(b.account_identity,old_uuid)
        return old_uuid,b.account_identity

    def _snapshot(self):
        from dkss_app.checklist_notify_identity import VehicleChecklistNotifyAccount
        self.db.session.expire_all()
        return tuple(tuple(tuple(getattr(row,c.name) for c in model.__table__.columns)
            for row in model.query.order_by(model.id).all()) for model in (
                self.models.ChecklistResult,self.models.VehicleChecklistResult,
                self.models.VehicleChecklistNotifySetting,VehicleChecklistNotifyAccount,
                self.models.ChecklistEvent,self.models.Notification,self.models.AuditLog))

    def _vehicle(self,fixed=False,requested=None):
        self.db.session.add(self.models.Vehicle(company_code='A',chassis_number='RACE-ONLY',deleted=False))
        self.db.session.commit()
        row=vehicle.Q02VehicleWorkflowBoundaryTests.record(self,fixed=fixed,general=True,requested=requested)
        page=f'/vehicle/checklists/{row.checklist_id}?vehicle_record_id={row.vehicle_record_id}&year=2026&month=10&active_day=23'
        return row,page

    def test_stale_new_safety_candidates_and_notifications_do_not_rebind(self):
        row=self.record((False,True))
        url=f'/safety/checklists/{row.checklist_id}/new'
        proof=self._page(url)
        old_uuid,new_uuid=self._replace()
        before=self._snapshot()
        data={'answer_0':'old form','approval_notify_users_1':'reviewer','notify_users':'reviewer',**proof}
        for _ in range(2):
            response=self.request('POST',url,data=data,headers={'X-DKSS-Final-Submit':'1'})
            self.assertEqual(response.status_code,409)
            self.assertEqual(self._snapshot(),before)
        fresh=self._page(url)
        self.assertEqual(self.request('POST',url,data={**data,**fresh}).status_code,302)
        new=self.models.ChecklistResult.query.order_by(self.models.ChecklistResult.id.desc()).first()
        self.assertEqual(json.loads(new.approvals_json)[1]['candidate_identities'],[new_uuid])
        self.assertNotEqual(old_uuid,new_uuid)
        before=self._snapshot()
        self.assertEqual(self.request('POST',url,data=data,headers={'X-DKSS-Final-Submit':'1'}).status_code,409)
        self.assertEqual(self._snapshot(),before)

    def test_stale_safety_edit_cannot_introduce_replacement_candidate(self):
        from dkss_app.checklists import checklist_result_edit_version
        row=self.record((False,True))
        url=self.url(row,'/edit')
        proof=self._page(url)
        version=checklist_result_edit_version(row)
        self._replace()
        before=self._snapshot()
        response=self.request('POST',url,data={'record_version':version,'answer_0':'old edit',
            'approval_notify_users_1':'reviewer',**proof},headers={'X-DKSS-Final-Submit':'1'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self._snapshot(),before)

    def test_stale_personal_target_cannot_become_replacement_subject(self):
        self.db.session.add(self.models.Driver(company_code='A',employee_id='reviewer',name='Original A'))
        self.db.session.commit()
        row=self.record((False,))
        url=f'/safety/checklists/{row.checklist_id}/new'
        proof=self._page(url)
        self._replace()
        before=self._snapshot()
        response=self.request('POST',url,data={'target_type':'user','target_user':'reviewer',**proof},
            headers={'X-DKSS-Final-Submit':'1'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self._snapshot(),before)

    def test_stale_vehicle_new_form_cannot_bind_replacement(self):
        row,_=self._vehicle()
        url=f'/vehicle/checklists/{row.checklist_id}/new'
        proof=self._page(url)
        self._replace()
        before=self._snapshot()
        response=self.request('POST',url,data={'vehicle_record_id':row.vehicle_record_id,
            'year':'2026','month':'10','day':'24','approval_notify_users_0':'reviewer',**proof},
            headers={'X-DKSS-Final-Submit':'1'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self._snapshot(),before)

    def test_stale_operation_notification_is_rechecked_on_confirmation_and_save(self):
        row,page=self._vehicle(fixed=True,requested=['admin'])
        person=self.models.User.query.filter_by(company_code='A',username='reviewer').one()
        person.role='admin'
        self.db.session.commit()
        proof=self._page(page)
        self._replace()
        before=self._snapshot()
        payload=vehicle.Q02VehicleWorkflowBoundaryTests.judge_data(self,row,
            decision='運行不可',approval_notify_users_operation='reviewer')
        for phase in ('X-DKSS-Validation-Only','X-DKSS-Final-Submit'):
            response=self.request('POST',f'/vehicle/checklist-results/{row.id}/operation-judgment',
                data={**payload,**proof},headers={phase:'1'})
            self.assertEqual(response.status_code,409)
            self.assertEqual(self._snapshot(),before)

    def test_absent_or_tampered_proof_cannot_bind_a_person(self):
        row=self.record((False,True))
        url=f'/safety/checklists/{row.checklist_id}/new'
        proof=self._page(url)['person_selection_token']
        before=self._snapshot()
        for value in ('',proof+'tampered'):
            response=self.request('POST',url,data={'answer_0':'body','approval_notify_users_1':'reviewer',
                'person_selection_token':value},headers={'X-DKSS-Final-Submit':'1'})
            self.assertEqual(response.status_code,409)
            self.assertEqual(self._snapshot(),before)

    def test_ambiguous_same_company_logins_are_not_resolved_by_row_order(self):
        row=self.record((False,True))
        self.db.session.add(self.models.User(company_code='A',username='reviewer',role='user',
            password='unused',last_name='Ambiguous other person'))
        self.db.session.commit()
        url=f'/safety/checklists/{row.checklist_id}/new'
        proof=self._page(url)
        before=self._snapshot()
        response=self.request('POST',url,data={'approval_notify_users_1':'reviewer',**proof},
            headers={'X-DKSS-Final-Submit':'1'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self._snapshot(),before)

    def test_confirmation_rechecks_the_original_generation(self):
        row=self.record((False,True))
        url=f'/safety/checklists/{row.checklist_id}/new'
        proof=self._page(url)
        self._replace()
        before=self._snapshot()
        response=self.request('POST',url,data={'approval_notify_users_1':'reviewer',**proof},
            headers={'X-DKSS-Validation-Only':'1'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self._snapshot(),before)

    def test_same_person_rename_preserves_a_fresh_selection(self):
        row=self.record((False,True))
        url=f'/safety/checklists/{row.checklist_id}/new'
        proof=self._page(url)
        person=self.models.User.query.filter_by(company_code='A',username='reviewer').one()
        saved=person.account_identity
        person.last_name='Renamed same person'
        self.db.session.commit()
        response=self.request('POST',url,data={'approval_notify_users_1':'reviewer',**proof})
        self.assertEqual(response.status_code,302)
        created=self.models.ChecklistResult.query.order_by(self.models.ChecklistResult.id.desc()).first()
        self.assertEqual(json.loads(created.approvals_json)[1]['candidate_identities'],[saved])

    def test_target_role_revocation_requires_reselection(self):
        person=self.models.User.query.filter_by(company_code='A',username='reviewer').one()
        person.role='admin'
        self.db.session.commit()
        row=self.record((False,))
        url=f'/safety/checklists/{row.checklist_id}/new'
        proof=self._page(url)
        person.role='user'
        self.db.session.commit()
        before=self._snapshot()
        response=self.request('POST',url,data={'approval_notify_users_0':'reviewer',**proof},
            headers={'X-DKSS-Final-Submit':'1'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self._snapshot(),before)

    def test_foreign_company_cannot_reuse_a_person_selection_proof(self):
        row=self.record((False,True))
        proof=self._page(f'/safety/checklists/{row.checklist_id}/new')
        foreign=self.record((False,True),company='B')
        self.login('admin','B')
        before=self._snapshot()
        response=self.request('POST',f'/safety/checklists/{foreign.checklist_id}/new',
            data={'approval_notify_users_1':'reviewer',**proof},headers={'X-DKSS-Final-Submit':'1'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self._snapshot(),before)

    def test_record_update_still_rejects_an_older_edit_version(self):
        from dkss_app.checklists import checklist_result_edit_version
        row=self.record((False,True))
        url=self.url(row,'/edit')
        proof=self._page(url)
        version=checklist_result_edit_version(row)
        row.answers_json='[{"value":"concurrent update"}]'
        self.db.session.commit()
        before=self._snapshot()
        response=self.request('POST',url,data={'record_version':version,'approval_notify_users_1':'reviewer',**proof},
            headers={'X-DKSS-Final-Submit':'1'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self._snapshot(),before)

    def test_actor_revocation_still_forbids_notification_settings(self):
        row,page=self._vehicle()
        proof=self._page(page)
        actor=self.models.User.query.filter_by(company_code='A',username='admin').one()
        actor.role='user'
        self.db.session.commit()
        before=self._snapshot()
        response=self.request('POST',f'/vehicle/checklists/{row.checklist_id}/reminder-notify-users',
            data={'vehicle_record_id':row.vehicle_record_id,'reminder_notify_users':'reviewer',**proof},
            headers={'X-DKSS-Final-Submit':'1'})
        self.assertEqual(response.status_code,403)
        self.assertEqual(self._snapshot(),before)

    def test_actor_cookie_cannot_follow_recreation_but_general_approval_survives(self):
        row=self.record((False,True),{'approval_notify_users_1':'reviewer'})
        self.request('POST',self.url(row,'/approve/0'))
        self.login('reviewer')
        self.assertEqual(self.request('GET',self.url(row)).status_code,200)
        old_uuid,new_uuid=self._replace()
        before=row.approvals_json
        self.assertEqual(self.request('POST',self.url(row,'/approve/1')).status_code,302)
        self.db.session.refresh(row)
        self.assertEqual(row.approvals_json,before)
        self.login('reviewer')
        self.assertEqual(self.request('GET',self.url(row)).status_code,200)
        self.request('POST',self.url(row,'/approve/1'))
        self.db.session.refresh(row)
        approval=json.loads(row.approvals_json)[1]
        self.assertEqual(approval['candidate_identities'],[old_uuid])
        self.assertEqual(approval['approved_by_identity'],new_uuid)

    def test_account_recreated_after_authentication_cannot_become_approval_actor(self):
        from flask import request
        row=self.record((True,))
        self.login('reviewer')
        self.assertEqual(self.request('GET',self.url(row)).status_code,200)
        before=self._snapshot()
        changed=[]
        def between_auth_and_view():
            if request.path==self.url(row,'/approve/0') and not changed:
                changed.append(self._replace())
        hooks=self.app.before_request_funcs[None]
        hooks.append(between_auth_and_view)
        self.addCleanup(lambda:hooks.remove(between_auth_and_view))
        response=self.request('POST',self.url(row,'/approve/0'),headers={'X-DKSS-Final-Submit':'1'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self._snapshot(),before)
        self.assertEqual(len(changed),1)
        self.login('reviewer')
        self.assertEqual(self.request('POST',self.url(row,'/approve/0')).status_code,302)
        self.db.session.refresh(row)
        self.assertEqual(row.approved_by_identity,changed[0][1])

    def test_role_revoked_after_authentication_cannot_use_old_admin_authority(self):
        from flask import request
        person=self.models.User.query.filter_by(company_code='A',username='reviewer').one()
        person.role='admin'
        self.db.session.commit()
        row=self.record((False,))
        self.login('reviewer')
        self.assertEqual(self.request('GET',self.url(row)).status_code,200)
        before=self._snapshot()
        changed=[]
        def between_auth_and_view():
            if request.path==self.url(row,'/approve/0') and not changed:
                changed.append(True)
                actor=self.models.User.query.filter_by(company_code='A',username='reviewer').one()
                actor.role='user'
                self.db.session.commit()
        hooks=self.app.before_request_funcs[None]
        hooks.append(between_auth_and_view)
        self.addCleanup(lambda:hooks.remove(between_auth_and_view))
        response=self.request('POST',self.url(row,'/approve/0'),headers={'X-DKSS-Final-Submit':'1'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self._snapshot(),before)

    def test_selection_lock_serializes_account_deletion_and_role_change(self):
        from flask import session
        from sqlalchemy import text
        from sqlalchemy.exc import OperationalError
        from dkss_app import person_selection
        row=self.record((False,True))
        proof=self._page(f'/safety/checklists/{row.checklist_id}/new')
        with self.client.session_transaction() as browser:
            claims=dict(browser)
        with self.app.test_request_context(method='POST',data={'approval_notify_users_1':'reviewer',**proof}):
            session.update(claims)
            self.assertIsNone(person_selection.validate())
            for sql in ('DELETE FROM "user" WHERE company_code=\'A\' AND username=\'reviewer\'',
                        'UPDATE "user" SET role=\'itc\' WHERE company_code=\'A\' AND username=\'reviewer\''):
                with self.db.engine.connect() as connection:
                    if self.db.engine.dialect.name=='sqlite':
                        connection.exec_driver_sql('PRAGMA busy_timeout=100')
                        connection.commit()
                    with self.assertRaises(OperationalError) as caught:
                        with connection.begin():
                            if self.db.engine.dialect.name=='postgresql':
                                connection.execute(text("SET LOCAL lock_timeout='100ms'"))
                            connection.execute(text(sql))
                    if self.db.engine.dialect.name=='postgresql':
                        self.assertEqual(caught.exception.orig.pgcode,'55P03')
                    else:
                        self.assertIn('database is locked',str(caught.exception))
            self.db.session.rollback()

    def test_busy_person_row_returns_conflict_without_a_partial_save(self):
        from sqlalchemy import text
        row=self.record((False,True))
        url=f'/safety/checklists/{row.checklist_id}/new'
        proof=self._page(url)
        before=self._snapshot()
        if self.db.engine.dialect.name=='sqlite':
            self.db.session.connection().exec_driver_sql('PRAGMA busy_timeout=100')
        else:
            self.db.session.execute(text("SET LOCAL lock_timeout='100ms'"))
        with self.db.engine.connect() as writer:
            transaction=writer.begin()
            try:
                writer.execute(text("UPDATE \"user\" SET last_name='concurrent edit' WHERE company_code='A' AND username='reviewer'"))
                response=self.request('POST',url,data={'approval_notify_users_1':'reviewer',**proof},
                    headers={'X-DKSS-Final-Submit':'1'})
                self.assertEqual(response.status_code,409)
            finally:
                transaction.rollback()
        self.assertEqual(self._snapshot(),before)
        self.assertEqual(self.request('POST',url,data={'approval_notify_users_1':'reviewer',**proof}).status_code,302)

    def test_stale_vehicle_notification_setting_does_not_attest_replacement(self):
        row,page=self._vehicle()
        proof=self._page(page)
        self._replace()
        before=self._snapshot()
        response=self.request('POST',f'/vehicle/checklists/{row.checklist_id}/reminder-notify-users',
            data={'vehicle_record_id':row.vehicle_record_id,'reminder_notify_users':'reviewer',**proof},
            headers={'X-DKSS-Final-Submit':'1'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self._snapshot(),before)

    def test_stale_vehicle_completion_cannot_select_replacement(self):
        row,page=self._vehicle()
        proof=self._page(page)
        self._replace()
        before=self._snapshot()
        response=self.request('POST',f'/vehicle/checklists/{row.checklist_id}/complete',
            data={'vehicle_record_id':row.vehicle_record_id,'year':'2026','month':'10','day':'24',
                'approval_notify_users_0':'reviewer','notify_users':'reviewer',**proof},
            headers={'X-DKSS-Final-Submit':'1'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self._snapshot(),before)

    def test_stale_manager_selection_cannot_assign_replacement(self):
        row,page=self._vehicle(fixed=True)
        a=self.models.User.query.filter_by(company_code='A',username='reviewer').one()
        a.role='admin'
        self.db.session.commit()
        self.login('checker')
        proof=self._page(page)
        self._replace()
        before=self._snapshot()
        payload=vehicle.Q02VehicleWorkflowBoundaryTests.judge_data(self,row,
            action='assign_operation_manager',manager_username='reviewer')
        response=self.request('POST',f'/vehicle/checklist-results/{row.id}/operation-judgment',
            data={**payload,**proof},headers={'X-DKSS-Final-Submit':'1'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self._snapshot(),before)


@unittest.skipUnless(os.environ.get('Q03_POSTGRES_TEST_URL'),'explicit disposable local PostgreSQL required')
class PostgresFormGenerationTests(FormGenerationTests):
    setUpClass=classmethod(postgres.Q03PostgresPersonIdentityTests.setUpClass.__func__)
    tearDownClass=classmethod(postgres.Q03PostgresPersonIdentityTests.tearDownClass.__func__)
