"""Offline stdlib-only regression for the real builder/sealer parent boundary.

The fixture is the Windows summary (CRLF normalized to LF only) from run
42535592454 at
ef4899fedfd8253804e4eec21c9a8a8b9dd7bc1b. That run's 265 tests passed, but the
builder failed afterward and the combined seal was skipped. Extending fixture
IDs/counts below is test input only, never evidence of a new run or a seal.
"""
import copy
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent
NEW_IDS = frozenset("""
test_inspect_diagnostic_io.DiagnosticCLIEnvelopeTests.test_absorbed_operational_cleanup_error_never_marks_completion
test_inspect_diagnostic_io.DiagnosticCLIEnvelopeTests.test_final_persist_error_after_completion_is_refreshed_before_stdout
test_inspect_diagnostic_io.DiagnosticCLIEnvelopeTests.test_genuine_plan_report_and_dispose_failure_never_print_completion
test_inspect_diagnostic_io.DiagnosticCLIEnvelopeTests.test_late_dispose_diagnostic_error_is_in_final_terminal_record
test_inspect_diagnostic_io.DiagnosticCLIEnvelopeTests.test_late_output_write_diagnostic_error_is_in_final_terminal_record
test_inspect_diagnostic_io.DiagnosticIOTests.test_actual_oserror_body_is_primary_after_diagnostic_denial
test_inspect_diagnostic_io.DiagnosticIOTests.test_after_fetch_replace_error_retains_success_and_residue
test_inspect_diagnostic_io.DiagnosticIOTests.test_cleanup_only_diagnostic_failure_does_not_become_operational
test_inspect_diagnostic_io.DiagnosticIOTests.test_close_error_is_not_retried_and_never_replaces
test_inspect_diagnostic_io.DiagnosticIOTests.test_create_directory_error_degrades_but_collision_still_aborts
test_inspect_diagnostic_io.DiagnosticIOTests.test_early_open_error_continues_body_once_without_future_file_access
test_inspect_diagnostic_io.DiagnosticIOTests.test_first_write_error_wins_over_close_error
test_inspect_diagnostic_io.DiagnosticIOTests.test_incomplete_or_failed_inspection_never_authorizes_execute
test_inspect_diagnostic_io.DiagnosticIOTests.test_mandatory_terminal_open_write_flush_fsync_close_and_read_fail_closed
test_inspect_diagnostic_io.DiagnosticIOTests.test_no_target_reopen_delete_or_write_after_disable
test_inspect_diagnostic_io.DiagnosticIOTests.test_primary_error_and_cleanup_body_error_remain_separate
test_inspect_diagnostic_io.DiagnosticIOTests.test_programming_and_schema_errors_are_not_degraded
test_inspect_diagnostic_io.DiagnosticIOTests.test_short_write_disables_without_retry_or_fabricated_errno
test_inspect_diagnostic_io.DiagnosticIOTests.test_successful_degraded_terminal_record_is_explicit_and_durable
test_inspect_diagnostic_io.DiagnosticIOTests.test_warning_schema_rejects_secrets_wrong_types_and_v1
test_inspect_diagnostic_io.DiagnosticIOTests.test_write_and_fsync_errors_close_once_and_latch
test_restore_ci_validator.IsolatedValidatorTests.test_actual_callers_accept_in_fresh_stdlib_processes
test_restore_ci_validator.IsolatedValidatorTests.test_actual_callers_reject_summary_tampering
test_restore_ci_validator.IsolatedValidatorTests.test_actual_callers_reject_unsafe_contract_sources
test_restore_insert_batch.InsertBatchTests.test_all_typed_values_and_explicit_ids_match_original_dbapi_order
test_restore_insert_batch.InsertBatchTests.test_bind_budget_exact_boundary_and_wider_rows
test_restore_insert_batch.InsertBatchTests.test_bytea_hex_expansion_and_utf8_are_measured_not_python_lengths
test_restore_insert_batch.InsertBatchTests.test_compiled_sql_budget_splits_and_rejects_oversized_singleton
test_restore_insert_batch.InsertBatchTests.test_compiler_shape_drift_fails_closed
test_restore_insert_batch.InsertBatchTests.test_eight_mib_singleton_boundary_is_enforced
test_restore_insert_batch.InsertBatchTests.test_exact_four_mib_multirow_and_next_byte_split
test_restore_insert_batch.InsertBatchTests.test_exact_four_mib_singleton_and_oversized_row_are_isolated
test_restore_insert_batch.InsertBatchTests.test_fixed_limits_and_existing_300s_transaction_budget
test_restore_insert_batch.InsertBatchTests.test_full_synthetic_source_dispatch_preserves_table_and_row_order
test_restore_insert_batch.InsertBatchTests.test_middle_batch_error_propagates_once_without_retry
test_restore_insert_batch.InsertBatchTests.test_missing_extra_or_mixed_columns_rejected_without_dispatch
test_restore_insert_batch.InsertBatchTests.test_missing_primary_key_and_nonprimitive_values_fail_closed
test_restore_insert_batch.InsertBatchTests.test_unknown_encoding_client_and_custom_adapter_fail_closed
test_restore_insert_batch.InsertBatchTests.test_wire_size_matches_actual_driver_bind_bytes_and_processors
test_restore_insert_batch.InsertBatchTests.test_zero_one_100_101_rows_use_single_execute_without_returning
test_restore_insert_postgres.InsertSizeFixtureTests.test_full_size_synthetic_envelope_and_five_large_draft_rows
test_restore_insert_postgres.PostgreSQLBoundedInsertAcceptance.test_actual_third_batch_constraint_error_rolls_back_without_retry
test_restore_insert_postgres.PostgreSQLBoundedInsertAcceptance.test_after_sequences_rolls_back_full_size_import
test_restore_insert_postgres.PostgreSQLBoundedInsertAcceptance.test_full_size_disconnect_after_commit
test_restore_insert_postgres.PostgreSQLBoundedInsertAcceptance.test_full_size_disconnect_before_commit
test_restore_insert_postgres.PostgreSQLBoundedInsertAcceptance.test_full_size_values_preservation_epochs_and_bounded_dispatch
test_restore_insert_postgres.PostgreSQLBoundedInsertAcceptance.test_middle_insert_batch_rolls_back
test_restore_observation_acceptance.PostgreSQLObservationAcceptance.test_formal_cli_degraded_diagnostics_same_read_only_plan_and_terminal
test_restore_observation_acceptance.PostgreSQLObservationAcceptance.test_formal_cli_required_plan_report_adapter_and_execute_marker_still_block
test_restore_observation_acceptance.PostgreSQLObservationAcceptance.test_formal_cli_server_error_after_degradation_stays_primary
test_restore_reconciled_attempt.ReconciledAttemptTests.test_active_source_archive_and_target_changes_rejected
test_restore_reconciled_attempt.ReconciledAttemptTests.test_any_prior_bytes_mutation_breaks_reconciliation_binding
test_restore_reconciled_attempt.ReconciledAttemptTests.test_baseline_flags_missing_false_wrong_type_or_extra_rejected
test_restore_reconciled_attempt.ReconciledAttemptTests.test_changed_expected_hashes_rejected
test_restore_reconciled_attempt.ReconciledAttemptTests.test_duplicate_json_fields_and_partial_json_rejected
test_restore_reconciled_attempt.ReconciledAttemptTests.test_exact_evidence_preserves_original_uncertainty
test_restore_reconciled_attempt.ReconciledAttemptTests.test_journal_incomplete_cleanup_and_wrong_order_rejected
test_restore_reconciled_attempt.ReconciledAttemptTests.test_missing_or_extra_evidence_fails_before_attempt
test_restore_reconciled_attempt.ReconciledAttemptTests.test_new_distinct_attempt_and_duplicate_invocation
test_restore_reconciled_attempt.ReconciledAttemptTests.test_nonascii_outer_runtime_uses_exact_core_digest
test_restore_reconciled_attempt.ReconciledAttemptTests.test_old_begin_attempt_does_not_accept_uncertain_without_reconciliation
test_restore_reconciled_attempt.ReconciledAttemptTests.test_partial_binding_persistence_poisoned_attempt_not_retried
test_restore_reconciled_attempt.ReconciledAttemptTests.test_prior_false_cannot_replace_historical_null
test_restore_schema_pool.SchemaPoolTests.test_child_only_config_copy_preserves_shared_options_and_ssl_context
test_restore_schema_pool.SchemaPoolTests.test_context_teardown_failure_disposes_once_and_remains_primary
test_restore_schema_pool.SchemaPoolTests.test_create_app_or_context_entry_failure_never_disposes_uncaptured_engine
test_restore_schema_pool.SchemaPoolTests.test_creator_failure_has_one_attempt_no_retry_or_fallback
test_restore_schema_pool.SchemaPoolTests.test_dispose_failure_never_replaces_primary_failure
test_restore_schema_pool.SchemaPoolTests.test_dispose_only_failure_cannot_report_success_or_retry
test_restore_schema_pool.SchemaPoolTests.test_each_initialization_failure_cleans_up_once_without_later_phases
test_restore_schema_pool.SchemaPoolTests.test_pool_has_distinct_overlapping_checkouts_and_no_overflow
test_restore_schema_pool.SchemaPoolTests.test_shared_ci_config_remains_nullpool_for_ui_and_keeps_guards
test_restore_schema_pool.SchemaPoolTests.test_simulated_initialization_order_and_rollback_semantics_match_nullpool
test_restore_schema_pool.SchemaPoolTests.test_tls_precheck_and_initializers_reuse_same_healthy_connection
""".split())


