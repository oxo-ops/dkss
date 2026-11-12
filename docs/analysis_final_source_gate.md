# Final source gate for the demonstrated ordinary writer families

## Why this narrow change

An immutable-V5 reproduction uses the ordinary daily-inspection repair POST without a subsequent normal recheck. The original defect moves from 対応待ち to 再確認待ち and its optional confirmation becomes held. If this commits after real reconciliation but before first save, a candidate with no prior saved history is saved for the first time, displayed as held 高 with no current score, and carried into the next generation. Performing the same POST before reconciliation yields no candidate in either generation. This invents saved history from an unsaved candidate, unlike a simple stale cancellation that GET already suppresses.

The repair/recheck writer already uses `lock_vehicle_inspection_updates`: a company/vehicle-scoped `Vehicle.id=id` update before source-row work, retained to its commit (`checklists.py`, repair entry at 3758, helper at 6509, commit at 3954). Optional confirmation and withdrawal use the same scoped vehicle row (`priority_confirmations.py:290–337`). No HTTP writer, source schema, audit format, classification or score is changed.

## Lock scope and order

The analysis job captures original company/vehicle identity before claiming. The claim commits before input/model work as before. After the model finishes, it expires cached ORM state, fetches the same non-deleted, company-scoped Vehicle with PostgreSQL `FOR NO KEY UPDATE`, performs fresh real confirmed-candidate reconciliation, then keeps that lock through the analysis-row save commit. Ordering is Vehicle → analysis state. The no-key-update mode still conflicts with normal source UPDATEs but permits foreign-key KEY SHARE. This mode is chosen to avoid a lock inversion against an old guarded evaluation writer that can hold the analysis row first and then insert a Vehicle-referencing evaluation. SQLAlchemy expresses this PostgreSQL mode with `with_for_update(key_share=True)` and the default `read=False`. The V7 queued-generation/token fence still owns the final state write.

There is no model call while holding this source gate, no new thread, and no company/global lock or epoch-table lock. Different vehicles remain independent. A target deleted or moved out of scope before the final gate is handled by the existing scoped skip path without saving the generated bundle. A thrown exception rolls back the source lock before the existing generation-aware failure handling.

- Writer wins first: the final phase waits, then sees the committed repair/recheck/confirmation change during fresh reconciliation. It cannot turn a newly held first candidate into prior history. A genuinely previously saved candidate can still be carried under the existing held-history rules.
- Saver wins first: the normal POST waits until saving commits while its source is still valid. The later source update can legitimately make that already-saved candidate historical. This is intended ordering, not a requirement to erase valid history.

The normal repair/recheck, confirmation/withdrawal paths are the demonstrated coverage. Other daily-inspection paths call the same helper, but only its applicable fixed daily-inspection template takes this gate. No general guarantee is made for unrelated maintenance, document, knowledge, account or direct database writes, or clock/validity boundaries. Any further expansion needs a concrete failure and writer-coverage proof, not an assumed universal synchronization contract.

## Queue, cost and operational effect

No job, reservation, retry interval, worker budget, model request or concurrency is added. The normal source scan still detects fresh inputs on its existing cadence. The gate itself neither queues regeneration nor makes an extra AI call. Synthetic success tests have the same one model call per job; next-generation tests use the existing queue and due time.

This is not a general unchanged-cost guarantee. A new lock wait/failure can use the existing error/retry path after model work has already been paid for. Token loss, database failure and process shutdown retain the prior recovery rules and possible repeated provider costs. Lock duration is the final read/reconciliation/save transaction, not the model duration. Production contention and duration have not been measured; no new timeout, monthly quota or service is silently configured.

The existing no-AI-on-GET, tenant scope, proof/ref matching, original-source invalidation, cancellation suppression and held-score behavior remain. No new end-user field or action is required.

## Verification

Two new disposable SQLite checks exercise real repair POSTs immediately before final gate acquisition. They establish logical ordering (model → gate → fresh reconciliation → finish), rejection of invented first-held history, preservation of legitimate previous held history, unchanged source/audit bytes after save, normal result GET, and next-generation behavior. A third SQLite check verifies that a target deleted or moved to a different company during model work cannot receive the generated result. SQLite does not prove row-level exclusion.

Two new official-only PostgreSQL cases use the existing exact service URL, GitHub context, owned database marker, cleared environment, synthetic provider and finite waits. They observe a genuine lock wait with the real repair POST in both writer-first and saver-first orderings, rather than trusting thread-start signals. A third PG case checks the observed old-writer lock order: analysis-row lock, then a real foreign-key evaluation insert, overlapping the new final gate. A successful run proves that lock-order compatibility, not an end-to-end run of the old rollback application. They are prepared, not executed locally. The combined official runner requires all 33 cases to run without skips.

V5 and V7 stay immutable. No local PostgreSQL/listener, production operation, real provider call, remote ref, dependency or DB schema change is part of this candidate. Independent fixed-tree review and one guarded official run remain before any activation decision.
