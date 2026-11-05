#!/usr/bin/env python3
"""Fail-closed, INSERT-only WORLEX restore. Never initialize or reset a database.

CLI uses one fixed archive and a structural policy. inspect is read-only;
execute is one transaction and requires the unchanged preflight plan plus an
explicit stopped-writers acknowledgement. Error details never expose row data.
"""
from __future__ import annotations
import argparse, datetime as dt, decimal, hashlib, json, os, re, subprocess, sys, tarfile, tempfile, uuid
from pathlib import Path
from sqlalchemy import (MetaData, Column, String, Integer, Boolean, DateTime, Date,
                        LargeBinary, Numeric, Float, select, func, text, create_engine, inspect, tuple_)
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

TENANT='WORLEX'
DEFERRED_SOURCE_ROWS={'push_subscription':[1]}
RESTORE_SCOPE={'source_rows':4100,'source_tables':37,'imported_rows':4099,
               'imported_tables':36,'deferred_rows':1,
               'deferred_source_rows':DEFERRED_SOURCE_ROWS}
SOURCE_MANIFEST_SHA256='eec49dd1e9a605b32bfd2eda777061be6e6c68fe4cd0193a8051f475bbd864e0'
SOURCE_COPY_SHA256='895a5f2eb85b6ea36df5154c606cfe8db4f65c60a5a3ac5fa550b0c1c4add012'
EXPECTED_HOST='dpg-dbkk5juc6qcc73am01r0-a.oregon-postgres.render.com'
EXPECTED_DATABASE='dkss_db_new_20261103'
EXPECTED_USER='dkss_db_new_20261103_user'
ARCHIVE_SHA256='a9cd94646f002f06a231412cbcb445283022c8fcaae0a16d82607bbe595a0565'
RETIRED={'checklist_result':{'target_vehicle'},'user':{'favorite_vehicles_json','microsoft_account_email','microsoft_connected','microsoft_tenant_id','microsoft_user_id','teams_notify_enabled'},'vehicle_checklist_notify_setting':{'vehicle_id'},'vehicle_checklist_result':{'vehicle_id'},'vehicle_patrol':{'vehicle_id'}}
LOGICAL_REFS=[('checklist_result','checklist_id','checklist','id'),('vehicle_checklist_result','checklist_id','checklist','id'),('vehicle_checklist_notify_setting','checklist_id','checklist','id'),('vehicle_checklist_result','vehicle_record_id','vehicle','id'),('vehicle_checklist_notify_setting','vehicle_record_id','vehicle','id')]
class Stop(RuntimeError): pass
def require(value, code):
 if not value: raise Stop(code)
def valid_uuid(value):
 try:return isinstance(value,str) and str(uuid.UUID(value))==value and uuid.UUID(value).int!=0
 except (ValueError,TypeError,AttributeError):return False
def sha(value):return hashlib.sha256(value).hexdigest()
def canonical(value):
 if hasattr(value,'_mapping'):return canonical(tuple(value))
 if isinstance(value,(bytes,bytearray,memoryview)):return {'bytes_sha256':sha(bytes(value)),'length':len(value)}
 if isinstance(value,dt.datetime):
  if value.tzinfo:value=value.astimezone(dt.timezone.utc).replace(tzinfo=None)
  return value.isoformat()
 if isinstance(value,decimal.Decimal):
  rendered=format(value,'f')
  return '0' if value==0 else (rendered.rstrip('0').rstrip('.') if '.' in rendered else rendered)
 if isinstance(value,dt.date):return str(value)
 if isinstance(value,dict):return {k:canonical(v) for k,v in value.items()}
 if isinstance(value,(list,tuple)):return [canonical(v) for v in value]
 return value
def digest(value):return sha(json.dumps(canonical(value),sort_keys=True,separators=(',',':'),ensure_ascii=False).encode())
def q(name):
 require(isinstance(name,str) and re.fullmatch(r'[a-z_][a-z_0-9]*',name),'UNSAFE_IDENTIFIER')
 return '"'+name+'"'
def decode_copy(value):
 if value==r'\N':return None
 def replace(m):
  v=m[1]
  if v in 'bfnrtv':return dict(b='\b',f='\f',n='\n',r='\r',t='\t',v='\v')[v]
  if re.fullmatch('[0-7]{1,3}',v):return chr(int(v,8))
  if v.startswith('x') and len(v)>1:return chr(int(v[1:],16))
  return v
 return re.sub(r'\\([0-7]{1,3}|x[0-9a-fA-F]{1,2}|.)',replace,value)
def read_copy(path):
 data={}; columns={}
 with Path(path).open(encoding='utf-8') as stream:
  for line in stream:
   m=re.fullmatch(r'COPY (?:public|"public")\.((?:"[^"]+")|\w+) \(([^\n]+)\) FROM stdin;\n?',line)
   if not m:continue
   name=m[1].strip('"');q(name)
   require(name not in data,'DUPLICATE_COPY_TABLE')
   cols=[c.strip('" ') for c in m[2].split(',')]
   require(len(cols)==len(set(cols)) and 'company_code' in cols,'UNSCOPED_SOURCE_TABLE')
   columns[name]=cols;data[name]=[];ended=False
   for line in stream:
    if line.rstrip('\n')==r'\.':ended=True;break
    values=line.rstrip('\n').split('\t');require(len(values)==len(cols),'COPY_WIDTH_MISMATCH')
    row=dict(zip(cols,map(decode_copy,values)))
    if row.get('company_code')==TENANT:data[name].append(row)
   require(ended,'COPY_NOT_TERMINATED')
 return data,columns

def copy_digest(path):
 state=hashlib.sha256();inside=False
 with Path(path).open('rb') as stream:
  for line in stream:
   if line.startswith(b'COPY public.') or line.startswith(b'COPY "public".'):inside=True
   if inside:state.update(line)
   if inside and line.rstrip(b'\n')==b'\\.':inside=False
 require(not inside,'COPY_NOT_TERMINATED')
 return state.hexdigest()

def render_environment(directory,environ=None):
 # Keep libpq credentials/service overrides out, while preserving only the
 # Windows OS paths required by side-by-side assemblies and crypto providers.
 source=os.environ if environ is None else environ
 env={'PATH':os.defpath,'HOME':str(directory),'LANG':'C.UTF-8','TZ':'UTC'}
 for key in ('SYSTEMROOT','WINDIR'):
  value=next((v for k,v in source.items() if k.upper()==key),None)
  if value:env[key]=value
 if os.name=='nt':require(bool(env.get('SYSTEMROOT')),'WINDOWS_SYSTEMROOT_MISSING')
 return env

