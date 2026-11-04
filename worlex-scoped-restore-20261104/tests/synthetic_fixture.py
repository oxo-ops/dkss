"""Programmatically generated synthetic data. No backup or personal data is read."""
import datetime, hashlib
from werkzeug.security import generate_password_hash
from test_restore_unit import synthetic_data
PASSWORD='Synthetic-Only-Password-2026!'
NEW_FIELDS={'account_identity','master_generation','owner_identity','actor_identity','actor_name','actor_user_id','checked_by_identity','checked_by_user_id','approved_by_identity','approved_by_user_id','target_identity','target_user_id','created_by_identity','created_by_user_id','countermeasure_by_identity','countermeasure_by_user_id','notification_identities_json'}

def fixture(policy,table_names):
 data={name:[] for name in table_names}
 source,_,_=synthetic_data()
 for name,rows in source.items():
  for source_row in rows:
   row={}
   for col,e in policy['tables'][name]['columns'].items():
    if col in NEW_FIELDS:continue
    if col in source_row:row[col]=source_row[col];continue
    if e['nullable']:row[col]=None;continue
    typ=e['type']
    if typ in ('INTEGER','BIGINT','SMALLINT','FLOAT','NUMERIC'):row[col]='0'
    elif typ=='BOOLEAN':row[col]='f'
    elif typ=='DATETIME':row[col]='2026-10-01 00:00:00+00'
    elif typ=='DATE':row[col]='2026-10-01'
    elif col.endswith('_json'):row[col]='[]' if col=='password_history_json' else '{}'
    else:row[col]='synthetic'
   row.update(source_row)
   if name=='company':row.update(active='t',vehicle_limit='9999')
   if name=='user':row.update(password=generate_password_hash(PASSWORD) if row['id']=='3' else 'synthetic-inactive-hash',last_name='Synthetic',first_name='Fixture',timezone='Asia/Tokyo',login_locked='f',failed_login_count='0',email_notify_enabled='f',password_changed_at=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S'))
   if name=='vehicle':row.update(plate_number='SYNTH-'+row['id'],office='Synthetic Office',type='Synthetic Type')
   if name=='vehicle_operation_record':row.update(operation_date='2026-10-01',report_number='SYNTH-'+row['id'],source_row_json='{}')
   data[name].append(row)
 data['audit_log']=[dict(id=str(i),company_code='WORLEX',username='synthetic-old-account',action='synthetic_imported_event',target_type='synthetic',target_id=str(i),detail='synthetic immutable history',ip_address=None,created_at='2026-10-01 00:00:00') for i in range(1001,1424)]
 data['push_subscription']=[dict(id='1',company_code='WORLEX',username='fixture-0',endpoint='https://synthetic-backup.invalid/push',p256dh='synthetic-p256dh',auth='synthetic-auth',created_at='2026-10-01 00:00:00')]
 data['office']=[dict(id='3',company_code='WORLEX',name='Synthetic Office')]
 data['notification']=[dict(id='7',company_code='WORLEX',target_user='Synthetic Fixture',target_username='fixture-0',title='Synthetic notification',message='Synthetic historical record',read='f',created_at='2026-10-01 00:00',files_json='[]')]
 blob=b'%PDF-1.4\nSynthetic fixture, not a real document.\n%%EOF\n'
 data['vehicle_document_import_draft']=[dict(id='synthetic-document',batch_id='synthetic-batch',company_code='WORLEX',created_by_username='fixture-0',source_filename='synthetic.pdf',source_sha256=hashlib.sha256(blob).hexdigest(),document_type='driving_report',source_file='\\x'+blob.hex(),status='completed',preview_json='{}',result_json='{}',created_at='2026-10-01 00:00:00+00',completed_at='2026-10-01 00:00:00+00')]
 from full_table_fixture import expand
 return expand(policy,table_names,data,NEW_FIELDS)
