"""Synthetic-only expansion to the public 4,100-row/37-table cardinality profile.

Inputs are structural policy and aggregate counts. No archive, copied IDs, names,
private row values, document bytes, endpoint or original password is read here.
"""
import copy, datetime, hashlib, json
from pathlib import Path

STAMP='2026-10-01 00:00:00'
JSON_ARRAYS={'files_json','line_items_json','invoice_details_json','countermeasure_files_json','items_json','notify_users_json','licenses_json','vehicles_json','version_history_json','password_history_json','approvals_json'}

def scalar(name,column,definition,index):
 typ=definition['type'];limit=definition['length']
 if column=='company_code':return 'WORLEX'
 if column.endswith('_json'):return '[]' if column in JSON_ARRAYS else '{}'
 if column in {'created_at','updated_at','checked_at'}:return STAMP+('+00' if typ=='DATETIME' else '')
 if column.endswith('_date') or column in {'date','sent_day','local_day'}:return '2026-10-01'
 if column in {'period_key','planned_month'}:return '2026-10'
 if column=='reminder_time':return '09:00'
 if column=='year':return '2026'
 if column=='month':return '10'
 if column=='day':return str(index%28+1)
 if typ=='BOOLEAN':return 'f'
 if typ in {'INTEGER','BIGINT','SMALLINT'}:return str(index+1)
 if typ in {'NUMERIC','FLOAT'}:return '1.25'
 if typ=='DATETIME':return STAMP+'+00'
 if typ=='DATE':return '2026-10-01'
 if typ=='BLOB':return '\\x'+b'SYNTHETIC NONPRIVATE BYTES\n'.hex()
 value='synthetic-'+column+'-'+str(index)
 if column in {'source_sha256','cache_key','input_signature','source_line_version','revision'}:value=hashlib.sha256((name+':'+column+':'+str(index)).encode()).hexdigest()
 if limit:value=value[:limit]
 return value

