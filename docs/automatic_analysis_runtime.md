# Automatic normal analysis runtime candidate

This opt-in integration is not an enabled production rollout. It does not create
services, change database/TLS/start guards, migrate schemas, or invoke AI on GET.
The existing inspection and optional-confirmation POSTs remain unchanged.

## Activation decision

The existing Gunicorn `post_worker_init` additionally calls the analysis runner.
`VEHICLE_ANALYSIS_WORKER_ENABLED` must be exactly `1` to start it; default is `0`.
`TESTING=True` also prevents automatic startup. An app factory/import, Flask
request, or result GET never starts it. No additional end-user button is needed
after an approved deployment/configuration activation.

Do not enable this flag until the exact candidate passes PostgreSQL concurrency
and shutdown/restart checks, the existing startup/schema guard passes, the DB
connection budget and web memory/CPU headroom are accepted, and AI usage is
approved. No new mandatory paid service is required for this candidate, but
existing model usage and possible web/DB capacity upgrades still cost money.
Their total cannot be inferred from this code or the current inventory.

## Bounded execution and latency

Each web process creates at most one daemon thread. One PostgreSQL session-level
advisory lock selects one active analysis runner across processes/replicas.
Standby threads attempt leadership every 60 seconds. The leader holds one extra
DB connection; the normal ORM uses a separate connection and commits normally.
Use a direct/session-persistent PostgreSQL connection, not transaction-pooling
middleware. No new tables or dependencies are required. Before work, the leader
performs read-only critical-column probes; missing schema causes sanitized error
logging and retries, never implicit schema creation.

One pass scans up to 20 active, non-deleted vehicles in primary-key order and
executes at most one due analysis job. It then waits 60 seconds. The cursor cycles
through the fleet, resetting on leader replacement. For N vehicles a full scan
needs ceil(N/20) passes, plus the time to build inputs and run due jobs. Persistent
restarts before a complete scan can delay higher-ID vehicles. The 2-minute queue
delay starts when a change is detected, not when the user confirms it. Existing
pending earlier deadlines are retained; this is coalescing, not a strict trailing
2-minute debounce. Routine changes retain the existing next-03:00-Japan schedule.

Under continuously available fast scans/jobs the web runner processes at most
60 jobs/hour, strictly less than 1,440 jobs/day once real work takes any time.
The routine fingerprint includes an evaluation date, so daily fleet work also
consumes this capacity. Real throughput is lower because a pass waits after work. One job
may make multiple model calls; this is not a token/currency or wall-clock budget.
The existing per-call HTTP timeout is 120 seconds. A single vehicle input can
include substantial history and peer comparisons. Batching bounds vehicle count,
not per-vehicle memory/CPU or provider bill. OCR and the existing periodic proposal
executor still share the web process, so production load measurement is required.
A dedicated worker may be preferable when latency, fleet size or HTTP load
exceeds this envelope; provisioning one needs separate configuration/cost approval.

## Coexistence, duplicate work and recovery

The updated analysis CLI tick uses the same advisory gate. A CLI tick prints
`ANALYSIS_WORKER_BUSY` while the web leader is active. Its pre-existing public
knowledge refresh still runs separately. The web runner itself does not add
monthly external public-source downloads; retain the established public-source
schedule if needed. SQLite remains supported by the explicit legacy CLI only;
the embedded web runner refuses non-PostgreSQL databases.

All concurrently running analysis producers should use this same version before
activation. The explicit CLI still scans the whole fleet and can execute up to
20 due jobs per tick. The web 20-scan/1-job/60-second envelope is not a global rate
or cost cap if a CLI wins leadership before web startup or during failover.
Inventory and accept any CLI scheduling/cost separately, or have no competing
analysis CLI when enabling the web runner. An older CLI does not know the global leader gate. Existing atomic
job claims and token-fenced saves reduce overlap, but cannot impose this global
resource cap on old external processes. The observed absence of a managed worker
is not proof that no external cron/process exists. Confirm that inventory first.

Queue updates now lock the analysis state row. They cannot overwrite a claim
based on an unlocked stale read. Each job retains the existing 3-minute token
lease, renewal before model chunks, stale-owner rejection and 1-hour retry after
an error. The leader's backend identity is checked before work, model chunks and
saving. Lost/reconnected leadership cannot intentionally continue a later chunk.

The Gunicorn exit hook only sets a cooperative stop event and wakes idle waits.
It does not join the daemon analysis thread. Normal SIGTERM/reload process exit
can therefore terminate an in-flight analysis immediately, as can a hard kill.
The existing 30-second graceful timeout governs HTTP worker shutdown; it is not
a promise to finish background model work. Interrupted jobs remain running until
their lease expires. Results remain until a token-owning successful save.
A crash or connection loss during a model request can cause a later retry to
incur another charge. Exactly-once provider execution/billing is not guaranteed.
A hung process retaining its live PostgreSQL connection can block leadership;
operations must monitor heartbeat age and restart through approved procedures.

## Visibility and verification

