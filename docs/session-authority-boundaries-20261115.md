# Session authority: next transaction and response boundaries

Non-production research only. Baseline: official main `7efa2fee57e64c17d64ba0c14c17a973ae1cb7ae`, tree `7cc7397b63611d3aa6a33c24908d3e60d3d66cdf`. The local baseline has the identical tree but a different commit ancestry because transport uses the approved connector. The initial characterization changed no runtime behavior; the limited candidate-only follow-up is described below. Push is owned by a separate lane.

## Initial characterization (before limited follow-up)

Two real Flask-app characterization tests use synthetic in-memory data only:

1. A completes login, B successfully replaces A; a request carrying A's old cookie returns API 401. Deliver B's Set-Cookie first and A's later response last. The late response deletes B's cookie. CAS-conflict suppression from #397 does not cover this path. This is availability/session continuity loss; the test does not show unauthorized access to B.
2. An actual request passes the authority check; the test revokes the authority immediately afterward, before a synthetic test-only write route runs. The write still commits. The test route exists only in the fixture. This proves request-entry validation is not a commit-time fence; it is not a PostgreSQL concurrent interleaving test.

The initial tests asserted the then-current known defect to preserve reproducibility. A green result means the defect reproduced, **not** that shared-device authentication is ready. The follow-up below replaces these with positive tests for its explicitly limited scope.

## Why not suppress every stale Set-Cookie

Expired sessions currently rely on clearing the cookie to reach a fresh login. Blindly suppressing their responses leaves a stale authority in the browser, and begin_replacement rejects it. It can block re-login. A DB freshness read in save_session also has a race between check, header generation, and network delivery. Merely adding another SELECT is not a complete fix.

## Next implementation boundary

- First design an explicit, tested reauthentication/reset transition alongside response ordering. No anonymous name switch, shared password, or weakened MFA. Consider a stable opaque session handle with server-owned revision/identity, rather than letting arbitrary late signed-cookie snapshots choose identity. A browser generation gate alone is insufficient for plain document navigations and HttpOnly Set-Cookie.
- For important DB writes, acquire and validate the authority row in the **same transaction** as the domain write and hold its lock through commit. Replacement/logout must use a compatible lock order. Define the winner by serialization: a write that commits before revocation may finish; one ordered after revocation must not mutate data. Recheck expiry at the chosen transaction boundary; document long transaction semantics explicitly.
- Authority-row locking alone does not serialize changes to User.login_locked, password_changed_at, account_identity, role, or Company.active. The selected real write must also guarantee user/company/permission/target-record predicates within the same transaction and document a consistent lock order for those mutations.
- Do not add a global SQLAlchemy before_commit hook without auditing nested transactions, internal commits, auth issuance/revocation, workers, and audit logging. Such a hook could intercept its own security writes or unrelated background tasks.
- Candidate first real write paths: vehicle analysis feedback and evaluation (`dkss_app/analysis_feedback.py`, functions save_vehicle_analysis_feedback / save_vehicle_analysis_evaluation, currently direct commits). These must retain existing company/user authorization and CSRF. No authorization broadening.
- Required next evidence: isolated PostgreSQL two-connection commit/revoke interleavings in both orders, rollback/exception handling, expiration while locked, deadlock/timeout fail-closed, then one real route integration. Local SQLite cannot prove row-lock behavior.
- External side effects such as notification sends are not atomic with a DB transaction. Coordinate with the Push owner; do not claim DB locking cancels already-sent notifications.

## Verification

Initial characterization: two new tests passed in 3.057 seconds. Follow-up candidate integration: 21 tests, 2 PG-only skips, 7.711 seconds. No repeated aggregate run, production connection, settings change, credential inspection, CI publication, merge, or deploy. Production timeout/unlock policy remains undecided.

Independent read-only review confirmed the two characterizations are valid and fixture-local, with no test-route registration outside the fresh test app. The broader user/company authorization transaction requirement above was added from review.

A stable handle must never reinterpret an already-started old-person request as the new person: capture `(owner, revision)` at request entry and require the same pair at the write boundary; mismatch rejects. Bind CSRF/transition nonces to that boundary as well. A shared handle is session routing, not proof of the current human's identity.


## Limited implementation follow-up (not full shared-device acceptance)

The two characterizations are now replaced with scoped positive acceptance:
- Rejected API polls do not set or delete the cookie. Interactive `/login` retains the existing expired-cookie reset and personal password/MFA flow. This does NOT resolve late HTML navigation, delayed successful authentication, CSRF errors, or other general responses; a complete versioned-session protocol remains required.
- Only the vehicle analysis evaluation commit uses a candidate-only fence. With candidate disabled the helper performs the same ordinary commit and no authorization query. With the candidate enabled it disables autoflush until authority/company/user/vehicle rows are locked, validates current identity/lock/password version/role/company/vehicle and expiry after lock waits, then commits under those locks. Failure rolls back pending mutations. Revocation ordered after this lock waits until commit; revocation already committed causes refusal.
- Lock timeout/deadlock/database exceptions roll back and propagate; they do not fail open. No automatic retry is added. Expiry is defined at the last authorization check before commit, not a guarantee against wall-clock expiry during the final database commit.
- This is not a global write fence. Background tasks, external delivery, other routes and duplicate-return read branches are not covered. Existing company/vehicle filters and CSRF are unchanged.
- Added PostgreSQL-specific two-thread actual-route write/revoke ordering test; execution pending isolated CI. SQLite results do not prove locks.

Independent follow-up review found the login dirty-user autoflush could reverse the lock order. begin_replacement now suppresses autoflush until authority CAS has executed; a focused real SQL-order test passed (1 test/1.595s). PG blocking proof uses pg_backend_pid/pg_blocking_pids instead of timing alone. The feedback route is deliberately left unchanged until equivalent real-route coverage exists. Proposal-analysis revision concurrency is outside this authorization fence; this limitation is not a claim of full transaction isolation for business content.

First isolated PostgreSQL18 run:22/22 passed in12.737s, run43695118713/job132753827359, exact head d72d12a038a598b550bff26ffc166ed584ae6aaa/tree5c2f53a938848b9b3adc68ac5c1903ef59d1f1bd. This includes observed DB blocking and both revocation/write orderings. Follow-up adds no-cookie suppression also to commit-fence rejection (focused local test1 passed/1.530s); final-head CI must be checked separately.
