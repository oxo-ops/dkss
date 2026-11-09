"""Fail-closed combined-gate checks for actual Windows pure-client evidence."""
import ast
import base64
import csv
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
from email.parser import BytesParser
import re
import stat
import zipfile


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def valid_hash(value):
    return isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value) is not None


def safe_relative(value):
    require(isinstance(value, str) and value, 'Empty artifact member path')
    relative = PurePosixPath(value)
    require(relative.parts and not relative.is_absolute() and '..' not in relative.parts and
            '\\' not in value and ':' not in value and str(relative) == value,
            'Unsafe artifact member path: ' + value)
    require(not any(ord(char) < 32 or char in '<>\"|?*' for char in value),
            'Windows-invalid artifact member path: ' + value)
    require(all(part not in ('', '.') and not part.endswith((' ', '.')) and
                not re.fullmatch(r'(?i)(?:con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?', part)
                for part in relative.parts), 'Windows-ambiguous artifact member path: ' + value)
    return relative


def artifact_path(directory, filename):
    relative = safe_relative(filename)
    require(len(relative.parts) == 1, 'Artifact filename must be a basename')
    path = directory / filename
    require(path.is_file() and not path.is_symlink() and
            path.resolve().is_relative_to(directory.resolve()), 'Artifact absent or unsafe: ' + filename)
    return path


def wheel_files(path, name, version):
    """Hash the complete exact wheel and reject native/ambiguous sidecar payloads."""
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        names = [entry.filename for entry in members if not entry.is_dir()]
        require(names and len(names) == len(set(names)) == len({n.casefold() for n in names}),
                'Duplicate or Windows-aliased wheel members')
        result = {}
        for entry in members:
            relative = entry.filename.rstrip('/') if entry.is_dir() else entry.filename
            safe_relative(relative)
            mode = entry.external_attr >> 16
            require(not stat.S_ISLNK(mode), 'Wheel symlink forbidden')
            if entry.is_dir():
                continue
            require(not re.search(r'(?i)\.(?:dll|pyd|so|exe|dylib)(?:\.[0-9.]+)?$', relative),
                    'Native binary forbidden in pure client wheel: ' + relative)
            require(not relative.lower().endswith('.pth') and
                    not any(part.endswith('.data') for part in PurePosixPath(relative).parts),
                    'Wheel requires installation transformations outside the sealed sidecar')
            content = archive.read(entry)
            require(not content.startswith((b'MZ', b'\x7fELF', b'\xfe\xed\xfa\xce', b'\xfe\xed\xfa\xcf',
                                            b'\xce\xfa\xed\xfe', b'\xcf\xfa\xed\xfe')),
                    'Native binary signature forbidden in pure client wheel')
            result[relative] = hashlib.sha256(content).hexdigest()
        wheel_metadata = [n for n in names if n.endswith('.dist-info/WHEEL')]
        package_metadata = [n for n in names if n.endswith('.dist-info/METADATA')]
        records = [n for n in names if n.endswith('.dist-info/RECORD')]
        require(len(wheel_metadata) == len(package_metadata) == len(records) == 1,
                'Exactly one package metadata record required per wheel')
        require(PurePosixPath(wheel_metadata[0]).parent == PurePosixPath(package_metadata[0]).parent,
                'Wheel metadata directories differ')
        require(PurePosixPath(records[0]).parent == PurePosixPath(package_metadata[0]).parent,
                'Wheel RECORD directory differs')
        rows = list(csv.reader(io.StringIO(archive.read(records[0]).decode('utf-8'))))
        require(all(len(row) == 3 for row in rows) and len(rows) == len(names) and
                {row[0] for row in rows} == set(names), 'Wheel RECORD must cover every file exactly once')
        for relative, digest, size in rows:
            if relative == records[0]:
                require(not digest and not size, 'Wheel RECORD self-entry must be unhashed')
                continue
            expected = 'sha256=' + base64.urlsafe_b64encode(bytes.fromhex(result[relative])).decode('ascii').rstrip('=')
            require(digest == expected and size == str(archive.getinfo(relative).file_size),
                    'Wheel RECORD payload hash/size mismatch: ' + relative)
        wheel = BytesParser().parsebytes(archive.read(wheel_metadata[0]))
        package = BytesParser().parsebytes(archive.read(package_metadata[0]))
        normalize = lambda value: re.sub(r'[-_.]+', '-', value).lower()
        require(normalize(package.get('Name', '')) == normalize(name) and
                package.get('Version') == version, 'Wheel package identity differs from lock')
        tags = wheel.get_all('Tag', [])
        require(wheel.get('Root-Is-Purelib', '').lower() == 'true' and tags and
                all(re.fullmatch(r'py[23](?:\.py[23])*-none-any', tag) for tag in tags),
                'Pure universal wheel metadata required')
    return dict(sorted(result.items()))



def validate_pure_wheels(packages, directory):
    """Validate the entire locked wheel directory before install or extraction."""
    directory = Path(directory)
    require(isinstance(packages, list) and packages, 'Pinned pure-client packages required')
    expected = {entry['filename']: entry for entry in packages}
    require(len(expected) == len(packages) == len({entry['name'] for entry in packages}),
            'Duplicate locked pure-client package or filename')
    require(directory.is_dir() and not directory.is_symlink(), 'Pure wheel directory missing or unsafe')
    require({path.name for path in directory.iterdir()} == set(expected),
            'Pure wheel directory must contain only the complete locked artifacts')
    wheels, merged, folded = {}, {}, set()
    for filename, entry in expected.items():
        require(filename.endswith('-none-any.whl') and valid_hash(entry['sha256']),
                'Pure universal locked wheel required')
        require(entry['url'].startswith('https://files.pythonhosted.org/packages/'),
                'Official PyPI wheel origin required')
        path = artifact_path(directory, filename)
        require(sha(path) == entry['sha256'], 'Pinned official wheel hash mismatch: ' + filename)
        files = wheel_files(path, entry['name'], entry['version'])
        require(not folded.intersection(name.casefold() for name in files), 'Cross-wheel file collision')
        folded.update(name.casefold() for name in files)
        merged.update(files)
        wheels[filename] = {'name': entry['name'], 'version': entry['version'],
                            'sha256': entry['sha256'], 'files': files}
    return dict(sorted(wheels.items())), dict(sorted(merged.items()))


def validate_imported_modules(imported, merged):
    module_files = {'pg8000': 'pg8000/__init__.py', 'scramp': 'scramp/__init__.py',
                    'asn1crypto': 'asn1crypto/__init__.py', 'dateutil': 'dateutil/__init__.py',
                    'six': 'six.py', 'certifi': 'certifi/__init__.py'}
    require(isinstance(imported, dict) and set(imported) == set(module_files),
            'Every imported pure dependency must be observed')
    sites = set()
    for module, relative in module_files.items():
        item = imported[module]
        path = PureWindowsPath(item['path'])
        require(path.is_absolute() and '..' not in path.parts and relative in merged and
                item.get('sha256') == merged[relative] and
                path.as_posix().lower().endswith('/' + relative.lower()),
                'Imported pure module path/hash mismatch: ' + module)
        sites.add(str(path.parents[len(PurePosixPath(relative).parts) - 1]).casefold())
    require(len(sites) == 1, 'Imported pure-client dependencies come from different environments')
    return next(iter(sites))


