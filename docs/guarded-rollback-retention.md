# Limited rollback: retain incompatible saved analysis

This candidate starts from old Live commit `e8a529e48be239e1acbebbab333fe6395fd061f3`
(tree `1463cb2ae034d9847cfe090f1435a6be4d48eabd`). It is **not a deployment** and
is not a backport of PR377. The pinned compatible PR377 candidate is
`0f91f42e3fe2ac88b4697c8935a49ffd8c48710f` (tree
`9afe16ebe79b895c557f9efa5c5290d0519a7a95`).
This pin includes the newer-generation reservation fence and the final Vehicle
FOR NO KEY UPDATE source gate. Pinning it does not claim its native PostgreSQL
acceptance has run. The guarded product remains based only on old Live.

## Why old Live alone is unsafe

Old periodic generation commits `{}` before submitting the worker. Opening its
page can automatically POST after a missing GET, without a button click.
Submission failure and worker failure leave the saved result erased. Successful
normal analysis also replaces the saved bundle. An audit trail alone cannot
reconstruct a prior candidate whose original confirmation is no longer valid.
Do not use Render's old-artifact rollback button for the unguarded e8a artifact.

## Retention boundary

`vehicle_saved_result_guard.py` detects PR377's persisted `priority_*` fields
recursively, including confirmation, provenance, carry history and periodic
source proof. Both versions use fingerprint policy 12; that value alone is not a
format discriminator. Invalid JSON, non-object envelopes, unknown top-level
fields, unsupported policy/contract values, malformed source objects, nested result
fields and recommendation field/container types are
held rather than repaired or erased. Ordinary legacy envelopes, including the
legacy AI output/risk contracts and model field, continue through the old code.
There is no claim to recognize an arbitrary future format that deliberately
reuses the same unversioned legacy shape without distinguishable fields.

For a protected saved result, preserve its original bytes, identifiers and row
metadata. Do not rewrite, normalize, strip new fields, regenerate, clear, or
manually reset the result. Preserve confirmation/audit events and their links.
The guard does not introduce schema changes, migrations, dependencies, restore
operations, environment flags, scoring rules or a new priority category.

- Normal queue and worker admission refuse protected results without paid work.
  Claim, finish, fail, skip and lease renewal check the latest row. Final writes
  retain the lease/token and checked result bytes. PostgreSQL row locks and
  conditional updates prevent this guarded worker from overwriting a newer result.
- The runnable-job limit is applied after protected rows are excluded, so twenty
  protected due rows cannot permanently starve ordinary legacy work.
- Periodic GET returns a held response before old input-digest interpretation.
  POST refuses with HTTP 409 before clearing/submitting. Start and final-save
  updates compare the checked bytes and token. Submission-failure updates are
  conditional on the legacy empty result and matching token. Worker failure and
  success both recheck the latest saved result.
- Document deletion, document-kind correction preparation and final source
  replacement reject protected normal or periodic results for the vehicle.
  Existing result rows are locked and checked before feedback/source/business
  mutations. A stale confirmation page is not authority to erase new results.
  Before this check, lock the existing Vehicle and every PeriodicRecord parent
  for that vehicle, in ID order, with FOR UPDATE NOWAIT. Both exact e8a and 97f
  first inserts use these foreign keys. The Vehicle fence also covers insertion
  of a new periodic parent. An earlier FK key-share makes this guarded request
  refuse; a later first insert waits until this transaction ends. On PostgreSQL
  lock-not-available (55P03), roll back the entire transaction and return the
  controlled conflict, never continue after releasing locks. This also rolls back
  already-flushed replacement business records. No Company lock is added, and
  NOWAIT avoids introducing a blocking lock-upgrade cycle with ongoing imports.
  Other database failures are not suppressed. Native PostgreSQL CI must prove
  these boundaries before release; SQLite does not certify them.
- Normal analysis, overview and dashboard withhold unsupported saved proposals.
  Periodic results are also withheld. Existing status areas explicitly explain
  that the saved result is retained and requires the compatible newer version.
  The state is not a fourth high/medium/low assessment and has no invented zero.
  Direct old feedback/evaluation POSTs against protected results return 409.
  Unsupported targets also stop influencing the overview's parts ordering.

## Limits during this rollback

