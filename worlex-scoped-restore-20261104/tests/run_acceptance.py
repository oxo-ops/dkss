"""Run mandatory synthetic PostgreSQL acceptance and seal only a complete pass."""
import hashlib,json,os,pathlib,sys,unittest
root=pathlib.Path(__file__).resolve().parents[1];evidence=pathlib.Path(os.environ['WORLEX_EVIDENCE_DIR']);evidence.mkdir(exist_ok=True)
if os.environ.get('WORLEX_REQUIRE_POSTGRES')!='1':raise SystemExit('Explicit PostgreSQL acceptance required')
suite=unittest.defaultTestLoader.discover(str(root/'tests'),pattern='test_restore_*.py')
expected=suite.countTestCases();result=unittest.TextTestRunner(verbosity=2).run(suite)
summary={'expected':expected,'run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'postgres_required':True}
(evidence/'summary.json').write_text(json.dumps(summary,indent=2))
if not result.wasSuccessful() or result.skipped or result.testsRun!=expected:raise SystemExit(1)
policy=json.loads((evidence/'candidate-policy.json').read_text())
policy['postgres_acceptance_passed']=True
policy['acceptance_summary']=summary
files=[root/'worlex_restore.py',root/'policy.json',root/'source-manifest.json',*sorted((root/'tests').glob('*.py'))]
code={str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
policy['tested_artifacts']=code
(evidence/'sealed-policy.json').write_text(json.dumps(policy,indent=2,sort_keys=True))
(evidence/'tested-code-sha256.json').write_text(json.dumps(code,indent=2,sort_keys=True))