def validate_ssl_runtime(ssl_runtime):
    require(ssl_runtime.get('ssl_provider') == {
                'kind': 'extension', 'has_file': True, 'listed_as_builtin': False,
                'origin_kind': 'file', 'loader_kind': 'extension'} and
            ssl_runtime.get('openssl_linkage') == 'dynamic',
            'Only the CI-verified extension/dynamic SSL provider is accepted')
    require(ssl_runtime.get('no_psycopg_or_libpq_loaded') is True,
            'Native PostgreSQL client absence must be checked in the live process')
    require(isinstance(ssl_runtime.get('python_version'), str) and
            re.match(r'^3\.12\.\d+(?:\s|$)', ssl_runtime['python_version']), 'Observed CPython 3.12 runtime required')
    executable = PureWindowsPath(ssl_runtime['python_executable'])
    base_prefix = PureWindowsPath(ssl_runtime['base_prefix'])
    system_directory = PureWindowsPath(ssl_runtime['system_directory'])
    require(executable.is_absolute() and base_prefix.is_absolute() and system_directory.is_absolute() and
            '..' not in executable.parts and '..' not in base_prefix.parts and
            '..' not in system_directory.parts and system_directory.name.lower() == 'system32' and
            executable.name.lower() == 'python.exe',
            'Actual Windows Python runtime paths required')
    openssl = ssl_runtime['openssl_version']
    require(type(openssl.get('number')) is int and openssl['number'] >= 0x30000000 and
            isinstance(openssl.get('text'), str) and re.match(r'^OpenSSL [0-9]+\.', openssl['text']),
            'Actual Python OpenSSL runtime version required')
    modules = ssl_runtime['loaded_modules']
    require(isinstance(modules, list) and modules, 'Actual mapped Python SSL modules required')
    observed = set()
    support = {'vcruntime140.dll', 'vcruntime140_1.dll', 'ucrtbase.dll'}
    for module in modules:
        path = PureWindowsPath(module['loaded_path'])
        name = module['name']
        require(isinstance(name, str), 'Mapped module name invalid')
        allowed = path.is_relative_to(base_prefix) or (name.casefold() in support and
                                                      path.parent == system_directory)
        require(path.is_absolute() and '..' not in path.parts and allowed and
                path.name == name and path.suffix.lower() in ('.dll', '.pyd') and
                valid_hash(module['sha256']), 'Mapped Python SSL module path/hash invalid')
        if name.casefold() in ('_ssl.pyd', 'python312.dll') or name.lower().startswith(('libssl', 'libcrypto')):
            require(path.is_relative_to(base_prefix), 'Required Python SSL module outside Python base')
        require(name.casefold() not in observed, 'Duplicate mapped Python SSL module')
        observed.add(name.casefold())
        require('file_version' in module and (module['file_version'] is None or
                re.fullmatch(r'[0-9]+(?:\.[0-9]+){3}', module['file_version'])),
                'Invalid Windows module version resource')
        require(not any(token in name.lower() for token in ('psycopg', 'libpq')),
                'Native PostgreSQL client module loaded')
    require(observed.issuperset({'_ssl.pyd', 'python312.dll'}) and
            sum(name.startswith('libssl') and name.endswith('.dll') for name in observed) == 1 and
            sum(name.startswith('libcrypto') and name.endswith('.dll') for name in observed) == 1,
            'Actual Python SSL extension/runtime/dependency observations missing')

    return ssl_runtime


def validate_restore_scope(item, counts):
    """Require complete source provenance and the exact one-row deferred import."""
    expected = {'source_rows': 4100, 'source_tables': 37, 'imported_rows': 4099,
                'imported_tables': 36, 'deferred_rows': 1, 'populated_tables': 37}
    require(all(type(item.get(k)) is int and item[k] == v for k, v in expected.items()),
            'Exact deferred restore cardinalities required')
    require(item.get('synthetic_only') is True and item.get('populated_tables_meaning') == 'source',
            'Synthetic source table coverage required')
    require(item.get('deferred_source_rows') == {'push_subscription': [1]} and
            type(item['deferred_source_rows']['push_subscription'][0]) is int,
            'Only source push_subscription ID 1 may be deferred')
    require(isinstance(counts, dict) and len(counts) == 62 and
            all(type(v) is int and v >= 0 for v in counts.values()) and
            sum(v > 0 for v in counts.values()) == 37 and sum(counts.values()) == 4100 and
            counts.get('push_subscription') == 1 and item.get('source_counts') == counts,
            'Full source cardinalities required')
    imports = dict(counts, push_subscription=0)
    require(item.get('import_counts') == imports and
            all(type(v) is int for v in item['import_counts'].values()),
            'Exact deferred import counts required')
    require(all(item.get(k) is True for k in ('deferred_source_fixture_retained',
                'push_subscription_rows_unchanged', 'push_subscription_sequence_unchanged')),
            'Deferred source and existing push preservation proof required')
    require(not any(k in item for k in ('push_subscription_ids_remapped',
                                       'all_source_values_and_blobs_match')),
            'Legacy remap/all-source import proof forbidden')


