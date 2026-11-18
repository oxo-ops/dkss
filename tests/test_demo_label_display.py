import importlib.util, unittest, copy, ast
from pathlib import Path
from flask import Flask, session, render_template_string
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('display',ROOT/'dkss_app/demo_label_display.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Tests(unittest.TestCase):
 def setUp(self):
  self.app=Flask(__name__);self.app.secret_key='isolated';self.app.config.update(PUBLIC_DEMO_CANDIDATE=True,PUBLIC_DEMO_SHARED_COMPANY=True,PUBLIC_DEMO_COMPANY='AONAGI')
  self.app.add_url_rule('/history','vehicle_karte_history',lambda:'')
  self.app.add_url_rule('/safety','checklist_result_detail',lambda:'')
  self.app.add_url_rule('/patrols','pointouts',lambda:'')
  self.app.add_url_rule('/patrol/11','pointout_detail',lambda:'',methods=['GET','POST'])
 def mark(self):session.update(aonagi_readonly_demo=True,company_code='AONAGI')
 def plan(self,**kw):
  args=dict(value='港南車両サービス（架空）',company='AONAGI',vehicle_id=649,plan_id=8,event_id=8);args.update(kw);return m.plan_factory(**args)
 def approval(self,**kw):
  args=dict(value='体験用管理者確認',company='AONAGI',checklist_id=13,result_id=17);args.update(kw);return m.approval_label(**args)
 def test_plan_exact_and_scopes(self):
  with self.app.test_request_context('/history'):
   self.mark();self.assertEqual(self.plan(),'港南車両サービス')
   for kw in [dict(company='B'),dict(vehicle_id=648),dict(plan_id=9),dict(event_id=9),dict(value='別社（架空）')]:self.assertEqual(self.plan(**kw),kw.get('value','港南車両サービス（架空）'))
 def test_approval_exact_scopes_roles(self):
  with self.app.test_request_context('/safety'):
   self.mark()
   for role in ['driver','admin']:
    session['role']=role
    for rid in [14,15,16,17]:self.assertEqual(self.approval(result_id=rid),'管理者確認')
   for kw in [dict(company='B'),dict(checklist_id=12),dict(result_id=13),dict(result_id=18),dict(value='他の体験用管理者確認')]:self.assertEqual(self.approval(**kw),kw.get('value','体験用管理者確認'))
 def test_normal_and_configuration(self):
  with self.app.test_request_context('/safety'):
   session['company_code']='AONAGI';self.assertEqual(self.approval(),'体験用管理者確認');self.mark()
   for key,value in [('PUBLIC_DEMO_CANDIDATE',False),('PUBLIC_DEMO_SHARED_COMPANY',False),('PUBLIC_DEMO_COMPANY','B')]:
    old=self.app.config[key];self.app.config[key]=value;self.assertEqual(self.approval(),'体験用管理者確認');self.app.config[key]=old
 def test_non_display_endpoints(self):
  with self.app.test_request_context('/history'):
   self.mark();self.assertEqual(self.approval(),'体験用管理者確認')
  with self.app.test_request_context('/safety'):
   self.mark();self.assertEqual(self.plan(),'港南車両サービス（架空）')
  self.assertEqual(self.approval(),'体験用管理者確認')
 def test_source_and_escaping(self):
  original={'label':'体験用管理者確認','candidate_usernames':['x'],'approved_by':'y','status':'approved','date':'2026-11-18'};before=copy.deepcopy(original)
  with self.app.test_request_context('/safety'):
   self.mark();self.assertEqual(render_template_string('{{ f(a.label) }}',a=original,f=lambda s:self.approval(value=s)),'管理者確認');self.assertEqual(original,before)
   self.assertEqual(render_template_string('{{ f(v) }}',v='<img src=x onerror=alert(1)>',f=lambda s:self.approval(value=s)),'&lt;img src=x onerror=alert(1)&gt;')


 def test_patrol_exact_read_only_display(self):
  for endpoint in ['/patrols','/patrol/11']:
   with self.app.test_request_context(endpoint):
    self.mark()
    for rid,raw in m._PATROL_CONTENT.items():
     for role in ['driver','admin']:
      session['role']=role
      self.assertEqual(m.patrol_content(raw,company='AONAGI',result_id=rid),raw.removeprefix('【体験用・架空】'))
     for company,other_id,value in [('OTHER',rid,raw),('AONAGI',99,raw),('AONAGI',rid,raw+'変更'),('AONAGI',rid,'別の【体験用・架空】本文')]:
      self.assertEqual(m.patrol_content(value,company=company,result_id=other_id),value)
    for key,value in [('PUBLIC_DEMO_CANDIDATE',False),('PUBLIC_DEMO_SHARED_COMPANY',False),('PUBLIC_DEMO_COMPANY','OTHER')]:
     before=self.app.config[key];self.app.config[key]=value
     self.assertEqual(m.patrol_content(raw,company='AONAGI',result_id=rid),raw)
     self.app.config[key]=before
    session.pop('aonagi_readonly_demo')
    self.assertEqual(m.patrol_content(raw,company='AONAGI',result_id=rid),raw)
  raw=m._PATROL_CONTENT[11]
  for path,method in [('/history','GET'),('/patrol/11','POST')]:
   with self.app.test_request_context(path,method=method):
    self.mark();self.assertEqual(m.patrol_content(raw,company='AONAGI',result_id=11),raw)
  self.assertEqual(m.patrol_content(raw,company='AONAGI',result_id=11),raw)
 def test_patrol_raw_field_preserved(self):
  tree=ast.parse((ROOT/'dkss_app/checklist_common.py').read_text())
  fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='patrol_result_to_dict')
  result_dict=next(n for n in ast.walk(fn) if isinstance(n,ast.Dict))
  fields={k.value:v for k,v in zip(result_dict.keys,result_dict.values)}
  self.assertEqual(ast.unparse(fields['content']),'result.content')
  self.assertIn('patrol_content',ast.unparse(fields['display_content']))
  for name,key in [('pointouts.html','item'),('pointout_detail.html','result')]:
   source=(ROOT/'templates'/name).read_text()
   self.assertIn('data-value="{{ '+key+'.display_content|default('+key+'.content) }}"',source)
   self.assertNotIn('data-value="{{ '+key+'.content }}"',source)
if __name__=='__main__':unittest.main()

