# Integration boundary and next connection steps

## Connected in this change

The implementation, synthetic fixtures, tests, and documentation are preserved
independently under `tools/quality/log_observation_ledger`. The dedicated
`Q09 Offline Log Observation Ledger` pull-request workflow verifies the exact
candidate head/tree and checks the recorded hashes before running all 54 tests.
It uses Python's standard library, a standard hosted Linux runner, fresh private
temporary state, no application imports, and an empty inherited test environment.
No dependency installation or new service is added. This is CI validation, not a
scheduled log collector or an alert transport. Remote outcomes must be checked
on the actual candidate SHA; this document is not itself proof that CI passed.

The workflow has read-only repository permission, disables persisted checkout
credentials, and declares no production environment, secret, database, paid
runner, schedule, notification recipient, or deployment action. Existing CI
workflows and product files are unchanged. The separate product-feature,
analysis-runtime, identity-fix, and rollback work is outside this change.

## Not connected

No live Render log response enters this repository or CI. No durable operational
ledger has been provisioned. There is no recurring job, notification sender,
delivery receipt store, recipient configuration, or human acknowledgment path.
New observed markers remain `not_sent` / `not_received`; previously uncertain
delivery must stay uncertain until the transport outcome is reconciled.

An existing connected Render read API is a candidate for future collection.
That access is not a credential usable by this offline Python program or by
GitHub Actions. Do not export credentials, add a GitHub secret, create a Render
cron service, reuse application notification credentials, or trigger a deploy
to bridge that gap. Do not repurpose an existing operational automation whose
scope differs from this ledger.

## Minimum safe future wiring

1. Confirm the existing authorized workspace/resource and a bounded read window.
   A trusted recorder may query application logs without text, level, or other
   narrowing filters. Retain each actual query/reply pair in memory, including
   every continuation page and sanitized failure status. Check routing and API
   success before normalization. Never retain or publish raw messages, original
   log/resource IDs, routing metadata, exception text, or credentials.
2. Choose an already-authorized scheduler and durable private state location.
   Set ownership, retention, single-writer behavior, and capacity handling before
   enabling it. Keep a bounded overlapping reread policy because timestamp-only
   pagination cannot establish complete coverage. Never replace
   `read_checkpoint = null` with a timestamp progress claim.
3. Validate the adapter with synthetic cumulative pages and multiple runs first.
   Check duplicates, late arrivals, partial pages, conflicts, process crashes,
   uncertain writes, and capacity exhaustion. The current 54 tests do not prove
   that a future adapter or a scheduled live run works.
4. Separately authorize the exact existing notification destination and fixed
   safe template. Add durable per-attempt receipts and outcome reconciliation
   before any send. Do not automatically retry an uncertain send. A successful
   send API call is not delivery or human receipt, and human acknowledgment
   requires its own evidence. Do not send real test alerts without permission.
5. Verify a scheduled run, transport delivery, and human acknowledgment as
   separate acceptance results. Do not label CI success, a linked terminal page,
   or zero observed markers as a completed monitoring system or an all-clear.

None of these future operational connection steps is enabled by this draft.