# Exact mandatory coverage for this candidate, including formal inspect and preservation.
REQUIRED_ACCEPTANCE_IDS = frozenset("""
test_readonly_reconciliation.PostgreSQLReadOnlyReconciliationAcceptance.test_after_commit_outcome_loss_keeps_full_legacy_verify_and_sequences_equal
test_readonly_reconciliation.PostgreSQLReadOnlyReconciliationAcceptance.test_before_commit_disconnect_keeps_full_legacy_plan_and_sequences_equal
test_readonly_reconciliation.ReadOnlyObservationTests.test_actual_sqlalchemy_absorbed_terminate_error_is_captured
test_readonly_reconciliation.ReadOnlyObservationTests.test_bundle_rejects_malformed_incomplete_secret_and_counter_mutations
test_readonly_reconciliation.ReadOnlyObservationTests.test_bundle_rejects_reordered_phases_and_unfinished_query
test_readonly_reconciliation.ReadOnlyObservationTests.test_clean_bundle_exact_files_and_nested_phase_order
test_readonly_reconciliation.ReadOnlyObservationTests.test_cleanup_only_pool_failure_never_allows_success
test_readonly_reconciliation.ReadOnlyObservationTests.test_mandatory_journal_failure_preserves_primary_and_still_runs_cleanup
test_readonly_reconciliation.ReadOnlyObservationTests.test_observer_removal_errors_restore_logger_and_keep_original_primary
test_readonly_reconciliation.ReadOnlyObservationTests.test_pid_never_retains_cancel_key_and_sqlstate_is_whitelisted
test_readonly_reconciliation.ReadOnlyObservationTests.test_primary_and_swallowed_pool_cleanup_are_separate_secret_free
test_readonly_reconciliation.ReadOnlySequenceTests.test_batch_failure_propagates_once_no_partial_result
test_readonly_reconciliation.ReadOnlySequenceTests.test_complete_state_shape_and_bounded_16_value_reads
test_readonly_reconciliation.ReadOnlySequenceTests.test_context_binds_original_and_restores_on_success_and_failure
test_readonly_reconciliation.ReadOnlySequenceTests.test_context_rejects_lock_other_connection_nested_changed_function_and_hash
test_readonly_reconciliation.ReadOnlySequenceTests.test_legacy_source_pin_and_no_production_changes
test_readonly_reconciliation.ReadOnlySequenceTests.test_original_sequence_guards_and_nonserial_keys_remain
test_readonly_reconciliation.ReadOnlySequenceTests.test_readonly_repeatable_read_is_required_and_request_limit_is_bounded
test_readonly_reconciliation.ReadOnlySequenceTests.test_transaction_swap_fails_after_every_read_no_retry
test_readonly_reconciliation.ReadOnlySequenceTests.test_unknown_metadata_and_ownership_fail_before_values
test_readonly_reconciliation.ReadOnlySequenceTests.test_value_results_are_order_independent_and_exact_typed
test_restore_execute_budget.ExecuteBudgetTests.test_effective_search_path_formatting_keeps_exact_schema_order_and_limits
test_restore_completed_reconciliation.CompletedReconciliationTests.test_absent_exact_requires_new_inspection_and_preserves_all_bytes
test_restore_completed_reconciliation.CompletedReconciliationTests.test_all_original_and_proof_files_required_for_both_outcomes
test_restore_completed_reconciliation.CompletedReconciliationTests.test_cannot_inject_present_mode_into_begin_attempt
test_restore_completed_reconciliation.CompletedReconciliationTests.test_every_present_result_required_field_is_required
test_restore_completed_reconciliation.CompletedReconciliationTests.test_mixed_unknown_cleanup_or_incomplete_result_refuses
test_restore_completed_reconciliation.CompletedReconciliationTests.test_nonzero_unknown_and_wrong_type_exit_refuse_stale_positive_before_parse
test_restore_completed_reconciliation.CompletedReconciliationTests.test_partial_duplicate_nonfinite_and_missing_result_refuse
test_restore_completed_reconciliation.CompletedReconciliationTests.test_present_branch_rejects_modified_prior_and_journal_bindings
test_restore_completed_reconciliation.CompletedReconciliationTests.test_present_exact_never_authorizes_existing_begin_attempt
test_restore_completed_reconciliation.CompletedReconciliationTests.test_unbound_expected_schema_cannot_authorize_transition
test_restore_execute_budget.ExecuteBudgetTests.test_generic_and_readonly_connection_defaults_remain_300s
test_restore_execute_budget.ExecuteBudgetTests.test_execute_local_limits_precede_lock_and_no_work_when_lock_refused
test_restore_execute_budget.ExecuteBudgetTests.test_missing_transaction_fails_before_settings_or_lock
test_restore_execute_budget.ExecuteBudgetTests.test_any_local_setting_failure_stops_once_without_lock_or_retry
test_restore_execute_budget.PostgreSQLExecuteBudgetAcceptance.test_actual_cli_execute_startup_and_local_budget_are_900s
test_restore_execute_budget.PostgreSQLExecuteBudgetAcceptance.test_actual_cli_inspect_verify_and_reconciliation_default_remain_300s
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
test_inspect_observation.ObservationEdgeTests.test_cleanup_runs_despite_persist_failure_without_primary
test_inspect_observation.ObservationEdgeTests.test_cli_rejects_unsealed_helpers_before_import
test_inspect_observation.ObservationEdgeTests.test_cursor_iterator_and_context_manager_contract
test_inspect_observation.ObservationEdgeTests.test_explicit_capture_survives_persist_failure
test_inspect_observation.ObservationEdgeTests.test_hostile_attribute_does_not_replace_error
test_inspect_observation.ObservationEdgeTests.test_logging_failure_cannot_skip_cleanup_or_mask_primary
test_inspect_observation.ObservationTests.test_atomic_snapshot_failure_does_not_reopen_old_attempt
test_inspect_observation.ObservationTests.test_cleanup_only_not_primary_or_stale_query
test_inspect_observation.ObservationTests.test_connect_start_not_tls_or_startup
test_inspect_observation.ObservationTests.test_dbapi_success_pid_only_no_extra_calls
test_inspect_observation.ObservationTests.test_error_graph_cycle_and_secret_omission
test_inspect_observation.ObservationTests.test_events_bounded_monotonic_and_durable_before_body
test_inspect_observation.ObservationTests.test_execute_failure_not_fetch
test_inspect_observation.ObservationTests.test_fetch_failure_retains_original_query_category
test_inspect_observation.ObservationTests.test_forwarding_execute_fetch_exact_args_results
test_inspect_observation.ObservationTests.test_graph_bounded
test_inspect_observation.ObservationTests.test_partial_persist_keeps_previous_valid_record
test_inspect_observation.ObservationTests.test_primary_frozen_cleanup_separate_and_exception_precedence
test_inspect_observation.ObservationTests.test_private_distinct_attempts
test_inspect_observation.ObservationTests.test_strict_launcher_roundtrip_and_extra_field_rejection
test_inspect_observation.ObservationTests.test_unknown_error_and_invalid_codes
test_preservation_scope.PostgreSQLPreservationScopeTests.test_pg_each_required_projection_mutation_is_rejected
test_preservation_scope.PostgreSQLPreservationScopeTests.test_pg_unrelated_business_change_preserves_plan
test_preservation_scope.PostgreSQLPreservationScopeTests.test_pg_unrelated_primary_key_collision_still_rejected
test_preservation_scope.PreservationScopeTests.test_all_global_and_push_rows_are_protected
test_preservation_scope.PreservationScopeTests.test_audit_import_exclusion_preserves_existing_worlex_audit
test_preservation_scope.PreservationScopeTests.test_contract_is_explicit_serializable_six_table_scope
test_preservation_scope.PreservationScopeTests.test_every_protected_column_change_is_detected
test_preservation_scope.PreservationScopeTests.test_exact_six_queries_and_exact_itc_selection
test_preservation_scope.PreservationScopeTests.test_invalid_audit_ids_fail_before_any_query
test_preservation_scope.PreservationScopeTests.test_keyless_duplicate_rows_are_not_collapsed
test_preservation_scope.PreservationScopeTests.test_missing_table_or_selector_fails_before_any_query
test_preservation_scope.PreservationScopeTests.test_null_changes_in_nonselector_columns_are_protected
test_preservation_scope.PreservationScopeTests.test_unrelated_business_and_non_itc_rows_are_out_of_scope
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
test_restore_ci_validator.IsolatedValidatorTests.test_actual_callers_accept_in_fresh_stdlib_processes
test_restore_ci_validator.IsolatedValidatorTests.test_actual_callers_reject_summary_tampering
test_restore_ci_validator.IsolatedValidatorTests.test_actual_callers_reject_unsafe_contract_sources
test_restore_client_bootstrap.BootstrapReview.test_arbitrary_target_rejected
test_restore_client_bootstrap.BootstrapReview.test_bootstrap_hash_mismatch_rejected
test_restore_client_bootstrap.BootstrapReview.test_cli_gate_appears_before_engine_connection
test_restore_client_bootstrap.BootstrapReview.test_cli_gate_executes_exact_guard
test_restore_client_bootstrap.BootstrapReview.test_cli_gate_refuses_unsealed_policy
test_restore_client_bootstrap.BootstrapReview.test_cli_gate_refuses_wrong_guard_hash
test_restore_client_bootstrap.BootstrapReview.test_fixed_core_target_after_guard
test_restore_client_bootstrap.BootstrapReview.test_fixed_launcher_target_after_guard
test_restore_client_bootstrap.BootstrapReview.test_guard_hash_mismatch_rejected_before_import
test_restore_client_bootstrap.BootstrapReview.test_guard_stop_does_not_run_target
test_restore_client_bootstrap.BootstrapReview.test_missing_sidecar_stops_before_target
test_restore_client_bootstrap.BootstrapReview.test_parent_client_import_does_not_pollute_fresh_bootstrap
test_restore_client_bootstrap.BootstrapReview.test_preimported_client_rejected
test_restore_client_bootstrap.BootstrapReview.test_real_nonisolated_interpreter_rejected
test_restore_client_cli.ClientCLITests.test_execute_uses_exact_database_plan_after_runtime_check
test_restore_client_cli.ClientCLITests.test_inspect_binds_runtime_and_starts_readonly
test_restore_client_cli.ClientCLITests.test_runtime_change_stops_before_connect_or_marker
test_restore_client_cli.ClientCLITests.test_verify_uses_original_plan_readonly_no_execute
test_restore_client_connection.ConnectionTests.test_execute_has_no_readonly_override_or_plaintext_flag
test_restore_client_connection.ConnectionTests.test_invalid_ca_does_not_fallback
test_restore_client_connection.ConnectionTests.test_read_only_is_connection_startup_setting
test_restore_client_connection.ConnectionTests.test_safe_sqlstate_never_returns_detail_or_secret
test_restore_client_connection.ConnectionTests.test_timeout_and_application_overrides_fail_closed
test_restore_client_connection.ConnectionTests.test_tls_context_requires_ca_and_hostname
test_restore_client_runtime.ClientRuntimeTests.test_actual_runtime_module_observation_contract
test_restore_client_runtime.ClientRuntimeTests.test_all_tls_negatives_and_runtime_proof_required
test_restore_client_runtime.ClientRuntimeTests.test_candidate_commit_mismatch_rejected
test_restore_client_runtime.ClientRuntimeTests.test_code_hash_and_old_native_seal_rejected
test_restore_client_runtime.ClientRuntimeTests.test_deferred_ci_scope_matches_runtime_contract
test_restore_client_runtime.ClientRuntimeTests.test_deferred_counts_and_legacy_fields_rejected
test_restore_client_runtime.ClientRuntimeTests.test_deferred_scope_rejects_old_import_and_wrong_deferred_identity
test_restore_client_runtime.ClientRuntimeTests.test_extra_modified_and_native_payload_rejected
test_restore_client_runtime.ClientRuntimeTests.test_full_values_and_disconnect_proof_required
test_restore_client_runtime.ClientRuntimeTests.test_native_magic_hidden_under_text_extension_rejected
test_restore_client_runtime.ClientRuntimeTests.test_outside_imported_module_rejected
test_restore_client_runtime.ClientRuntimeTests.test_path_aliases_and_casefold_collision_rejected
test_restore_client_runtime.ClientRuntimeTests.test_provider_shape_distinguishes_builtin_extension_unknown
test_restore_client_runtime.ClientRuntimeTests.test_push_preservation_required_in_every_runtime_proof
test_restore_client_runtime.ClientRuntimeTests.test_runtime_forbids_native_postgres_driver
test_restore_client_runtime.ClientRuntimeTests.test_runtime_rejects_duplicate_tls_module
test_restore_client_runtime.ClientRuntimeTests.test_runtime_rejects_external_tls_module
test_restore_client_runtime.ClientRuntimeTests.test_runtime_requires_each_tls_module
test_restore_client_runtime.ClientRuntimeTests.test_runtime_support_dll_allowed_only_in_base_or_real_system
test_restore_client_runtime.ClientRuntimeTests.test_valid_pure_manifest_and_imported_modules
test_restore_client_runtime.ClientRuntimeTests.test_wheel_provenance_and_distribution_version_rejected
test_restore_client_runtime.ClientRuntimeTests.test_wrong_platform_and_unsealed_policy_rejected
test_restore_collision_batch.CollisionBatchTests.test_baseline_pin_and_exact_change_scope
test_restore_collision_batch.CollisionBatchTests.test_batch_first_middle_last_collision_original_order
test_restore_collision_batch.CollisionBatchTests.test_caps_branches_and_bind_parameters
test_restore_collision_batch.CollisionBatchTests.test_catalog_failure_scope_guards_unchanged
test_restore_collision_batch.CollisionBatchTests.test_chunk_sizes_zero_one_499_500_501_2571
test_restore_collision_batch.CollisionBatchTests.test_compilation_binding_unicode_uuid_date_binary_decimal
test_restore_collision_batch.CollisionBatchTests.test_composite_key_respects_full_tuple
test_restore_collision_batch.CollisionBatchTests.test_diagnostic_allowlist_new_statements_and_denials
test_restore_collision_batch.CollisionBatchTests.test_different_column_order_not_deduplicated
test_restore_collision_batch.CollisionBatchTests.test_disconnect_during_flush_before_invalid_source_not_retried
test_restore_collision_batch.CollisionBatchTests.test_disconnect_not_retried_or_replaced_with_fallback
test_restore_collision_batch.CollisionBatchTests.test_duplicate_constraint_backing_index_one_probe
test_restore_collision_batch.CollisionBatchTests.test_duplicate_missing_or_extra_ordinal_same_length_fails
test_restore_collision_batch.CollisionBatchTests.test_empty_no_unique_no_extra_call
test_restore_collision_batch.CollisionBatchTests.test_empty_rows_skip_catalog_and_probe
test_restore_collision_batch.CollisionBatchTests.test_full_count_synthetic_fixture_query_reduction
test_restore_collision_batch.CollisionBatchTests.test_invalid_later_duplicate_metadata_still_rejected
test_restore_collision_batch.CollisionBatchTests.test_itc_and_other_tenant_global_unique_collisions
test_restore_collision_batch.CollisionBatchTests.test_later_source_invalid_flushes_earlier_target_collision
test_restore_collision_batch.CollisionBatchTests.test_later_unsupported_index_preserves_earlier_target_precedence
test_restore_collision_batch.CollisionBatchTests.test_malformed_result_shapes_rejected
test_restore_collision_batch.CollisionBatchTests.test_no_result_cache_across_calls_or_connections
test_restore_collision_batch.CollisionBatchTests.test_null_keys_skipped_without_changing_null_policy
test_restore_collision_batch.CollisionBatchTests.test_partial_metadata_not_used_to_hide_collision
test_restore_collision_batch.CollisionBatchTests.test_reordered_valid_result_rows_are_matched_by_ordinal
test_restore_collision_batch.CollisionBatchTests.test_same_columns_different_partial_metadata_checked
test_restore_collision_batch.CollisionBatchTests.test_same_transaction_required_before_and_after_query
test_restore_collision_batch.CollisionBatchTests.test_single_oversize_probe_fails_closed
test_restore_collision_batch.CollisionBatchTests.test_single_probe_bind_cap_fails_closed
test_restore_collision_batch.CollisionBatchTests.test_source_and_target_uniqueness_guards
test_restore_collision_batch.CollisionBatchTests.test_sql_byte_cap_is_applied
test_restore_collision_batch.CollisionBatchTests.test_tenant_alias_pk_uuid_itc_guards_unchanged
test_restore_collision_evidence.CollisionEvidenceTests.test_all_execution_and_seal_routes_call_shared_validator
test_restore_collision_evidence.CollisionEvidenceTests.test_altered_collision_metrics_and_boolean_proofs_rejected
test_restore_collision_evidence.CollisionEvidenceTests.test_complete_synthetic_schema_is_accepted_without_claiming_live_proof
test_restore_collision_evidence.CollisionEvidenceTests.test_contract_and_oracles_are_hashed_and_missing_or_altered_rejected
test_restore_collision_evidence.CollisionEvidenceTests.test_every_catalog_map_proof_is_required
test_restore_collision_evidence.CollisionEvidenceTests.test_every_collision_field_is_required
test_restore_collision_evidence.CollisionEvidenceTests.test_missing_or_duplicate_mandatory_id_rejected
test_restore_collision_evidence.CollisionEvidenceTests.test_old_139_case_evidence_cannot_pass
test_restore_collision_evidence.CollisionEvidenceTests.test_stale_hash_counts_and_incomplete_runs_rejected
test_restore_full_fixture.FullSyntheticFixtureCoverage.test_all_24_source_blobs_are_nonempty_and_hash_verified
test_restore_full_fixture.FullSyntheticFixtureCoverage.test_all_37_primary_keys_are_present_and_unique
test_restore_full_fixture.FullSyntheticFixtureCoverage.test_all_required_columns_lengths_and_typed_values
test_restore_full_fixture.FullSyntheticFixtureCoverage.test_broken_reference_is_rejected_for_each_represented_fk
test_restore_full_fixture.FullSyntheticFixtureCoverage.test_count_drift_is_rejected_for_each_declared_source_table
test_restore_full_fixture.FullSyntheticFixtureCoverage.test_every_represented_fk_is_populated_closed_and_ordered
test_restore_full_fixture.FullSyntheticFixtureCoverage.test_every_source_value_is_preserved_except_documented_transformations
test_restore_full_fixture.FullSyntheticFixtureCoverage.test_historical_accounts_are_not_rebound_and_generated_ids_replay
test_restore_full_fixture.FullSyntheticFixtureCoverage.test_legacy_acceptance_anchors_and_vehicle_state_counts_remain
test_restore_full_fixture.FullSyntheticFixtureCoverage.test_matches_every_approved_source_count_including_empty_tables
test_restore_full_fixture.FullSyntheticFixtureCoverage.test_primary_key_corruption_is_rejected_in_every_populated_table
test_restore_full_fixture.FullSyntheticFixtureCoverage.test_sqlite_all_rows_insert_with_fk_checks_and_preserved_values
test_restore_full_fixture.FullSyntheticFixtureCoverage.test_synthetic_copy_roundtrip_covers_all_62_tables
test_restore_insert_batch.InsertBatchTests.test_all_typed_values_and_explicit_ids_match_original_dbapi_order
test_restore_insert_batch.InsertBatchTests.test_bind_budget_exact_boundary_and_wider_rows
test_restore_insert_batch.InsertBatchTests.test_bytea_hex_expansion_and_utf8_are_measured_not_python_lengths
test_restore_insert_batch.InsertBatchTests.test_compiled_sql_budget_splits_and_rejects_oversized_singleton
test_restore_insert_batch.InsertBatchTests.test_compiler_shape_drift_fails_closed
test_restore_insert_batch.InsertBatchTests.test_eight_mib_singleton_boundary_is_enforced
test_restore_insert_batch.InsertBatchTests.test_exact_four_mib_multirow_and_next_byte_split
test_restore_insert_batch.InsertBatchTests.test_exact_four_mib_singleton_and_oversized_row_are_isolated
test_restore_insert_batch.InsertBatchTests.test_fixed_limits_and_execute_only_900s_transaction_budget
test_restore_insert_batch.InsertBatchTests.test_full_synthetic_source_dispatch_preserves_table_and_row_order
test_restore_insert_batch.InsertBatchTests.test_middle_batch_error_propagates_once_without_retry
test_restore_insert_batch.InsertBatchTests.test_missing_extra_or_mixed_columns_rejected_without_dispatch
test_restore_insert_batch.InsertBatchTests.test_missing_primary_key_and_nonprimitive_values_fail_closed
test_restore_insert_batch.InsertBatchTests.test_missing_unknown_and_replaced_adapter_entries_are_rejected
test_restore_insert_batch.InsertBatchTests.test_real_on_connect_initialization_is_required_and_exact_map_accepted
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
test_restore_launcher_adapter.LauncherAdapterTests.test_exclusive_result_and_failed_persistence_stop_progression
test_restore_launcher_adapter.LauncherAdapterTests.test_new_attempt_requires_immediate_stop_active_inputs_and_unique_directory
test_restore_launcher_adapter.LauncherAdapterTests.test_safe_observation_roundtrip_persisted_without_secrets
test_restore_launcher_adapter.LauncherAdapterTests.test_unknown_observation_fields_and_missing_observation_fail_closed
test_restore_observation_acceptance.DeterministicCatalogInputTests.test_actual_catalog_sql_and_binds_equal_for_reordered_input
test_restore_observation_acceptance.DeterministicCatalogInputTests.test_changed_missing_extra_identity_remains_visible
test_restore_observation_acceptance.DeterministicCatalogInputTests.test_exact_trace_comparison_rejects_sql_bind_order_and_count_changes
test_restore_observation_acceptance.DeterministicCatalogInputTests.test_wrapper_forwards_once_without_sql_or_row_replacement
test_restore_observation_acceptance.DeterministicCatalogInputTests.test_wrapper_rejects_duplicates_invalid_oids_and_names
test_restore_observation_acceptance.PostgreSQLObservationAcceptance.test_formal_cli_degraded_diagnostics_same_read_only_plan_and_terminal
test_restore_observation_acceptance.PostgreSQLObservationAcceptance.test_formal_cli_observation_roundtrip_and_canonical_plan
test_restore_observation_acceptance.PostgreSQLObservationAcceptance.test_formal_cli_required_plan_report_adapter_and_execute_marker_still_block
test_restore_observation_acceptance.PostgreSQLObservationAcceptance.test_formal_cli_server_error_after_degradation_stays_primary
test_restore_observation_acceptance.PostgreSQLObservationAcceptance.test_formal_cli_server_error_preserved_before_cleanup_no_reconnect
test_restore_observation_acceptance.PostgreSQLObservationAcceptance.test_instrumentation_preserves_exact_sql_binds_and_connection_count
test_restore_observation_acceptance.PostgreSQLObservationAcceptance.test_locked_context_rejects_other_connection_and_stale_transaction
test_restore_postgres.PostgreSQLRestoreAcceptance.test_audit_baseline_change_between_inspection_and_execution_stops
test_restore_postgres.PostgreSQLRestoreAcceptance.test_audit_ids_are_never_rewritten_to_hide_a_collision
test_restore_postgres.PostgreSQLRestoreAcceptance.test_case_alias_is_rejected
test_restore_postgres.PostgreSQLRestoreAcceptance.test_catalog_maps_match_original_full_fixture
test_restore_postgres.PostgreSQLRestoreAcceptance.test_catalog_preflight_reduces_real_full_fixture_queries
test_restore_postgres.PostgreSQLRestoreAcceptance.test_changed_schema_is_rejected
test_restore_postgres.PostgreSQLRestoreAcceptance.test_collision_batch_real_cross_tenant_conflicts_match_sequential
test_restore_postgres.PostgreSQLRestoreAcceptance.test_commit_preserves_rows_blobs_ownership_and_sequence_next_insert
test_restore_postgres.PostgreSQLRestoreAcceptance.test_disconnect_after_commit_reconciles_without_reinserting
test_restore_postgres.PostgreSQLRestoreAcceptance.test_disconnect_before_commit_rolls_back_all_imported_tables_and_sequences
test_restore_postgres.PostgreSQLRestoreAcceptance.test_existing_one_audit_and_all_423_source_audits_survive
test_restore_postgres.PostgreSQLRestoreAcceptance.test_full_count_fixture_all_tables_constraints_and_preservation
test_restore_postgres.PostgreSQLRestoreAcceptance.test_more_than_one_existing_worlex_audit_is_rejected
test_restore_postgres.PostgreSQLRestoreAcceptance.test_pk_conflict_is_rejected_before_insert
test_restore_postgres.PostgreSQLRestoreAcceptance.test_push_endpoint_and_id_collision_defers_source_and_preserves_all_values
test_restore_postgres.PostgreSQLRestoreAcceptance.test_push_without_collision_is_still_deferred_without_owner_rebinding
test_restore_postgres.PostgreSQLRestoreAcceptance.test_raw_deferred_source_mutation_is_rejected_with_unchanged_source_hash
test_restore_postgres.PostgreSQLRestoreAcceptance.test_read_only_reconciliation_and_modified_payload_rejected
test_restore_postgres.PostgreSQLRestoreAcceptance.test_real_synthetic_login_and_primary_pages
test_restore_postgres.PostgreSQLRestoreAcceptance.test_replay_is_rejected
test_restore_postgres.PostgreSQLRestoreAcceptance.test_rollback_after_sequences_restores_rows_column_triggers_and_sequences
test_restore_postgres.PostgreSQLRestoreAcceptance.test_rollback_keeps_existing_audit_and_original_sequence
test_restore_postgres.PostgreSQLRestoreAcceptance.test_second_connection_is_rejected
test_restore_postgres.PostgreSQLRestoreAcceptance.test_sequence_batch_lock_preserves_push_and_value_order
test_restore_postgres.PostgreSQLRestoreAcceptance.test_sequence_batch_matches_original_and_reduces_queries
test_restore_postgres.PostgreSQLRestoreAcceptance.test_unapproved_existing_audit_is_not_allowed
test_restore_postgres.PostgreSQLRestoreAcceptance.test_unsealed_policy_is_rejected
test_restore_postgres.PostgreSQLRestoreAcceptance.test_verified_restore_detects_additional_unplanned_audit
test_restore_postgres.PostgreSQLRestoreAcceptance.test_verified_restore_detects_changes_to_preserved_audit
test_restore_postgres.PostgreSQLRestoreAcceptance.test_verified_restore_detects_preserved_push_value_mutation
test_restore_postgres.PostgreSQLRestoreAcceptance.test_verified_restore_detects_push_sequence_called_mutation
test_restore_postgres.PostgreSQLRestoreAcceptance.test_verified_restore_detects_push_sequence_catalog_mutation
test_restore_postgres.PostgreSQLRestoreAcceptance.test_verified_restore_detects_push_sequence_last_value_mutation
test_restore_postgres.ServiceGuardTests.test_app_config_rejects_non_ci_destinations_before_context_creation
test_restore_postgres.ServiceGuardTests.test_app_config_uses_explicit_context_without_libpq_environment
test_restore_postgres.ServiceGuardTests.test_dedicated_service_and_rejections
test_restore_postgres.ServiceGuardTests.test_missing_explicit_ca_fails_closed
test_restore_postgres.ServiceGuardTests.test_tls_check_requires_verified_pg8000_socket
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
test_restore_schema_diagnostics.SchemaDiagnosticsTests.test_child_reporting_failure_preserves_exit_and_does_not_retry
test_restore_schema_diagnostics.SchemaDiagnosticsTests.test_graph_cycles_and_truncation_are_bounded
test_restore_schema_diagnostics.SchemaDiagnosticsTests.test_parser_rejects_malformed_oversize_nonfinite_and_unknown_fields
test_restore_schema_diagnostics.SchemaDiagnosticsTests.test_partial_write_never_publishes_saved_evidence
test_restore_schema_diagnostics.SchemaDiagnosticsTests.test_reporting_failures_do_not_mask_original_or_retry
test_restore_schema_diagnostics.SchemaDiagnosticsTests.test_ssl_subclasses_and_primary_cleanup_edges_survive
test_restore_schema_diagnostics.SchemaDiagnosticsTests.test_strict_redaction_never_includes_messages_args_sql_or_paths
test_restore_schema_diagnostics.SchemaDiagnosticsTests.test_timeline_bound_and_legacy_v1_are_supported
test_restore_schema_diagnostics.SchemaDiagnosticsTests.test_timeline_partial_timeout_bytes_and_final_event_are_retained
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
test_restore_sequence_batch.SequenceBatchDifferential.test_all_differential_guards
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_allowlisted_events_have_synthetic_correlation
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_atomic_publish_failure_keeps_complete_old_file_and_removes_temp
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_callbacks_run_once_without_retries_or_extra_processes
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_cleanup_only_failure_propagates
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_collector_failure_never_masks_primary
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_diagnostics_failure_does_not_change_acceptance_gates
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_evidence_ancestor_symlink_is_rejected
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_evidence_target_symlink_is_rejected
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_invalid_timestamp_and_session_rejected
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_missing_log_explicit_status
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_oversize_input_and_output_are_bounded
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_owned_ancestor_symlink_is_rejected
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_owned_marker_and_log_hardlinks_are_rejected
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_partial_evidence_write_falls_back_without_masking_primary
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_partial_write_discarded
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_predictable_temp_symlink_is_never_opened
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_primary_cleanup_and_secrets_failure_recorded_separately
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_rare_failure_survives_later_connection_chatter
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_secrets_sql_urls_cancel_keys_and_data_never_copied
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_start_failure_still_collects_and_cleans_once
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_symlink_log_rejected
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_truncated_partial_and_omitted_snapshots_mark_incomplete
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_unknown_exception_class_never_leaks_name
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_unrecognized_records_have_counts_not_inferred_causes
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_windows_reparse_ancestor_metadata_is_rejected
test_restore_server_diagnostics.OwnedServerDiagnosticsTests.test_wrong_marker_and_outside_root_rejected
test_restore_unit.RestoreGuards.test_blob_hashes_are_sensitive_to_bytes_without_exposing_them
test_restore_unit.RestoreGuards.test_copy_decoding
test_restore_unit.RestoreGuards.test_counts_and_exact_states
test_restore_unit.RestoreGuards.test_deferred_mapping_rejects_other_tables_ids_counts_and_types
test_restore_unit.RestoreGuards.test_deferred_source_requires_one_id_one_tenant_and_unbound_owner
test_restore_unit.RestoreGuards.test_exactly_one_push_row_is_deferred_without_mutating_source
test_restore_unit.RestoreGuards.test_full_synthetic_fixture_matches_pinned_schema
test_restore_unit.RestoreGuards.test_malformed_and_duplicate_copy_are_blocked
test_restore_unit.RestoreGuards.test_payload_count_tenant_and_numeric_id_guards
test_restore_unit.RestoreGuards.test_render_environment_preserves_only_windows_runtime_paths
test_restore_unit.RestoreGuards.test_render_failure_classification_never_exposes_raw_details
test_restore_unit.RestoreGuards.test_safe_identifiers
test_restore_unit.RestoreGuards.test_tenant_filter_and_escapes
""".split())
COLLISION_REQUIRED_CASES = 32
POSTGRES_REQUIRED_CASES = 53


