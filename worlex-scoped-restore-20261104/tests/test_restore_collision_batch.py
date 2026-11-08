"""Offline, synthetic-only differential collision tests. No Engine or sockets.

Uses SQLAlchemy's actual PostgreSQL/pg8000 compiler and reflection mapper, with
an inert connection supplying synthetic catalog/results. Not PostgreSQL E2E.
"""
import ast,copy,datetime as dt,decimal,hashlib,importlib.util,json,re,sys,unittest,uuid
from pathlib import Path
from unittest.mock import patch
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path[:0]=[str(ROOT),str(HERE)]
COLLISION_OFFLINE_EVIDENCE={}
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module
import collision_baseline as old
import worlex_restore as new
import test_restore_batched_catalog as helper
from sqlalchemy import Column,DateTime,LargeBinary,MetaData,String,Table,tuple_,select
from sqlalchemy.dialects.postgresql.pg8000 import PGDialect_pg8000
from sqlalchemy.sql.selectable import CompoundSelect,Select
from sqlalchemy import exc

class Connection(helper.InertConnection):
 def __init__(self,f,version=(18,0)):
  super().__init__(f,version)
  self.dialect=PGDialect_pg8000();self.dialect.server_version_info=version;self.engine.dialect=self.dialect
  self.tx=object();self.batches=[];self.expanded=[];self.result_mutator=None;self.execute_hook=None;self.fail_batch=None
 def get_transaction(self):return self.tx
 def in_transaction(self):return self.tx is not None
 def execute(self,statement,parameters=None):
  branches=list(statement.selects) if isinstance(statement,CompoundSelect) else [statement]
  batch=all(isinstance(s,Select) and list(s.selected_columns.keys())==['probe_ordinal','has_collision'] for s in branches)
  if not batch:return super().execute(statement,parameters)
  sql,params=self.compile(statement,parameters)
  self.application_calls.append((sql,params));trace=[];result=[]
  for branch in branches:
   cols=list(branch.selected_columns);ordinal=cols[0].element.value;inner=cols[1].element.element.element
   table=inner.get_final_froms()[0];source_query=self.compile(inner);trace.append(source_query);self.expanded.append(source_query)
   matches=any(all(helper.evaluate(c,r) for c in inner._where_criteria) for r in self.fixture['target'].get(table.name,[]))
   result.append((ordinal,matches))
  self.batches.append({'branches':len(branches),'binds':len(params),'sql_bytes':len(sql.encode()),'source_queries':trace})
  if self.execute_hook:self.execute_hook(self)
  if self.fail_batch==len(self.batches):raise exc.InterfaceError(None,None,RuntimeError('SYNTHETIC_DISCONNECT'))
  return helper.Result(self.result_mutator(result) if self.result_mutator else result)

def run(core,f,connection=None,mutation=None):
 c=connection or Connection(f);c.mutation=mutation
 try:
  with patch.object(core,'inspect',side_effect=lambda x:c.inspector() if x is c else None):core.check_empty_and_itc(c,f['tables'],f['typed'])
 except core.Stop as error:outcome=str(error)
 except exc.ArgumentError:outcome='ERROR:ArgumentError'
 else:outcome='PASS'
 return outcome,c

def unique_queries(connection):return [(s,p) for s,p in connection.application_calls if re.search(r'WHERE \(',s) and ' IN ((' in s and 'probe_ordinal' not in s]
def key(query):
 sql,params=query
 return sql,tuple((k,type(v).__name__,repr(v)) for k,v in params.items())
def distinct(queries):
 seen=set();out=[]
 for query in queries:
  k=key(query)
  if k not in seen:seen.add(k);out.append(query)
 return out

