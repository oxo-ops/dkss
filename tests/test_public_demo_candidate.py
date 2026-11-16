import os
import time
import unittest
from unittest.mock import patch
from dkss_app import create_app
from dkss_app.extensions import db, limiter
from dkss_app.models import Company, User, Vehicle

class PublicDemoTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'RENDER':'','SECRET_KEY':'isolated-only','DATABASE_URL':'sqlite://','S3_BUCKET_NAME':'','SMTP_HOST':'','OPENAI_API_KEY':''})
        self.env.start()
        self.app=create_app({'TESTING':True,'SQLALCHEMY_DATABASE_URI':'sqlite://', 'WTF_CSRF_ENABLED':False,
            'PUBLIC_DEMO_CANDIDATE':True,'PUBLIC_DEMO_COMPANY':'A','PUBLIC_DEMO_USERNAME':'viewer',
            'PUBLIC_DEMO_EPOCH':'event-v1','PUBLIC_DEMO_UNTIL':int(time.time())+3600,'PUBLIC_DEMO_VEHICLE_ID':1})
        limiter.enabled=False
        self.ctx=self.app.app_context();self.ctx.push();db.create_all()
        for code in ['A','B']:
            db.session.add(Company(company_code=code,company_name='青凪' if code=='A' else 'Other',active=True))
            db.session.add(User(company_code=code,username='viewer',role='admin',last_name='Demo',first_name='Viewer',password='unused',password_changed_at='2026-11-16 00:00:00'))
            db.session.add(Vehicle(company_code=code,chassis_number=code+'-SYNTHETIC',office='中央',deleted=False))
        db.session.commit();self.client=self.app.test_client()
    def tearDown(self):
        db.session.remove();db.drop_all();self.ctx.pop();self.env.stop()
    def enter(self):
        response=self.client.get('/demo');self.assertEqual(response.status_code,302);return response
    def test_real_templates_and_no_last_view_write(self):
        self.enter()
        user=User.query.filter_by(company_code='A').one();before=user.dashboard_settings_json
        for path in ['/vehicle/karte/1','/vehicle/karte/1/history','/vehicle/karte/1/parts','/vehicle/karte/1/costs','/vehicle/karte/1/documents']:
            response=self.client.get(path);self.assertEqual(response.status_code,200,path)
            self.assertIn(b'vehicle',response.data)
        db.session.refresh(user);self.assertEqual(user.dashboard_settings_json,before)
    def test_other_company_id_denied(self):
        self.enter()
        for tail in ['', '/history','/parts','/costs','/documents']:
            self.assertEqual(self.client.get('/vehicle/karte/2'+tail).status_code,404)
    def test_mutations_and_sensitive_routes_denied(self):
        self.enter()
        for method,path in [('post','/vehicle/karte/1/note'),('get','/settings'),('get','/itc'),('get','/notifications/1/open'),('get','/vehicle/karte/1/analysis/result'),('post','/api/push/subscribe'),('get','/static/uploads/anything.pdf')]:
            self.assertEqual(getattr(self.client,method)(path).status_code,403,path)
    def test_expiry_and_epoch_apply_to_existing_session(self):
        self.enter();self.app.config['PUBLIC_DEMO_EPOCH']='revoked'
        self.assertEqual(self.client.get('/vehicle/karte/1').status_code,410)
        self.enter();self.app.config['PUBLIC_DEMO_UNTIL']=int(time.time())-1
        self.assertEqual(self.client.get('/vehicle/karte/1').status_code,410)
        self.assertEqual(self.client.get('/demo').status_code,410)
    def test_fixed_identity_and_account_generation(self):
        self.assertEqual(self.client.get('/demo?company_code=B').status_code,400)
        self.enter();user=User.query.filter_by(company_code='A').one();db.session.execute(db.update(User).where(User.id==user.id).values(account_identity='changed'));db.session.commit()
        self.assertEqual(self.client.get('/vehicle/karte/1').status_code,410)
    def test_ordinary_session_is_not_replaced(self):
        with self.client.session_transaction() as s:s['username']='ordinary'
        self.assertEqual(self.client.get('/demo').status_code,409)
    def test_disable_revokes_existing_demo(self):
        self.enter();self.app.config['PUBLIC_DEMO_CANDIDATE']=False
        self.assertEqual(self.client.get('/vehicle/karte/1').status_code,410)
        self.assertEqual(self.client.get('/demo').status_code,404)
    def test_entry_is_rate_limited(self):
        limiter.enabled=True
        try:
            limiter.reset()
            statuses=[self.client.get('/demo').status_code for _ in range(31)]
            self.assertEqual(statuses[:30],[302]*30)
            self.assertEqual(statuses[30],429)
        finally:
            limiter.enabled=False
    def test_disabled_by_default(self):
        app=create_app({'TESTING':True,'SQLALCHEMY_DATABASE_URI':'sqlite://'})
        self.assertNotIn('PUBLIC_DEMO_CANDIDATE',app.config)

if __name__=='__main__':unittest.main()
