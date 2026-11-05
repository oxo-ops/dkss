"""Load only the sealed sidecar client for the fixed scoped restore scripts."""
import hashlib,importlib.util,json,re,runpy,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
TARGET_STARTED=False
class Stop(RuntimeError):pass
def require(v,code):
 if not v:raise Stop(code)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
 global TARGET_STARTED
 require(sys.flags.isolated==1,'ISOLATED_PYTHON_REQUIRED')
 sys.dont_write_bytecode=True
 require(len(sys.argv)>=2 and sys.argv[1] in ('worlex_restore.py','run_restore_once.py'),'FIXED_RESTORE_TARGET_REQUIRED')
 policy=json.loads((ROOT/'policy.json').read_text());profile=policy.get('windows_client_acceptance',{})
 require(profile.get('bootstrap_sha256')==sha(Path(__file__)),'CLIENT_BOOTSTRAP_HASH_MISMATCH')
 guard_path=ROOT/'client_runtime_guard.py';require(profile.get('guard_sha256')==sha(guard_path),'CLIENT_GUARD_HASH_MISMATCH')
 spec=importlib.util.spec_from_file_location('sealed_client_runtime_guard',guard_path);guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
 profile=guard.policy_profile(ROOT,policy);sidecar=ROOT/'client-sidecar';guard.validate_manifest(sidecar,profile)
 prefixes=('pg8000','scramp','asn1crypto','dateutil','six','certifi','psycopg2','psycopg')
 require(not any(name==prefix or name.startswith(prefix+'.') for name in sys.modules for prefix in prefixes),'CLIENT_ALREADY_IMPORTED')
 sys.dont_write_bytecode=True
 sys.path.insert(0,str(sidecar));sys.path.insert(1,str(ROOT))
 guard.enforce(ROOT,policy)
 target=ROOT/sys.argv[1];sys.argv=[str(target),*sys.argv[2:]]
 TARGET_STARTED=True
 runpy.run_path(str(target),run_name='__main__')
if __name__=='__main__':
 try:main()
 except SystemExit:raise
 except BaseException as error:
  reason=str(error) if type(error).__name__ in ('Stop','ClientStop') and re.fullmatch('[A-Z0-9_]{1,80}',str(error)) else None
  print(json.dumps({'status':'CLIENT_BOOTSTRAP_STOPPED_NO_RETRY','error_type':type(error).__name__,'reason':reason,'client_evidence':getattr(error,'safe_evidence',None) if type(error).__name__=='ClientStop' else None,'target_started':TARGET_STARTED,'database_connection_state':'unknown_after_target_start' if TARGET_STARTED else 'not_attempted'}));sys.exit(2)
