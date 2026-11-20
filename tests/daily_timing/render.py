import os,sys,socket,unittest,json,time,cProfile,pstats
from pathlib import Path
repo=Path(os.environ['PRODUCT_REPO']);out=Path(os.environ['DIAGNOSTIC_OUT']);out.mkdir(parents=True,exist_ok=True);sys.path[:0]=[str(repo),str(repo/'tests')]
import sqlalchemy,sqlalchemy.engine.create
original=sqlalchemy.engine.create.create_engine
def safe(url,*a,**kw):
 if not str(url).startswith('sqlite:'):raise AssertionError('nonSQLite forbidden')
 return original(url,*a,**kw)
sqlalchemy.create_engine=safe;sqlalchemy.engine.create.create_engine=safe
socket.socket.connect=lambda *a,**kw:(_ for _ in ()).throw(AssertionError('outbound forbidden'))
socket.create_connection=socket.socket.connect
from test_q02_daily_inspection_flow import Q02DailyInspectionFlowTests
class Probe(Q02DailyInspectionFlowTests):
 def test_profile_get(self):
  self.begin(defect=True)
  url=f'/vehicle/checklists/{self.checklist.id}?vehicle_record_id={self.row.vehicle_record_id}&year=2026&month=10&active_day=23'
  results=[]
  for kind in ['first','repeat']:
   q=[]
   def sql(conn,cursor,statement,parameters,context,executemany):q.append(statement)
   sqlalchemy.event.listen(self.db.engine,'before_cursor_execute',sql)
   before=self.snapshot();q.clear();p=cProfile.Profile();t=time.perf_counter();p.enable();r=self.client.get(url);p.disable();elapsed=time.perf_counter()-t
   sqlalchemy.event.remove(self.db.engine,'before_cursor_execute',sql)
   self.assertEqual(r.status_code,200);self.assertEqual(before,self.snapshot())
   results.append(dict(kind=kind,seconds=elapsed,bytes=len(r.data),queries=len(q),write_sql=[s for s in q if s.lstrip().upper().startswith(('UPDATE','INSERT','DELETE'))]))
   (out/'selected.html').write_bytes(r.data)
   with open(out/('profile-'+kind+'.txt'),'w') as f:pstats.Stats(p,stream=f).sort_stats('cumulative').print_stats(35)
  (out/'isolated.json').write_text(json.dumps(results,indent=2));print(results)
from test_demo_inspection_compact import CompactDemoTests
class Entry(CompactDemoTests):
 def test_entry_timing(self):
  rows=[];before=self.snapshot()
  for iteration in range(3):
   c=self.app.test_client()
   for url in ['/demo','/?__aonagi_entry=1',f'/vehicle/checklists/{self.app.config["PUBLIC_DEMO_CHECKLIST_ID"]}?vehicle_record_id={self.vehicle_id}&year=2026&month=10&active_day=23']:
    t=time.perf_counter();r=c.get(url);elapsed=time.perf_counter()-t
    self.assertEqual(r.status_code,302 if url=='/demo' else 200)
    rows.append(dict(iteration=iteration,path=url,seconds=elapsed,bytes=len(r.data),status=r.status_code))
  self.assertEqual(before,self.snapshot())
  (out/'entry-memory-sqlite.json').write_text(json.dumps(rows,indent=2))
r=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([Probe('test_profile_get'),Entry('test_entry_timing')]));sys.exit(not r.wasSuccessful())
