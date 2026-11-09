"""Offline evidence-gate mutation tests; never connect to a database or seal policy."""
import ast
import copy
import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('collision_evidence_verifier', ROOT / 'tests/windows-ci/verify_client_evidence.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def fixture():
    ids = sorted(gate.REQUIRED_ACCEPTANCE_IDS)
    preflight = dict(source_rows=4100, import_rows=4099, populated_import_tables=36,
        old_catalog_execute_calls=108, prior_catalog_execute_calls=3, new_catalog_execute_calls=3,
        old_application_execute_calls=159, prior_application_execute_calls=159,
        new_application_execute_calls=112, old_unique_probe_round_trips=49,
        new_unique_probe_round_trips=2, distinct_unique_predicates=29,
        noncollision_application_queries_and_binds_equal=True,
        distinct_unique_predicates_and_binds_equal=True, same_readonly_transaction=True,
        preserved_state_unchanged=True, synthetic_only=True, network_disconnect_fix_proven=False,
        collision_max_branches=16, collision_max_binds=8000, collision_max_sql_bytes=131072)
    maps = dict(populated_import_tables=36, exact_public_keys=True, unique_maps_equal=True,
        index_maps_equal=True, ordered_combination_equal=True, preserved_state_unchanged=True)
    controls = dict(actual_postgresql=True, implementations=['sequential','batched'],
        tenants=['ITC','SYNTHETIC_OTHER'], positions=['first','middle','last'],
        collision_cases=6, noncollision_cases=6, exact_outcomes_equal=True,
        same_readonly_transaction=True, preserved_rows_and_sequences_unchanged=True,
        global_and_scoped_unique_keys_verified=True)
    from preservation_scope import PRESERVATION_CONTRACT
    from bounded_insert_evidence_fixture import fixture as bounded_fixture
    return dict(postgres_cases=gate.POSTGRES_REQUIRED_CASES, preservation_contract=PRESERVATION_CONTRACT, suite_ids=ids, suite_ids_sha256=hashlib.sha256('\n'.join(ids).encode()).hexdigest(),
        expected=len(ids), run=len(ids), failures=0, errors=0, skipped=0, postgres_required=True,
        catalog_required_cases=36, collision_required_cases=32,
        bounded_insert=bounded_fixture(),
        catalog_batching=dict(maps=maps, preflight=preflight, collision_controls=controls))


class CollisionEvidenceTests(unittest.TestCase):
    def test_complete_synthetic_schema_is_accepted_without_claiming_live_proof(self):
        gate.validate_acceptance(fixture())

    def test_old_139_case_evidence_cannot_pass(self):
        item = fixture(); item.update(expected=139, run=139)
        item['suite_ids'] = [i for i in item['suite_ids'] if '.CollisionBatchTests.' not in i]
        with self.assertRaises(ValueError): gate.validate_acceptance(item)

    def test_missing_or_duplicate_mandatory_id_rejected(self):
        for index in range(len(gate.REQUIRED_ACCEPTANCE_IDS)):
            item = fixture(); item['suite_ids'].pop(index)
            with self.assertRaises(ValueError): gate.validate_acceptance(item)
        item = fixture(); item['suite_ids'].append(item['suite_ids'][0])
        with self.assertRaises(ValueError): gate.validate_acceptance(item)

    def test_stale_hash_counts_and_incomplete_runs_rejected(self):
        for key, value in [('suite_ids_sha256','0'*64), ('expected',172), ('run',170),
                ('failures',1), ('errors',1), ('skipped',1), ('postgres_required',False),
                ('catalog_required_cases',35), ('collision_required_cases',31), ('run',True),
                ('postgres_cases',33), ('preservation_contract',{})]:
            item = fixture(); item[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): gate.validate_acceptance(item)

    def test_every_collision_field_is_required(self):
        item = fixture(); del item['catalog_batching']['collision_controls']
        with self.assertRaises(ValueError): gate.validate_acceptance(item)
        for key in fixture()['catalog_batching']['collision_controls']:
            item = fixture(); del item['catalog_batching']['collision_controls'][key]
            with self.subTest(control=key), self.assertRaises(ValueError): gate.validate_acceptance(item)
        for key in fixture()['catalog_batching']['preflight']:
            item = fixture(); del item['catalog_batching']['preflight'][key]
            with self.subTest(key=key), self.assertRaises(ValueError): gate.validate_acceptance(item)

    def test_altered_collision_metrics_and_boolean_proofs_rejected(self):
        for key, value in fixture()['catalog_batching']['collision_controls'].items():
            item = fixture()
            changed = not value if type(value) is bool else value + 1 if type(value) is int else value[:-1]
            item['catalog_batching']['collision_controls'][key] = changed
            with self.subTest(control=key), self.assertRaises(ValueError): gate.validate_acceptance(item)
        for key in ('collision_cases', 'noncollision_cases'):
            item = fixture(); item['catalog_batching']['collision_controls'][key] = 6.0
            with self.subTest(control_type=key), self.assertRaises(ValueError): gate.validate_acceptance(item)
        for key, value in fixture()['catalog_batching']['preflight'].items():
            item = fixture()
            item['catalog_batching']['preflight'][key] = not value if type(value) is bool else value + 1
            with self.subTest(key=key), self.assertRaises(ValueError): gate.validate_acceptance(item)

    def test_every_catalog_map_proof_is_required(self):
        for key in fixture()['catalog_batching']['maps']:
            item = fixture(); del item['catalog_batching']['maps'][key]
            with self.subTest(key=key), self.assertRaises(ValueError): gate.validate_acceptance(item)

    def test_contract_and_oracles_are_hashed_and_missing_or_altered_rejected(self):
        paths = gate.acceptance_artifact_paths(ROOT)
        hashes = {p.relative_to(ROOT).as_posix(): gate.sha(p) for p in paths}
        required = ('tests/application_contract.json', 'tests/collision_baseline.py',
                    'tests/collision_diagnostic_guard.py', 'inspect_observation.py',
                    'preservation_scope.py', 'launcher_adapter.py')
        for key in required: self.assertIn(key, hashes)
        gate.validate_acceptance_artifacts(hashes, ROOT)
        for key in required:
            item = dict(hashes); del item[key]
            with self.assertRaises(ValueError): gate.validate_acceptance_artifacts(item, ROOT)
            item = dict(hashes); item[key] = '0'*64
            with self.assertRaises(ValueError): gate.validate_acceptance_artifacts(item, ROOT)

    def test_all_execution_and_seal_routes_call_shared_validator(self):
        for relative in ('tests/run_acceptance.py', 'tests/windows-ci/build_windows_client.py',
                         'tests/windows-ci/seal_combined.py', 'tests/windows-ci/verify_client_evidence.py'):
            tree = ast.parse((ROOT / relative).read_text())
            calls = [n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
            self.assertIn('validate_acceptance', calls, relative)


if __name__ == '__main__': unittest.main()
