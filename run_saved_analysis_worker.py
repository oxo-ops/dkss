"""Run the existing analysis queue/jobs for explicit vehicles using saved evidence only.
No public-document tick, extraction, source edits, or cross-company scan.
The worker writes scheduling/results to the backed-up DB; API calls occur only for due jobs.
"""
import argparse,ast,contextlib,hashlib,importlib,io,json,os,re,sqlite3,sys,time
from pathlib import Path
from datetime import datetime,timezone


def utc(value):
    if value is None:return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

def stamp(value):return utc(value).isoformat() if value else None

def current_result(module, vehicle):
    state=module.VehicleKarteAnalysis.query.filter_by(company_code=vehicle.company_code,vehicle_record_id=vehicle.id).first()
    bundle=module.safe_json_dict(state.result_json) if state else {}
    with module.app.test_request_context('/'):
        payload,_=module.get_vehicle_karte_analysis_job_data(vehicle)
    previous=bundle.get('fingerprints') or {};current=payload['_fingerprints']
    matches=all(key in previous and key in current and previous[key]==current[key] for key in ('policy_version','important_hash','routine_hash'))
    return state, bool(state and state.status=='completed' and matches)

def tick(module, company, ids):
    reports=[]
    for vehicle_id in ids:
        try:
            with module.app.app_context():
                vehicle=module.Vehicle.query.filter_by(company_code=company,id=vehicle_id,deleted=False).first()
                active=module.Company.query.filter_by(company_code=company,active=True).first()
                if vehicle is None or active is None:raise ValueError('Target missing, deleted, or company inactive')
                with module.app.test_request_context('/'):
                    payload,_=module.get_vehicle_karte_analysis_job_data(vehicle)
                state=module.queue_vehicle_karte_analysis(vehicle,payload)
                if module.db.session.new or module.db.session.dirty or module.db.session.deleted:module.db.session.commit()
                due=utc(state.next_analysis_at);lease=utc(state.lease_expires_at);now=datetime.now(timezone.utc)
                attempted=False
                if state.status in ('pending','error','running') and due and due<=now and (not lease or lease<=now):
                    attempted=True
                    module.run_vehicle_karte_analysis_job(state.id)
                    module.db.session.expire_all()
                state,is_current=current_result(module,vehicle)
                reports.append(dict(vehicle_id=vehicle_id,status=state.status,is_current=is_current,next_analysis_at_utc=stamp(state.next_analysis_at),request_reason=state.request_reason or '',job_attempted=attempted))
        except Exception as exc:
            # Never print raw API errors/keys. The application's existing error log retains detail.
            reports.append(dict(vehicle_id=vehicle_id,status='tick_error',error_type=type(exc).__name__))
        finally:
            with module.app.app_context():module.db.session.remove()
    return reports

def database_path():
    try:
        from dotenv import load_dotenv
        load_dotenv(Path('.env'))
    except ImportError:pass
    from sqlalchemy.engine import make_url
    url=make_url(os.environ.get('DATABASE_URL') or 'sqlite:///dkss.db')
    if url.get_backend_name()!='sqlite':raise ValueError('This local worker requires the existing SQLite database')
    path=Path(url.database)
    if not path.is_absolute():path=Path('instance')/path
    if not path.is_file():raise ValueError('Database missing; refusing to create one')
    return path.resolve()

def validate_targets(database,company,ids):
    with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        if not db.execute('SELECT 1 FROM company WHERE company_code=? AND active=1',(company,)).fetchone():raise ValueError('Company missing or inactive')
        for id in ids:
            if not db.execute('SELECT 1 FROM vehicle WHERE id=? AND company_code=? AND deleted=0',(id,company)).fetchone():raise ValueError('Vehicle missing/deleted in requested company: '+str(id))

def backup_database(database):
    folder=Path('backups')/('saved-analysis-worker-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));folder.mkdir(parents=True)
    path=folder/'dkss.db'
    with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True,timeout=15) as src,sqlite3.connect(path) as dst:src.backup(dst,pages=1000)
    print('DB_BACKUP_OK:',path,flush=True)

@contextlib.contextmanager
def exclusive_lock(path):
    # An OS lock is released on process exit, including crashes; stale files do not block startup.
    with path.open('a+b') as stream:
        if stream.seek(0,2)==0:stream.write(b' ');stream.flush()
        stream.seek(0)
        if os.name=='nt':
            import msvcrt
            try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:raise RuntimeError('A saved-analysis worker already owns this company/database lock')
        else:
            import fcntl
            try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError:raise RuntimeError('A saved-analysis worker already owns this company/database lock')
        try:yield
        finally:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream,fcntl.LOCK_UN)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',action='store_true');p.add_argument('--company',required=True);p.add_argument('--vehicles',required=True,help='Explicit comma-separated vehicle IDs');p.add_argument('--interval',type=int,default=60);args=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',args.company):p.error('Invalid company code')
    try:ids=sorted(set(int(v.strip()) for v in args.vehicles.split(',')))
    except ValueError:p.error('Vehicle IDs must be comma-separated integers')
    if not ids or min(ids)<=0:p.error('Vehicle IDs must be positive')
    if not 15<=args.interval<=300:p.error('Interval must be 15 to 300 seconds')
    print('VERSION: saved-evidence-analysis-worker-v1',flush=True)
    source=Path('app.py')
    if not source.is_file():raise ValueError('Run from C:\\Users\\takah\\dkss')
    tree=ast.parse(source.read_bytes(),filename='app.py')
    required={'get_vehicle_karte_analysis_job_data','queue_vehicle_karte_analysis','run_vehicle_karte_analysis_job'}
    if not required<={node.name for node in tree.body if isinstance(node,ast.FunctionDef)}:raise ValueError('Required analysis functions missing')
    database=database_path();validate_targets(database,args.company,ids)
    print('COMPANY:',args.company,'VEHICLES:',','.join(map(str,ids)),flush=True)
    print('DATABASE:',database,flush=True)
    print('SAVED_EVIDENCE_ONLY; NO_PUBLIC_TICK; NO_EXTRACTION; NO_OTHER_VEHICLES; NO_SOURCE_EDITS',flush=True)
    if not args.run:print('PREFLIGHT_OK; READ_ONLY; NO_API_REQUESTS; use --run to start');return
    lock=database.parent/('saved-analysis-worker-'+args.company+'.lock')
    with exclusive_lock(lock):
        backup_database(database)
        sys.path.insert(0,str(Path.cwd().resolve()))
        module=importlib.import_module('app')
        if Path(module.__file__).resolve()!=source.resolve():raise ValueError('Unexpected app module')
        with module.app.app_context():
            if Path(module.db.engine.url.database).resolve()!=database:raise ValueError('Application DB differs from the backed-up DB')
        print('WORKER_STARTED; PID:',os.getpid(),'; Ctrl+C stops this worker',flush=True)
        previous=None;count=0
        try:
            while True:
                reports=tick(module,args.company,ids);encoded=json.dumps(reports,ensure_ascii=False)
                if encoded!=previous or count%5==0:
                    print('HEARTBEAT_UTC:',datetime.now(timezone.utc).isoformat(),flush=True)
                    print('TARGET_STATES:',encoded,flush=True)
                previous=encoded;count+=1;time.sleep(args.interval)
        except KeyboardInterrupt:print('WORKER_STOPPED',flush=True)

if __name__=='__main__':main()