def classify_render_failure(stderr):
 message=(stderr.decode('utf-8',errors='replace') if isinstance(stderr,bytes) else str(stderr or '')).lower()
 for fragment,code in (
  ('wsastartup() failed','WINDOWS_SOCKET_PROVIDER_INITIALIZATION_FAILED'),
  ('could not generate restrict key','RESTRICT_KEY_GENERATION_FAILED'),
  ('could not open output file','OUTPUT_FILE_ACCESS_FAILED'),
  ('could not open input file','INPUT_FILE_ACCESS_FAILED'),
  ('unsupported version','ARCHIVE_VERSION_UNSUPPORTED'),
  ('could not read from input file','INPUT_FILE_READ_FAILED'),
  ('could not decompress','ARCHIVE_DECOMPRESSION_FAILED'),
  ('permission denied','FILE_PERMISSION_DENIED')):
  if fragment in message:return code
 return 'UNCLASSIFIED_PROCESS_FAILURE'

def render_archive(archive,pg_restore,directory):
 archive=Path(archive);require(sha(archive.read_bytes())==ARCHIVE_SHA256,'ARCHIVE_HASH_MISMATCH')
 root=Path(directory);dump=root/'dump';dump.mkdir(mode=0o700)
 with tarfile.open(archive,'r:gz') as tar:
  members=tar.getmembers();require(len(members)<2000,'ARCHIVE_SIZE_LIMIT')
  total=0
  for member in members:
   parts=Path(member.name).parts
   require(not Path(member.name).is_absolute() and '..' not in parts,'UNSAFE_ARCHIVE_PATH')
   require(member.isfile() or member.isdir(),'UNSAFE_ARCHIVE_MEMBER')
   total+=member.size;require(total<250_000_000,'ARCHIVE_SIZE_LIMIT')
  # Map directory-format members into a neutral local directory. The original
  # timestamp directory contains ':' and cannot be created safely on Windows.
  files=[m for m in members if m.isfile()]
  require(len({m.name.rsplit('/',1)[0] for m in files})==1,'UNEXPECTED_ARCHIVE_LAYOUT')
  names=set()
  for member in files:
   name=member.name.rsplit('/',1)[-1]
   require(re.fullmatch(r'(?:toc|[0-9]+)\.dat',name) and name not in names,'UNEXPECTED_ARCHIVE_FILENAME')
   names.add(name)
   source=tar.extractfile(member);require(source is not None,'ARCHIVE_MEMBER_UNREADABLE')
   with source, (dump/name).open('xb') as target:target.write(source.read())
 toc=list(dump.rglob('toc.dat'));require(len(toc)==1,'ARCHIVE_TOC_COUNT')
 output=root/'rendered.sql'
 env=render_environment(root)
 # Explicit binary, no destination argument and no inherited libpq/service settings.
 result=subprocess.run([str(Path(pg_restore).resolve(strict=True)),'--file',str(output),str(toc[0].parent)],env=env,capture_output=True,timeout=90)
 require(result.returncode==0,'OFFLINE_RENDER_FAILED:'+classify_render_failure(result.stderr))
 require(output.is_file(),'OFFLINE_RENDER_OUTPUT_MISSING')
 return output

def type_family(t):
 if isinstance(t,Boolean):return 'bool'
 if isinstance(t,Integer):return 'integer'
 if isinstance(t,DateTime):return 'datetime'
 if isinstance(t,Date):return 'date'
 if isinstance(t,LargeBinary):return 'binary'
 if isinstance(t,Float):return 'float'
 if isinstance(t,Numeric):return 'numeric'
 if isinstance(t,String):return 'text'
 return str(t).lower()
def policy_type(value):
 return {'BOOLEAN':'bool','INTEGER':'integer','BIGINT':'integer','SMALLINT':'integer','DATETIME':'datetime','DATE':'date','BLOB':'binary','FLOAT':'float','NUMERIC':'numeric','VARCHAR':'text','TEXT':'text'}.get(value,value.lower())

