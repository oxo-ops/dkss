# Atomic collection history: offline synthetic v2 only

This adds collection history to the existing synthetic monitor without changing
its v1 files or outbox state machine. It does not run against Render, schedule
collection, send notifications, modify the application or migrate any live data.

`integrated_monitor.FileStore` persists one v2 bundle containing the exact v1
monitor (ledger, outbox, revision and proofs) plus immutable scan summaries.
`Projection` gives the unchanged v1 operations an operation-local view and commits
whole-bundle digest CAS updates. `collect_once` appends once after all pages,
not once per page. Reservations/results/recovery do not append scan history.
A later successful empty fetch never erases prior failures or verifies coverage.

## Explicit migration, not automatic replacement

`FileStore(new_path).migrate_from(old_path, writers_stopped=True)` is an explicit
**offline synthetic-only** API. The caller must stop all old writers and keep them
stopped permanently after cutover. This boolean is an assertion, not detection or
authorization. The cooperative source lock excludes in-flight old writes only
during migration. The source remains intact as an archive; it must not be resumed
alongside the new writer. The destination must be new and different from source.
There is no migration CLI/startup wiring or production operation in this PR.

Unknown legacy history is counted in `prior_runs_without_history`; it cannot be
reconstructed. All five outbox states and existing proofs remain unchanged.
Reserved/accepted/uncertain/known-not-sent entries must not be automatically
rearmed. A failure after replace may mean a commit occurred. Never blindly retry
an uncertain operation or steal stale locks. Independently inspect the private
state and confirm no writer runs before any manual recovery.

## Verification and limits

Run `python -I -B test_integrated_monitor.py` in this directory. The 18 tests block
socket creation and use only private temporary files and fake transports. They
cover migration of all five states, resend suppression, single history entry for
multiple pages, stale-CAS races, two real competing processes, SIGKILL before/after
replace, fsync/cleanup uncertainty, malformed/missing/link state and full history.
Independent review verified accepted migration and suppression; its not-due
strict-type validation finding was fixed and has a regression test.

This is POSIX/cooperative-writer acceptance, not Windows/shared-FS/power-loss or
adversarial same-UID security certification. History stops at 1000 rather than
evicting unresolved intervals; archive/retention design is still required.
Real source recording, operational schedules, delivery destinations, receipts,
and production adoption remain separate unimplemented acceptance work.