def regression_summary(validator):
    content = (HERE / 'fixtures/ci-summary-ef4899fe.json').read_bytes()
    if hashlib.sha256(content).hexdigest() != '5bdfbe6d3e2f12b511c01a0871cae6f85b2b746d7e8e76c5acb88f0de34dae8a':
        raise AssertionError('Authenticated predecessor fixture changed')
    original = json.loads(content)
    if not (original['expected'] == original['run'] == len(original['suite_ids']) == 265
            and original['suite_ids_sha256'] == 'd6aa43f9288c8a077dff3e07f3b514001724ab9b3ecc3895d54425b57c1d609b'
            and original['failures'] == original['errors'] == original['skipped'] == 0):
        raise AssertionError('Predecessor fixture identity differs')
    summary = copy.deepcopy(original)
    summary['suite_ids'] = sorted(set(original['suite_ids']) | NEW_IDS)
    if set(summary['suite_ids']) != validator.REQUIRED_ACCEPTANCE_IDS:
        raise AssertionError('Regression fixture must retain exactly the old suite plus new controls')
    summary['suite_ids_sha256'] = hashlib.sha256('\n'.join(summary['suite_ids']).encode()).hexdigest()
    summary['run'] = summary['expected'] = len(summary['suite_ids'])
    summary['postgres_cases'] = validator.POSTGRES_REQUIRED_CASES
    sys.path.insert(0, str(HERE))
    from bounded_insert_evidence_fixture import fixture as bounded_fixture
    summary['bounded_insert'] = bounded_fixture()
    return original, summary


