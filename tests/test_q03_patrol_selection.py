"""Previously uncovered patrol form selections; real GET/POST, synthetic DBs only."""
import html
import os
import re
import unittest
from unittest.mock import patch

from flask.testing import FlaskClient
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

import test_q03_form_generation as forms
import test_q03_postgres_person_identity as postgres


class PatrolSelectionTests(unittest.TestCase):
    setUpClass = classmethod(forms.FormGenerationTests.setUpClass.__func__)
    tearDownClass = classmethod(forms.FormGenerationTests.tearDownClass.__func__)
    tearDown = forms.FormGenerationTests.tearDown
    login = forms.FormGenerationTests.login
    request = forms.FormGenerationTests.request
    replace = forms.FormGenerationTests._replace

    def setUp(self):
        forms.FormGenerationTests.setUp(self)
        # Never synthesize a fresh proof for stale/missing-proof acceptance.
        self.client = FlaskClient(self.app, response_wrapper=self.app.response_class)
        self.login('admin')
        self.db.session.add(self.models.Driver(company_code='A', employee_id='reviewer', name='Original A'))
        self.db.session.add(self.models.Driver(company_code='B', employee_id='reviewer', name='Other company A'))
        self.db.session.commit()

    def prepare(self, editing=False):
        if editing:
            row = self.models.PatrolResult(company_code='A', created_by_username='admin',
                created_by_name='Author', target_type='user', target_username='checker',
                target_user='Previous C', category='安全', date='2026-10-29',
                content='ORIGINAL CONTENT', files_json='["old-synthetic.pdf"]', approval_status='未対応')
            self.db.session.add(row)
            self.db.session.commit()
            path = f'/pointouts/{row.id}/edit'
        else:
            path = '/pointouts/new'
        page = self.request('GET', path)
        self.assertEqual(page.status_code, 200)
        match = re.search(r'name="person_selection_token"\s+value="([^"]+)"', page.get_data(as_text=True))
        data = {'date':'2026-10-29', 'category':'安全', 'target_user':'reviewer',
                'content':'SYNTHETIC PRIVATE CONTENT', 'person_selection_token':html.unescape(match[1]) if match else ''}
        if not editing:
            data['target_type'] = 'user'
        return path, data

    def snapshot(self):
        self.db.session.expire_all()
        return tuple(tuple(tuple(getattr(row,c.name) for c in model.__table__.columns)
            for row in model.query.order_by(model.id)) for model in (
                self.models.PatrolResult, self.models.Notification,
                self.models.ChecklistEvent, self.models.AuditLog))

    def post(self, path, data):
        return self.request('POST', path, data=data, headers={'X-DKSS-Final-Submit':'1'})

    def stale(self, editing):
        path,data = self.prepare(editing)
        old,new = self.replace()
        before = self.snapshot()
        for _ in range(2):
            response = self.post(path,data)
            self.assertEqual(response.status_code,409)
            self.assertEqual(self.snapshot(),before)
        self.login('reviewer')
        self.assertEqual(self.models.Notification.query.filter_by(owner_identity=new).count(),0)

    def test_new_stale_target_does_not_bind_same_id_new_uuid(self): self.stale(False)
    def test_edit_stale_target_does_not_bind_same_id_new_uuid(self): self.stale(True)

    def fail_notice(self, editing):
        path,data = self.prepare(editing)
        # Existing mention syntax exercises the real notification insertion.
        data['content'] += ' [[reviewer|Testreviewer]]'
        before = self.snapshot()
        hits=[]
        def fail(connection,cursor,statement,parameters,context,executemany):
            if statement.lower().startswith('insert into notification '):
                hits.append(True)
                raise RuntimeError('SYNTHETIC_NOTICE_INSERT_FAILURE')
        event.listen(self.db.engine,'after_cursor_execute',fail)
        try: response=self.post(path,data)
        finally: event.remove(self.db.engine,'after_cursor_execute',fail)
        self.assertEqual(response.status_code,500)
        self.assertTrue(hits)
        self.assertEqual(self.snapshot(),before)

    def test_new_notice_failure_does_not_partially_save_patrol(self): self.fail_notice(False)
    def test_edit_notice_failure_does_not_partially_save_patrol(self): self.fail_notice(True)

    def normal(self, editing, rename=False, replacement=False):
        path,data=self.prepare(editing)
        if replacement:
            self.replace()
            path,data=self.prepare(editing)
        target=self.models.User.query.filter_by(company_code='A',username='reviewer').one()
        identity=target.account_identity
        if rename:
            target.last_name='Same person renamed'
            self.models.Driver.query.filter_by(company_code='A',employee_id='reviewer').one().name='Renamed A'
            self.db.session.commit()
        with patch('dkss_app.notifications_delivery.dispatch_external_notification') as delivery:
            self.assertEqual(self.post(path,data).status_code,302)
        row=self.models.PatrolResult.query.order_by(self.models.PatrolResult.id.desc()).first()
        self.assertEqual(row.target_identity,identity)
        self.assertEqual(row.target_username,'reviewer')
        self.assertEqual(row.content,data['content'])
        if rename:self.assertEqual(row.target_user,'Renamed A')
        notices=self.models.Notification.query.filter_by(owner_identity=identity).all()
        self.assertEqual(len(notices),0 if editing else 1)
        self.assertEqual(delivery.call_count,0 if editing else 1)

    def reject_target(self, editing, change):
        path,data=self.prepare(editing)
        target=self.models.User.query.filter_by(company_code='A',username='reviewer').one()
        if change=='locked':target.login_locked=True
        elif change=='role':target.role='admin'
        elif change=='company':target.company_code='MovedAway'
        elif change=='gone':self.db.session.delete(target)
        elif change=='missing':data['person_selection_token']=''
        elif change=='forged':data['person_selection_token']+='x'
        self.db.session.commit()
        before=self.snapshot()
        data['delete_files']='old-synthetic.pdf'
        with patch('dkss_app.storage.save_uploaded_file') as upload, patch('dkss_app.safety._dkss_common.os.remove') as remove:
            self.assertIn(self.post(path,data).status_code,(400,409))
            self.assertEqual(self.snapshot(),before)
            upload.assert_not_called();remove.assert_not_called()

    def held(self,editing):
        from dkss_app import person_selection
        path,data=self.prepare(editing)
        real=person_selection.validate;hits=[]
        def compete(**kwargs):
            response=real(**kwargs)
            self.assertIsNone(response)
            for sql in ("DELETE FROM \"user\" WHERE company_code='A' AND username='reviewer'",
                        "UPDATE \"user\" SET role='itc' WHERE company_code='A' AND username='reviewer'"):
                with self.db.engine.connect() as other:
                    if other.dialect.name=='sqlite':
                        other.exec_driver_sql('PRAGMA busy_timeout=100');other.commit()
                    with self.assertRaises(OperationalError) as caught:
                        with other.begin():
                            if other.dialect.name=='postgresql':other.exec_driver_sql("SET LOCAL lock_timeout='100ms'")
                            other.exec_driver_sql(sql)
                    if other.dialect.name=='postgresql':self.assertEqual(caught.exception.orig.pgcode,'55P03')
                    else:self.assertIn('locked',str(caught.exception))
            hits.append(True)
            return response
        with patch.object(person_selection,'validate',side_effect=compete), patch('dkss_app.notifications_delivery.dispatch_external_notification'):
            self.assertEqual(self.post(path,data).status_code,302)
        self.assertEqual(hits,[True])

    def recovery(self,editing):
        path,data=self.prepare(editing);self.replace();before=self.snapshot()
        response=self.request('POST',path,data=data,headers={'Accept':'text/html'},follow_redirects=True)
        self.assertEqual(response.status_code,200)
        page=response.get_data(as_text=True)
        self.assertRegex(page,r'name="target_user"\s+id="target_user"\s+value=""')
        self.assertEqual(self.snapshot(),before)

    def foreign(self,editing):
        path,data=self.prepare(editing);before=self.snapshot();self.login('admin','B')
        data['company_code']='A'
        self.assertIn(self.post(path,data).status_code,(302,400,409))
        self.assertEqual(self.snapshot(),before)

    def actor_race(self,editing):
        from flask import request
        path,data=self.prepare(editing);before=self.snapshot();hits=[]
        def after_auth():
            if request.path!=path or request.method!='POST' or hits:return
            hits.append(True);self.replace('admin')
        hooks=self.app.before_request_funcs[None];hooks.append(after_auth)
        try:response=self.post(path,data)
        finally:hooks.remove(after_auth)
        self.assertEqual(hits,[True]);self.assertEqual(response.status_code,409)
        self.assertEqual(self.snapshot(),before)

    def csrf(self,editing):
        path,data=self.prepare(editing);before=self.snapshot()
        self.app.config['WTF_CSRF_ENABLED']=True
        try:
            self.assertEqual(self.post(path,data).status_code,400)
            self.assertEqual(self.snapshot(),before)
            page=self.request('GET',path).get_data(as_text=True)
            token=html.unescape(re.search(r'name="csrf_token"\s+value="([^"]+)"',page)[1])
            with patch('dkss_app.notifications_delivery.dispatch_external_notification'):
                self.assertEqual(self.post(path,{**data,'csrf_token':token}).status_code,302)
        finally:self.app.config['WTF_CSRF_ENABLED']=False

    def after_commit_replacement(self,editing):
        from dkss_app import safety
        path,data=self.prepare(editing)
        old=self.models.User.query.filter_by(company_code='A',username='reviewer').one().account_identity
        data['content']+=' [[reviewer|Testreviewer]]'
        real=safety._dispatch_patrol_notifications
        def replace_then_dispatch(pending):
            self.replace()
            real(pending)
        with patch.object(safety,'_dispatch_patrol_notifications',side_effect=replace_then_dispatch), patch('dkss_app.notifications_delivery.dispatch_external_notification') as external:
            self.assertEqual(self.post(path,data).status_code,302)
            external.assert_not_called()
        row=self.models.PatrolResult.query.order_by(self.models.PatrolResult.id.desc()).first()
        self.assertEqual(row.target_identity,old)
        self.login('reviewer')
        self.assertEqual(self.request('GET',f'/pointouts/{row.id}').status_code,302)
        self.assertEqual(self.models.Notification.query.filter_by(owner_identity=old).count(),1 if editing else 2)

    def delivery_target(self,editing):
        m=self.models
        self.db.session.add(m.DeliveryPlace(company_code='A',name='Synthetic Place'))
        self.db.session.commit()
        if editing:
            row=m.PatrolResult(company_code='A',created_by_username='admin',created_by_name='Author',
                target_type='delivery_place',delivery_place='Synthetic Place',date='2026-10-29',
                category='品質',content='Before',approval_status='未対応')
            self.db.session.add(row);self.db.session.commit();path=f'/pointouts/{row.id}/edit'
        else:path='/pointouts/new'
        self.assertEqual(self.request('GET',path).status_code,200)
        self.assertEqual(self.post(path,{'target_type':'delivery_place','delivery_place':'Synthetic Place',
            'date':'2026-10-29','category':'品質','content':'After'}).status_code,302)
        self.assertEqual(m.PatrolResult.query.order_by(m.PatrolResult.id.desc()).first().content,'After')
        self.assertEqual(m.Notification.query.count(),0)


def case(method,*args):
    def run(self):getattr(self,method)(*args)
    return run


for editing in (False,True):
    prefix='edit' if editing else 'new'
    for change in ('locked','role','company','gone','missing','forged'):
        setattr(PatrolSelectionTests,f'test_{prefix}_reject_{change}',case('reject_target',editing,change))
    for method in ('held','recovery','foreign','actor_race','csrf','after_commit_replacement','delivery_target'):
        setattr(PatrolSelectionTests,f'test_{prefix}_{method}',case(method,editing))
    for variant,rename,replacement in [('normal',False,False),('rename',True,False),('fresh_replacement',False,True)]:
        setattr(PatrolSelectionTests,f'test_{prefix}_{variant}',case('normal',editing,rename,replacement))


@unittest.skipUnless(os.environ.get('Q03_POSTGRES_TEST_URL'),'explicit disposable local PostgreSQL required')
class PostgresPatrolSelectionTests(PatrolSelectionTests):
    setUpClass=classmethod(postgres.Q03PostgresPersonIdentityTests.setUpClass.__func__)
    tearDownClass=classmethod(postgres.Q03PostgresPersonIdentityTests.tearDownClass.__func__)
