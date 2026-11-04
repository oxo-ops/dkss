"""No network or database service needed. Uses synthetic values only."""
import copy, json, pathlib, tempfile, unittest, decimal
from sqlalchemy import MetaData, Table, Column, Integer, String, Boolean, Text, BigInteger, SmallInteger, Float, Numeric, DateTime, Date, LargeBinary, ForeignKeyConstraint
from worlex_restore import Stop, decode_copy, read_copy, typed_payload, digest, q, render_environment, classify_render_failure


def synthetic_tables():
 m=MetaData()
 Table('company',m,Column('id',Integer,primary_key=True),Column('company_code',String,nullable=False),Column('company_name',String,nullable=False))
 Table('user',m,Column('id',Integer,primary_key=True),Column('company_code',String,nullable=False),Column('username',String,nullable=False),Column('password',String,nullable=False),Column('account_identity',String),Column('role',String))
 Table('vehicle',m,Column('id',Integer,primary_key=True),Column('company_code',String,nullable=False),Column('chassis_number',String),Column('deleted',Boolean))
 Table('vehicle_operation_record',m,Column('id',Integer,primary_key=True),Column('company_code',String,nullable=False),Column('vehicle_record_id',Integer,nullable=False))
 return m.tables

def synthetic_data():
 data={
 'company':[dict(id='2',company_code='WORLEX',company_name='Synthetic Company')],
 'user':[dict(id=str(i+3),company_code='WORLEX',username='fixture-'+str(i),password='synthetic-not-a-real-hash',role='admin' if i==0 else 'user') for i in range(15)],
 'vehicle':[dict(id=str(i+2),company_code='WORLEX',chassis_number='' if i<11 else 'SYNTH-'+str(i),deleted='f' if i<289 else 't',vehicle_id='SYNTH-LABEL-'+str(i) if i<241 else '') for i in range(565)],
 'vehicle_operation_record':[dict(id=str(i+1),company_code='WORLEX',vehicle_record_id=str(2+i%565)) for i in range(2571)]}
 return data,{n:list(rows[0]) for n,rows in data.items()},{n:len(rows) for n,rows in data.items()}

def policy_metadata(policy):
 m=MetaData();types={'INTEGER':Integer,'BIGINT':BigInteger,'SMALLINT':SmallInteger,'VARCHAR':String,'TEXT':Text,'BOOLEAN':Boolean,'FLOAT':Float,'NUMERIC':Numeric,'DATETIME':DateTime,'DATE':Date,'BLOB':LargeBinary}
 for name,p in policy['tables'].items():
  cols=[]
  for n,e in p['columns'].items():
   typ=types[e['type']](e['length']) if e['length'] else types[e['type']]()
   cols.append(Column(n,typ,primary_key=n in p['pk'],nullable=e['nullable']))
  Table(name,m,*cols)
 for name,p in policy['tables'].items():
  for col,target,tcol in p['fk']:m.tables[name].append_constraint(ForeignKeyConstraint([col],[target+'.'+tcol]))
 return m.tables

