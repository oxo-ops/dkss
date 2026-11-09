"""Small invented evidence objects for gate mutation tests, NEVER a CI receipt."""
import copy
import json
from pathlib import Path


def fixture():
    counts = json.loads((Path(__file__).parents[1] / 'source-counts.json').read_text())
    batches = []
    for name, count in sorted(counts.items()):
        if name == 'push_subscription':
            continue
        width = 1 if name == 'vehicle_operation_import_draft' else 100
        for start in range(0, count, width):
            batches.append(dict(table=name, rows=min(width, count-start), binds=2*min(width,count-start),
                sql_bytes=256, parameter_bytes=5*1024*1024 if width == 1 else 1000,
                executemany=False, returning=False, explicit_multi_values=True))
    small = [b for b in batches if b['table'] != 'vehicle_operation_import_draft']
    padding, remainder = divmod(60968018 - sum(b['parameter_bytes'] for b in batches), len(small))
    for i, batch in enumerate(small):
        batch['parameter_bytes'] += padding + (i < remainder)
    envelope = dict(source_rows=4100, imported_rows=4099, blob_values=24,
                    blob_bytes=15189518, encoded_parameter_bytes=60968018)
    def receipt(dispatch):
        return dict(synthetic_only=True, actual_postgres_18=True,
                    envelope=copy.deepcopy(envelope), insert_dispatch=copy.deepcopy(dispatch))
    full = receipt(batches)
    full.update(exact_all_imported_values_and_blobs=True, preserved_itc_settings_audit_push=True,
                deferred_source_retained=True, exact_epoch_revisions={'shared':3271})
    partial = [next(b for b in batches if b['table']=='company')]
    partial += [b for b in batches if b['table']=='vehicle_operation_record'][:2]
    result = {'full-size': full}
    for name, dispatch in [('middle_insert_batch',partial), ('actual-third-batch-error',partial),
                           ('after_sequences',batches)]:
        result[name] = receipt(dispatch)
        result[name].update(all_imports_absent=True, preserved_rows_match=True,
                            sequences_unchanged=True, compatibility_column_rolled_back=True)
    result['actual-third-batch-error'].update(actual_postgres_constraint_error=True,
        target_table='vehicle_operation_record',attempted_target_batches=3,successful_target_batches=2,restore_retried=False)
    result['disconnect-before-commit'] = receipt(batches)
    result['disconnect-before-commit']['reconciliation'] = dict(actual_connection_closed_before_commit=True,
        all_imports_absent=True,preserved_rows_match=True,sequences_unchanged=True,
        fresh_readonly_verification_rejects_absent_restore=True,restore_retried=False)
    result['disconnect-after-commit'] = receipt(batches)
    result['disconnect-after-commit'].update(exact_epoch_revisions={'shared':3271},
        reconciliation=dict(real_commit_then_client_error=True,fresh_readonly_verification_matches=True,
        preserved_rows_match=True,replay_guard_rejected_before_insert=True,sequences_unchanged_by_replay=True,
        network_packet_loss_reproduced=False))
    return result
