"""Explicit scope of the new integrated contract, against the pinned full oracle.

Old batching tests still check their SQL/parameter/result equivalence. Their
historical 'everything else byte-identical' premise no longer describes this
release. Compare all remaining business function ASTs rather than replacing an
old whole-source hash with a self-generated hash of today's implementation.
"""
import ast
from pathlib import Path

CHANGED_FUNCTIONS = frozenset({
    'validate_schema',       # SHOW version once; same predicates
    'snapshot',              # explicit six-table preservation module
    'verify_deferred_plan',  # version 4 + preservation contract
    'plan',                  # contract and same-transaction private context
    'execute_restore',       # locked context plus bounded explicit INSERTs
    'verify_restore',        # truthful output key
    'check_empty_and_itc',    # approved batching + first-error capture before flush
    'cli',                   # formal inspect observation envelope
})


def assert_unchanged_business_functions(testcase, candidate):
    baseline = Path(__file__).with_name('collision_baseline.py').read_text()
    before = {n.name:n for n in ast.parse(baseline).body if isinstance(n,ast.FunctionDef)}
    after = {n.name:n for n in ast.parse(candidate).body if isinstance(n,ast.FunctionDef)}
    testcase.assertEqual(set(after)-set(before),{'insert_batch_metrics','iter_insert_batches'})
    testcase.assertTrue(set(before).issubset(after))
    for name in sorted(set(before)-CHANGED_FUNCTIONS):
        testcase.assertEqual(ast.dump(before[name]),ast.dump(after[name]),name)
