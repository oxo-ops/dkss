"""Disposable SQLite real GET pages; no live credentials or remote services."""
import os,sys,json,unittest,socket
from pathlib import Path
import sqlalchemy
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('network forbidden'))
socket.create_connection=socket.socket.connect
original=sqlalchemy.create_engine
def sqlite_only(url,*a,**k):
 assert str(url).startswith('sqlite:')
 return original(url,*a,**k)
sqlalchemy.create_engine=sqlite_only
sqlalchemy.engine.create.create_engine=sqlite_only
R=Path(os.environ['PRODUCT_REPO']).resolve()
sys.path[:0]=[str(R/'tests/demo_guide/fixtures'),str(R/'tests'),str(R)]
from test_demo_inspection_compact import CompactDemoTests
class Pages(CompactDemoTests):
 def test_pages(self):
  self.enter();m=self.models;out=Path(os.environ['HTML_OUT']);out.mkdir(parents=True,exist_ok=True)
  u=m.User.query.filter_by(company_code='AONAGI',username='checker').one()
  for i,status in enumerate(['Good','none','承認待ち','差し戻し','承認済み']):
   self.db.session.add(m.PatrolResult(company_code='AONAGI',created_by_username=u.username,created_by_user_id=u.id,created_by_identity=u.account_identity,created_by_name='Test checker',date='2026-11-18',office='test',category='Good' if status=='Good' else '指摘',target_type='user',target_user='Test checker',target_username=u.username,target_user_id=u.id,target_identity=u.account_identity,content=('通路の荷物と歩行者動線を確認。負傷なし。'+('長い本文を省略せず確認します。'*25 if i==1 else '')),approval_status=status,countermeasure='' if status=='none' else '通路を整理しました',files_json=json.dumps(['synthetic.png'] if i%2==0 else [])))
  self.db.session.commit()
  rows=[]
  for role,username in [('manager','admin'),('driver','checker')]:
   self.login(username)
   with self.client.session_transaction() as s:s['demo_role_selected']=True
   r=self.client.get('/pointouts');self.assertEqual(r.status_code,200);self.assertIn('patrol-row-extra',r.text)
   (out/f'{role}.html').write_text(r.text)
   for p in m.PatrolResult.query.filter_by(company_code='AONAGI').all():
    detail=self.client.get(f'/pointouts/{p.id}');self.assertEqual(detail.status_code,200);(out/f'{role}-detail-{p.id}.html').write_text(detail.text)
   for variant,query,expected in [('filtered','keyword=通路&category=Good',1),('empty','keyword=NO_MATCH_42&category=Good',0)]:
    filtered=self.client.get('/pointouts?type=user&page_size=8&'+query)
    self.assertEqual(filtered.status_code,200)
    self.assertEqual(filtered.text.count('<article class="safety-result-mobile-card">'),expected)
    self.assertIn('value="Good"',filtered.text)
    (out/f'{role}-{variant}.html').write_text(filtered.text)
   rows.append({'role':role,'count':m.PatrolResult.query.filter_by(company_code='AONAGI').count(),'real_filtered_get':True,'empty_get':True})
  (out/'routes.json').write_text(json.dumps(rows))
if __name__=='__main__':
 r=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([Pages('test_pages')]))
 sys.exit(not r.wasSuccessful())