The new priority-confirmation UI, numeric assessment, proof inspection, carry
history display and associated new endpoints are unavailable. Retention is not
feature parity. Do not interpret a retained result as a current assessment, a
low-risk result or an absence of proposals. Do not use old UI to review or amend
new priority confirmations. The original daily/periodic/maintenance records and
human operation decisions remain legacy functions; this guard does not claim
those screens support new priority semantics.

To preserve the exact confirmation state, leave the referenced original records,
actor identity, confirmation/audit events and persisted result fields unchanged.
A legitimate source edit can make a confirmation stale when the newer version
returns. Keeping the saved bundle lets that version show retained history, but
cannot make invalidated facts current again. Do not perform source deletion or
correction through direct SQL or an unguarded process. Previously open browser
tabs must be reloaded to obtain the versioned retained-result status handlers.

The parent fence protects this candidate's source mutation against first
normal/proposal inserts through the exact e8a/97f FK paths. It does not protect
against disabling constraints, direct SQL, an unknown writer using another path,
or a destructive request issued by another unguarded binary after our commit.
In particular, e8a normal worker success, periodic start/final writes, and e8a/97f
document deletion or final kind correction can still erase saved bytes if those
old executions remain active. An e8a request already accepted before cutover or
an in-flight correction resuming after a preview commit is a concrete risk.
Before accepting guarded traffic, confirm the previous processes have terminated
and their pending/executing work has drained using the approved platform release
workflow. Do not infer this from a new health check alone. If the platform cannot
establish that boundary without unapproved changes, stop the release and report
the remaining executions; do not weaken DB protections. Final PostgreSQL lock/concurrency
validation remains a release dependency; isolated SQLite tests exercise
conditional writes and deterministic interleavings, not PostgreSQL locking.

## Required deployment procedure, only after separate authorization

1. Publish/review this separate candidate, obtain its exact immutable commit/tree,
   and run its own required CI, including PostgreSQL concurrency where available.
   PR377's successful CI does not certify a different rollback commit.
2. Obtain approval for the exact guarded SHA and the release procedure. Confirm
   the existing backup/recovery readiness without restoring or altering data.
   Record the actual current deployment and runtime version before making changes.
3. Drain/quiesce existing web and worker executions using the approved release
   workflow. Verify that no unguarded old binary or stale queue executable can
   still write. Do not disable DB safeguards to achieve this.
4. Deploy the **new guarded artifact**, not the old e8a artifact. The release must
   satisfy its own validated expected-SHA guard. Keep the fixed database target,
   TLS `verify-full`, certificate-authority configuration and existing DB
   protection unchanged. Do not enable auto-deploy or relax protection settings.
   If this cannot be done within the authorized release workflow, stop.
5. Verify the live SHA, basic health and the retention status on a pre-agreed
   representative saved result. Confirm the persisted result/audit evidence is
   unchanged using the authorized read-only validation. Do not trigger production
   AI or modify production fixtures merely to test the guard. Reload old tabs.
6. When returning to a compatible newer release, repeat the approved drained
   release process with that exact validated SHA. The newer code reads the same
   saved JSON and audit. With unchanged sources, the synthetic active fixture
   returns the legal-deadline score 60; the held fixture returns its carried history without a
   fabricated current score. Do not force regeneration or DB restoration as a
   substitute for preserving these bytes.

## Independent tests with no stored result fixtures

The standalone retention and PG modules require an independently generated private
provider. Use the non-exporting runner, not unittest's ordinary text runner:

```sh
private_root=$(mktemp -d)
export DKSS_VALIDATION_TMP="$private_root" TMPDIR="$private_root"
export PYTHONPATH="$PWD/tests/guarded_independent_guard:$PWD:$PWD/tests"
python tests/run_guarded_independent.py --producer /path/to/exact-v8
rm -rf "$private_root"
```

The producer must have tree 9afe16ebe79b895c557f9efa5c5290d0519a7a95, commit
0f91f42e3fe2ac88b4697c8935a49ffd8c48710f. The runner checks the full source tree.
The dedicated CI additionally verifies both checkout HEADs. No saved JSON fixture,
old snapshot, prior recipe or generated-data hash is an input or an export.

The independent scenario is the already-published CertificateSourceTests setup
and confirm_http workflow in tests/test_priority_certificate_sources.py, followed
by its original completed_at change scenario. This legal-deadline confirmation
is separate from recurrent-defect confirmation. Existing published HTTP inspection
import helpers add a periodic record. Actual new normal/periodic workers persist
the server-generated legal result, with only external model output stubbed empty.