def _preservation_contract_from_source():
    """Read the reviewed literal without importing application dependencies.

    Builder and sealer parents have only the standard library. Resolve this
    checkout's source, never cwd/sys.path or a cached application module. The
    byte pin also rejects indirect mutation through globals(), exec or aliases
    that inspecting only AST Name nodes could not rule out.
    """
    source = Path(__file__).resolve().parents[2] / 'preservation_scope.py'
    require(source.is_file() and not source.is_symlink(),
            'Reviewed preservation source missing or unsafe')
    try:
        content = source.read_bytes()
        tree = ast.parse(content, filename='preservation_scope.py')
        bindings = [node for node in tree.body if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and
                            target.id == 'PRESERVATION_CONTRACT' for target in node.targets)]
        names = [node for node in ast.walk(tree) if isinstance(node, ast.Name)
                 and node.id == 'PRESERVATION_CONTRACT']
        require(len(bindings) == len(names) == 1 and len(bindings[0].targets) == 1,
                'One unmodified literal preservation contract required')
        contract = ast.literal_eval(bindings[0].value)
    except (OSError, SyntaxError, ValueError, TypeError) as error:
        raise ValueError('Invalid reviewed preservation contract source') from error
    require(isinstance(contract, dict), 'Preservation contract dictionary required')
    require(hashlib.sha256(content).hexdigest() ==
            '7b8038196a3be17ba8bfbd84c16cec30ce03de77e97827c5e372b69a40e6ac66',
            'Reviewed preservation source hash differs')
    return contract


