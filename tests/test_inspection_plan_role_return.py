import sys,unittest,html,re
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
D=Path(__file__).resolve().parents[1];sys.path[:0]=[str(D),str(D/'tests')]
from test_demo_role_return import RoleReturnTests
class Plans(RoleReturnTests):
 def test_plan_role_and_view(self):
  for role,view in (('manager','year'),('driver','month'),('manager','calendar')):
   token,_=self.enter()
   target='/vehicle/inspection-plans?scope=office&office=本社&month=2026-12&view='+view+'&kind=3month&state=candidate&q=101&vehicle_id='+str(self.vehicle_id)
   page=self.client.get(target);self.assertEqual(page.status_code,200)
   hidden=html.unescape(re.search(r'name="checklist_return" value="([^"]+)"',page.text)[1])
   before=self.models.VehicleChecklistResult.query.count()
   r=self.client.post('/demo/role',data={'role':role,'csrf_token':token,'checklist_return':hidden});self.assertEqual(r.status_code,302)
   self.assertEqual(urlsplit(r.location).path,'/vehicle/inspection-plans');self.assertEqual(parse_qs(urlsplit(r.location).query),parse_qs(urlsplit(target).query))
   after=self.client.get(r.location);self.assertEqual(after.status_code,200);self.assertNotIn('class="alert public-demo-notice"',after.text)
   self.assertEqual(self.models.VehicleChecklistResult.query.count(),before)
 def test_plan_reject_write_and_extra(self):
  token,_=self.enter()
  for target in ('/vehicle/inspection-plans/save','/vehicle/inspection-plans/export.xlsx','//evil.example/vehicle/inspection-plans','/vehicle/inspection-plans#x'):
   r=self.client.post('/demo/role',data={'role':'manager','csrf_token':token,'checklist_return':target});self.assertEqual(r.location,'/')
  r=self.client.post('/demo/role',data={'role':'manager','csrf_token':token,'checklist_return':'/vehicle/inspection-plans?scope=bad&month=evil&view=evil&next=https://evil.example&office=%0d%0aX:1&q=abc'})
  self.assertEqual(r.location,'/vehicle/inspection-plans?q=abc')
if __name__=='__main__':
 suite=unittest.TestSuite(Plans(n) for n in list(RoleReturnTests.__dict__) + list(Plans.__dict__) if n.startswith('test_'))
 result=unittest.TextTestRunner(verbosity=2).run(suite);sys.exit(not result.wasSuccessful())
