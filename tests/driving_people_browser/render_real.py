"""Disposable SQLite real Flask route; no deployed resources."""
import os,sys,json,unittest
from pathlib import Path
from unittest.mock import patch
repo=Path(os.environ['PRODUCT_REPO']).resolve();sys.path[:0]=[str(repo),str(repo/'tests')]
import test_driving_workspace as workspace
from driving_report_data import payload
class Directory(workspace.WorkspaceTests):
 def test_real_pages(self):
  out=Path(os.environ['HTML_OUT']);out.mkdir(parents=True,exist_ok=True)
  prior=self.save(4,day='2026-09-10',distance='20',count='3')
  for row,counts in [(self.a,('1','4')),(prior,('3','2'))]:
   data=payload(row); prototype=data['report_items'][0]; items=[]
   for name,count in zip(['急加速','急減速'],counts):
    item=dict(prototype,item_name=name,value=count,raw_result=count+'回',definition=name+'の回数');items.append(item)
   data['report_items']=items;row.details_json=json.dumps(data,ensure_ascii=False)
  self.base='/safety/driving-reports?period=custom&start=2026-10-01&end=2026-10-31&compare=custom&compare_start=2026-09-01&compare_end=2026-09-30'
  self.m.db.session.commit()
  # Existing fixture's users/reports are synthetic and company-filtered.
  for row in [self.secret,self.b]:
   data=payload(row);data['review']={'note':'範囲外の振り返り本文'};row.details_json=json.dumps(data,ensure_ascii=False)
  self.m.db.session.commit()
  for mode,note in [('empty',''),('content','車間距離を確認しました。\n次の運行でも余裕を持って操作します。<script>not executable</script>')]:
   data=payload(self.a);data['review']={'state':'reviewed','note':note};self.a.details_json=json.dumps(data,ensure_ascii=False);self.m.db.session.commit()
   response,ctx=self.render(self.base+'&scope=office&panel=analysis')
   html=response.get_data(as_text=True);self.assertIn('driving-directory-table',html)
   self.assertNotIn('他社の秘密',html);self.assertNotIn('範囲外の振り返り本文',html);self.assertNotIn('分析を見る →',html)
   self.assertIn('aria-label="減少"',html);self.assertIn('aria-label="増加"',html)
   if note:self.assertIn('&lt;script&gt;not executable&lt;/script&gt;',html)
   else:self.assertNotIn('driving-person-review-entry',html)
   (out/(mode+'.html')).write_text(html)
  (out/'route.json').write_text(json.dumps({'url':self.base+'&scope=office&panel=analysis','cases':2,'synthetic':True}))
# Run only the new real-route case, not inherited suite as new tests.
if __name__=='__main__':
 result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([Directory('test_real_pages')]));sys.exit(not result.wasSuccessful())