BOUNDED_INSERT_CASES = ('full-size', 'middle_insert_batch', 'actual-third-batch-error',
                        'after_sequences', 'disconnect-before-commit', 'disconnect-after-commit')


def validate_bounded_insert(evidence):
    """Require actual full-size PG receipts in each OS's mandatory suite."""
    require(isinstance(evidence, dict) and set(evidence) == set(BOUNDED_INSERT_CASES),
            'Full-size bounded INSERT cases missing')
    envelope = {'source_rows': 4100, 'imported_rows': 4099, 'blob_values': 24,
                'blob_bytes': 15189518, 'encoded_parameter_bytes': 60968018}
    partial = {'middle_insert_batch', 'actual-third-batch-error'}
    for name, item in evidence.items():
        require(isinstance(item, dict) and item.get('synthetic_only') is True and
                item.get('actual_postgres_18') is True and item.get('envelope') == envelope and
                all(type(item['envelope'].get(k)) is int for k in envelope),
                'Actual synthetic PG size envelope missing')
        dispatch = item.get('insert_dispatch')
        require(isinstance(dispatch, list) and 0 < len(dispatch) < 150,
                'Bounded INSERT dispatch proof missing')
        for batch in dispatch:
            require(isinstance(batch, dict) and isinstance(batch.get('table'), str) and
                    batch.get('executemany') is False and batch.get('returning') is False and
                    batch.get('explicit_multi_values') is True, 'Explicit INSERT-only dispatch required')
            for key, maximum in (('rows',100), ('binds',8000), ('sql_bytes',131072),
                                 ('parameter_bytes',8388608 if batch.get('rows') == 1 else 4194304)):
                require(type(batch.get(key)) is int and 0 < batch[key] <= maximum,
                        'Bounded INSERT limit exceeded: ' + key)
        if name in partial:
            require(len(dispatch) > 2 and sum(b['table'] == 'vehicle_operation_record' for b in dispatch) == 2,
                    'Rollback must follow two successful split-table batches')
        else:
            require(sum(b['rows'] for b in dispatch) == 4099 and
                    len({b['table'] for b in dispatch}) == 36 and
                    sum(b['parameter_bytes'] for b in dispatch) == 60968018 and
                    sum(b['parameter_bytes'] > 4194304 for b in dispatch) == 5,
                    'Full-size bounded INSERT cardinality or bytes differ')
    full = evidence['full-size']
    require(all(full.get(k) is True for k in ('exact_all_imported_values_and_blobs',
                'preserved_itc_settings_audit_push', 'deferred_source_retained')),
            'Full-size value or preservation verification missing')
    epochs = full.get('exact_epoch_revisions')
    require(isinstance(epochs, dict) and epochs and
            all(isinstance(k, str) and type(v) is int and v > 0 for k,v in epochs.items()) and
            sum(epochs.values()) == 3271, 'Exact per-row trigger revisions missing')
    for name in partial | {'after_sequences'}:
        item = evidence[name]
        require(all(item.get(k) is True for k in ('all_imports_absent', 'preserved_rows_match', 'sequences_unchanged')),
                'Full-size rollback verification missing')
    require(all(evidence[name].get('compatibility_column_rolled_back') is True
                for name in ('middle_insert_batch', 'after_sequences')),
            'Compatibility DDL rollback verification missing')
    error = evidence['actual-third-batch-error']
    require(error.get('actual_postgres_constraint_error') is True and
            error.get('target_table') == 'vehicle_operation_record' and
            type(error.get('attempted_target_batches')) is int and error['attempted_target_batches'] == 3 and
            type(error.get('successful_target_batches')) is int and error['successful_target_batches'] == 2 and
            error.get('restore_retried') is False, 'Actual middle-batch constraint failure/no-retry proof missing')
    before = evidence['disconnect-before-commit'].get('reconciliation', {})
    after = evidence['disconnect-after-commit'].get('reconciliation', {})
    require(all(before.get(k) is True for k in ('actual_connection_closed_before_commit',
                'all_imports_absent', 'preserved_rows_match', 'sequences_unchanged',
                'fresh_readonly_verification_rejects_absent_restore')) and
            before.get('restore_retried') is False, 'Full-size before-commit disconnect proof missing')
    require(all(after.get(k) is True for k in ('real_commit_then_client_error',
                'fresh_readonly_verification_matches', 'preserved_rows_match',
                'replay_guard_rejected_before_insert', 'sequences_unchanged_by_replay')) and
            after.get('network_packet_loss_reproduced') is False and
            evidence['disconnect-after-commit'].get('exact_epoch_revisions') == epochs,
            'Full-size after-commit reconciliation proof missing')