def validate_schema(connection,policy,*,building_ci_seal=False):
 require(digest(policy.get('restore_scope'))==digest(RESTORE_SCOPE),'RESTORE_SCOPE_POLICY_REQUIRED')
 require(connection.dialect.name=='postgresql','POSTGRESQL_REQUIRED')
 require(connection.scalar(text('SHOW server_version_num')) and int(connection.scalar(text('SHOW server_version_num')))>=180000 and int(connection.scalar(text('SHOW server_version_num')))<190000,'POSTGRESQL_18_REQUIRED')
 require(connection.scalar(text("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema','public') AND n.nspname NOT LIKE 'pg_toast%' AND n.nspname NOT LIKE 'pg_temp%' AND c.relkind IN ('r','p','f')"))==0,'UNREVIEWED_NONPUBLIC_TABLES')
 require(connection.scalar(text("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND (c.relkind IN ('p','f') OR c.relrowsecurity OR c.relforcerowsecurity OR c.relispartition)"))==0,'UNSUPPORTED_TABLE_SECURITY_OR_PARTITION')
 require(connection.scalar(text("SELECT count(*) FROM pg_inherits i JOIN pg_class c ON c.oid=i.inhrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'"))==0,'INHERITANCE_BLOCKED')
 require(connection.scalar(text("SELECT count(*) FROM pg_rewrite r JOIN pg_class c ON c.oid=r.ev_class JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r'"))==0,'CUSTOM_RULE_BLOCKED')
 require(connection.scalar(text("SELECT count(*) FROM pg_event_trigger WHERE evtenabled<>'D'"))==0,'EVENT_TRIGGER_BLOCKED')
 require(connection.scalar(text("SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='public' AND NOT c.convalidated"))==0,'UNVALIDATED_CONSTRAINT')
 require(connection.scalar(text("SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND (NOT i.indisvalid OR NOT i.indisready)"))==0,'INVALID_INDEX')
 require(connection.scalar(text('SHOW session_replication_role'))=='origin','REPLICATION_ROLE_BLOCKED')
 require(connection.scalar(text("SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND t.tgisinternal AND t.tgenabled<>'O'"))==0,'INTERNAL_CONSTRAINT_TRIGGER_DISABLED')
 md=MetaData();md.reflect(connection,schema='public')
 tables={t.name:t for t in md.tables.values()}
 require(set(tables)==set(policy['tables']),'SCHEMA_TABLE_SET_CHANGED')
 for name,t in tables.items():
  expected=policy['tables'][name]; actual=set(t.c.keys());wanted=set(expected['columns'])
  if name=='vehicle':actual.discard('vehicle_id')
  require(actual==wanted,'SCHEMA_COLUMNS_CHANGED:'+name)
  require([c.name for c in t.primary_key]==expected['pk'],'SCHEMA_PRIMARY_KEY_CHANGED:'+name)
  require(sorted([[f.parent.name,f.column.table.name,f.column.name] for f in t.foreign_keys])==expected['fk'],'SCHEMA_FOREIGN_KEYS_CHANGED:'+name)
  for colname,e in expected['columns'].items():
   col=t.c[colname]
   require(type_family(col.type)==policy_type(e['type']),'SCHEMA_TYPE_CHANGED:'+name+'.'+colname)
   require(getattr(col.type,'length',None)==e['length'],'SCHEMA_LENGTH_CHANGED:'+name+'.'+colname)
   require(col.nullable==e['nullable'],'SCHEMA_NULLABILITY_CHANGED:'+name+'.'+colname)
  if name=='vehicle' and 'vehicle_id' in t.c:
   c=t.c.vehicle_id;require(type_family(c.type)=='text' and getattr(c.type,'length',None)==50 and c.nullable and c.server_default is None and c.computed is None and c.identity is None,'LEGACY_VEHICLE_ID_INCOMPATIBLE')
 # Refuse unreviewed executable database logic. FK/internal triggers remain enabled.
 triggers=list(connection.execute(text("SELECT c.relname,t.tgname,t.tgenabled,t.tgtype,t.tgargs,p.proname,p.prosrc,p.prosecdef,p.proconfig,l.lanname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_proc p ON p.oid=t.tgfoid JOIN pg_language l ON l.oid=p.prolang WHERE n.nspname='public' AND NOT t.tgisinternal ORDER BY 1,2")).mappings())
 expected_triggers={}
 for name in policy['analysis_input_tables']:
  field='id' if name=='vehicle' else ('vehicle_record_id' if 'vehicle_record_id' in tables[name].c else '')
  expected_triggers[(name,'dkss_analysis_'+name)]=(29,'dkss_analysis_input_changed',(field+'\0').encode())
  expected_triggers[(name,'dkss_analysis_'+name+'_truncate')]=(32,'dkss_analysis_input_truncated',b'')
 require({(r['relname'],r['tgname']) for r in triggers}==set(expected_triggers),'TRIGGER_SET_CHANGED')
 for r in triggers:
  kind,fn,args=expected_triggers[(r['relname'],r['tgname'])]
  require(r['tgenabled']=='O' and r['tgtype']==kind and bytes(r['tgargs'])==args and r['proname']==fn and r['lanname']=='plpgsql' and not r['prosecdef'] and r['proconfig'] is None,'TRIGGER_SIGNATURE_CHANGED')
  require(r['prosrc']==policy['trigger_functions'][fn],'TRIGGER_FUNCTION_CHANGED')
 # Including full pg definitions catches changes in defaults, indexes and checks.
 structure={
  'columns':list(connection.execute(text("SELECT table_name,column_name,data_type,udt_name,is_nullable,column_default,character_maximum_length,numeric_precision,numeric_scale,datetime_precision,collation_name,is_identity,identity_generation,is_generated,generation_expression FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name,ordinal_position")).tuples()),
  'constraints':list(connection.execute(text("SELECT c.relname,co.conname,pg_get_constraintdef(co.oid) FROM pg_constraint co JOIN pg_class c ON c.oid=co.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY 1,2")).tuples()),
  'indexes':list(connection.execute(text("SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY 1,2")).tuples()),
  'triggers':list(connection.execute(text("SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid),p.prosrc,nf.nspname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_proc p ON p.oid=t.tgfoid JOIN pg_namespace nf ON nf.oid=p.pronamespace WHERE n.nspname='public' AND NOT t.tgisinternal ORDER BY 1,2")).tuples())}
 structure['columns']=[r for r in structure['columns'] if not (r[0]=='vehicle' and r[1]=='vehicle_id')]
 signature=digest(structure)
 if not building_ci_seal:
  require(policy.get('postgres_structure_sha256') and policy.get('postgres_acceptance_passed') is True,'POSTGRES_CI_SEAL_REQUIRED')
  require(policy.get('windows_render_acceptance_passed') is True,'WINDOWS_CI_SEAL_REQUIRED')
  require(policy.get('tested_runner_sha256')==sha(Path(__file__).read_bytes()),'RUNNER_DIFFERS_FROM_POSTGRES_TESTED_REVISION')
  require(signature==policy['postgres_structure_sha256'],'POSTGRES_CATALOG_DIFFERS_FROM_TESTED_SCHEMA')
 return tables,signature

