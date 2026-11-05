"""Run mandatory synthetic PostgreSQL acceptance and emit nonexecutable Linux acceptance evidence."""
import hashlib,json,os,pathlib,sys,unittest
root=pathlib.Path(__file__).resolve().parents[1];evidence=pathlib.Path(os.environ['WORLEX_EVIDENCE_DIR']);evidence.mkdir(exist_ok=True)
if os.environ.get('WORLEX_REQUIRE_POSTGRES')!='1':raise SystemExit('Explicit PostgreSQL acceptance required')
suite=unittest.defaultTestLoader.discover(str(root/'tests'),pattern='test_restore_*.py')
expected=suite.countTestCases()
if expected<93:raise SystemExit('Full 93-case acceptance suite required')
result=unittest.TextTestRunner(verbosity=2).run(suite)
summary={'expected':expected,'run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'postgres_required':True}
(evidence/'summary.json').write_text(json.dumps(summary,indent=2))
if not result.wasSuccessful() or result.skipped or result.testsRun!=expected:raise SystemExit(1)
coverage=json.loads((evidence/'full-fixture-coverage.json').read_text())
counts=json.loads((root/'source-counts.json').read_text())
if coverage.get('synthetic_only') is not True or coverage.get('source_counts')!=counts or coverage.get('source_rows')!=4100 or coverage.get('populated_tables')!=37:raise SystemExit('Full synthetic table coverage is required')
if not all(coverage.get(k) is True for k in ('imported_values_and_blobs_match','preserved_rows_match','owner_bindings_quarantined')):raise SystemExit('Full synthetic value/preservation proof is required')
before=json.loads((evidence/'disconnect-before-commit.json').read_text())
after=json.loads((evidence/'disconnect-after-commit.json').read_text())
for item in (before,after):
 if item.get('synthetic_only') is not True or item.get('source_rows')!=4100 or item.get('populated_tables')!=37:raise SystemExit('Full-table disconnect evidence missing')
if not all(before.get(k) is True for k in ('actual_connection_closed_before_commit','all_imports_absent','preserved_rows_match','sequences_unchanged','fresh_readonly_verification_rejects_absent_restore')) or before.get('restore_retried') is not False:raise SystemExit('Pre-commit disconnect rollback proof missing')
if not all(after.get(k) is True for k in ('real_commit_then_client_error','fresh_readonly_verification_matches','preserved_rows_match','replay_guard_rejected_before_insert','sequences_unchanged_by_replay')) or after.get('network_packet_loss_reproduced') is not False:raise SystemExit('Post-commit reconciliation proof missing')
policy=json.loads((evidence/'candidate-policy.json').read_text())
policy['disconnect_acceptance']={'before_commit':before,'after_commit':after}
policy['full_table_acceptance']=coverage
policy.pop('postgres_acceptance_passed',None)
policy.pop('windows_render_acceptance_passed',None)
policy['acceptance_summary']=summary
files=[root/'.gitattributes',root/'worlex_restore.py',root/'policy.json',root/'source-manifest.json',root/'source-counts.json',root/'client_runtime_guard.py',root/'client_bootstrap.py',root/'client_connection.py',root/'tests/windows-ci/client-build-inputs.json',*sorted((root/'tests').rglob('*.py')),*sorted((root/'tests').rglob('*.sh'))]
code={f.relative_to(root).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
policy['tested_artifacts']=code
policy['workflow_sha256']=hashlib.sha256(pathlib.Path('.github/workflows/worlex-restore-postgres.yml').read_bytes()).hexdigest()
(evidence/'provisional-policy.json').write_text(json.dumps(policy,indent=2,sort_keys=True))
(evidence/'tested-code-sha256.json').write_text(json.dumps(code,indent=2,sort_keys=True))