def validate_readonly_batch(evidence):
    """Both OS jobs must report actual fd22 read-only equality around commit."""
    require(type(evidence) is dict and set(evidence)=={'before_commit','after_commit'},
            'Actual readonly batching evidence required')
    for name, classification, outcome in (
            ('before_commit','absent','actual_close_before_commit'),
            ('after_commit','present','real_commit_before_outcome_loss')):
        value=evidence[name]
        required={'synthetic_only','actual_postgres_18','legacy_core_sha256',
            'complete_plan_or_verify_equal','complete_sequence_dict_equal',
            'preserved_itc_audit_settings_push_equal','same_readonly_transaction','actual_observer_pid_and_clean_bundle','sequences',
            'old_sequence_queries','new_sequence_queries','max_branches','max_sql_bytes',
            'restore_retried','classification',outcome}
        require(type(value) is dict and set(value)==required
                and value['legacy_core_sha256']=='fd22c4f29b566a0403da17d9b524ad8d6091a417d4ab9f2ca3788991eb2ba446'
                and all(value[k] is True for k in ('synthetic_only','actual_postgres_18',
                    'complete_plan_or_verify_equal','complete_sequence_dict_equal',
                    'preserved_itc_audit_settings_push_equal','same_readonly_transaction','actual_observer_pid_and_clean_bundle',outcome))
                and value['restore_retried'] is False and value['classification']==classification,
                'Readonly identity, equivalence or outcome proof invalid')
        require(all(type(value[k]) is int for k in ('sequences','old_sequence_queries','new_sequence_queries','max_branches','max_sql_bytes'))
                and 30<value['sequences']<=256 and value['max_branches']==16 and value['max_sql_bytes']==32768
                and value['old_sequence_queries']==value['sequences']+2
                and value['new_sequence_queries']==2+(value['sequences']+15)//16,
                'Readonly bounded value query proof invalid')