def full_fixture():
 from synthetic_fixture import fixture
 from test_restore_unit import policy_metadata
 policy=json.loads((ROOT/'policy.json').read_text());counts=json.loads((ROOT/'source-counts.json').read_text())
 data,columns,_=fixture(policy,counts);tables=policy_metadata(policy)
 typed,_=old.typed_payload(data,columns,tables,counts);old.defer_push_subscription(typed,old.DEFERRED_SOURCE_ROWS)
 catalog={name:{'oid':1000+i,'constraints':[],'indexes':[]} for i,(name,rows) in enumerate(typed.items()) if rows}
 target={'company':[{'id':1,'company_code':'ITC'},{'id':900000,'company_code':'SYNTHETIC_OTHER'}],
         'user':[{'id':1,'company_code':'ITC','username':'itc','role':'itc','account_identity':'00000000-0000-0000-0000-000000090000'}],
         'vehicle':[{'id':900000,'company_code':'SYNTHETIC_OTHER','chassis_number':'SYNTHETIC-OTHER'}]}
 f={'tables':tables,'typed':typed,'target':target,'catalog':catalog}
 contract=json.loads((HERE/'application_contract.json').read_text())
 for name,ddl in contract['tables'].items():
  if name not in catalog:continue
  for cols in re.findall(r'UNIQUE \(([^)]+)\)',ddl):
   names=[c.strip().strip('"') for c in cols.split(',')]
   helper.constraint(f,name,columns=names);helper.index(f,name,columns=names,duplicate=True)
 for ddl in contract['indexes']+[
  'CREATE UNIQUE INDEX uq_user_company_username ON "user" (company_code, username)',
  'CREATE UNIQUE INDEX uq_driver_company_employee_id ON driver (company_code, employee_id)',
  'CREATE UNIQUE INDEX uq_vehicle_checklist_result_target_date ON vehicle_checklist_result (company_code, checklist_id, vehicle_record_id, year, month, day)']:
  m=re.fullmatch(r'CREATE UNIQUE INDEX \w+ ON "?(\w+)"? \(([^)]+)\)',ddl)
  if m and m[1] in catalog:helper.index(f,m[1],columns=[c.strip().strip('"') for c in m[2].split(',')])
 return f

