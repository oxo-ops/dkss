"""Actor generation is checked and held between authenticated POST and commit."""
import json
import os
import unittest
from unittest.mock import patch

from flask import request
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

import test_q03_form_generation as forms


class ActorGenerationTests(unittest.TestCase):
    setUpClass=classmethod(forms.FormGenerationTests.setUpClass.__func__)
    tearDownClass=classmethod(forms.FormGenerationTests.tearDownClass.__func__)
    setUp=forms.FormGenerationTests.setUp
    tearDown=forms.FormGenerationTests.tearDown
    login=forms.FormGenerationTests.login
    request=forms.FormGenerationTests.request
    _replace=forms.FormGenerationTests._replace

    def prepare(self, kind):
        m=self.models
        if kind.startswith('vehicle'):
            v=m.Vehicle(company_code='A',chassis_number='ACTOR-SYNTHETIC',deleted=False)
            c=m.Checklist(company_code='A',name='Actor synthetic',target='車両管理',
                frequency_unit='day',display_type='month',active=True,
                items_json='[{"item_type":"check","input_type":"text","content":"Synthetic"}]')
            self.db.session.add_all([v,c]);self.db.session.commit()
            path=f'/vehicle/checklists/{c.id}/'+('save-detail' if kind=='vehicle_detail' else 'save-one')
            data={'vehicle_record_id':v.id,'year':'2026','month':'10','day':'23','item_no':'0',
                  'value':'SYNTHETIC_A_INPUT','comment':'SYNTHETIC_A_INPUT'}
            model,field=m.VehicleChecklistResult,'checked_by_identity'
        else:
            self.db.session.add(m.Driver(company_code='A',employee_id='checker',name='Other person C'))
            self.db.session.commit();path='/pointouts/new'
            data={'target_type':'user','target_user':'checker','category':'安全',
                  'date':'2026-10-23','content':'SYNTHETIC_A_INPUT'}
            model,field=m.PatrolResult,'created_by_identity'
        self.login('reviewer')
        actor=m.User.query.filter_by(company_code='A',username='reviewer').one()
        return path,data,model,field,actor.account_identity

    def snapshot(self):
        self.db.session.expire_all()
        m=self.models
        return tuple(tuple(tuple(getattr(row,col.name) for col in model.__table__.columns)
            for row in model.query.order_by(model.id).all()) for model in (
                m.ChecklistResult,m.VehicleChecklistResult,m.PatrolResult,m.ChecklistEvent,
                m.Notification,m.AuditLog,m.VehicleMaintenanceRecord,m.VehicleMaintenanceRecordEvent))

    def post(self,path,data):
        return self.request('POST',path,data=data,headers={'X-DKSS-Final-Submit':'1'})

    def normal(self,kind,rename=False):
        path,data,model,field,identity=self.prepare(kind)
        if rename:
            self.models.User.query.filter_by(company_code='A',username='reviewer').one().last_name='Renamed same person'
            self.db.session.commit()
        self.assertIn(self.post(path,data).status_code,(200,302))
        row=model.query.filter_by(company_code='A').one()
        self.assertEqual(getattr(row,field),identity)
        if kind.startswith('vehicle'):
            ident=row.id
            self.assertIn(self.post(path,{**data,'value':'updated','comment':'updated'}).status_code,(200,302))
            self.db.session.refresh(row)
            self.assertEqual(row.id,ident)
            self.assertEqual(getattr(row,field),identity)
            self.assertIn('updated',row.answers_json)

    def reject_change(self,kind,change):
        path,data,model,field,identity=self.prepare(kind)
        before=self.snapshot();changed=[]
        def after_auth():
            if request.path!=path or changed:return
            changed.append(True)
            if change=='replace':self._replace()
            else:
                actor=self.models.User.query.filter_by(company_code='A',username='reviewer').one()
                if change=='gone':self.db.session.delete(actor)
                elif change=='lock':actor.login_locked=True
                elif change=='role':actor.role='itc'
                self.db.session.commit()
        hooks=self.app.before_request_funcs[None];hooks.append(after_auth)
        try:response=self.post(path,data)
        finally:hooks.remove(after_auth)
        self.assertEqual(changed,[True])
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.snapshot(),before,'Business rows, events, notices and audit must be atomic')

    def foreign(self,kind):
        path,data,model,field,identity=self.prepare(kind)
        before=self.snapshot();self.login('reviewer','B')
        response=self.post(path,{**data,'company_code':'A'})
        self.assertEqual(response.status_code,302 if kind.startswith('vehicle') else 400)
        self.assertEqual(self.snapshot(),before)

    def rollback(self,kind):
        path,data,model,field,identity=self.prepare(kind)
        before=self.snapshot();hits=[]
        def fail(connection,cursor,statement,parameters,context,executemany):
            if statement.lower().startswith('insert into '+model.__tablename__+' '):
                hits.append(True);raise RuntimeError('Q03_ACTOR_AFTER_INSERT')
        event.listen(self.db.engine,'after_cursor_execute',fail)
        try:response=self.post(path,data)
        finally:event.remove(self.db.engine,'after_cursor_execute',fail)
        self.assertEqual(response.status_code,500)
        self.assertEqual(hits,[True]);self.assertEqual(self.snapshot(),before)
        self.assertIn(self.post(path,data).status_code,(200,302))
        self.assertEqual(getattr(model.query.filter_by(company_code='A').one(),field),identity)

    def held_after_check(self,kind):
        from dkss_app import person_selection
        path,data,model,field,identity=self.prepare(kind)
        real=person_selection.validate;checked=[]
        def check_then_compete(**kwargs):
            response=real(**kwargs)
            self.assertIsNone(response)
            for sql in ('DELETE FROM "user" WHERE company_code=\'A\' AND username=\'reviewer\'',
                        'UPDATE "user" SET role=\'itc\' WHERE company_code=\'A\' AND username=\'reviewer\''):
                with self.db.engine.connect() as writer:
                    if writer.dialect.name=='sqlite':
                        writer.exec_driver_sql('PRAGMA busy_timeout=100');writer.commit()
                    with self.assertRaises(OperationalError) as caught:
                        with writer.begin():
                            if writer.dialect.name=='postgresql':writer.execute(text("SET LOCAL lock_timeout='100ms'"))
                            writer.execute(text(sql))
                    if writer.dialect.name=='postgresql':self.assertEqual(caught.exception.orig.pgcode,'55P03')
                    else:self.assertIn('database is locked',str(caught.exception))
            checked.append(True)
            return response
        with patch.object(person_selection,'validate',side_effect=check_then_compete):
            self.assertIn(self.post(path,data).status_code,(200,302))
        self.assertEqual(checked,[True])
        self.assertEqual(getattr(model.query.filter_by(company_code='A').one(),field),identity)

    # Preserve the two originally failing acceptance cases as named regressions.
    def test_replaced_patrol_actor(self):self.reject_change('patrol','replace')
    def test_replaced_vehicle_actor(self):self.reject_change('vehicle','replace')


