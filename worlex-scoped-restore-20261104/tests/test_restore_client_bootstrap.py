"""Synthetic bootstrap/core preconnection-gate tests. No DB or DLL operations."""
import ast, hashlib, json, pathlib, subprocess, sys, tempfile, unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parent
if ROOT.name=='tests':ROOT=ROOT.parent
class BootstrapReview(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='synthetic-bootstrap-');self.addCleanup(self.tmp.cleanup);self.root=pathlib.Path(self.tmp.name)
  (self.root/'client_bootstrap.py').write_bytes((ROOT/'client_bootstrap.py').read_bytes())
  self.guard=self.root/'client_runtime_guard.py';self.guard.write_text("class ClientStop(RuntimeError):pass\ndef policy_profile(root,policy):return policy['windows_client_acceptance']\ndef validate_manifest(root,profile):\n if not root.is_dir():raise ClientStop('SYNTHETIC_SIDECAR_MISSING')\ndef enforce(root,policy):\n (root/'guard-first').write_text('verified before target')\n")
  (self.root/'client-sidecar').mkdir()
  for name in ('worlex_restore.py','run_restore_once.py'):
   (self.root/name).write_text("import pathlib,sys,json\np=pathlib.Path(__file__).parent\nassert (p/'guard-first').exists()\n(p/'target-ran').write_text(json.dumps(sys.argv))\n")
  self.policy={'windows_client_acceptance':{'bootstrap_sha256':hashlib.sha256((ROOT/'client_bootstrap.py').read_bytes()).hexdigest(),'guard_sha256':hashlib.sha256(self.guard.read_bytes()).hexdigest()}}
  self.save()
 def save(self):(self.root/'policy.json').write_text(json.dumps(self.policy))
 def run_target(self,name='worlex_restore.py',*args,preimport=None,isolated=True):
  # Bootstrap is a process entry point. Never clear the acceptance interpreter's
  # loaded modules or fake sys.flags: exercise the exact file in a fresh Python.
  command=[sys.executable]
  if isolated:command.append('-I')
  script=str(self.root/'client_bootstrap.py')
  if preimport is None:command.extend([script,name,*args])
  else:
   command.extend(['-c',"import runpy,sys; sys.modules[sys.argv.pop(1)]=object(); sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name='__main__')",preimport,script,name,*args])
  return subprocess.run(command,cwd=self.root,capture_output=True,text=True,timeout=30)
 def stopped(self,result,reason):
  self.assertEqual(result.returncode,2,result.stderr)
  saved=json.loads(result.stdout)
  self.assertEqual(saved['status'],'CLIENT_BOOTSTRAP_STOPPED_NO_RETRY')
  self.assertEqual(saved['reason'],reason)
  self.assertIs(saved['target_started'],False)
  self.assertEqual(saved['database_connection_state'],'not_attempted')
  self.assertFalse((self.root/'target-ran').exists())
 def test_fixed_core_target_after_guard(self):
  process=self.run_target('worlex_restore.py','inspect','--argument','synthetic value')
  self.assertEqual(process.returncode,0,process.stdout+process.stderr)
  result=json.loads((self.root/'target-ran').read_text());self.assertEqual(result[1:],['inspect','--argument','synthetic value'])
 def test_fixed_launcher_target_after_guard(self):
  process=self.run_target('run_restore_once.py')
  self.assertEqual(process.returncode,0,process.stdout+process.stderr)
  self.assertTrue((self.root/'target-ran').exists())
 def test_arbitrary_target_rejected(self):
  for name in ('../other.py','other.py','./worlex_restore.py'):
   with self.subTest(name=name):self.stopped(self.run_target(name),'FIXED_RESTORE_TARGET_REQUIRED')
 def test_bootstrap_hash_mismatch_rejected(self):
  self.policy['windows_client_acceptance']['bootstrap_sha256']='0'*64;self.save()
  self.stopped(self.run_target(),'CLIENT_BOOTSTRAP_HASH_MISMATCH')
  self.assertFalse((self.root/'guard-first').exists())
 def test_guard_hash_mismatch_rejected_before_import(self):
  self.guard.write_text("raise RuntimeError('should never execute')")
  self.stopped(self.run_target(),'CLIENT_GUARD_HASH_MISMATCH')
 def test_preimported_client_rejected(self):
  for prefix in ('pg8000','scramp','asn1crypto','dateutil','six','certifi','psycopg2','psycopg'):
   for name in (prefix,prefix+'.synthetic_child'):
    with self.subTest(name=name):
     self.stopped(self.run_target(preimport=name),'CLIENT_ALREADY_IMPORTED')
     self.assertFalse((self.root/'guard-first').exists())
 def test_parent_client_import_does_not_pollute_fresh_bootstrap(self):
  with patch.dict(sys.modules,{'pg8000':object(),'psycopg2':object()}):
   process=self.run_target()
  self.assertEqual(process.returncode,0,process.stdout+process.stderr)
  self.assertTrue((self.root/'target-ran').exists())
 def test_real_nonisolated_interpreter_rejected(self):
  self.stopped(self.run_target(isolated=False),'ISOLATED_PYTHON_REQUIRED')
  self.assertFalse((self.root/'guard-first').exists())
 def test_guard_stop_does_not_run_target(self):
  self.guard.write_text(self.guard.read_text()+"\ndef enforce(root,policy):raise ClientStop('SYNTHETIC_GUARD_STOP')\n")
  self.policy['windows_client_acceptance']['guard_sha256']=hashlib.sha256(self.guard.read_bytes()).hexdigest();self.save()
  self.stopped(self.run_target(),'SYNTHETIC_GUARD_STOP')
 def test_missing_sidecar_stops_before_target(self):
  (self.root/'client-sidecar').rmdir()
  self.stopped(self.run_target(),'SYNTHETIC_SIDECAR_MISSING')
 def core_gate(self):
  source=(ROOT/'worlex_restore.py').read_text();node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='enforce_windows_client')
  class Stop(RuntimeError):pass
  def require(value,reason):
   if not value:raise Stop(reason)
  scope={'Stop':Stop,'require':require,'sha':lambda b:hashlib.sha256(b).hexdigest()}
  exec(compile(ast.Module(body=[node],type_ignores=[]),'synthetic-isolated-gate','exec'),scope)
  return scope['enforce_windows_client'],Stop
 def test_cli_gate_refuses_unsealed_policy(self):
  f,stop=self.core_gate()
  with self.assertRaisesRegex(stop,'WINDOWS_CLIENT_CI_SEAL'):f(self.root,{})
  self.assertFalse((self.root/'guard-first').exists())
 def test_cli_gate_refuses_wrong_guard_hash(self):
  f,stop=self.core_gate()
  with self.assertRaisesRegex(stop,'GUARD_DIFFERS'):f(self.root,{'windows_client_acceptance_passed':True,'tested_artifacts':{'client_runtime_guard.py':'0'*64}})
  self.assertFalse((self.root/'guard-first').exists())
 def test_cli_gate_executes_exact_guard(self):
  f,_=self.core_gate();f(self.root,{'windows_client_acceptance_passed':True,'tested_artifacts':{'client_runtime_guard.py':hashlib.sha256(self.guard.read_bytes()).hexdigest()}})
  self.assertTrue((self.root/'guard-first').exists())
 def test_cli_gate_appears_before_engine_connection(self):
  source=(ROOT/'worlex_restore.py').read_text();node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='cli')
  calls=[n for n in ast.walk(node) if isinstance(n,ast.Call)]
  gate=min(n.lineno for n in calls if isinstance(n.func,ast.Name) and n.func.id=='enforce_windows_client')
  connections=[n.lineno for n in calls if (isinstance(n.func,ast.Name) and n.func.id=='create_engine') or (isinstance(n.func,ast.Attribute) and n.func.attr in ('connect','begin'))]
  self.assertTrue(connections);self.assertLess(gate,min(connections))
if __name__=='__main__':
 result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(BootstrapReview))
 (ROOT/'independent-bootstrap-tests.json').write_text(json.dumps({'scope':'synthetic fixed-target scripts and isolated core function only; no DB or DLL load','bootstrap_sha256':hashlib.sha256((ROOT/'client_bootstrap.py').read_bytes()).hexdigest(),'core_sha256':hashlib.sha256((ROOT/'worlex_restore.py').read_bytes()).hexdigest(),'run':result.testsRun,'errors':len(result.errors),'failures':len(result.failures),'skipped':len(result.skipped)},indent=2))
 raise SystemExit(not result.wasSuccessful())
