# M06 compatible recovery candidate

Base: `cf202c12e3ce7ea135ed18052dc5aaf1ab120dee` (PR #351). This is a separate, review-only recovery branch; do not merge it into #351 as routine feature work.

## Actual recovery scope

This candidate removes automatic OCR consumption inside Gunicorn Web workers and forces `DOCUMENT_IMPORT_WORKER_ENABLED=0` in that process. It keeps all M06 kind separation, legacy evidence resolution, unknown-only notification holds, receipt preservation and original-reference code unchanged. Existing application initializers are retained. No schema, data migration or bulk reclassification is included.

The recovery target is Web-embedded OCR startup/lifecycle or mixed consumer issues. It is **not** a rollback for an unidentified fault in the M06 business implementation, which remains identical to #351. For such a fault, diagnose and prepare a compatible fix before resuming writes. Returning to `0919278742e4f21f08c405b3946d2f8fec410bc4` after new values were saved is not compatible: old readers/writers and duplicate queries omit `periodic_12month`, and notification GET paths can write.

OCR requires a separately operated explicit `flask --app app document-import-worker` at this candidate's exact SHA. That CLI intentionally bypasses the Web flag. Its existence in source is not evidence that a separate service is deployed. Provisioning/starting it and changing production topology require separate approval. Without that consumer OCR processing is unavailable; do not represent this profile as a transparent full-service rollback.

## Nonproduction validation

The frozen #351 application first creates a synthetic SQLite dataset. A separate candidate process opens the same database, then another #351 process reopens it. Outbound socket connections are rejected; OCR results and original PDFs are synthetic. The reusable harness is `tools/m06_recovery_switch_acceptance.py` (set `M06_SWITCH_EVIDENCE_DIR` to a new temporary directory, then execute stages `seed`, `candidate`, `return` from the respective checkouts with `PYTHONPATH=.;tests`). Never point it at an existing application database. Seed refuses to overwrite an existing fixture.

Inputs include confirmed legacy 12-month records/plans from upload and human confirmation; an unchanged ambiguous legacy row; new independent 12-month and vehicle-inspection plans; same-day independent executions linked to one original; held, closed/read and normal notices/receipts. Candidate reads API, vehicle karte and Excel; original bytes must match SHA256. Candidate duplicate previews reject same-kind/same-date actuals and same-kind/same-month plans with 409. New separate kinds remain registerable. Candidate writes additional February 2027 plans and July 14 executions of both kinds, then #351 reads them and rejects duplicate execution registration. Existing persistent rows, including every receipt and read/history field, must remain identical throughout. Alert bookkeeping runs are excluded from the business snapshot, not receipts or notices.

All three stages passed locally on 2026-10-30. The additional profile tests verify forced Web disable despite an inherited enabled flag, retained initialization hooks, and explicit CLI invocation. Targeted existing queue tests cover stale-owner rejection and retry limits. Evidence manifests contain file hashes; no production data is included.

## Production cutover plan — preparation only

1. Before approval, inventory actual Web instances/PIDs and supervisors, embedded OCR, any separate CLI consumer, external cron and watch/tick processes. Source candidates include `inspection-plan-alerts --watch`, `vehicle-karte-analysis-worker`, `vehicle-karte-analysis-tick`, `public-knowledge-tick`. Their actual deployment is unverified. `document_schedule` is claim fairness, not proof of an external cron. Record restart policies, exact artifact SHA and how each old generation can be prevented from restarting.
2. Obtain approval for production deployment and any necessary service/configuration actions. Preserve evidence of current release, job IDs/status, attempts, lease owner/generation and lease deadlines without exposing secrets. Inventory and backup operations themselves must follow the approved production boundary. No such operations have been performed by this task.
3. Under the approved maintenance procedure, stop new admissions and all inventoried old writers/consumers and their restart sources. HTTP traffic removal or a new Live deployment alone is insufficient. `stop_worker` sets an event, does not join/cancel AI; Gunicorn graceful timeout is 30 seconds while AI default timeout is 600 seconds. The separate heartbeat can renew a lease every 15 seconds while the old PID survives.
4. Verify termination of every old PID/instance and every scheduled old command, using platform/process evidence. Do not treat elapsed 120 seconds, an environment flag, or an HTTP status/job GET as this evidence: status/job GET can start an OCR worker in the normal profile. Preserve remaining reading-job lease/attempt state. Do not steal an unexpired lease, reset attempts, bulk-reset jobs or create duplicate retry jobs. Only after old owners are gone may the existing expired-lease recovery and attempt limits operate at the approved new SHA.
5. Start approved Web and explicit OCR consumers at the exact selected SHA; verify each process's revision and role, restart settings and absence of old generations. This candidate's Web cannot consume OCR; the explicit CLI can. Check the existing representative input/notification/original flows against approved acceptance data, with approval for any production writes. Application startup also invokes driving-access/coupling initializers: OCR-disabled startup is not a no-write diagnostic and must not be substituted for M01 stage B.
6. On failure, stop admission and new writers/consumers using the approved procedure; preserve logs and lease/history state. Identify whether the failure is within this candidate's recovery scope. If so, activate this validated candidate only after old-owner retirement and same-SHA role checks. If not, keep the affected operation stopped and prepare a compatible correction; do not deploy old `0919278`, rewrite saved kinds, or clear receipts. Reopening traffic is a separate acceptance decision.

## Remaining acceptance and proposed gates

These are recommendations, not approval to defer tests or deploy.

| Item | Proposed gate | Evidence / remaining limit |
|---|---|---|
| Representative real OCR → human confirmation → two independent kinds / shared original | Before release | Synthetic pipeline accepted; real OCR and ambiguous original quality not yet accepted. |
| M06 mobile input, confirmation, cancel/retry, both plans and same-day actuals | Emulated gate passed | Installed Chromium 390x844 and 360x844 touch emulation passed on #351; no forced clicks; old rows and other-kind completion preserved. Native devices, IME/pickers and Safari remain unverified. |
| M06 PostgreSQL concurrent registration, semantic duplicate and notification behavior | Before release | SQLite tests do not establish PostgreSQL concurrency. Existing Q02/Q10 PostgreSQL success is not direct M06 acceptance. Use isolated PostgreSQL, never production. |
| Representative-scale historical data: synchronous notification GET, annual table and Excel response and state invariance | Before release | Actual scale and acceptable latency are not yet defined. Agree assumptions/thresholds; do not invent production capacity claims or duplicate Q12 implementation. |
| Exact deployed process inventory, compatible artifact availability and old-writer retirement evidence | Before release | Procedure prepared, actual topology and process retirement not verified. Recovery candidate only covers the documented lifecycle scope. |
| Every OCR format, every device/browser, long-term traffic monitoring | Candidate for conditional post-release work | Broader than representative acceptance; requires explicit risk/owner acceptance, monitoring and fallback conditions. Not automatically deferred. |

PR #351 regression: 2014 tests, 212 skips. Independent audit: 50 class-level plus 162 test-level skip records; 210 PostgreSQL-condition and 2 native-Chromium-condition records. Same-head separate-job execution evidence exists for 49 records (19 classes and 30 tests); 163 lack such evidence. Missing evidence is not failure and does not invalidate other owners' completed work. M06's eight modules / 41 tests ran without skips. Do not describe all 212 as covered elsewhere.

GitHub CI success, merge, Render Live, and business acceptance are distinct. This work performs no production operation, merge, deployment, DB migration, M01 stage B or change to the P1 hold.