class RestoreGuards(unittest.TestCase):
 def test_render_environment_preserves_only_windows_runtime_paths(self):
  value=render_environment('private-directory',{'SystemRoot':r'C:\Windows','windir':r'C:\Windows','PGHOST':'do-not-inherit','PGPASSWORD':'synthetic-secret','WORLEX_NEW_DATABASE_URL':'synthetic-secret','DATABASE_URL':'synthetic-secret','PATH':'untrusted'})
  self.assertEqual(value['SYSTEMROOT'],r'C:\Windows');self.assertEqual(value['WINDIR'],r'C:\Windows')
  self.assertEqual(set(value),{'SYSTEMROOT','WINDIR','PATH','HOME','LANG','TZ'})
  self.assertNotIn('synthetic-secret',str(value))
 def test_render_failure_classification_never_exposes_raw_details(self):
  self.assertEqual(classify_render_failure(b'pg_restore: error: could not generate restrict key'), 'RESTRICT_KEY_GENERATION_FAILED')
  self.assertEqual(classify_render_failure(b'pg_restore: error: WSAStartup() failed: error code 10106'),'WINDOWS_SOCKET_PROVIDER_INITIALIZATION_FAILED')
  self.assertEqual(classify_render_failure(b'unknown synthetic-sensitive-value'), 'UNCLASSIFIED_PROCESS_FAILURE')
  self.assertEqual(classify_render_failure(b'could not open output file C:/synthetic-private-name'),'OUTPUT_FILE_ACCESS_FAILED')

 def test_full_synthetic_fixture_matches_pinned_schema(self):
  from synthetic_fixture import fixture
  root=pathlib.Path(__file__).resolve().parents[1]
  policy=json.loads((root/'policy.json').read_text());names=json.loads((root/'source-counts.json').read_text())
  data,cols,counts=fixture(policy,names)
  typed,order=typed_payload(data,cols,policy_metadata(policy),counts)
  self.assertEqual(len(typed['vehicle_operation_record']),2571)
  self.assertIsNone(typed['notification'][0]['owner_identity'])
  self.assertIsNone(typed['vehicle_document_import_draft'][0]['owner_identity'])
  self.assertEqual(typed['vehicle_document_import_draft'][0]['status'],'completed')

 def test_copy_decoding(self):
  self.assertIsNone(decode_copy(r'\N'));self.assertEqual(decode_copy(r'a\tb\n\\c'),'a\tb\n\\c')
  self.assertEqual(decode_copy(r'\\x0001'),r'\x0001')
 def test_tenant_filter_and_escapes(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'input.sql';p.write_text('COPY public.vehicle (id, company_code, value) FROM stdin;\n1\tITC\tignore\n2\tWORLEX\tx\\ty\n\\.\n')
   data,cols=read_copy(p);self.assertEqual(data['vehicle'],[{'id':'2','company_code':'WORLEX','value':'x\ty'}])
 def test_malformed_and_duplicate_copy_are_blocked(self):
  valid='COPY public.vehicle (id, company_code) FROM stdin;\n1\tWORLEX\n\\.\n'
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'input.sql'
   for payload in [valid+valid,valid.replace('1\tWORLEX','1'),valid.replace('\\.\n',''),valid.replace('company_code','other')]:
    p.write_text(payload)
    with self.assertRaises(Stop):read_copy(p)
 def test_counts_and_exact_states(self):
  data,cols,counts=synthetic_data();typed,order=typed_payload(data,cols,synthetic_tables(),counts)
  self.assertEqual(len(typed['vehicle']),565);self.assertEqual(sum(r['deleted'] for r in typed['vehicle']),276)
  self.assertEqual(sum(r['chassis_number'] is None for r in typed['vehicle']),11)
  self.assertEqual(sum(bool(r['vehicle_id']) for r in typed['vehicle']),241)
  self.assertEqual(len({r['account_identity'] for r in typed['user']}),15)
 def test_payload_count_tenant_and_numeric_id_guards(self):
  for mutation in ('count','tenant','pk','state','chassis','unknown'):
   data,cols,counts=synthetic_data()
   if mutation=='count':data['user'].pop()
   elif mutation=='tenant':data['user'][0]['company_code']='itc'
   elif mutation=='pk':data['user'][0]['id']=data['user'][1]['id']
   elif mutation=='state':data['vehicle'][0]['deleted']='t'
   elif mutation=='chassis':data['vehicle'][0]['chassis_number']='ACTUAL'
   else:data['user'][0]['unexpected']='filled'
   with self.subTest(mutation=mutation), self.assertRaises(Stop):typed_payload(data,cols,synthetic_tables(),counts)
 def test_safe_identifiers(self):
  self.assertEqual(q('user'),'"user"')
  for x in ['public.vehicle','vehicle; DROP TABLE user','UPPER','"user"']:
   with self.assertRaises(Stop):q(x)
 def test_blob_hashes_are_sensitive_to_bytes_without_exposing_them(self):
  self.assertNotEqual(digest(b'a'),digest(b'b'));self.assertEqual(len(digest(b'a')),64)
  self.assertNotEqual(digest(decimal.Decimal('12345678901234567890123456789')),digest(decimal.Decimal('12345678901234567890123456788')))
  self.assertEqual(digest(decimal.Decimal('1')),digest(decimal.Decimal('1.00')))
  self.assertNotEqual(digest(decimal.Decimal('10')),digest(decimal.Decimal('1')))

if __name__=='__main__':unittest.main()