Logs: `ANALYSIS_WORKER_STARTED`, `ANALYSIS_WORKER_STANDBY`,
`ANALYSIS_WORKER_HEARTBEAT` (cursor/scanned/errors/completed/failed),
`ANALYSIS_WORKER_STOPPED`, `ANALYSIS_SCAN_FAILED`, `ANALYSIS_JOB_FAILED`, and
`ANALYSIS_WORKER_ITERATION_FAILED`. New runtime logs emit error types, not raw SQL,
credentials or source payloads. Existing job-service error storage/redaction is
unchanged. Heartbeats are between jobs, not an independent liveness thread.
Existing result GET still displays pending/running/error and the previous result;
there is no new admin backlog dashboard or alert service.

Targeted isolated checks:

```
python -m unittest test_analysis_worker test_vehicle_analysis_service \
  test_priority_candidate_completion test_analysis_result_consistency -v
```

The end-to-end runtime test uses real HTTP inspection/recheck/confirmation input,
real fingerprint scheduling/claims/persistence/projection, disposable SQLite, a
synthetic clock/leadership, and mocked AI. It proves pending at 0/60 seconds and a
current confirmed result at 120 seconds without another POST. It does not prove
PostgreSQL concurrency or real Gunicorn shutdown.

`test_analysis_worker_postgres` provides seven supplemental checks for a dedicated
loopback PostgreSQL service only. Set `ANALYSIS_RUNTIME_REQUIRE_POSTGRES=1` and
`ANALYSIS_RUNTIME_POSTGRES_TEST_URL` with driver `postgresql+psycopg2`, host
`127.0.0.1`, port `5432`, database `dkss_analysis_runtime_ci`, user
`analysis_runtime_ci`, and the exact disposable CI-only password defined in `analysis_runtime_ci_support.py`.
The test also requires the owned GitHub Actions repository/environment and a
database comment ownership marker set by this job in its service container. URL
query overrides and ambient PG environment settings are rejected before DDL. The tests create/drop
all tables in that dedicated database. They verify one leader, leadership release
and connection loss, competing claims, queue/claim serialization and stale-owner
fencing. Never point these tests at a production or migration-validation DB.

Before activation, official CI should additionally exercise two real Gunicorn
processes, SIGTERM/forced kill during mocked model execution, new-version CLI
coexistence, missing-schema refusal, and representative fleet/backlog load.
Verification here does not grant permission to activate the flag, deploy, create
paid services, or call a real provider.


## Official finite process acceptance

`.github/workflows/automatic-analysis-runtime.yml` checks out the exact incoming
head and records its commit/tree before running only the focused acceptance.
It provisions an owned PostgreSQL 18 service with an explicit synthetic marker,
then clears the test environment and installs a Python audit guard that permits
only loopback PostgreSQL/HTTP and the owned temporary SQLite directory. It does
not use repository/environment secrets, new packages, real AI, notifications,
S3 or public-knowledge downloads. A failed guard or ownership marker fails closed.

Seven PostgreSQL cases include observed `pg_stat_activity` lock blocking in both
queue/claim interleavings, not merely thread start signals. Seven process cases
run real Gunicorn with its existing startup/exit hooks and two web processes:
one synthetic model call plus CLI coexistence and a responsive ordinary login GET, SIGTERM during
model work, worker SIGKILL/respawn, HUP reload, and missing-schema refusal. Process
cases use a short idle wait only inside their test WSGI module and explicitly
expire a synthetic fixture lease to avoid waiting three wall-clock minutes.
Product queue/lease deadlines and Gunicorn shutdown settings are unchanged.

The model transport is entirely replaced in a CI-only WSGI app; calls are appended
to a synthetic JSONL log and held/released by fixture files. No production route
or secret can enable this test app. Each process wait, SQL wait and job has a
finite timeout. The job uploads exact source identity, counts and logs even on
failure. These are acceptance artifacts, not a benchmark or proof of provider
exactly-once billing. Their real execution result remains unverified until this
specific new head passes official CI.

The WSGI harness has no extra health route or authentication bypass. A Flask
test-client check verifies ordinary `/login` serves while protected analysis
GET still redirects unauthenticated users. This check performs no model call,
listener or external database access. Official acceptance requires 16 executed
checks with zero skips: two guard/WSGI checks, seven PG and seven process cases.


Two additional process cases keep the original OS worker alive while terminating
only its dedicated leadership DB session. The target must hold this exact
advisory tag in the marked synthetic database, use the owned CI role and have
the expected OS-worker application name. The complete predicate is rechecked in
the terminating SQL. It is issued once; an uncertain result fails without resend.
Read-only polling observes a different standby acquire leadership while the
original token remains valid and unexpired.

One case releases a paused first model chunk and requires the next progress
callback to fail before any second synthetic transport marker. The other pauses
after real reconciliation and the last model callback, keeping the original
valid token, then requires the final ownership check to reject saving. Both must
retain the previous result, enter the normal error state and schedule the existing
one-hour retry, not claim immediate retry or token-expiry recovery. Synthetic
chunk/fence markers and the exact backend-termination scope are uploaded as
acceptance evidence. No product behavior or model provider is replaced outside
the explicitly gated CI-only WSGI harness.
