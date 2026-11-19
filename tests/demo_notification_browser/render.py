"""Synthetic actual GET responses. No sockets or non-SQLite database."""
import os,sys,json,socket,unittest,re
from pathlib import Path
from urllib.parse import urlencode
import sqlalchemy
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external socket forbidden'))
socket.create_connection=socket.socket.connect
_create=sqlalchemy.create_engine
def sqlite_only(url,*a,**kw):
 assert str(url).startswith('sqlite:');return _create(url,*a,**kw)
sqlalchemy.create_engine=sqlite_only
R=Path(os.environ['PRODUCT_REPO']).resolve()
sys.path[:0]=[str(R/'tests/demo_guide/fixtures'),str(R/'tests'),str(R)]
from test_demo_inspection_compact import CompactDemoTests
class Pages(CompactDemoTests):
 def test_entries(self):
  from dkss_app.demo_label_display import _NOTIFICATION_LABELS
  out=Path(os.environ['HTML_OUT']);out.mkdir(parents=True,exist_ok=True)
  self.enter();m=self.models
  u=m.User.query.filter_by(company_code='AONAGI',username='checker').one()
  for nid,(raw,label) in _NOTIFICATION_LABELS.items():
   self.db.session.add(m.Notification(id=nid,company_code='AONAGI',target_user=u.username,target_username=u.username,owner_identity=u.account_identity,title='安全パトロールが差し戻されました' if nid==259 else '車両の運行判断：'+('判定保留' if nid==262 else '運行不可'),message=raw,link='/pointouts/10' if nid==259 else '/vehicle/checklists/1',read=True,created_at='2026-11-17 10:00:00'))
  self.db.session.commit()
  before={n.id:(n.message,n.read,n.link,n.workflow_context_json) for n in m.Notification.query.all()}
  for mode in ['demo','normal','other']:
   self.demo_active=mode=='demo';self.login('checker','B' if mode=='other' else 'AONAGI')
   listing=self.client.get('/notifications');self.assertEqual(listing.status_code,200)
   recent=self.client.get('/api/notifications/recent');self.assertEqual(recent.status_code,200)
   (out/(mode+'-list.html')).write_text(listing.text)
   for nid,(raw,label) in _NOTIFICATION_LABELS.items():
    r=self.client.get(f'/notifications/{nid}?panel=1')
    if mode=='other':self.assertEqual(r.status_code,404);continue
    self.assertEqual(r.status_code,200)
    detail=r.get_json()['html']
    if mode=='demo':
     self.assertNotIn(label,detail);self.assertNotIn(label,listing.text);self.assertNotIn(label,json.dumps(recent.get_json(),ensure_ascii=False))
    else:
     self.assertIn(label,detail);self.assertIn(label,listing.text)
    (out/f'{mode}-{nid}.html').write_text(detail)
  after={n.id:(n.message,n.read,n.link,n.workflow_context_json) for n in m.Notification.query.all()}
  self.assertEqual(before,after)
if __name__=='__main__':
 r=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([Pages('test_entries')]));sys.exit(not r.wasSuccessful())
