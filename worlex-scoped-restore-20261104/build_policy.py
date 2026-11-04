"""Build a structural allowlist from pinned application source in disposable SQLite.
No production URL is accepted and no archive data is loaded.
"""
import argparse, os, sys, json, hashlib, re
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--manifest',required=True);p.add_argument('--output',required=True);a=p.parse_args()
src=Path(a.source).resolve(); manifest=json.loads(Path(a.manifest).read_text())
if not all(hashlib.sha256((src/n).read_bytes()).hexdigest()==v for n,v in manifest['files'].items()):raise RuntimeError('SOURCE_MANIFEST_MISMATCH')
for key in list(os.environ):
 if key.startswith(('PG','AWS_')) or key in {'DATABASE_URL','RENDER','SECRET_KEY','S3_BUCKET_NAME','ITC_INITIAL_PASSWORD'}:os.environ.pop(key,None)
os.environ.update(ANALYSIS_READ_CACHE_ENABLED='0',AWS_EC2_METADATA_DISABLED='true',S3_BUCKET_NAME='',OPENAI_API_KEY='',SMTP_HOST='',VAPID_PRIVATE_KEY='',DOCUMENT_IMPORT_WORKER_ENABLED='0',ITC_INITIAL_PASSWORD='synthetic-policy-builder-only')
sys.path.insert(0,str(src))
from dkss_app import create_app
from dkss_app.extensions import db
from sqlalchemy import MetaData
app=create_app({'SQLALCHEMY_DATABASE_URI':'sqlite:///:memory:','SECRET_KEY':'synthetic-policy-only','TESTING':True,'MFA_ENABLED':False,'RATELIMIT_ENABLED':False},initialize_database=False)
with app.app_context():
 r=app.test_cli_runner().invoke(args=['init-db'])
 if r.exit_code:raise RuntimeError('SYNTHETIC_SCHEMA_INIT_FAILED') from r.exception
 from dkss_app.driving_access import initialize_driving_access
 from dkss_app.vehicle_couplings import initialize_coupling_schema
 from dkss_app.analysis_read_cache import trigger_statements, INPUT_TABLES
 initialize_driving_access(app);initialize_coupling_schema(app)
 md=MetaData();md.reflect(db.engine)
 tables={}
 for n,t in md.tables.items():
  tables[n]={'columns':{c.name:{'type':c.type.__class__.__name__,'length':getattr(c.type,'length',None),'nullable':c.nullable} for c in t.c},'pk':[c.name for c in t.primary_key], 'fk':sorted([[f.parent.name,f.column.table.name,f.column.name] for f in t.foreign_keys])}
 funcs={}
 for stmt in trigger_statements('postgresql',md.tables):
  if stmt.startswith('CREATE OR REPLACE FUNCTION'):
   name=re.search(r'FUNCTION (\w+)\(',stmt)[1];funcs[name]=stmt.split('$$')[1]
 result={'source_manifest_sha256':hashlib.sha256(Path(a.manifest).read_bytes()).hexdigest(),'tables':tables,'trigger_functions':funcs,'analysis_input_tables':list(INPUT_TABLES)}
 Path(a.output).write_text(json.dumps(result,indent=2,sort_keys=True))
 print('STRUCTURAL_POLICY_CREATED',len(tables))
