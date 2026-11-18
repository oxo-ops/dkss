import sys,time,json,hashlib
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

class FixedDatetime(datetime):
 @classmethod
 def now(cls,tz=None): return cls(2026,11,19,12,tzinfo=tz)

from sqlalchemy import event
from test_inspection_plans import InspectionPlanTests
T=InspectionPlanTests;T.setUpClass();t=T();t.setUp();m=t.m
try:
 vs=[m.Vehicle(company_code='TEST',chassis_number=f'SYN-{i}',office='Synthetic',inspection_expiry='2027-01-01') for i in range(160)]
 m.db.session.add_all(vs);m.db.session.flush()
 m.db.session.add(m.VehicleDocumentImportDraft(id='synthetic-source',batch_id='synthetic',company_code='TEST',created_by_username='admin',document_type='inspection',source_filename='synthetic.pdf',source_file=b'%PDF-synthetic',source_sha256='0'*64,status='completed'));m.db.session.flush()
 m.db.session.bulk_insert_mappings(m.VehiclePeriodicInspectionRecord,[dict(company_code='TEST',vehicle_record_id=v.id,inspection_type='3month',inspection_date=f'{2021+n//12}-{n%12+1:02d}-15',content='Synthetic',source_draft_id='synthetic-source',source_record_index=v.id*100+n,created_by_username='admin') for v in vs for n in range(60)])
 m.db.session.commit()
 statements=[]
 def sql(conn,cursor,statement,parameters,ctx,many):statements.append(statement.split()[0])
 event.listen(m.db.engine,'before_cursor_execute',sql)
 results=[]
 for n in range(3):
  statements.clear();start=time.perf_counter()
  with patch('vehicle_inspection_plans.datetime',FixedDatetime):
   r=t.client.get('/api/vehicle/inspection-plans?scope=company&year=2026&month=2026-11')
  elapsed=time.perf_counter()-start
  assert r.status_code==200,r.status_code
  results.append(dict(ms=round(elapsed*1000,2),queries=len(statements),writes=sum(x in ('INSERT','UPDATE','DELETE') for x in statements),rows=len(r.json['plans']),bytes=len(r.data),sha=hashlib.sha256(r.data).hexdigest()))
 output={'fixture':{'vehicles':160,'history_records':9600},'samples':results}
 Path(sys.argv[1]).write_text(json.dumps(output,indent=2))
 print(json.dumps(output,indent=2))
finally:t.tearDown();T.tearDownClass()