def case(method,*args):
    def run(self):getattr(self,method)(*args)
    return run


for _kind in ('patrol','vehicle','vehicle_detail'):
    for _change in ('gone','lock','role'):
        setattr(ActorGenerationTests,'test_'+_kind+'_'+_change,case('reject_change',_kind,_change))
    setattr(ActorGenerationTests,'test_'+_kind+'_normal_and_update',case('normal',_kind))
    setattr(ActorGenerationTests,'test_'+_kind+'_same_generation_rename',case('normal',_kind,True))
    setattr(ActorGenerationTests,'test_'+_kind+'_foreign_company',case('foreign',_kind))
    setattr(ActorGenerationTests,'test_'+_kind+'_rollback_retry',case('rollback',_kind))
    setattr(ActorGenerationTests,'test_'+_kind+'_lock_after_check',case('held_after_check',_kind))
setattr(ActorGenerationTests,'test_replaced_vehicle_detail_actor',case('reject_change','vehicle_detail','replace'))


@unittest.skipUnless(os.environ.get('Q03_POSTGRES_TEST_URL'),'explicit disposable PostgreSQL required')
class PostgresActorGenerationTests(ActorGenerationTests):
    setUpClass=classmethod(forms.PostgresFormGenerationTests.setUpClass.__func__)
    tearDownClass=classmethod(forms.PostgresFormGenerationTests.tearDownClass.__func__)
