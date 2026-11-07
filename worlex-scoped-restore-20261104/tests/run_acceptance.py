"""Run mandatory synthetic PostgreSQL acceptance and emit nonexecutable Linux acceptance evidence."""
import hashlib,json,os,pathlib,sys,unittest
sys.dont_write_bytecode = True
root=pathlib.Path(__file__).resolve().parents[1];evidence=pathlib.Path(os.environ['WORLEX_EVIDENCE_DIR']);evidence.mkdir(exist_ok=True)
sys.path.insert(0,str(root/'tests/windows-ci'))
from verify_client_evidence import validate_restore_scope
if os.environ.get('WORLEX_REQUIRE_POSTGRES')!='1':raise SystemExit('Explicit PostgreSQL acceptance required')
suite=unittest.defaultTestLoader.discover(str(root/'tests'),pattern='test_restore_*.py')
expected=suite.countTestCases()
if expected<136:raise SystemExit('Full 136-case catalog-batching acceptance suite required')
def test_ids(items):
 for item in items:
  if isinstance(item,unittest.TestSuite):yield from test_ids(item)
  else:yield item.id()
ids=list(test_ids(suite))
required_catalog_tests=frozenset("""
test_restore_batched_catalog.EquivalenceTests.test_bulk_query_failure_propagates_without_retry_or_fallback
test_restore_batched_catalog.EquivalenceTests.test_compilation_across_postgres_dialect_versions
test_restore_batched_catalog.EquivalenceTests.test_composite_key_noncollision
test_restore_batched_catalog.EquivalenceTests.test_constraint_and_unique_index
test_restore_batched_catalog.EquivalenceTests.test_duplicate_constraint_backing_index_retained
test_restore_batched_catalog.EquivalenceTests.test_empty_typed_never_queries_all_catalog
test_restore_batched_catalog.EquivalenceTests.test_exact_source_and_change_scope
test_restore_batched_catalog.EquivalenceTests.test_existing_uuid_duplicate_rejected
test_restore_batched_catalog.EquivalenceTests.test_expression_index_blocked
test_restore_batched_catalog.EquivalenceTests.test_fresh_inspector_each_preflight
test_restore_batched_catalog.EquivalenceTests.test_included_columns_are_not_added_to_unique_key
test_restore_batched_catalog.EquivalenceTests.test_itc_guards_unchanged
test_restore_batched_catalog.EquivalenceTests.test_missing_actual_oid_fails_closed
test_restore_batched_catalog.EquivalenceTests.test_missing_foreign_extra_keys_fail_closed
test_restore_batched_catalog.EquivalenceTests.test_no_unique_constraints
test_restore_batched_catalog.EquivalenceTests.test_nonunique_expression_index_ignored
test_restore_batched_catalog.EquivalenceTests.test_null_keys_skipped
test_restore_batched_catalog.EquivalenceTests.test_nulls_not_distinct_constraint_and_index_blocked
test_restore_batched_catalog.EquivalenceTests.test_only_exact_populated_names_any_kind_any_scope
test_restore_batched_catalog.EquivalenceTests.test_partial_index_keeps_conservative_full_key_check
test_restore_batched_catalog.EquivalenceTests.test_partial_index_noncollision
test_restore_batched_catalog.EquivalenceTests.test_pk_collision_before_catalog
test_restore_batched_catalog.EquivalenceTests.test_real_compiled_catalog_calls_36_tables_108_to_3
test_restore_batched_catalog.EquivalenceTests.test_real_dialect_maps_and_ordered_combination_equal
test_restore_batched_catalog.EquivalenceTests.test_seen_dedup_null_and_500_row_chunk_semantics
test_restore_batched_catalog.EquivalenceTests.test_source_natural_key_collision
test_restore_batched_catalog.EquivalenceTests.test_target_natural_key_collision
test_restore_batched_catalog.EquivalenceTests.test_tenant_case_alias_before_catalog
test_restore_batched_catalog.EquivalenceTests.test_unique_index_target_collision
test_restore_batched_catalog.EquivalenceTests.test_unknown_and_empty_columns_blocked
test_restore_batched_catalog.EquivalenceTests.test_uuid_and_generation_checks_unchanged
test_restore_postgres.PostgreSQLRestoreAcceptance.test_catalog_maps_match_original_full_fixture
test_restore_postgres.PostgreSQLRestoreAcceptance.test_catalog_preflight_reduces_real_full_fixture_queries
""".split())
if len(ids)!=len(set(ids)) or not required_catalog_tests.issubset(ids):raise SystemExit('Required catalog-batching tests missing or duplicate tests discovered')

result=unittest.TextTestRunner(verbosity=2).run(suite)
summary={'suite_ids_sha256':hashlib.sha256('\n'.join(sorted(ids)).encode()).hexdigest(),'catalog_required_cases':len(required_catalog_tests),'expected':expected,'run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'postgres_required':True}
(evidence/'summary.json').write_text(json.dumps(summary,indent=2))
if not result.wasSuccessful() or result.skipped or result.testsRun!=expected:raise SystemExit(1)
from test_restore_postgres import CATALOG_BATCHING_EVIDENCE
maps=CATALOG_BATCHING_EVIDENCE.get('maps',{});preflight=CATALOG_BATCHING_EVIDENCE.get('preflight',{})
if maps.get('populated_import_tables')!=36 or not all(maps.get(k) is True for k in ('exact_public_keys','unique_maps_equal','index_maps_equal','ordered_combination_equal','preserved_state_unchanged')):raise SystemExit('Actual PostgreSQL catalog equivalence evidence missing')
if any(preflight.get(k)!=v for k,v in {'source_rows':4100,'import_rows':4099,'populated_import_tables':36,'old_catalog_execute_calls':108,'new_catalog_execute_calls':3}.items()) or not all(preflight.get(k) is True for k in ('application_queries_and_binds_equal','preserved_state_unchanged','synthetic_only')) or preflight.get('network_disconnect_fix_proven') is not False:raise SystemExit('Actual PostgreSQL catalog query reduction evidence missing')
if type(preflight.get('old_application_execute_calls')) is not int or preflight['old_application_execute_calls']<=0 or preflight.get('new_application_execute_calls')!=preflight['old_application_execute_calls']:raise SystemExit('Application query equivalence evidence missing')
summary['catalog_batching']=CATALOG_BATCHING_EVIDENCE
(evidence/'summary.json').write_text(json.dumps(summary,indent=2))
coverage=json.loads((evidence/'full-fixture-coverage.json').read_text())
counts=json.loads((root/'source-counts.json').read_text())
validate_restore_scope(coverage,counts)
if coverage.get('synthetic_only') is not True or coverage.get('source_counts')!=counts or coverage.get('source_rows')!=4100 or coverage.get('populated_tables')!=37:raise SystemExit('Full synthetic table coverage is required')
if not all(coverage.get(k) is True for k in ('imported_values_and_blobs_match','preserved_rows_match','owner_bindings_quarantined')):raise SystemExit('Full synthetic value/preservation proof is required')
before=json.loads((evidence/'disconnect-before-commit.json').read_text())
after=json.loads((evidence/'disconnect-after-commit.json').read_text())
for item in (before,after):
 validate_restore_scope(item,counts)
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