def expand(policy,table_names,data,new_fields):
 profile=Path(__file__).resolve().parents[1]/'source-counts.json'
 if hashlib.sha256(profile.read_bytes()).hexdigest()!='dee9682036836ba09e7d689ffdb202a6f33498b11640a61674af12e7c2490b37':raise ValueError('PUBLIC_COUNT_PROFILE_HASH_CHANGED')
 counts=json.loads(profile.read_text())
 if set(table_names)!=set(counts):raise ValueError('PUBLIC_COUNT_PROFILE_TABLES_CHANGED')
 if sum(counts.values())!=4100 or sum(bool(v) for v in counts.values())!=37:raise ValueError('PUBLIC_COUNT_PROFILE_CHANGED')
 # Preserve existing synthetic IDs used by the acceptance tests. All newly
 # represented tables use deterministic, non-private IDs in a separate range.
 for ordinal,name in enumerate(sorted(counts)):
  wanted=counts[name];table=policy['tables'].get(name)
  if not wanted:
   data[name]=[];continue
  if table is None:raise ValueError('SYNTHETIC_TABLE_NOT_MODELED')
  existing=copy.deepcopy(data.get(name,[]));rows=[]
  for i in range(wanted):
   row={column:(None if d['nullable'] else scalar(name,column,d,i)) for column,d in table['columns'].items() if column not in new_fields}
   if i<len(existing):row.update(existing[i])
   elif existing:
    row.update(copy.deepcopy(existing[0]))
    for pk in table['pk']:
     if pk=='company_code':continue
     d=table['columns'][pk]
     row[pk]=str(int(existing[0][pk])+i) if d['type'] in {'INTEGER','BIGINT','SMALLINT'} else ('synthetic-document' if i==0 else 'synthetic-document-'+str(i))
    if name=='office':row['name']='Synthetic Office '+str(i)
    if name=='notification':row['title']='Synthetic notification '+str(i)
    if name=='vehicle_document_import_draft':row['source_filename']='synthetic-'+str(i)+'.pdf'
   else:
    for pk in table['pk']:
     if pk=='company_code':row[pk]='WORLEX'
     elif table['columns'][pk]['type'] in {'INTEGER','BIGINT','SMALLINT'}:row[pk]=str(100000+ordinal*1000+i)
     else:row[pk]='synthetic-'+str(ordinal)+'-'+str(i)
   rows.append(row)
  data[name]=rows
 # Exercise every FK whose target is represented. Leave references to empty
 # optional tables NULL; required absent targets are a fixture design error.
 for name,rows in data.items():
  table=policy['tables'].get(name)
  if table is None:continue
  for i,row in enumerate(rows):
   for column,target,target_column in table['fk']:
    if column in new_fields:continue
    targets=data.get(target,[])
    if targets:row[column]=targets[i%len(targets)][target_column]
    elif not table['columns'][column]['nullable']:raise ValueError('REQUIRED_SYNTHETIC_TARGET_EMPTY')
   for column in ('checklist_id',):
    if column in row and name in {'checklist_result','vehicle_checklist_result','vehicle_checklist_notify_setting'}:row[column]=data['checklist'][i%len(data['checklist'])]['id']
   if name=='checklist':row.update(active='t',name='Synthetic Checklist '+str(i),items_json='[]',notify_users_json='[]',version_history_json='[]',target='vehicle',display_type='normal',frequency_unit='day',frequency_value='1',reminder_enabled='f',reminder_time='09:00')
   if name=='checklist_event':row.update(result_id=data['checklist_result'][i%9]['id'],result_type='checklist',event_type='created',detail_json='{}',actor_username='fixture-0')
   if name=='checklist_result':row.update(status='pending',target_type='vehicle',answers_json='{}',approvals_json='[]',notify_users_json='[]',checklist_snapshot_json='{}')
   if name=='driver':row.update(employee_id='SYN-EMP-'+str(i),name='Synthetic Driver '+str(i),office='Synthetic Office',role='driver',licenses_json='[]',vehicles_json=json.dumps([int(data['vehicle'][i]['id'])]),safe_start_date='2026-10-01')
   if name=='vehicle_type_import_mapping':row.update(excel_value='SYN-TYPE-'+str(i),vehicle_type_name='Synthetic Type '+str(i%8))
   if name=='vehicle_type':row['name']='Synthetic Type '+str(i)
   if name=='vehicle_checklist_notify_setting':row['notify_users_json']='[]'
   if name=='vehicle_checklist_result':row.update(year='2026',month='10',day=str(i%28+1),status='pending',answers_json='{}',approvals_json='[]',notify_users_json='[]',operation_judgment_json='{}',checklist_snapshot_json='{}')
   if name=='patrol_result':row.update(date='2026-10-01',office='Synthetic Office',target_type='user',target_username='fixture-0',content='Synthetic observation',files_json='[]',countermeasure_files_json='[]',approval_status='pending')
   if name=='driving_report_reflection':row.update(status='completed',result_json='{}')
   if name in {'inspection_expiry_alert_delivery','inspection_plan_alert_delivery'}:row.update(office='Synthetic Office',phase='synthetic',target_username='fixture-0',sent_day='2026-10-01',bucket=str(i+1))
   if name=='vehicle_inspection_plan':row.update(kind='periodic',source='manual',status='planned',factory='Synthetic Factory',note='Synthetic plan',period_key='2026-10',planned_month='2026-10',updated_by='fixture-0',version='1',completed_record_id=None)
   if name=='vehicle_inspection_plan_event':row.update(action='created',created_by='fixture-0',detail_json='{}')
   if name=='vehicle_maintenance_record':row.update(status='completed',entry_date='2026-10-01',completion_date='2026-10-01',files_json='[]',invoice_details_json='{}',line_items_json='[]',content='Synthetic maintenance',created_by_username='fixture-0',total_cost='10.25',mileage='1000.5')
   if name=='vehicle_maintenance_record_event':row.update(action='created',changes_json='{}')
   if name=='vehicle_part_replacement':row.update(part_name='Synthetic Part '+str(i),replacement_date='2026-10-01',quantity='1.25')
   if name=='vehicle_part_replacement_source':row['source_line_index']=str(i)
   if name=='vehicle_operation_vehicle_mapping':row.update(source_vehicle_code='SYN-CODE-'+str(i),source_vehicle_number='SYN-NUM-'+str(i),confirmed_by_username='fixture-0')
   if name=='vehicle_operation_import_draft':
    blob=('date,vehicle,value\n2026-10-01,SYNTHETIC,'+str(i)+'\n').encode()
    row.update(created_by_username='fixture-0',status='completed',selection_json='{}',result_json='{}',source_filename='synthetic-'+str(i)+'.csv',source_file='\\x'+blob.hex())
   if name in {'vehicle_driving_report_record','vehicle_periodic_inspection_record'}:
    row.update(created_by_username='fixture-0',details_json='{}',source_record_index=str(i))
    if name=='vehicle_driving_report_record':row.update(operation_date='2026-10-01',content='Synthetic driving record',report_number='SYN-DRIVE-'+str(i),mileage='1000.5')
    else:row.update(inspection_date='2026-10-01',inspection_type='periodic')
 # ORM-facing logical relationship fields must describe the same synthetic
 # vehicle as their referenced maintenance/inspection parent.
 for name in ('vehicle_part_replacement','vehicle_maintenance_record_event'):
  parents={r['id']:r for r in data['vehicle_maintenance_record']}
  for row in data[name]:row['vehicle_record_id']=parents[row['maintenance_record_id']]['vehicle_record_id']
 for row in data['vehicle_maintenance_inspection_link']:
  maintenance=next(r for r in data['vehicle_maintenance_record'] if r['id']==row['maintenance_record_id'])
  inspection=next(r for r in data['vehicle_checklist_result'] if r['id']==row['inspection_result_id'])
  row['vehicle_record_id']=maintenance['vehicle_record_id'];inspection['vehicle_record_id']=row['vehicle_record_id']
 columns={n:list(rows[0]) if rows else [] for n,rows in data.items()}
 if any(set(r)!=set(columns[n]) for n,rows in data.items() for r in rows):raise ValueError('SYNTHETIC_COLUMN_SET_DRIFT')
 if {n:len(rows) for n,rows in data.items()}!=counts:raise ValueError('SYNTHETIC_CARDINALITY_DRIFT')
 return data,columns,counts
