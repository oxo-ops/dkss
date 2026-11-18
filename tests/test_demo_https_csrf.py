"""HTTPS CSRF + demo response referrer-policy regression. Synthetic database only."""
import re,html,json,unittest
from test_demo_inspection_compact import CompactDemoTests
class HttpsTests(CompactDemoTests):
 def test_detail_https_referrer_contract(self):
  from flask import g
  self.login('checker')
  self.app.config['WTF_CSRF_ENABLED']=True
  self.addCleanup(self.app.config.update,WTF_CSRF_ENABLED=False)
  self.assertTrue(self.app.config['WTF_CSRF_SSL_STRICT'])
  cid=self.app.config['PUBLIC_DEMO_CHECKLIST_ID'];path=f'/vehicle/checklists/{cid}'
  p={'vehicle_record_id':self.vehicle_id,'year':'2026','month':'10','day':'23','active_day':'23','item_no':'7','comment':'作動時に拭き残しが見られる'}
  g.pop('csrf_token',None);g.pop('csrf_valid',None)
  page=self.client.get(path,query_string=p,base_url='https://localhost');self.assertEqual(page.status_code,200)
  policy=page.headers['Referrer-Policy'];print('GET policy:',policy)
  token=html.unescape(re.search(r'name="csrf_token" value="([^"]+)"',page.get_data(as_text=True))[1])
  def snap():return tuple(tuple(tuple(getattr(r,c.name) for c in m.__table__.columns) for r in m.query.order_by(m.id).all()) for m in (self.models.VehicleChecklistResult,self.models.ChecklistEvent,self.models.Notification))
  def post(ref=None,t=token):
   g.pop('csrf_token',None);g.pop('csrf_valid',None)
   headers={'X-DKSS-Validation-Only':'1'}
   if ref:headers['Referer']=ref
   return self.client.post(path+'/save-detail',data={**p,'csrf_token':t},headers=headers,base_url='https://localhost')
  before=snap()
  for ref,t in [(None,token),('https://evil.example/',token),('https://localhost'+path,'wrong')]:
   reply=post(ref,t);self.assertEqual(reply.status_code,400);self.assertEqual(before,snap())
  # Browser follows the response policy: no-referrer omits header; same-origin retains it.
  reply=post('https://localhost'+path if policy=='same-origin' else None)
  self.assertEqual(policy,'same-origin');self.assertEqual(reply.status_code,302)
  row=self.models.VehicleChecklistResult.query.filter_by(company_code='A').one()
  self.assertEqual(next(a for a in json.loads(row.answers_json) if str(a['item_no'])=='7')['comment'],p['comment'])
  before=snap()
  target=path+'?vehicle_record_id='+str(self.vehicle_id)
  for role in ('manager','driver'):
   g.pop('csrf_token',None);g.pop('csrf_valid',None)
   page=self.client.get(path,query_string=p,base_url='https://localhost')
   self.assertEqual(page.status_code,200)
   fresh=html.unescape(re.search(r'name="csrf_token" value="([^"]+)"',page.get_data(as_text=True))[1])
   g.pop('csrf_token',None);g.pop('csrf_valid',None)
   reply=self.client.post('/demo/role',base_url='https://localhost',headers={'Referer':'https://localhost'+path},data={'role':role,'csrf_token':fresh,'checklist_return':target})
   self.assertEqual(reply.status_code,302);self.assertEqual(reply.location,target)
   with self.client.session_transaction() as state:self.assertEqual(state['demo_role'],role)
   self.assertEqual(snap(),before)

def load_tests(loader,tests,pattern):return unittest.TestSuite([HttpsTests('test_detail_https_referrer_contract')])
if __name__=='__main__':unittest.main(verbosity=2)