def validate_acceptance(summary):
    """Validate offline evidence structure only; this does not prove a live run."""
    require(isinstance(summary, dict), 'Acceptance summary missing')
    ids = summary.get('suite_ids')
    require(isinstance(ids, list) and all(isinstance(i, str) for i in ids) and
            len(ids) == len(set(ids)) and REQUIRED_ACCEPTANCE_IDS == set(ids),
            'Mandatory collision/full-suite test IDs missing or duplicated')
    require(summary.get('suite_ids_sha256') == hashlib.sha256(
            '\n'.join(sorted(ids)).encode()).hexdigest(), 'Acceptance suite ID hash differs')
    require(summary.get('postgres_required') is True and
            type(summary.get('expected')) is int and summary['expected'] >= len(REQUIRED_ACCEPTANCE_IDS) and
            summary['expected'] == len(ids) and type(summary.get('run')) is int and
            summary['run'] == summary['expected'] and
            all(type(summary.get(k)) is int and summary[k] == 0
                for k in ('failures', 'errors', 'skipped')), 'Full acceptance run incomplete')
    require(type(summary.get('catalog_required_cases')) is int and
            summary['catalog_required_cases'] == 36 and
            type(summary.get('collision_required_cases')) is int and
            summary['collision_required_cases'] == COLLISION_REQUIRED_CASES,
            'Required batching coverage counts differ')
    require(type(summary.get('postgres_cases')) is int and summary['postgres_cases'] == POSTGRES_REQUIRED_CASES,
            'Exact PostgreSQL coverage required')
    PRESERVATION_CONTRACT = _preservation_contract_from_source()
    require(summary.get('preservation_contract') == PRESERVATION_CONTRACT,
            'Current required preservation scope required')
    validate_bounded_insert(summary.get('bounded_insert'))
    validate_readonly_batch(summary.get('readonly_batch'))
    batching = summary.get('catalog_batching')
    require(isinstance(batching, dict), 'Actual PostgreSQL batching evidence missing')
    controls = batching.get('collision_controls')
    require(isinstance(controls, dict), 'Actual PostgreSQL collision controls missing')
    expected_controls = {
        'actual_postgresql': True,
        'implementations': ['sequential', 'batched'],
        'tenants': ['ITC', 'SYNTHETIC_OTHER'],
        'positions': ['first', 'middle', 'last'],
        'collision_cases': 6,
        'noncollision_cases': 6,
        'exact_outcomes_equal': True,
        'same_readonly_transaction': True,
        'preserved_rows_and_sequences_unchanged': True,
        'global_and_scoped_unique_keys_verified': True,
    }
    require(all(type(controls.get(k)) is type(v) and controls[k] == v
                for k, v in expected_controls.items()),
            'Actual PostgreSQL cross-tenant collision controls incomplete or changed')
    maps, preflight = batching.get('maps'), batching.get('preflight')
    require(isinstance(maps, dict) and maps.get('populated_import_tables') == 36 and
            all(maps.get(k) is True for k in ('exact_public_keys', 'unique_maps_equal',
                'index_maps_equal', 'ordered_combination_equal', 'preserved_state_unchanged')),
            'Actual PostgreSQL catalog equivalence evidence missing')
    expected = {'source_rows':4100, 'import_rows':4099, 'populated_import_tables':36,
        'old_catalog_execute_calls':108, 'prior_catalog_execute_calls':3,
        'new_catalog_execute_calls':3, 'old_application_execute_calls':159,
        'prior_application_execute_calls':159, 'new_application_execute_calls':112,
        'old_unique_probe_round_trips':49, 'new_unique_probe_round_trips':2,
        'distinct_unique_predicates':29}
    require(isinstance(preflight, dict) and all(type(preflight.get(k)) is int and
            preflight[k] == v for k, v in expected.items()),
            'Actual PostgreSQL collision query reduction evidence missing')
    require(all(preflight.get(k) is True for k in (
                'noncollision_application_queries_and_binds_equal',
                'distinct_unique_predicates_and_binds_equal', 'same_readonly_transaction',
                'preserved_state_unchanged', 'synthetic_only')) and
            preflight.get('network_disconnect_fix_proven') is False,
            'Collision semantic/transaction preservation evidence missing')
    for key, limit in (('collision_max_branches',16), ('collision_max_binds',8000),
                       ('collision_max_sql_bytes',131072)):
        require(type(preflight.get(key)) is int and 0 < preflight[key] <= limit,
                'Collision batch resource bound missing or exceeded: ' + key)


def acceptance_artifact_paths(root):
    root = Path(root)
    return [root / name for name in ('.gitattributes', 'worlex_restore.py', 'policy.json',
        'source-manifest.json', 'source-counts.json', 'client_runtime_guard.py',
        'client_bootstrap.py', 'client_connection.py', 'inspect_observation.py',
        'preservation_scope.py', 'launcher_adapter.py', 'readonly_reconciliation.py', 'tests/application_contract.json',
        'tests/windows-ci/client-build-inputs.json',
        'tests/fixtures/ci-summary-ef4899fe.json')] + sorted((root / 'tests').rglob('*.py')) + sorted((root / 'tests').rglob('*.sh'))


def validate_acceptance_artifacts(artifacts, root):
    root = Path(root)
    required = {p.relative_to(root).as_posix() for p in acceptance_artifact_paths(root)}
    require(isinstance(artifacts, dict) and set(artifacts) == required,
            'Full current acceptance artifact coverage required')
    for relative in required:
        safe_relative(relative)
        path = root / relative
        require(path.is_file() and not path.is_symlink() and
                path.resolve().is_relative_to(root.resolve()) and
                artifacts[relative] == sha(path), 'Acceptance artifact mismatch: ' + relative)