def typed_payload(data,columns,tables,expected_counts,generated=None):
 require(set(data)==set(expected_counts),'SOURCE_TABLE_SET_CHANGED')
 require({n:len(rows) for n,rows in data.items()}==expected_counts,'SOURCE_COUNT_CHANGED')
 vehicles={r['id']:r for r in data.get('vehicle',[])}
 typed={}; normalized=0
 for name,rows in data.items():
  require(name in tables or not rows,'UNMODELED_SOURCE_TABLE')
  if name not in tables:continue
  table=tables[name];typed[name]=[]
  for row in rows:
   require(row.get('company_code')==TENANT,'CROSS_TENANT_PAYLOAD')
   converted={}
   for col,val in row.items():
    if col not in table.c:
     if name=='vehicle' and col=='vehicle_id':converted[col]=val;continue
     require(col in RETIRED.get(name,set()),'UNMAPPED_SOURCE_COLUMN')
     if col=='vehicle_id':
      require(not val or (row.get('vehicle_record_id') in vehicles and vehicles[row['vehicle_record_id']].get('vehicle_id')==val),'LEGACY_VEHICLE_LABEL_MISMATCH')
     else:require(val in (None,'','[]','{}','f'),'NONEMPTY_RETIRED_FIELD')
     continue
    typ=table.c[col].type
    if val is not None:
     if isinstance(typ,Boolean):require(val in ('t','f'),'INVALID_BOOLEAN');val=val=='t'
     elif isinstance(typ,Integer):val=int(val)
     elif isinstance(typ,Float):val=float(val)
     elif isinstance(typ,Numeric):val=decimal.Decimal(val)
     elif isinstance(typ,DateTime):val=dt.datetime.fromisoformat(val)
     elif isinstance(typ,Date):val=dt.date.fromisoformat(val)
     elif isinstance(typ,LargeBinary):require(val.startswith('\\x'),'INVALID_BYTEA');val=bytes.fromhex(val[2:])
    converted[col]=val
   if name=='vehicle' and converted.get('chassis_number')=='':converted['chassis_number']=None;normalized+=1
   if name=='user':converted['account_identity']=(generated[name][str(converted['id'])]['account_identity'] if generated is not None else str(uuid.uuid4()))
   if 'master_generation' in table.c:converted['master_generation']=(generated[name][str(converted['id'])]['master_generation'] if generated is not None else str(uuid.uuid4()))
   if 'notification_identities_json' in table.c:converted['notification_identities_json']='{}'
   # Do not infer any historical person/owner binding. Reflected Core, no ORM hooks.
   for col in table.c:
    if col.name not in converted:
     if not col.nullable:raise Stop('UNMAPPED_REQUIRED_COLUMN:'+name+'.'+col.name)
     if col.nullable:converted[col.name]=None
   for field in ('account_identity','master_generation'):
    if field in converted:require(valid_uuid(converted[field]),'INVALID_GENERATED_IDENTIFIER')
   typed[name].append(converted)
 require(normalized==11,'CHASSIS_NORMALIZATION_COUNT_CHANGED')
 require(sum(not r['deleted'] for r in typed['vehicle'])==289 and sum(r['deleted'] for r in typed['vehicle'])==276,'VEHICLE_STATE_COUNTS_CHANGED')
 # Real and synthetic acceptance share these hard cardinalities.
 require(len(typed['user'])==15 and len(typed['vehicle'])==565 and len(typed['vehicle_operation_record'])==2571,'CRITICAL_COUNTS_CHANGED')
 keys={}
 for name,rows in typed.items():
  for col in tables[name].primary_key:
   vals=[r[col.name] for r in rows];require(None not in vals,'SOURCE_PRIMARY_KEY_INVALID')
   keys[(name,col.name)]=set(vals)
  for field in ('account_identity','master_generation'):
   values=[r[field] for r in rows if field in r]
   require(len(values)==len(set(values)),'DUPLICATE_GENERATED_IDENTIFIER')
  primary=[tuple(r[c.name] for c in tables[name].primary_key) for r in rows]
  require(len(primary)==len(set(primary)),'SOURCE_PRIMARY_KEY_INVALID')
 edges=set()
 refs=[(n,f.parent.name,f.column.table.name,f.column.name) for n,t in tables.items() for f in t.foreign_keys]
 refs += [r for r in LOGICAL_REFS if r[0] in typed]
 for name,col,target,target_col in refs:
  for row in typed.get(name,[]):
   val=row.get(col)
   require(val is None or val in keys.get((target,target_col),set()),'SOURCE_REFERENCE_NOT_TENANT_CLOSED:'+name+'.'+col)
   if val is not None and name!=target:edges.add((name,target))
 order=[];remaining={n for n,r in typed.items() if r}
 while remaining:
  ready=sorted(n for n in remaining if not any(a==n and b in remaining for a,b in edges))
  require(ready,'CYCLIC_POPULATED_TABLE_DEPENDENCY');order+=ready;remaining-=set(ready)
 return typed,order

def defer_push_subscription(typed,deferred_source_rows):
 """Select one reviewed legacy row for deferral; do not mutate the source data.

 This runs only AFTER typed_payload has validated the complete source closure.
 Keeping an empty push table in typed makes post-write checks require zero
 imported WORLEX subscriptions. There is no remapping or quarantine insertion.
 """
 require(digest(deferred_source_rows)==digest(DEFERRED_SOURCE_ROWS),'DEFERRED_SOURCE_SCOPE_CHANGED')
 rows=typed.get('push_subscription',[])
 require(len(rows)==1 and type(rows[0].get('id')) is int and rows[0]['id']==1 and rows[0].get('company_code')==TENANT,'DEFERRED_SOURCE_ROW_CHANGED')
 require(rows[0].get('owner_identity') is None,'HISTORICAL_PUSH_OWNER_MUST_REMAIN_UNBOUND')
 typed['push_subscription']=[]

def import_scope(counts,deferred_source_rows):
 require(digest(deferred_source_rows)==digest(DEFERRED_SOURCE_ROWS),'DEFERRED_SOURCE_SCOPE_CHANGED')
 require(counts.get('push_subscription')==1 and sum(counts.values())==4100 and sum(bool(n) for n in counts.values())==37,'DEFERRED_SOURCE_COUNTS_CHANGED')
 imported=dict(counts);imported['push_subscription']=0
 require(sum(imported.values())==4099 and sum(bool(n) for n in imported.values())==36,'IMPORTED_COUNTS_CHANGED')
 return {**RESTORE_SCOPE,'import_counts':imported}

def assert_no_deferred_references(tables):
 # Retain the original reviewed-schema guard after removing the old ID remap.
 # Source closure was checked before deferral; imported rows must never depend
 # on a row deliberately excluded from the restore.
 require(not any(f.column.table.name=='push_subscription' for t in tables.values() for f in t.foreign_keys),'PUSH_ID_REFERENCE_REQUIRES_REVIEW')
 require(not any(target=='push_subscription' for _,_,target,_ in LOGICAL_REFS),'PUSH_LOGICAL_REFERENCE_REQUIRES_REVIEW')

def prepare_deferred_push(connection,tables,typed):
 audit=tables['audit_log']
 existing=list(connection.execute(select(audit).where(func.lower(audit.c.company_code)==TENANT.lower())).mappings())
 # Only the observed failed-login audit may coexist with imported history.
 # Its full row, plus every other existing audit, is bound to the plan snapshot.
 require(len(existing)<=1 and all(r['company_code']==TENANT and r['id']==1 and r['created_at']=='2026-11-04 07:55:08' and r['action']=='login_failed' and r['target_type']=='user' and r['actor_identity'] is None and r['actor_name'] is None for r in existing),'EXISTING_WORLEX_AUDIT_NOT_APPROVED')
 assert_no_deferred_references(tables)
 defer_push_subscription(typed,DEFERRED_SOURCE_ROWS)
 return len(existing)

