"""Synthetic bootstrap/core preconnection-gate tests. No DB or DLL operations."""
import ast, hashlib, importlib.util, json, pathlib, sys, tempfile, unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parent
if ROOT.name=='tests':ROOT=ROOT.parent
class BootstrapReview(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='synthetic-bootstrap-');self.addCleanup(self.tmp.cleanup);self.root=pathlib.Path(self.tmp.name)
  spec=importlib.util.spec_from_file_location('bootstrap_review',ROOT/'client_bootstrap.py');self.b=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.b);self.b.ROOT=self.root
  self.oldpath=list(sys.path);self.addCleanup(lambda:sys.path.__setitem__(slice(None),self.oldpath))
  self.addCleanup(lambda:setattr(sys,'dont_write_bytecode',True))
  self.guard=self.root/'client_runtime_guard.py';self.guard.write_text("class ClientStop(RuntimeError):pass\ndef policy_profile(root,policy):return policy['windows_client_acceptance']\ndef validate_manifest(root,profile):\n if not root.is_dir():raise ClientStop('SYNTHETIC_SIDECAR_MISSING')\ndef enforce(root,policy):\n (root/'guard-first').write_text('verified before target')\n")
  (self.root/'client-sidecar').mkdir()
  for name in ('worlex_restore.py','run_restore_once.py'):
   (self.root/name).write_text("import pathlib,sys,json\np=pathlib.Path(__file__).parent\nassert (p/'guard-first').exists()\n(p/'target-ran').write_text(json.dumps(sys.argv))\n")
  self.policy={'windows_client_acceptance':{'bootstrap_sha256':hashlib.sha256((ROOT/'client_bootstrap.py').read_bytes()).hexdigest(),'guard_sha256':hashlib.sha256(self.guard.read_bytes()).hexdigest()}}
  self.save()
 def save(self):(self.root/'policy.json').write_text(json.dumps(self.policy))
 def run_target(self,name='worlex_restore.py',*args):
  original_flags=sys.flags
  class IsolatedFlags:
   def __getattr__(self,name):return 1 if name=='isolated' else getattr(original_flags,name)
  with patch.object(sys,'argv',['client_bootstrap.py',name,*args]),patch.object(sys,'flags',IsolatedFlags()):self.b.main()
 def test_fixed_core_target_after_guard(self):
  self.run_target('worlex_restore.py','inspect','--argument','synthetic value')
  result=json.loads((self.root/'target-ran').read_text());self.assertEqual(result[1:],['inspect','--argument','synthetic value']);self.assertTrue(self.b.TARGET_STARTED)
 def test_fixed_launcher_target_after_guard(self):self.run_target('run_restore_once.py');self.assertTrue((self.root/'target-ran').exists())
 def test_arbitrary_target_rejected(self):
  for name in ('../other.py','other.py','./worlex_restore.py'):
   with self.subTest(name=name),self.assertRaisesRegex(self.b.Stop,'FIXED_RESTORE'):self.run_target(name)
  self.assertFalse((self.root/'target-ran').exists())
 def test_bootstrap_hash_mismatch_rejected(self):
  self.policy['windows_client_acceptance']['bootstrap_sha256']='0'*64;self.save()
  with self.assertRaisesRegex(self.b.Stop,'BOOTSTRAP_HASH'):self.run_target()
  self.assertFalse((self.root/'guard-first').exists())
 def test_guard_hash_mismatch_rejected_before_import(self):
  self.guard.write_text("raise RuntimeError('should never execute')")
  with self.assertRaisesRegex(self.b.Stop,'GUARD_HASH'):self.run_target()
 def test_preimported_client_rejected(self):
  with patch.dict(sys.modules,{'psycopg2':object()}),self.assertRaisesRegex(self.b.Stop,'ALREADY_IMPORTED'):self.run_target()
  self.assertFalse((self.root/'guard-first').exists())
 def test_guard_stop_does_not_run_target(self):
  self.guard.write_text(self.guard.read_text()+"\ndef enforce(root,policy):raise ClientStop('SYNTHETIC_GUARD_STOP')\n")
  self.policy['windows_client_acceptance']['guard_sha256']=hashlib.sha256(self.guard.read_bytes()).hexdigest();self.save()
  with self.assertRaisesRegex(RuntimeError,'SYNTHETIC_GUARD_STOP'):self.run_target()
  self.assertFalse(self.b.TARGET_STARTED);self.assertFalse((self.root/'target-ran').exists())
 def test_missing_sidecar_stops_before_target(self):
  (self.root/'client-sidecar').rmdir()
  with self.assertRaisesRegex(RuntimeError,'SIDECAR_MISSING'):self.run_target()
  self.assertFalse(self.b.TARGET_STARTED)
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