def validate_client(client, linux_policy, root, directory, commit):
    lock = json.loads((root / 'tests/windows-ci/client-build-inputs.json').read_text())
    require(client.get('schema_version') == 2 and client.get('passed') is True and
            client.get('actual_windows') is True and client.get('synthetic_only') is True,
            'Actual Windows synthetic pure-client proof required')
    require(client.get('client_profile') == 'pg8000-pure-python' and
            client.get('package_version') == '1.31.6', 'Approved pg8000 client identity required')
    require(not any(key in client for key in ('source_client', 'wheel', 'libpq_compile_version',
                                             'libpq_runtime_version', 'custom_wait_callback')),
            'Legacy native-client proof cannot seal a pure client')
    require(isinstance(commit, str) and re.fullmatch(r'[a-f0-9]{40}', commit) and
            client.get('candidate_commit') == commit, 'Windows client commit mismatch')
    require(client.get('runner_sha256') == sha(root / 'worlex_restore.py'), 'Windows client core mismatch')
    require(client.get('tested_artifacts') == linux_policy['tested_artifacts'], 'Linux/Windows code maps differ')
    require(client.get('workflow_sha256') == linux_policy['workflow_sha256'], 'Linux/Windows workflows differ')
    for relative in ('worlex_restore.py', 'client_runtime_guard.py', 'client_bootstrap.py',
                     'client_connection.py', 'inspect_observation.py', 'preservation_scope.py',
                     'launcher_adapter.py', 'tests/windows-ci/client-build-inputs.json'):
        require(client['tested_artifacts'].get(relative) == sha(root / relative),
                'Required client artifact hash mismatch: ' + relative)
    validate_acceptance_artifacts(client['tested_artifacts'], root)
    summary = client['acceptance_summary']
    require(summary == linux_policy['acceptance_summary'], 'Linux/Windows test coverage differs')
    validate_acceptance(summary)
    for key in ('full_table_acceptance', 'disconnect_acceptance'):
        require(client.get(key) == linux_policy.get(key), 'Linux/Windows acceptance evidence differs: ' + key)
    full = client['full_table_acceptance']
    counts = json.loads((root / 'source-counts.json').read_text())
    validate_restore_scope(full, counts)
    require(full.get('synthetic_only') is True and full.get('source_rows') == 4100 and
            full.get('populated_tables') == 37 and
            full.get('source_counts') == json.loads((root / 'source-counts.json').read_text()) and
            all(full.get(k) is True for k in ('imported_values_and_blobs_match', 'preserved_rows_match',
                                             'owner_bindings_quarantined')),
            'Full-table synthetic value/preservation proof required')
    disconnect = client['disconnect_acceptance']
    for key in ('before_commit', 'after_commit'):
        item = disconnect[key]
        validate_restore_scope(item, counts)
        require(item.get('synthetic_only') is True and item.get('source_rows') == 4100 and
                item.get('populated_tables') == 37, 'Full-table disconnect scope required')
    before, after = disconnect['before_commit'], disconnect['after_commit']
    require(all(before.get(k) is True for k in ('actual_connection_closed_before_commit', 'all_imports_absent',
            'preserved_rows_match', 'sequences_unchanged', 'fresh_readonly_verification_rejects_absent_restore')) and
            before.get('restore_retried') is False, 'Pre-commit rollback proof missing')
    require(all(after.get(k) is True for k in ('real_commit_then_client_error', 'fresh_readonly_verification_matches',
            'preserved_rows_match', 'replay_guard_rejected_before_insert', 'sequences_unchanged_by_replay')) and
            after.get('network_packet_loss_reproduced') is False, 'Post-commit reconciliation proof missing')

    tls = client['tls']
    require(tls.get('sslmode') == 'verify-full' and tls.get('verify_mode') == 'CERT_REQUIRED' and
            all(tls.get(k) is True for k in ('in_use', 'check_hostname', 'wrong_root_rejected',
                                           'wrong_hostname_rejected', 'plaintext_server_rejected',
                                           'tls_read_timeout_rejected')),
            'Verifying SSLContext positive/negative/refusal TLS proof missing')
    require(tls.get('protocol') in ('TLSv1.2', 'TLSv1.3') and
            isinstance(tls.get('cipher'), str) and bool(tls['cipher']),
            'Modern TLS evidence required')
    timeout_control = tls['read_timeout_control']
    require(timeout_control.get('actual_exception_type') in ('TimeoutError', 'InterfaceError') and
            type(timeout_control.get('elapsed_seconds')) in (float, int) and
            math.isfinite(timeout_control['elapsed_seconds']) and
            4.5 <= timeout_control['elapsed_seconds'] <= 15 and
            type(timeout_control.get('socket_timeout_seconds')) is int and
            timeout_control['socket_timeout_seconds'] == 5 and
            type(timeout_control.get('connect_attempts')) is int and timeout_control['connect_attempts'] == 1 and
            timeout_control.get('startup_received') is True and
            timeout_control.get('password_message_sent') is False and
            timeout_control.get('authentication_response_sent') is False,
            'Owned TLS read-timeout/no-retry/no-password control missing')
    stability = client['stability']
    require(stability.get('synthetic_only') is True and stability.get('read_only') is True and
            stability.get('client_profile') == 'pg8000-pure-python' and
            type(stability.get('buffer_queries')) is int and stability['buffer_queries'] >= 64 and
            type(stability.get('window_queries')) is int and stability['window_queries'] >= 185 and
            type(stability.get('window_seconds')) in (float, int) and
            math.isfinite(stability['window_seconds']) and stability['window_seconds'] >= 185 and
            type(stability.get('query_count')) is int and
            stability['query_count'] >= stability['buffer_queries'] + stability['window_queries'] and
            stability.get('exact_external_38_queries_replayed') is False and
            stability.get('external_disconnect_cause_proven') is False and
            'libpq_runtime_version' not in stability, 'Synthetic Windows TLS stability proof missing')

    packages = lock['pure_client']['packages']
    require(isinstance(packages, list) and len(packages) == 6,
            'Complete pinned pure-client dependency closure required')
    by_name = {item['name']: item for item in packages}
    require(set(by_name) == {'pg8000', 'scramp', 'asn1crypto', 'python-dateutil', 'six', 'certifi'} and
            by_name['pg8000']['version'] == '1.31.6', 'Unexpected pure-client package closure')
    wheels, merged = validate_pure_wheels(packages, directory / 'pure-wheels')
    require(client.get('wheels') == wheels, 'Exact pinned pure wheel manifests differ')
    require(client.get('wheel_files') == merged, 'Complete merged pure-client file manifest mismatch')
    imported = client['imported_modules']
    validate_imported_modules(imported, merged)

    ssl_runtime = validate_ssl_runtime(client['ssl_runtime'])

    build = client['build_proof']
    require(all(build.get(k) is True for k in ('pure_client_verified', 'no_native_client_payload',
                                             'pip_check_passed')), 'Pure-client integrity proof missing')
    expected_inputs = {x['filename']: x['sha256'] for x in
                       [*lock['build_tools'], *packages, *lock['application_source_wheels']]}
    require(build.get('source_inputs_sha256') == expected_inputs, 'Pinned build input hashes differ')
    require(build.get('pg_config_version') == 'PostgreSQL 18.6' and
            build.get('postgres_archive_sha256') == lock['postgresql']['sha256'],
            'Synthetic fixture server archive provenance mismatch')
    application_wheels = build.get('application_source_wheels', [])
    require(len(application_wheels) == len(lock['application_source_wheels']) == 1,
            'Reviewed application source wheel proof required')
    app = application_wheels[0]
    require(app.get('name') == 'http-ece' and app.get('version') == '1.2.1' and
            app.get('sdist_sha256') == lock['application_source_wheels'][0]['sha256'] and
            app.get('source_unmodified') is True and app.get('pure_python') is True,
            'Application source wheel provenance mismatch')
    require(bool(re.fullmatch(r'http_ece-1\.2\.1-[A-Za-z0-9.]+-none-any\.whl', app['wheel_filename'])),
            'Unexpected application wheel tag')
    app_path = artifact_path(directory / 'application-wheels', app['wheel_filename'])
    require(valid_hash(app['wheel_sha256']) and sha(app_path) == app['wheel_sha256'],
            'Application wheel artifact mismatch')
    require(wheel_files(app_path, app['name'], app['version']) == app['files'],
            'Application pure wheel content mismatch')
    return {'actual_windows': True, 'candidate_commit': commit,
            'client_profile': 'pg8000-pure-python', 'package_version': '1.31.6',
            'runner_sha256': client['runner_sha256'],
            'guard_sha256': sha(root / 'client_runtime_guard.py'),
            'bootstrap_sha256': sha(root / 'client_bootstrap.py'),
            'connection_helper_sha256': sha(root / 'client_connection.py'),
            'observation_sha256': sha(root / 'inspect_observation.py'),
            'preservation_sha256': sha(root / 'preservation_scope.py'),
            'launcher_adapter_sha256': sha(root / 'launcher_adapter.py'),
            'wheels': wheels, 'wheel_files': merged, 'imported_modules': imported,
            'ssl_runtime': ssl_runtime, 'acceptance_summary': summary,
            'full_table_acceptance': full, 'disconnect_acceptance': disconnect,
            'tls_acceptance': {'verify_full_used': True, 'wrong_root_rejected': True,
                               'wrong_hostname_rejected': True, 'plaintext_server_rejected': True,
                               'tls_read_timeout_rejected': True, 'read_timeout_control': timeout_control,
                               'check_hostname': True, 'verify_mode': 'CERT_REQUIRED'},
            'stability_acceptance': stability}