def verify_deferred_plan(approved,data,counts):
 scope=import_scope(counts,approved.get('deferred_source_rows'))
 require(type(approved.get('version')) is int and approved['version']==3 and all(digest(approved.get(k))==digest(v) for k,v in scope.items()),'DEFERRED_PLAN_SCOPE_CHANGED')
 require(digest(approved.get('source_counts'))==digest(counts) and approved.get('archive_sha256')==ARCHIVE_SHA256 and approved.get('tenant')==TENANT,'DEFERRED_PLAN_SOURCE_CHANGED')
 require(approved.get('deferred_source_sha256')==digest(data.get('push_subscription')),'DEFERRED_SOURCE_DIGEST_CHANGED')
 require('push_subscription_id_remap' not in approved,'LEGACY_PUSH_REMAP_PLAN_BLOCKED')
 return scope

def snapshot(connection,tables,exclude_vehicle_compat=False,audit_import_ids=()):
 result={}
 for name,t in sorted(tables.items()):
  stmt=select(*[c for c in t.c if not (exclude_vehicle_compat and name=='vehicle' and c.name=='vehicle_id')])
  if name=='audit_log':
   if audit_import_ids:stmt=stmt.where(t.c.id.not_in(audit_import_ids))
  elif 'company_code' in t.c:stmt=stmt.where((t.c.company_code!=TENANT)|(t.c.company_code.is_(None)))
  # Sorting by row digests works for tables without a primary key and binary columns.
  rows=sorted(digest(dict(r)) for r in connection.execute(stmt).mappings())
  result[name]={'count':len(rows),'sha256':digest(rows)}
 return result

def identity(connection):
 row=connection.execute(text("SELECT current_database(),current_user,(SELECT oid FROM pg_database WHERE datname=current_database()),inet_server_addr()::text,inet_server_port(),current_setting('server_version_num')")).one()
 return digest(tuple(row))

def check_empty_and_itc(connection,tables,typed):
 for name,t in tables.items():
  if 'company_code' in t.c and name!='audit_log':
   require(connection.scalar(select(func.count()).select_from(t).where(func.lower(t.c.company_code)==TENANT.lower()))==0,'TARGET_WORLEX_OR_CASE_ALIAS_EXISTS:'+name)
 for name,rows in typed.items():
  table=tables[name]
  for pk in table.primary_key:
   values=[r[pk.name] for r in rows]
   if values:require(connection.execute(select(pk).where(pk.in_(values))).first() is None,'PRIMARY_KEY_COLLISION:'+name)
 for name,table in tables.items():
  for field in ('account_identity','master_generation'):
   if field not in table.c:continue
   existing=list(connection.scalars(select(table.c[field])))
   require(all(valid_uuid(v) for v in existing) and len(existing)==len(set(existing)),'INVALID_EXISTING_GENERATION:'+name)
   require(not set(existing).intersection(r[field] for r in typed.get(name,[]) if field in r),'GENERATED_IDENTIFIER_COLLISION:'+name)
 inspector=inspect(connection)
 for name,rows in typed.items():
  if not rows:continue
  table=tables[name]
  indexes=inspector.get_unique_constraints(name,schema='public')+ [i for i in inspector.get_indexes(name,schema='public') if i.get('unique')]
  for index in indexes:
   cols=index.get('column_names') or []
   require(cols and all(c in table.c for c in cols),'EXPRESSION_UNIQUE_INDEX_BLOCKED:'+name)
   # Apply full-key checks conservatively for partial indexes. False positives stop.
   require(not index.get('dialect_options',{}).get('postgresql_nulls_not_distinct'),'NULLS_NOT_DISTINCT_INDEX_BLOCKED:'+name)
   seen=set()
   for row in rows:
    values=tuple(row.get(c) for c in cols)
    if None in values:continue
    require(values not in seen,'SOURCE_UNIQUE_KEY_COLLISION:'+name);seen.add(values)
   values=list(seen)
   for offset in range(0,len(values),500):
    require(connection.execute(select(*[table.c[c] for c in cols]).where(tuple_(*[table.c[c] for c in cols]).in_(values[offset:offset+500])).limit(1)).first() is None,'TARGET_UNIQUE_KEY_COLLISION:'+name)
 user=tables['user']; company=tables['company']
 require(connection.scalar(select(func.count()).select_from(company).where(company.c.company_code=='ITC'))==1,'ITC_COMPANY_MISSING')
 require(connection.scalar(select(func.count()).select_from(user).where(user.c.company_code=='ITC',user.c.username=='itc',user.c.role=='itc'))>=1,'ITC_ADMIN_MISSING')

def sequence_states(connection,tables,lock=False):
 states={}
 for name,t in sorted(tables.items()):
  for col in t.primary_key:
   seq=connection.scalar(text('SELECT pg_get_serial_sequence(:table,:column)'),{'table':'public.'+q(name),'column':col.name})
   if not seq:
    require(not (col.name=='id' and isinstance(col.type,Integer)),'OWNED_ID_SEQUENCE_MISSING:'+name)
    continue
   meta=connection.execute(text("SELECT n.nspname,c.relname,c.oid,c.relowner,c.relacl::text,c.relpersistence,c.reloptions,c.reltablespace,c.relfilenode,s.seqtypid,s.seqstart,s.seqincrement,s.seqmin,s.seqmax,s.seqcache,s.seqcycle FROM pg_sequence s JOIN pg_class c ON c.oid=s.seqrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.oid=CAST(:seq AS regclass)"),{'seq':seq}).one()
   schema,sn,oid,owner,acl,persistence,options,tablespace,filenode,type_oid,start,inc,mn,mx,cache,cycle=meta
   ownership=[list(r) for r in connection.execute(text("SELECT d.refobjid,d.refobjsubid,d.deptype FROM pg_depend d WHERE d.classid='pg_class'::regclass AND d.objid=CAST(:seq AS regclass) AND d.refclassid='pg_class'::regclass AND d.deptype IN ('a','i') ORDER BY 1,2,3"),{'seq':seq}).tuples()]
   require(schema=='public' and inc==1 and mn==1 and cache==1 and not cycle and len(ownership)==1,'UNSUPPORTED_SEQUENCE:'+name)
   qualified=q(schema)+'.'+q(sn)
   # Even a no-op ALTER touches sequence state/catalog. Never issue one for
   # the preserved push sequence. All writer sessions and tables are locked.
   if lock and name!='push_subscription':connection.exec_driver_sql('ALTER SEQUENCE '+qualified+' CACHE 1')
   last,called,log_cnt=connection.exec_driver_sql('SELECT last_value,is_called,log_cnt FROM '+qualified).one()
   states[(name,col.name)]={'qualified':qualified,'last':last,'called':called,'next':last+1 if called else last,'max':mx,
    'catalog':{'schema':schema,'name':sn,'oid':oid,'owner':owner,'acl':acl,'type_oid':type_oid,'start':start,'increment':inc,'min':mn,'max':mx,'cache':cache,'cycle':cycle,'ownership':ownership}}
   if name=='push_subscription':
    states[(name,col.name)]['log_cnt']=log_cnt
    states[(name,col.name)]['catalog'].update(persistence=persistence,options=options,tablespace=tablespace,filenode=filenode)
 return states