def isolated_case(mode, caller):
    case = unittest.TestCase()
    case.assertEqual((sys.flags.isolated, sys.flags.no_site, sys.dont_write_bytecode), (1, 1, True))
    case.assertIsNone(importlib.util.find_spec('sqlalchemy'))
    case.assertNotIn('preservation_scope', sys.modules)
    case.assertNotIn('sqlalchemy', sys.modules)
    # Match script invocation: only the CI script directory is supplied. The
    # builder itself adds tests/, not PACKAGE or application site-packages.
    sys.path.insert(0, str(HERE / 'windows-ci'))
    module = importlib.import_module(caller)
    validator = sys.modules['verify_client_evidence']
    case.assertNotIn(str(PACKAGE), sys.path)
    validate = module.acceptance_valid if caller == 'build_windows_client' else module.validate_acceptance

    def accept(value):
        case.assertIs(validate(value), True if caller == 'build_windows_client' else None)

    def reject(value):
        if caller == 'build_windows_client':
            case.assertIs(validate(value), False)
        else:
            with case.assertRaises(ValueError):
                validate(value)

    original, summary = regression_summary(validator)
    accept(summary)
    checks = []
    if mode == 'positive':
        # A forged cached module and arbitrary cwd/sys.path cannot replace the
        # exact reviewed source. Neither production code nor its import runs.
        poisoned = types.ModuleType('preservation_scope')
        poisoned.PRESERVATION_CONTRACT = {'forged': True}
        with patch.dict(sys.modules, {'preservation_scope': poisoned}):
            sys.path.insert(0, str(Path.cwd()))
            try:
                accept(summary)
                checks.append('cached_module_and_cwd_shadowing_ignored')
            finally:
                sys.path.pop(0)
    elif mode == 'summary':
        reject(original)
        checks.append('stale_original_suite')
        for label in ('missing_contract', 'changed_contract', 'skip', 'failure', 'error',
                      'missing_mandatory', 'duplicate_id', 'suite_hash', 'incomplete',
                      'postgres_count', 'collision_count', 'catalog_count',
                      'query_count', 'preserved_state', 'network_fix_claim', 'missing_insert',
                      'insert_oversize', 'insert_rollback', 'insert_epoch'):
            value = copy.deepcopy(summary)
            if label == 'missing_contract': value.pop('preservation_contract')
            elif label == 'changed_contract': value['preservation_contract']['tables'].pop('push_subscription')
            elif label in ('skip', 'failure', 'error'):
                value[{'skip': 'skipped', 'failure': 'failures', 'error': 'errors'}[label]] = 1
            elif label == 'missing_mandatory': value['suite_ids'].pop()
            elif label == 'duplicate_id': value['suite_ids'].append(value['suite_ids'][0])
            elif label == 'suite_hash': value['suite_ids_sha256'] = '0' * 64
            elif label == 'incomplete': value['run'] -= 1
            elif label == 'postgres_count': value['postgres_cases'] -= 1
            elif label == 'collision_count': value['collision_required_cases'] -= 1
            elif label == 'catalog_count': value['catalog_required_cases'] -= 1
            elif label == 'query_count': value['catalog_batching']['preflight']['new_catalog_execute_calls'] = 108
            elif label == 'preserved_state': value['catalog_batching']['preflight']['preserved_state_unchanged'] = False
            elif label == 'network_fix_claim': value['catalog_batching']['preflight']['network_disconnect_fix_proven'] = True
            if label == 'missing_insert': value.pop('bounded_insert')
            elif label == 'insert_oversize': value['bounded_insert']['full-size']['insert_dispatch'][0]['binds'] = 8001
            elif label == 'insert_rollback': value['bounded_insert']['actual-third-batch-error']['restore_retried'] = True
            elif label == 'insert_epoch': value['bounded_insert']['full-size']['exact_epoch_revisions'] = {'shared':1}
            reject(value)
            checks.append(label)
    elif mode == 'source':
        source = PACKAGE / 'preservation_scope.py'
        reviewed = source.read_bytes()
        read_bytes = Path.read_bytes
        unsafe = {
            'missing_assignment': b'UNRELATED = {}',
            'duplicate_assignment': b'PRESERVATION_CONTRACT = {}\nPRESERVATION_CONTRACT = {}',
            'annotated_assignment': b'PRESERVATION_CONTRACT: dict = {}',
            'annotated_duplicate': b'PRESERVATION_CONTRACT = {}\nPRESERVATION_CONTRACT: dict = {}',
            'not_dictionary': b'PRESERVATION_CONTRACT = []',
            'nonliteral': b'PRESERVATION_CONTRACT = dict()',
            'executable_expression': b'PRESERVATION_CONTRACT = __import__("pathlib").Path("SOURCE_EXECUTED").touch()',
            'alias': b'ALIAS = PRESERVATION_CONTRACT = {}',
            'nested_assignment': b'if True:\n    PRESERVATION_CONTRACT = {}',
            'syntax_error': b'PRESERVATION_CONTRACT = {',
            'invalid_encoding': b'\xff',
            'mutated_after_assignment': reviewed + b'\nPRESERVATION_CONTRACT["version"] = 2\n',
            'augmented_assignment': reviewed + b'\nPRESERVATION_CONTRACT |= {}\n',
            'indirect_mutation': reviewed + b'\nglobals()["PRESERVATION_CONTRACT"]["version"] = 2\n',
            'unexecuted_extra_code': reviewed + b'\n__import__("pathlib").Path("SOURCE_EXECUTED").touch()\n',
            'changed_literal': reviewed.replace(b"'version': 1", b"'version': 2"),
            'duplicate_literal_key': reviewed.replace(b"'version': 1,", b"'version': 1, 'version': 1,"),
        }
        for label, content in unsafe.items():
            with patch.object(Path, 'read_bytes', lambda path: content if path == source else read_bytes(path)):
                reject(summary)
                if label == 'changed_literal':
                    # Matching forged evidence must not authorize source changes.
                    forged = copy.deepcopy(summary)
                    forged['preservation_contract']['version'] = 2
                    reject(forged)
            checks.append(label)
        with patch.object(Path, 'is_file', return_value=False):
            reject(summary)
        checks.append('missing_source_file')
        with patch.object(Path, 'is_symlink', return_value=True):
            reject(summary)
        checks.append('symlink_source_file')
        with patch.object(Path, 'read_bytes', side_effect=OSError('unreadable fixture')):
            reject(summary)
        checks.append('unreadable_source_file')
        case.assertFalse((Path.cwd() / 'SOURCE_EXECUTED').exists())
    else:
        raise AssertionError('Unknown isolated test mode')
    case.assertNotIn('preservation_scope', sys.modules)
    case.assertNotIn('sqlalchemy', sys.modules)
    print(json.dumps({'mode': mode, 'caller': caller, 'checks': checks,
                      'isolated': True, 'site_disabled': True,
                      'application_imports_absent': True}, sort_keys=True))


