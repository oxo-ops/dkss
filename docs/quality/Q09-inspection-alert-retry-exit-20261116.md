# Q09 inspection reminder incomplete-tick exit status

Base: main `1f37376f36f48741194f42aff5bad5ac00c24704`.

The quality plan separates safe logging, operational monitoring and production acceptance. This local follow-up closes a concrete incomplete-tick success signal, not formal monitoring acceptance.

## Problem and scope

`process_company` returns `retry: true` after rolling back an IntegrityError or OperationalError. The CLI previously printed that report and exited successfully, including when database unavailability prevented a tick. The report could also retain a positive `expiry_candidates` count even though its notification transaction was rolled back.

The command now preserves per-company JSON output but treats any retry report as an incomplete overall tick. It follows the existing fixed-category safe database-error log path. Single-shot use exits nonzero; watch mode continues on its existing cadence. Successful companies' already-committed work remains intact. Rolled-back expiry counts are zeroed with notification/plan counts.

No changes to HTTP polling, retry classification, company locks, scheduling, recipients, notification content or external delivery. An actual concurrency retry may now produce a nonzero single-shot exit, intentionally signaling incomplete work rather than falsely claiming completion. Reruns retain existing deduplication. No new daemon, resource, database schema, production setting or deploy.

## Evidence

- Before fix: 3 new tests produced 4 failures: both database exception types gave exit 0, watch emitted no safe failure log, and rolled-back expiry count stayed positive.
- After fix: 58 focused tests passed (retry, safe logging, inspection alerts and Q05 date suites), 6.303 seconds.
- Added mixed-company test: all 4 retry tests passed, 1.524 seconds; the successful company's Run/Notification/receipt remains while the next company's retry makes the overall command nonzero.
- Synthetic SQLite and canary payloads only. External delivery mocked, no production DB or real notification.

Remaining limits: IntegrityError/OperationalError classification is intentionally unchanged; HTTP polling retry reporting and secondary rollback/remove failures remain outside this patch. Real scheduler exit-code handling and production monitoring acceptance are still separate work.