def require_push_sequence_unchanged(states,baseline,code):
 key=('push_subscription','id')
 require(key in states and 'push_subscription.id' in baseline and digest(states[key])==digest(baseline['push_subscription.id']),code)

def plan(connection,data,columns,policy,counts,source_sha,generated=None):
 tables,schema_hash=validate_schema(connection,policy)
 typed,order=typed_payload(data,columns,tables,counts,generated)
 scope=import_scope(counts,DEFERRED_SOURCE_ROWS)
 preserved_audits=prepare_deferred_push(connection,tables,typed)
 check_empty_and_itc(connection,tables,typed)
 baseline=snapshot(connection,tables)
 seq=sequence_states(connection,tables)
 generated={name:{str(r['id']):{field:r[field] for field in ('account_identity','master_generation') if field in r} for r in rows} for name,rows in typed.items() if rows and any(field in rows[0] for field in ('account_identity','master_generation'))}
 return {**scope,'deferred_source_sha256':digest(data['push_subscription']),'preserved_worlex_audit_rows':preserved_audits,'generated_identifiers':generated,'version':3,'tenant':TENANT,'source_sha256':source_sha,'archive_sha256':ARCHIVE_SHA256,'runner_sha256':sha(Path(__file__).read_bytes()),'policy_sha256':digest(policy),'target_sha256':identity(connection),'schema_sha256':schema_hash,'preserved_rows_sha256':digest(baseline),'sequence_baseline':{'.'.join(k):v for k,v in seq.items()},'sequences_sha256':digest(sorted((list(k),v) for k,v in seq.items())),'source_counts':counts,'blank_chassis_to_null':11,'account_owner_policy':'new account UUID; historical owner/actor identity NULL; no username rebinding','legacy_vehicle_id_addition': 'vehicle_id' not in tables['vehicle'].c}