class CollisionBatchTests(unittest.TestCase):
 def equivalent(self,f,expected='PASS',**kw):
  before=copy.deepcopy((f['typed'],f['target'],f['catalog']))
  a,ca=run(old,f,**kw);b,cb=run(new,f,**kw)
  self.assertEqual(a,expected);self.assertEqual(b,expected)
  self.assertEqual(before,(f['typed'],f['target'],f['catalog']))
  if expected=='PASS':
   self.assertEqual(distinct(unique_queries(ca)),cb.expanded)
   self.assertEqual([x for x in ca.application_calls if x not in unique_queries(ca)],
                    [x for x in cb.application_calls if 'probe_ordinal' not in x[0]])
  self.assertEqual(ca.catalog_calls,cb.catalog_calls)
  return ca,cb
 def test_baseline_pin_and_exact_change_scope(self):
  original=(HERE/'collision_baseline.py').read_bytes();candidate=(ROOT/'worlex_restore.py').read_bytes()
  self.assertEqual(hashlib.sha256(original).hexdigest(),'d60e65fd1d19eb615ad880081e9ed368c93210d8057548f71f3ec57159471972')
  def split(raw):
   text=raw.decode();node=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=='check_empty_and_itc');lines=text.splitlines(keepends=True)
   return ''.join(lines[:node.lineno-1]+lines[node.end_lineno:]),node
  oa,on=split(original);na,nn=split(candidate)
  from integrated_change_scope import assert_unchanged_business_functions
  assert_unchanged_business_functions(self,candidate.decode())
  self.assertEqual([ast.dump(n) for n in on.body[:3]],[ast.dump(n) for n in nn.body[:3]])
  self.assertEqual([ast.dump(n) for n in on.body[-3:]],[ast.dump(n) for n in nn.body[-3:]])
  self.assertFalse(any(isinstance(n,ast.Assert) for n in ast.walk(nn)))
  dangerous={'commit','rollback','begin','begin_nested','connect','create_engine','exec_driver_sql','invalidate'}
  self.assertFalse(any(isinstance(n,ast.Attribute) and n.attr in dangerous for n in ast.walk(nn)))
 def test_empty_no_unique_no_extra_call(self):self.equivalent(helper.fixture())
 def test_empty_rows_skip_catalog_and_probe(self):
  f=helper.fixture();f['typed']['thing']=[];_,c=self.equivalent(f);self.assertEqual(c.batches,[])
 def test_duplicate_constraint_backing_index_one_probe(self):
  f=helper.fixture();helper.constraint(f);helper.index(f,duplicate=True)
  a,b=self.equivalent(f);self.assertEqual(len(unique_queries(a)),2);self.assertEqual(len(b.expanded),1);self.assertEqual(len(b.batches),1)
 def test_partial_metadata_not_used_to_hide_collision(self):
  f=helper.fixture();helper.constraint(f);helper.index(f,partial='key_b IS NOT NULL');f['target']['thing'][0].update(key_a='new',key_b=None)
  self.equivalent(f,'TARGET_UNIQUE_KEY_COLLISION:thing')
 def test_different_column_order_not_deduplicated(self):
  f=helper.fixture();helper.constraint(f,columns=['key_a','key_b']);helper.index(f,columns=['key_b','key_a']);_,c=self.equivalent(f);self.assertEqual(len(c.expanded),2)
 def test_same_columns_different_partial_metadata_checked(self):
  f=helper.fixture();helper.constraint(f);helper.index(f,partial='key_b IS NULL');_,c=self.equivalent(f);self.assertEqual(len(c.expanded),1)
 def test_invalid_later_duplicate_metadata_still_rejected(self):
  for factory,kwargs in [(helper.index,{'nnd':True}),(helper.constraint,{'nnd':True}),(helper.index,{'columns':['lower(key_a)'],'expression':True}),(helper.constraint,{'columns':[]})]:
   with self.subTest(factory=factory.__name__,kwargs=kwargs):
    f=helper.fixture();helper.constraint(f);factory(f,**kwargs)
    expected='ERROR:ArgumentError' if kwargs.get('expression') else 'NULLS_NOT_DISTINCT_INDEX_BLOCKED:thing' if kwargs.get('nnd') else 'EXPRESSION_UNIQUE_INDEX_BLOCKED:thing'
    self.equivalent(f,expected)
 def test_source_and_target_uniqueness_guards(self):
  f=helper.fixture();helper.constraint(f);f['typed']['thing'].append(dict(f['typed']['thing'][0],id=11));self.equivalent(f,'SOURCE_UNIQUE_KEY_COLLISION:thing')
  f=helper.fixture();helper.constraint(f);f['target']['thing'][0]['key_a']='new';self.equivalent(f,'TARGET_UNIQUE_KEY_COLLISION:thing')
 def test_itc_and_other_tenant_global_unique_collisions(self):
  for company in ['ITC','SYNTHETIC_OTHER',None]:
   f=helper.fixture();helper.constraint(f);f['target']['thing'][0].update(key_a='new',company_code=company);self.equivalent(f,'TARGET_UNIQUE_KEY_COLLISION:thing')
 def test_composite_key_respects_full_tuple(self):
  f=helper.fixture();helper.constraint(f,columns=['key_a','key_b']);f['target']['thing'][0]['key_a']='new';f['target']['thing'][0]['key_b']='different';self.equivalent(f)
 def test_null_keys_skipped_without_changing_null_policy(self):
  for cols in [['key_a'],['key_a','key_b']]:
   f=helper.fixture();helper.constraint(f,columns=cols);f['typed']['thing']=[dict(f['typed']['thing'][0],id=10+i,key_a=None) for i in range(2)];f['target']['thing'][0]['key_a']=None;_,c=self.equivalent(f);self.assertEqual(c.batches,[])
 def test_tenant_alias_pk_uuid_itc_guards_unchanged(self):
  f=helper.fixture();f['target']['thing'][0]['company_code']='wOrLeX';self.equivalent(f,'TARGET_WORLEX_OR_CASE_ALIAS_EXISTS:thing')
  f=helper.fixture();f['target']['thing'][0]['id']=10;self.equivalent(f,'PRIMARY_KEY_COLLISION:thing')
  f=helper.fixture(identity=True);self.equivalent(f)
  for field in ['account_identity','master_generation']:
   f=helper.fixture(identity=True);f['target']['thing'][0][field]='invalid';self.equivalent(f,'INVALID_EXISTING_GENERATION:thing')
   f=helper.fixture(identity=True);f['target']['thing'][0][field]=f['typed']['thing'][0][field];self.equivalent(f,'GENERATED_IDENTIFIER_COLLISION:thing')
  for table,code in [('company','ITC_COMPANY_MISSING'),('user','ITC_ADMIN_MISSING')]:
   f=helper.fixture();f['target'][table]=[];self.equivalent(f,code)
 def test_batch_first_middle_last_collision_original_order(self):
  for which in [0,8,15,16,35]:
   f=helper.fixture(36)
   for name in f['typed']:helper.constraint(f,name)
   name=list(f['typed'])[which];f['target'][name][0]['key_a']='new';self.equivalent(f,'TARGET_UNIQUE_KEY_COLLISION:'+name)
 def test_later_source_invalid_flushes_earlier_target_collision(self):
  for collision in [False,True]:
   f=helper.fixture(2);helper.constraint(f,'thing_000');helper.constraint(f,'thing_001')
   f['typed']['thing_001'].append(dict(f['typed']['thing_001'][0],id=11))
   if collision:f['target']['thing_000'][0]['key_a']='new'
   self.equivalent(f,'TARGET_UNIQUE_KEY_COLLISION:thing_000' if collision else 'SOURCE_UNIQUE_KEY_COLLISION:thing_001')
 def test_later_unsupported_index_preserves_earlier_target_precedence(self):
  f=helper.fixture(2);helper.constraint(f,'thing_000');helper.index(f,'thing_001',nnd=True);f['target']['thing_000'][0]['key_a']='new';self.equivalent(f,'TARGET_UNIQUE_KEY_COLLISION:thing_000')
 def test_chunk_sizes_zero_one_499_500_501_2571(self):
  for count in [0,1,499,500,501,2571]:
   with self.subTest(count=count):
    f=helper.fixture();helper.constraint(f);f['typed']['thing']=[{'id':1000+i,'company_code':'WORLEX','key_a':f'key{i:04d}','key_b':'b'} for i in range(count)]
    _,c=self.equivalent(f)
    sizes=[len([k for k in params if k.startswith('param_1_')]) for _,params in c.expanded]
    self.assertEqual(sizes,[500]*(count//500)+([count%500] if count%500 else []));self.assertTrue(all(n<=500 for n in sizes))
 def test_compilation_binding_unicode_uuid_date_binary_decimal(self):
  for value in ['日本語🚛',uuid.UUID('00000000-0000-0000-0000-000000000123'),dt.date(2026,11,8),dt.datetime(2026,11,8,tzinfo=dt.timezone.utc),b'\x00\xff\n',decimal.Decimal('123.450')]:
   with self.subTest(type=type(value).__name__):
    f=helper.fixture();helper.constraint(f);f['typed']['thing'][0]['key_a']=value;_,c=self.equivalent(f);self.assertTrue(any(type(v) is type(value) and v==value for v in c.expanded[0][1].values()))
 def test_caps_branches_and_bind_parameters(self):
  f=helper.fixture(36)
  for name in f['typed']:helper.constraint(f,name)
  _,c=self.equivalent(f);self.assertEqual([b['branches'] for b in c.batches],[16,16,4])
  f=helper.fixture(20)
  for name in f['typed']:
   helper.constraint(f,name,columns=['key_a','key_b']);f['typed'][name]=[{'id':1000+i,'company_code':'WORLEX','key_a':f'k{i}','key_b':'b'} for i in range(500)]
  _,c=self.equivalent(f);self.assertTrue(len(c.batches)>2)
  for b in c.batches:self.assertLessEqual(b['branches'],16);self.assertLessEqual(b['binds'],8000);self.assertLessEqual(b['sql_bytes'],131072)
 def test_sql_byte_cap_is_applied(self):
  f=helper.fixture(18)
  # Long bounded identifiers stress query bytes without increasing bind count.
  for i,name in enumerate(list(f['typed'])):
   table=f['tables'][name];long='column_'+('x'*8000)+str(i);table.append_column(Column(long,String));helper.constraint(f,name,columns=[long]);f['typed'][name][0][long]='synthetic'
  _,c=self.equivalent(f);self.assertGreater(len(c.batches),2);self.assertTrue(all(b['sql_bytes']<=131072 for b in c.batches))
 def test_single_oversize_probe_fails_closed(self):
  f=helper.fixture();long='column_'+('x'*70000);f['tables']['thing'].append_column(Column(long,String));helper.constraint(f,columns=[long]);f['typed']['thing'][0][long]='synthetic'
  outcome,c=run(new,f);self.assertEqual(outcome,'COLLISION_PROBE_BUDGET_EXCEEDED');self.assertEqual(c.batches,[])
 def test_single_probe_bind_cap_fails_closed(self):
  f=helper.fixture();columns=['key_a','key_b']
  for i in range(15):
   name='wide_'+str(i);f['tables']['thing'].append_column(Column(name,String));columns.append(name)
  helper.constraint(f,columns=columns)
  f['typed']['thing']=[dict({'id':1000+i,'company_code':'WORLEX'},**{name:f'k{i}' for name in columns}) for i in range(500)]
  outcome,c=run(new,f);self.assertEqual(outcome,'COLLISION_PROBE_BUDGET_EXCEEDED');self.assertEqual(c.batches,[])
 def test_duplicate_missing_or_extra_ordinal_same_length_fails(self):
  for mutate in [lambda r:[r[0],r[0],r[2]],lambda r:[r[0],r[1],(3,False)],lambda r:r[:-1]]:
   f=helper.fixture(3)
   for name in f['typed']:helper.constraint(f,name)
   c=Connection(f);c.result_mutator=mutate;outcome,c=run(new,f,c);self.assertEqual(outcome,'COLLISION_RESULT_SHAPE_CHANGED');self.assertEqual(len(c.batches),1)
 def test_malformed_result_shapes_rejected(self):
  mutations=[lambda r:[],lambda r:r+r,lambda r:[(999,False)],lambda r:[(True,False)],lambda r:[(0,0)],lambda r:[(0,None)],lambda r:[(0,False,'extra')],lambda r:[None],lambda r:None]
  for mutate in mutations:
   f=helper.fixture();helper.constraint(f);c=Connection(f);c.result_mutator=mutate
   outcome,c=run(new,f,c);self.assertEqual(outcome,'COLLISION_RESULT_SHAPE_CHANGED');self.assertEqual(len(c.batches),1)
 def test_reordered_valid_result_rows_are_matched_by_ordinal(self):
  f=helper.fixture(3)
  for name in f['typed']:helper.constraint(f,name)
  c=Connection(f);c.result_mutator=lambda rows:list(reversed(rows));self.assertEqual(run(new,f,c)[0],'PASS')
 def test_disconnect_not_retried_or_replaced_with_fallback(self):
  for count in [1,17,36]:
   f=helper.fixture(count)
   for name in f['typed']:helper.constraint(f,name)
   c=Connection(f);c.fail_batch=1
   with self.assertRaises(exc.InterfaceError):run(new,f,c)
   self.assertEqual(len(c.batches),1)
 def test_disconnect_during_flush_before_invalid_source_not_retried(self):
  f=helper.fixture(2);helper.constraint(f,'thing_000');helper.constraint(f,'thing_001',nnd=True);c=Connection(f);c.fail_batch=1
  with self.assertRaises(exc.InterfaceError):run(new,f,c)
  self.assertEqual(len(c.batches),1)
 def test_same_transaction_required_before_and_after_query(self):
  f=helper.fixture();helper.constraint(f);c=Connection(f);c.tx=None
  self.assertEqual(run(new,f,c)[0],'COLLISION_TRANSACTION_REQUIRED');self.assertEqual(c.batches,[])
  c=Connection(f);c.execute_hook=lambda conn:setattr(conn,'tx',object())
  self.assertEqual(run(new,f,c)[0],'COLLISION_TRANSACTION_CHANGED');self.assertEqual(len(c.batches),1)
 def test_no_result_cache_across_calls_or_connections(self):
  f=helper.fixture();helper.constraint(f);helper.index(f,duplicate=True);c=Connection(f)
  self.assertEqual(run(new,f,c)[0],'PASS');self.assertEqual(run(new,f,c)[0],'PASS');self.assertEqual(len(c.batches),2)
  f['target']['thing'][0]['key_a']='new';self.assertEqual(run(new,f,c)[0],'TARGET_UNIQUE_KEY_COLLISION:thing');self.assertEqual(len(c.batches),3)
  self.assertEqual(run(new,f)[0],'TARGET_UNIQUE_KEY_COLLISION:thing')
 def test_catalog_failure_scope_guards_unchanged(self):
  for method,code in [('get_multi_unique_constraints','UNIQUE_CATALOG_SCOPE_MISMATCH'),('get_multi_indexes','INDEX_CATALOG_SCOPE_MISMATCH')]:
   def mutate(called,result):return {} if called==method else result
   self.equivalent(helper.fixture(),code,mutation=mutate)
  for kind in ['table_oids','unique_constraints','indexes']:
   f=helper.fixture();c=Connection(f);c.fail_kind=kind
   with self.assertRaises(exc.InterfaceError):run(new,f,c)
   self.assertEqual(c.batches,[])
 def test_diagnostic_allowlist_new_statements_and_denials(self):
  self.assertEqual(hashlib.sha256((HERE/'collision_diagnostic_guard.py').read_bytes()).hexdigest(),'b4933631d0a78c6e98b340b4d9f6dedf4c817dfe0fe272b591619ac9b15fedd7')
  guard=load('collision_diagnostic_guard',HERE/'collision_diagnostic_guard.py')
  f=helper.fixture(18)
  for name in f['typed']:helper.constraint(f,name)
  _,c=self.equivalent(f)
  for sql,_ in c.application_calls:self.assertEqual(guard.guard_sql(sql,'check_empty_and_itc',True),'tenant_collision_query')
  for sql in ["SELECT nextval('x')","SELECT pg_sleep(1)","SELECT 1; SELECT 2","DELETE FROM t","SELECT 1 UNION ALL SELECT evil(1)"]:
   with self.assertRaises(guard.Stop):guard.guard_sql(sql,'check_empty_and_itc',True)
  with self.assertRaises(guard.Stop):guard.guard_sql(c.application_calls[-1][0],'check_empty_and_itc',False)
 def test_full_count_synthetic_fixture_query_reduction(self):
  f=full_fixture();self.assertEqual(sum(map(len,f['typed'].values())),4099);self.assertEqual(sum(bool(v) for v in f['typed'].values()),36)
  a,b=self.equivalent(f)
  evidence={'source':'synthetic full-count fixture with pinned application contract plus three explicit bootstrap indexes','private_backup_read':False,'database_connected':False,
   'application_calls_before':len(a.application_calls),'application_calls_after':len(b.application_calls),'catalog_calls_before':len(a.catalog_calls),'catalog_calls_after':len(b.catalog_calls),
   'unique_probe_round_trips_before':len(unique_queries(a)),'unique_probe_round_trips_after':len(b.batches),'distinct_natural_key_predicates':len(b.expanded),
   'max_branches':max(x['branches'] for x in b.batches),'max_binds':max(x['binds'] for x in b.batches),'max_sql_bytes':max(x['sql_bytes'] for x in b.batches),'batch_sizes':[{k:v for k,v in x.items() if k!='source_queries'} for x in b.batches],
   'predicates_and_binds_equivalent':True,'noncollision_application_calls_unchanged':True,'preserved_fixture_unchanged':True,'postgresql_e2e_passed':False,'transport_disconnect_fix_proven':False}
  COLLISION_OFFLINE_EVIDENCE.clear();COLLISION_OFFLINE_EVIDENCE.update(evidence)
  self.assertLess(len(b.application_calls),len(a.application_calls));self.assertEqual(len(a.catalog_calls),3);self.assertEqual(len(b.catalog_calls),3)

if __name__=='__main__':unittest.main(verbosity=2)
