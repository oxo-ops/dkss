import os,sys,socket,time,json,tempfile,runpy,cProfile,pstats,io
from pathlib import Path
ROOT=Path(sys.argv[1]).resolve();OUT=Path(sys.argv[2]).resolve();OUT.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory() as tmp:
 os.environ.clear();os.environ.update(HOME=tmp,TMPDIR=tmp,AWS_EC2_METADATA_DISABLED='true',AWS_CONFIG_FILE='/dev/null',AWS_SHARED_CREDENTIALS_FILE='/dev/null',DOCUMENT_IMPORT_WORKER_ENABLED='0',RATELIMIT_STORAGE_URI='memory://',RENDER='',OPENAI_API_KEY='',SMTP_HOST='',S3_BUCKET_NAME='')
 tempfile.tempdir=tmp
 def guard(event,args):
  if event in ('socket.connect','socket.getaddrinfo','subprocess.Popen','os.system'):raise RuntimeError('EXTERNAL_IO_BLOCKED')
  if event=='sqlite3.connect' and str(args[0])!=':memory:' and not Path(str(args[0])).resolve().is_relative_to(tmp):raise RuntimeError('SQLITE_OUTSIDE_TEMP')
 sys.addaudithook(guard);sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
 # reuse audited fixture seed, measure broader initial GET paths instead of prior API-only loop
 source=(ROOT/'tests/plan_read_performance/probe.py').read_text();source=source[:source.index(' statements=[]')]+'''\n statements=[];sql_ms=[0];state={};from flask import before_render_template,template_rendered
 def sql_before(conn,cursor,statement,parameters,ctx,many):
  statements.append(statement.split()[0]);ctx._start=time.perf_counter()
 def sql_after(conn,cursor,statement,parameters,ctx,many):sql_ms[0]+=(time.perf_counter()-ctx._start)*1000
 event.listen(m.db.engine,'before_cursor_execute',sql_before);event.listen(m.db.engine,'after_cursor_execute',sql_after)
 def render_start(*a,**k):state['template_start']=time.perf_counter()
 def render_done(*a,**k):state['template_ms']=(time.perf_counter()-state['template_start'])*1000
 before_render_template.connect(render_start,m.app,weak=False);template_rendered.connect(render_done,m.app,weak=False)
 orig=m.app.preprocess_request
 def preprocess():
  begin=time.perf_counter()
  try:return orig()
  finally:state['preprocess_ms']=(time.perf_counter()-begin)*1000
 m.app.preprocess_request=preprocess
 result=[]
 paths=['/vehicle/inspection-plans?scope=company&year=2026&month=2026-11','/api/vehicle/inspection-plans?scope=company&year=2026&month=2026-11','/notifications','/api/notifications/recent']
 for idx,path in enumerate(paths):
  for n in range(3):
   statements.clear();sql_ms[0]=0;state.clear();begin=time.perf_counter();cpu=time.process_time()
   with patch('vehicle_inspection_plans.datetime',FixedDatetime):r=t.client.get(path)
   row=dict(path=path,iteration=n,status=r.status_code,wall_ms=(time.perf_counter()-begin)*1000,cpu_ms=(time.process_time()-cpu)*1000,sql_ms=sql_ms[0],queries=len(statements),writes=sum(s in ('INSERT','UPDATE','DELETE') for s in statements),bytes=len(r.data),preprocess_ms=state.get('preprocess_ms'),template_ms=state.get('template_ms'))
   result.append(row);print(json.dumps(row),flush=True)
   if n==2:(OUT/f'response-{idx}.bin').write_bytes(r.data)
 (OUT/'server.json').write_text(json.dumps(result,indent=2))
finally:t.tearDown();T.tearDownClass()
'''
 exec(compile(source,'isolated_initial.py','exec'),globals())