The active, held and pending-reservation states and their baseline responses live only in fresh temporary
SQLite files outside both checkouts. Separate processes run the new producer,
guarded old code and compatible new code. Round trips compare full responses and
all tables without exporting their contents. Temporary DBs are removed on exit.

The added pending case uses the public real-reconcile/queue interleaving from
tests/test_analysis_generation_fence.py on the same independent Certificate60
case. After real reconciliation, the certificate's published completed_at change
is applied and the actual input builder and queue create a distinct reservation.
The actual new worker must reject its obsolete save, retain the previous result
bytes, last analysis time and error, and return to pending with the new input hash,
reason and due time unchanged and its old lease released. The audit stays intact.
The hook must complete normally, the wrapped real finish must be called once and
return false, and the wrapped real fail must not be called. Every audit column is
compared, not only its identifier and detail payload. A failure-path lookalike is
therefore not counted as successful final-save refusal.
Its baseline new response is stale/pending with no current score. Both guarded
old and returning new code must leave every table and reservation column unchanged;
the new responses must match the pre-rollback baseline exactly. This is a
deterministic SQLite generation-fence check, not proof that source writers can
enter the V8 locked section concurrently. It neither asserts nor simulates native
lock scheduling.

Four boundary tests assert success/failure output suppression, refusal when the
child guard is absent, and transport/SQLite/PG audit-event enforcement. Every
child verifies the exact guard path and boundary rejection before app imports.
These event probes do not open a socket, listener or external database. Then25 portable retention tests keep the
same write/read/refusal boundaries. Native PostgreSQL acceptance requires all24
methods, zero skips, on the existing Q08 disposable localhost fixture. Twenty
methods consume freshly generated protected legal results; four are independent
of such results (normal/periodic stale token, duplicate legacy claim, and a new
PeriodicRecord parent's insert). Passing those four alone is not acceptance of24.

Local SQLite proves the assertions and deterministic interleavings, not native
PostgreSQL locking. Do not claim the20 native protected-data races pass until the
PG stage executes. No-URL discovery/skips are not acceptance. New→guarded-old→new
checks include active legal confirmation and held/carry history without a current
score, plus the pending reservation described above. They do not assert equality
with any prior fixed fixture contents. The earlier 97f roundtrip evidence remains
version-specific; this new producer pin needs its own acceptance. The existing
24 PG guard methods are unchanged and are a separate gate from the producer's
five queued-generation/source-gate PG methods. No pending or skipped PG run counts
as native acceptance. Ordinary legacy scheduling has not acquired the producer's
new reservation behavior through a product backport.

The producer's FOR NO KEY UPDATE gate excludes source UPDATEs while permitting
FK KEY SHARE. Its separate native compatibility case addresses an analysis-row
first lock followed by an evaluation FK insert; it is not an end-to-end old-guard
HTTP evaluation run. The guarded document NOWAIT fence and the release-time
drain of unguarded processes remain required.

Every child discards stdout/stderr at OS descriptor level before app imports,
including loader, SQL bind and future-result exception output. The controller
exports only fixed stage/method IDs, counts, booleans and source versions. It does
not emit exception values, trace variables, generated JSON/body, DB, raw diff or
generated-data hashes. CI uploads only three explicit safe summary/source-version
files. No tests.log, screenshot, temp directory or workspace glob is uploaded.

The disposable CI PostgreSQL container has Docker logging disabled. Before any
generation, CI verifies that driver and configures/checks effective server statement,
parameter, detail and duration logging settings on fresh connections. Python-only
FD suppression is insufficient for server/teardown logs. These settings affect
only the fresh test container; production logging is never accessed or changed.
Failure to verify either layer stops before generating data. No native PG result
or logging-configuration success is claimed until the dedicated CI actually runs.

The dedicated validation/guarded-rollback-independent-20261112 branch push runs
this workflow. A separately opened PR can run other existing required workflows.
The workflow's optional native PG flag uses the existing disposable test URL;
it is not a production setting and is never enabled by product code.

A rejected correction may normalize the separate replacement preview form;
that existing staging behavior is not source replacement. Tests preserve every
original document/source, saved result/audit and business record, and all
replacement columns except the editable preview JSON. Direct final replacement
refusal is also checked for full table equality.