class IsolatedValidatorTests(unittest.TestCase):
    def run_cases(self, mode, *, repository_cwd=False):
        with tempfile.TemporaryDirectory() as temp:
            unrelated = Path(temp)
            # Detect accidental cwd imports even if a future change adds cwd.
            for name in ('preservation_scope.py', 'sqlalchemy.py'):
                (unrelated / name).write_text('raise AssertionError("UNTRUSTED_CWD_IMPORT")\n', encoding='utf-8')
            directories = [PACKAGE.parent, unrelated] if repository_cwd else [unrelated]
            for cwd in directories:
                for caller in ('build_windows_client', 'seal_combined'):
                    with self.subTest(mode=mode, cwd=str(cwd), caller=caller):
                        result = subprocess.run([sys.executable, '-I', '-B', '-S', str(Path(__file__).resolve()),
                                                 '--isolated', mode, caller], cwd=cwd,
                            env={key: value for key, value in os.environ.items()
                                 if key not in {'PYTHONPATH', 'PYTHONHOME'}},
                            capture_output=True, text=True, timeout=30)
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        report = json.loads(result.stdout)
                        self.assertEqual((report['mode'], report['caller']), (mode, caller))
                        self.assertTrue(report['application_imports_absent'])
                        self.assertTrue(report['isolated'] and report['site_disabled'])

    def test_actual_callers_accept_in_fresh_stdlib_processes(self):
        self.run_cases('positive', repository_cwd=True)

    def test_actual_callers_reject_summary_tampering(self):
        self.run_cases('summary')

    def test_actual_callers_reject_unsafe_contract_sources(self):
        self.run_cases('source')


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--isolated':
        isolated_case(*sys.argv[2:])
    else:
        unittest.main()
