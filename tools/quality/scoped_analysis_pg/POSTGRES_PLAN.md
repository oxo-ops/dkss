# Current candidate: PostgreSQL ledger variant

Use `run_postgres_once.py` + `postgres_ledger.py`, NOT the earlier POSIX SQLite `run_once.py` on current Render. These are offline-prepared artifacts, not merged/deployed and not a completed pilot.

## Required production change
Apply reviewed `002_postgres_pilot_ledger.sql` once on the verified current database. It creates only three new `dkss_scoped_pilot_*` tables, with no existing-business-table alteration/drop/data deletion. The unique trial ID is fixed to this approval/target. The script deliberately has no IF NOT EXISTS; any existing names require inspection instead of replacement. Rollback is transactional if CREATE fails. Once a run starts, never delete its records, even if no HTTP send happened.

## Runtime
- Exact #388 code, fixed current DB host/name, explicit approved DB username and verify-full CA must pass.
- Verified official pricing/approval refs and applicable tax/region factor <= 1.21 required.
- The database provides permanent trial/phase/reservation storage; no Render disk/additional service required.
- Official leadership and fixed DB hold precede count. One fixed trial `INSERT` consumes the attempt before queue. Queue+hold atomic commit, no unheld pending-state window.
- Count and generation reservations each use separate committed PostgreSQL transactions before send. One row per phase, no UPSERT/retry; uncertain stays blocked.
- Same CountHTTPS, ScopedJobBridge, generation transport and canonical VehicleAnalysisJobService as reviewed code. Scoped repository sanitizes failure text to fixed PILOT_FAILED_NO_RETRY.
- No global worker activation, no AI retry, no other vehicles, no maintenance/reset script.
- Importing modules does not execute the runner. An authorized owner must explicitly call run_once with verified conditions and the credential in memory. Keep the adapter module importable alongside the candidate runner; no secret in argv or output.

## Checks completed / remaining
- AST parse passed.
- Existing SQLite-runner envelope independent tests passed (6), but they are not a full proof of this new PostgreSQL orchestration.
- PostgreSQL adapter disposable SQLite-model tests: 7 passed (phase/run replay rejection, uncertain retry blocked, immutable body, scope, count policy, committed reservation visibility). Tests never contact the live DB or provider.
- No PostgreSQL server binary is available in this workspace. Actual PostgreSQL migration/row-lock races remain unverified here and must use an owned disposable PostgreSQL CI fixture before production readiness.
- Independent review in progress. Production schema migration, actual pilot and final screen/business acceptance all pending.

## Independent-review hardening
All write transactions explicitly set `synchronous_commit=on` before mutation; SQL and migration table names are `public.`-qualified to avoid search_path dependence. Disposable SQLite model tests remain 7/7 PASS after these changes.

`test_postgres_ledger_owned_ci.py` adds three PostgreSQL checks (concurrent reservation, connection reopen/replay rejection, synchronous_commit). It accepts only the existing repo's exact loopback GitHub Actions service with validated database ownership marker; arbitrary URLs and ambient PG overrides are rejected. Here it correctly skips because that owned CI service is not configured. It has not proved PostgreSQL runtime behavior yet.

## Reviewed pre-send continuation
The first live invocation committed only the trial marker, then stopped before any phase/reservation/analysis state. Read-only diagnosis found a valid normal payload with no important history. The existing 11/10 tyre-work note was an inspection-plan manual execution, not a canonical maintenance record. It must not be represented as lost maintenance data or silently force AI use.

The new `continue_before_send` entry retains the same trial marker and verifies its approval/pricing hashes. It rejects any existing phase, reservation or target analysis state, under official leadership. It is not count/generation retry; either phase's reservation remains one-shot. The operator must first verify the authorized single canonical maintenance record and its provenance to the existing manual execution. No extra incident, cost or invoice is invented. New fixed-stage/allowlisted-class/SQLSTATE output avoids raw exception disclosure.
