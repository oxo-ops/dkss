import os,sys,json,unittest
from pathlib import Path
from unittest.mock import patch
p=Path(os.environ['PRODUCT_REPO']).resolve();sys.path[:0]=[str(p),str(p/'tests')]
from test_driving_admin_self import AdminSelfTests
from identity_fixture import identity_for
class Render(AdminSelfTests):
 def test_render(self):
  out=Path(os.environ['HTML_OUT']);out.mkdir(parents=True,exist_ok=True)
  for mode,scope in [('self','self'),('office','office'),('user','self')]:
   if mode=='user':
    with self.client.session_transaction() as state:state.update(account_identity=identity_for(state.get('company_code'),'two',app=self.client.application),username='two',role='user',password_changed_at='stamp')
   for period in ['all']:
    url='/safety/driving-reports?scope='+scope+'&period='+period+'&compare=previous&panel=reports'
    with patch('driving_report_reflection.generate',side_effect=AssertionError('no AI')):
     response,ctx=self.render(url)
    (out/(mode+'-'+period+'.html')).write_text(response.get_data(as_text=True))
  print('3 real report templates rendered, no AI')
if __name__=='__main__':
 r=unittest.TextTestRunner().run(unittest.TestSuite([Render('test_render')]));sys.exit(not r.wasSuccessful())