def execute_restore(connection,data,columns,policy,counts,source_sha,approved_plan,*,inject_failure=False):
 """Caller owns ONE transaction. All exceptions must roll it back, never retry."""
 require(connection.in_transaction(),'TRANSACTION_REQUIRED')
 connection.exec_driver_sql("SET LOCAL lock_timeout='10s'")
 connection.exec_driver_sql("SET LOCAL statement_timeout='120s'")
 connection.exec_driver_sql("SET LOCAL idle_in_transaction_session_timeout='180s'")
 connection.exec_driver_sql("SET LOCAL transaction_timeout='300s'")
 connection.exec_driver_sql("SET LOCAL search_path=pg_catalog,public")
 require(connection.scalar(text('SELECT pg_try_advisory_xact_lock(873624100,20261104)')),'RESTORE_ALREADY_RUNNING')
 # Every writer pool must have been stopped externally. No termination is attempted.
 def no_sessions():
  require(connection.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND backend_type='client backend'"))==0,'OTHER_DATABASE_SESSIONS_PRESENT')
 no_sessions()
 names=list(connection.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")))
 require(names,'TARGET_SCHEMA_MISSING')
 connection.exec_driver_sql('LOCK TABLE '+','.join('public.'+q(n) for n in names)+' IN ACCESS EXCLUSIVE MODE')
 no_sessions()
 # Validate AFTER locks, not only at the earlier read-only inspection.
 current=plan(connection,data,columns,policy,counts,source_sha,approved_plan.get('generated_identifiers'))
 require(current==approved_plan,'PREFLIGHT_PLAN_CHANGED')
 tables,_=validate_schema(connection,policy)
 baseline=snapshot(connection,tables)
 typed,order=typed_payload(data,columns,tables,counts,approved_plan['generated_identifiers'])
 verify_deferred_plan(approved_plan,data,counts)
 assert_no_deferred_references(tables)
 defer_push_subscription(typed,approved_plan['deferred_source_rows'])
 order=[name for name in order if typed[name]]
 seq=sequence_states(connection,tables,lock=True)
 require(digest(sorted((list(k),v) for k,v in seq.items()))==current['sequences_sha256'],'SEQUENCE_CHANGED_DURING_LOCK')
 if current['legacy_vehicle_id_addition']:
  connection.exec_driver_sql('ALTER TABLE public.vehicle ADD COLUMN vehicle_id VARCHAR(50) NULL')
  tables['vehicle'].append_column(Column('vehicle_id',String(50),nullable=True))
 for name in order:
  # No default-ID generation, conflict handlers, updates, deletes, truncate or init.
  connection.execute(tables[name].insert(),typed[name])
 if inject_failure=='after_insert':raise Stop('INJECTED_ROLLBACK_PROBE')
 for name,rows in typed.items():
  table=tables[name]
  query=select(table).where(table.c.company_code==TENANT)
  if name=='audit_log':query=query.where(table.c.id.in_([r['id'] for r in rows]))
  fetched=list(connection.execute(query).mappings())
  require(len(fetched)==len(rows),'RESTORED_COUNT_MISMATCH:'+name)
  keys=[c.name for c in table.primary_key]
  keyed={tuple(r[k] for k in keys):r for r in fetched}
  for row in rows:
   actual=keyed.get(tuple(row[k] for k in keys));require(actual is not None,'RESTORED_PK_MISMATCH')
   require(digest({k:actual[k] for k in row})==digest(row),'RESTORED_VALUE_MISMATCH:'+name)
 # Compare the original projection when a new compatibility column was added.
 if current['legacy_vehicle_id_addition']:
  vehicle=tables['vehicle']
  require(connection.scalar(select(func.count()).select_from(vehicle).where((vehicle.c.company_code!=TENANT)|(vehicle.c.company_code.is_(None)),vehicle.c.vehicle_id.is_not(None)))==0,'COMPATIBILITY_COLUMN_CHANGED_OTHER_TENANT')
 require(snapshot(connection,tables,exclude_vehicle_compat=current['legacy_vehicle_id_addition'],audit_import_ids=[r['id'] for r in typed.get('audit_log',[])])==baseline,'OTHER_TENANT_OR_GLOBAL_ROWS_CHANGED')
 # Derived cache epochs are allowed for WORLEX only; other extra data is refused.
 derived={}
 for name,table in tables.items():
  if name not in typed and 'company_code' in table.c:
   count=connection.scalar(select(func.count()).select_from(table).where(table.c.company_code==TENANT))
   require(not count or name=='analysis_input_epoch','UNEXPECTED_DERIVED_TENANT_ROWS:'+name)
   if count:derived[name]=count
 sequence_changes=0
 for (name,col),state in seq.items():
  if not typed.get(name):continue
  mx=connection.scalar(select(func.max(tables[name].c[col])))
  next_value=max(state['next'],(mx or 0)+1)
  require(next_value<=state['max'],'SEQUENCE_EXHAUSTED:'+name)
  if next_value!=state['next']:
   connection.exec_driver_sql('ALTER SEQUENCE '+state['qualified']+' RESTART WITH '+str(int(next_value)))
   sequence_changes+=1
 require_push_sequence_unchanged(sequence_states(connection,{'push_subscription':tables['push_subscription']}),current['sequence_baseline'],'PUSH_SEQUENCE_CHANGED_DURING_RESTORE')
 if inject_failure in (True,'after_sequences'):raise Stop('INJECTED_ROLLBACK_PROBE')
 no_sessions()
 return {'status':'TRANSACTION_VERIFIED','preserved_worlex_audit_rows':current['preserved_worlex_audit_rows'],**import_scope(counts,current['deferred_source_rows']),'imported_values_and_blobs_match':True,'deferred_source_not_imported':True,'push_subscription_rows_unchanged':True,'push_subscription_sequence_unchanged':True,'users':15,'vehicles':565,'active_vehicles':289,'deleted_vehicles':276,'operation_records':2571,'blank_chassis_normalized':11,'derived_rows':derived,'sequences_advanced':sequence_changes,'non_worlex_and_global_rows_unchanged':True,'owner_bindings_quarantined':True,'live_login_tested':False,'live_pages_tested':False}

def verify_restore(connection,data,columns,policy,counts,source_sha,approved):
 """Read-only reconciliation, including commit-disconnect outcomes. Never retry."""
 require(approved['runner_sha256']==sha(Path(__file__).read_bytes()),'RUNNER_CHANGED_SINCE_INSPECTION')
 require(approved['target_sha256']==identity(connection) and approved['source_sha256']==source_sha and approved['policy_sha256']==digest(policy),'VERIFY_PLAN_INPUT_MISMATCH')
 tables,_=validate_schema(connection,policy)
 typed,_=typed_payload(data,columns,tables,counts,approved['generated_identifiers'])
 scope=verify_deferred_plan(approved,data,counts)
 assert_no_deferred_references(tables)
 defer_push_subscription(typed,approved['deferred_source_rows'])
 for name,rows in typed.items():
  table=tables[name]
  query=select(table).where(table.c.company_code==TENANT)
  if name=='audit_log':query=query.where(table.c.id.in_([r['id'] for r in rows]))
  fetched=list(connection.execute(query).mappings())
  require(len(rows)==len(fetched),'VERIFY_SOURCE_COUNT_MISMATCH:'+name)
  keys=[c.name for c in table.primary_key];keyed={tuple(r[k] for k in keys):r for r in fetched}
  for row in rows:
   actual=keyed.get(tuple(row[k] for k in keys))
   require(actual is not None and digest({k:actual[k] for k in row})==digest(row),'VERIFY_SOURCE_VALUE_MISMATCH:'+name)
 require(digest(snapshot(connection,tables,exclude_vehicle_compat=approved['legacy_vehicle_id_addition'],audit_import_ids=[r['id'] for r in typed.get('audit_log',[])]))==approved['preserved_rows_sha256'],'VERIFY_PRESERVED_ROWS_CHANGED')
 if approved['legacy_vehicle_id_addition']:
  vehicle=tables['vehicle']
  require(connection.scalar(select(func.count()).select_from(vehicle).where((vehicle.c.company_code!=TENANT)|(vehicle.c.company_code.is_(None)),vehicle.c.vehicle_id.is_not(None)))==0,'VERIFY_COMPATIBILITY_COLUMN_CHANGED_OTHER_TENANT')
 for name,table in tables.items():
  if name not in typed and 'company_code' in table.c:
   count=connection.scalar(select(func.count()).select_from(table).where(table.c.company_code==TENANT))
   require(not count or name=='analysis_input_epoch','VERIFY_UNEXPECTED_DERIVED_TENANT_ROWS:'+name)
 seq=sequence_states(connection,tables)
 require_push_sequence_unchanged(seq,approved['sequence_baseline'],'VERIFY_PUSH_SEQUENCE_CHANGED')
 for key,state in seq.items():
  before=approved['sequence_baseline']['.'.join(key)]
  require(state['next']>=before['next'],'VERIFY_SEQUENCE_REWOUND')
  if typed.get(key[0]):
   maximum=connection.scalar(select(func.max(tables[key[0]].c[key[1]])))
   require(state['next']>maximum,'VERIFY_SEQUENCE_NOT_AHEAD')
 return {'status':'RESTORE_PRESENT_MATCHES_PLAN','preserved_worlex_audit_rows':approved['preserved_worlex_audit_rows'],**scope,'imported_values_and_blobs_match':True,'deferred_source_not_imported':True,'push_subscription_rows_unchanged':True,'push_subscription_sequence_unchanged':True,'non_worlex_and_global_rows_unchanged':True,'sequence_positions_safe':True,'read_only':True}

def enforce_windows_client(root,policy):
 # The operational CLI requires the exact CI-tested pure client and verified
 # TLS settings, while observing the existing CPython native TLS runtime.
 require(policy.get('windows_client_acceptance_passed') is True,'WINDOWS_CLIENT_CI_SEAL_REQUIRED')
 guard_path=root/'client_runtime_guard.py'
 expected=policy.get('tested_artifacts',{}).get('client_runtime_guard.py')
 require(guard_path.is_file() and not guard_path.is_symlink() and expected and expected==sha(guard_path.read_bytes()),'CLIENT_GUARD_DIFFERS_FROM_TESTED_REVISION')
 import importlib.util
 spec=importlib.util.spec_from_file_location('scoped_restore_client_guard',guard_path)
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 try:return module.enforce(root,policy)
 except module.ClientStop as error:raise Stop(str(error)) from None

def cli():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['inspect','execute','verify']);p.add_argument('--archive',required=True);p.add_argument('--pg-restore',required=True);p.add_argument('--plan',required=True);p.add_argument('--report',required=True);p.add_argument('--writers-stopped',action='store_true')
 a=p.parse_args();require(not Path(a.report).exists(),'REPORT_ALREADY_EXISTS')
 root=Path(__file__).resolve().parent;policy=json.loads((root/'policy.json').read_text());counts=json.loads((root/'source-counts.json').read_text())
 value=os.environ.get('WORLEX_NEW_DATABASE_URL','');require(value,'EXPLICIT_NEW_DATABASE_URL_REQUIRED')
 url=make_url(value);require(url.drivername=='postgresql+pg8000' and url.host and url.database and url.username,'EXPLICIT_POSTGRES_TARGET_REQUIRED')
 require(url.host==EXPECTED_HOST and url.database==EXPECTED_DATABASE and url.username==EXPECTED_USER and url.port in (None,5432),'NOT_AUTHORIZED_NEW_DATABASE')
 require(set(url.query)<= {'sslmode'} and url.query.get('sslmode','verify-full')=='verify-full','TLS_OR_URL_OVERRIDE_BLOCKED')
 require(policy.get('postgres_structure_sha256') and policy.get('postgres_acceptance_passed') is True,'POSTGRES_CI_SEAL_REQUIRED')
 require(policy.get('windows_render_acceptance_passed') is True,'WINDOWS_CI_SEAL_REQUIRED')
 require(policy.get('source_manifest_sha256')==SOURCE_MANIFEST_SHA256,'UNREVIEWED_APPLICATION_SOURCE')
 require(policy.get('tested_runner_sha256')==sha(Path(__file__).read_bytes()),'RUNNER_DIFFERS_FROM_POSTGRES_TESTED_REVISION')
 client_runtime=enforce_windows_client(root,policy)
 if a.action in ('execute','verify'):
  if a.action=='execute':require(a.writers_stopped,'STOPPED_WRITERS_ACK_REQUIRED')
  approved=json.loads(Path(a.plan).read_text())
  require(approved.get('client_runtime_sha256')==digest(client_runtime),'CLIENT_RUNTIME_CHANGED_SINCE_INSPECT')
  # Runtime binding belongs to the CLI envelope, not the exact database plan.
  approved.pop('client_runtime_sha256')
  if a.action=='execute':
   attempt=Path(str(a.plan)+'.execution.json')
   fd=os.open(attempt,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
   with os.fdopen(fd,'w') as out:
    json.dump({'status':'STARTED_NO_RETRY','target_sha256':approved['target_sha256']},out);out.flush();os.fsync(out.fileno())
 else:require(not Path(a.plan).exists(),'PLAN_ALREADY_EXISTS')
 # Never inherit service files, options or PG environment overrides.
 for key in list(os.environ):
  if key.startswith('PG'):os.environ.pop(key,None)
 from client_connection import connection_args,verify_tls_connection
 # sslmode is a validated user-facing declaration, not a pg8000 keyword.
 engine=create_engine(url.set(query={}),poolclass=NullPool,hide_parameters=True,connect_args=connection_args(read_only=a.action in ('inspect','verify')))
 try:
  with tempfile.TemporaryDirectory(prefix='worlex-private-render-') as tmp:
   sql=render_archive(a.archive,a.pg_restore,tmp);require(copy_digest(sql)==SOURCE_COPY_SHA256,'SOURCE_COPY_HASH_MISMATCH');data,columns=read_copy(sql)
   source_sha=digest({'columns':columns,'data':data})
   with engine.connect() as connection:
    try:verify_tls_connection(connection,EXPECTED_HOST)
    except ValueError as error:raise Stop(str(error)) from None
    with connection.begin():
     if a.action in ('inspect','verify'):
      connection.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
      result=plan(connection,data,columns,policy,counts,source_sha) if a.action=='inspect' else verify_restore(connection,data,columns,policy,counts,source_sha,approved)
     else:result=execute_restore(connection,data,columns,policy,counts,source_sha,approved)
   if a.action=='inspect':
    result['client_runtime_sha256']=digest(client_runtime)
    Path(a.plan).write_text(json.dumps(result,indent=2));os.chmod(a.plan,0o600)
    output={'status':'READ_ONLY_PREFLIGHT_PASSED','target_sha256':result['target_sha256'],**import_scope(counts,result['deferred_source_rows']),'live_changes':False}
   elif a.action=='execute':
    output={**result,'status':'COMMITTED'}
    attempt.write_text(json.dumps({'status':'COMMITTED','target_sha256':approved['target_sha256']}))
   else:output=result
   Path(a.report).write_text(json.dumps(output,indent=2));os.chmod(a.report,0o600)
   print(json.dumps(output))
 finally:engine.dispose()
if __name__=='__main__':
 try:cli()
 except Stop as error:print(json.dumps({'status':'STOPPED','reason':str(error)}));sys.exit(2)
 except Exception as error:
  # SQLAlchemy errors can include credentials, source values and constraint data.
  print(json.dumps({'status':'FAILED_OR_COMMIT_UNCERTAIN','error_type':type(error).__name__,'instruction':'Do not retry. Inspect the target read-only and reconcile before any new write.'}));sys.exit(3)
