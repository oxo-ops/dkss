# M06 notification plan reads

Base: `065cb157c3680c5b1b31a70febee4c2a7e2e651f` (#353 merged).

This change batches only the plan reads in expiry_is_planned and
legacy_expiry_dependency. Actual-record/Execution queries and receipt DML retain
their existing behavior. It is separate from login/OCR recovery.

## Bounds and correctness

Hints exist only during one process_company invocation, inside its existing
company lock/transaction. Keys include vehicle and month and are scoped to the
company/session. Relevant pending changes, flushes, bulk statements and transaction
end invalidate hints. Missing/invalid entries use the original query.

At most 2,000 keys are selected, with 100 vehicles per month/batch. A query fetches
at most 201 plan rows. When it exceeds 200, the entire batch is discarded and the
original predicate is used: no history is truncated and no partial negative
answer is cached. Original fallback memory behavior is unchanged. Scalar flags
are retained; fetched ORM rows are not retained in the hint map.

## Isolated evidence (2026-10-30)

Fresh fictional SQLite databases; external socket connections blocked. Existing
databases, production, Render and real AI were not used.

The same 25-vehicle query-budget regression fails on the base (25 queries) and
passes after the change. Twenty focused tests pass (46.894 seconds), including
nonempty actual records/Executions, both kinds on one day, legacy confirmed and
unknown evidence, reserved dates, different months/companies, whole persisted
notice/receipt comparisons, writes/flush/bulk/commit/rollback invalidation and
an unknown dependency beyond an overfull 201-row batch. Existing #349 and M06
notification protections are included. No full local suite was repeated.

Same fixture and unread-count endpoint, sequential before/after measurements:

| Fictional vehicles | Base SQL | New SQL | Base seconds | New seconds |
|---|---:|---:|---:|---:|
|100|1,633|1,435|0.7030|0.6158|
|1,000 sample 1|16,177|14,188|6.8869|5.9574|
|1,000 sample 2|16,177|14,188|6.7943|6.0666|

At 1,000 vehicles SELECTs fall from 14,095 to 12,106; INSERTs remain 2,081
and UPDATEs remain 1. Two thousand plan queries become ten batch queries plus
one distinct receipt-month query. Mean elapsed time is 6.8406 to 6.0120 seconds.
Each sample uses fresh data; imports are warm after the 100-vehicle run. Two
samples are not a percentile or production SLA. The load fixture has confirmed
September actuals and October plans; nonempty same-month correctness is covered
separately by the regression fixture.

A separate tracemalloc run measures endpoint peak allocations of 17,830,021
bytes before and 14,678,241 after. Tracemalloc timings are not used above.
The normal batch fixture fetched at most 100 plan rows per batch, retained
1,000 scalar keys (148,952 shallow bytes). The overflow test fetches 201 and
falls back. These are measured Python allocations, not total process RSS.

Remaining 14,188 queries include unchanged receipt writes and record/Execution
reads. Further optimization is a separate task; this change does not claim to
eliminate all N+1 queries. SQLite evidence does not establish PostgreSQL latency
or real production scale. No schema, migration, business rule or deployment
change is included.
