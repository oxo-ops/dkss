import ast, pathlib, re, json, unittest
from types import SimpleNamespace
ROOT=pathlib.Path(__file__).parent
class Integer:pass
class Stop(Exception):pass
def require(ok,code):
 if not ok:raise Stop(code)
def q(s):
 require(bool(re.fullmatch('[a-z_][a-z_0-9]*',s)),'UNSAFE_IDENTIFIER');return '"'+s+'"'
def load(name):
 tree=ast.parse((ROOT/name if name == "sequence_baseline.py" else ROOT.parent/name).read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='sequence_states')
 ns=dict(Integer=Integer,Stop=Stop,require=require,q=q,text=lambda s:s)
 exec(compile(ast.Module(body=[node],type_ignores=[]),name,'exec'),ns);return ns['sequence_states']
class Result:
 def __init__(self,x):self.x=x
 def one(self):return self.x[0]
 def all(self):return self.x
 def tuples(self):return iter(self.x)
class Conn:
 def __init__(self,items):self.items=items;self.calls=[];self.value_calls=[]
 def scalar(self,sql,p):
  self.calls.append(sql);return self.items[p['table'].split('"')[1]]['seq']
 def execute(self,sql,p):
  self.calls.append(sql)
  if sql.startswith('WITH requested(ord,table_name'):
   return Result([(p['i%d'%i],self.items[p['t%d'%i].split('"')[1]]['seq'],*(self.items[p['t%d'%i].split('"')[1]]['meta'] if self.items[p['t%d'%i].split('"')[1]]['seq'] else [None]*16)) for i in range(len(p)//3)])
  if sql.startswith('WITH requested(ord,seq)'):
   out=[]
   for key in p:
    if key.startswith('i'):
     i=p[key];item=next(v for v in self.items.values() if v['seq']==p['s%d'%i]);out.extend((i,*r) for r in item['dep'])
   return Result(out)
  item=next(v for v in self.items.values() if v['seq']==p['seq'])
  if sql.startswith('SELECT n.nspname'):return Result([item['meta']])
  if sql.startswith('SELECT d.refobjid'):return Result(item['dep'])
  raise AssertionError(sql)
 def exec_driver_sql(self,sql):
  self.calls.append(sql);self.value_calls.append(sql)
  if sql.startswith('ALTER'):return Result([])
  item=next(v for v in self.items.values() if '"'+v['meta'][1]+'"' in sql)
  return Result([item['value']])
def setup(n=36):
 names=['push_subscription']+['table_%02d'%i for i in range(n-1)]
 items={name:dict(seq='public.'+name+'_id_seq',meta=['public',name+'_id_seq',100+i,10,None,'p',None,0,200+i,23,1,1,1,2147483647,1,False],dep=[[300+i,1,'a']],value=[i+5,bool(i%2),32]) for i,name in enumerate(names)}
 tables={name:SimpleNamespace(primary_key=[SimpleNamespace(name='id',type=Integer())]) for name in names}
 return items,tables
base,new=load('sequence_baseline.py'),load('worlex_restore.py');reports=[]
def run(label,mutate=lambda x,t:None,n=36,lock=False):
 items,tables=setup(n);mutate(items,tables);a,b=Conn(items),Conn(items)
 def outcome(fn,conn):
  try:return ('ok',fn(conn,tables,lock))
  except Stop as e:return ('stop',str(e))
 x,y=outcome(base,a),outcome(new,b);assert x==y,(label,x,y)
 if x[0]=='ok':assert a.value_calls==b.value_calls,label
 if lock:assert not any(s.startswith('ALTER') and 'push_subscription' in s for s in b.calls)
 reports.append(dict(case=label,status=x[0],old_queries=len(a.calls),new_queries=len(b.calls)))
class SequenceBatchDifferential(unittest.TestCase):
 def test_all_differential_guards(self):
  run('36_readonly');run('36_locked',lock=True)
  run('one_readonly',n=1);run('one_locked',n=1,lock=True)
  for idx,value,label in [(0,'other','schema'),(11,2,'increment'),(12,2,'minimum'),(14,2,'cache'),(15,True,'cycle')]:
   run(label,lambda x,t,i=idx,v=value:x['push_subscription']['meta'].__setitem__(i,v))
  run('ownership_missing',lambda x,t:x['push_subscription'].__setitem__('dep',[]))
  run('ownership_multiple',lambda x,t:x['push_subscription'].__setitem__('dep',[[1,1,'a'],[2,1,'a']]))
  run('sequence_missing',lambda x,t:x['push_subscription'].__setitem__('seq',None))
  def nonserial(x,t):
   x['push_subscription']['seq']=None;t['push_subscription'].primary_key[0].name='code';t['push_subscription'].primary_key[0].type=object()
  run('nonserial_valid',nonserial)
  run('later_sequence_missing',lambda x,t:x['table_34'].__setitem__('seq',None),lock=True)
  run('later_cache_invalid',lambda x,t:x['table_34']['meta'].__setitem__(14,2),lock=True)
  assert new(Conn({}),{})=={}
