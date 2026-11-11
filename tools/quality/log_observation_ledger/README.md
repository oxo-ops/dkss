# Q09: offline observation ledger, not a running monitor

This is a **nonproduction, no-cost preparation artifact**. It adds bounded cross-page/run deduplication and recorded read progress to the existing five-marker projector. It does not touch product code, use any service, start a schedule, send a notification, acknowledge an incident, or determine a root cause. A fixed log marker is evidence that a log record was observed, not proof of a business incident.

## Repository preservation

This directory preserves the reviewed offline implementation independently of
product code. See [INTEGRATION.md](INTEGRATION.md) for the synthetic-only PR CI
and the explicit boundary before scheduling or notifications. All commands below
run from this directory. The three Python source/test files remain byte-identical
to the validated artifact.

## Files and verified scope

- `log_ledger.py`: standard-library-only pure observation functions and optional private local state CLI.
- `log_event_receipts.py`: unchanged copy of the supplied projector. SHA-256 `f27d2a5647d1d1707e51ad2a06209d4ce7ebff315f34fe74ecbdcbc4be4732a7`.
- `test_log_ledger.py`: 54 passing synthetic tests of the new functions/CLI only. No existing app tests were run.
- `tests.log`: focused test result, not an integration/production certification.
- `synthetic-example.json`: synthetic query/reply fixture, containing no real data.

The initial offline validation used no network, inherited environment settings, Render request, real database, AI, SMTP, S3, paid service, installation, notification, scheduler, git publication, CI, or deployment. Tests use newly created private temporary state. Repository preservation adds only the PR CI described in INTEGRATION.md; it does not activate a live monitor.

## What is recorded, and what is not proved

The input must come from a **trusted recorder**. This offline tool cannot authenticate a tool call or prove that the recorder included every response. Each invocation supplies the cumulative, ordered transcript from the original explicitly declared query window. It must not supply just the final continuation page.

Each envelope binds the actual query resource, application type, direction, explicit start/end times, and limit to the actual reply. The first query must equal the declared window. Every later query must exactly match the preceding response's `nextStartTime`/`nextEndTime`, after nanosecond-preserving UTC normalization. Resource, type, direction, and absence of other filters remain fixed. A terminal response cannot be followed by another page. Missing, stalled, reversed, or mismatched continuations are reported.

`last_scan.chain_status = linked_terminal` means only that the supplied query/reply chain reached `hasMore=false` through correctly linked timestamp windows. `window`, `pages_linked`, `last_query_window`, `last_response_status`, and `last_response_has_more` record useful observed progress. A mid-chain API failure is recorded without its error text. `next_window` is only a diagnostic continuation hint for the same incomplete scan, not a safe next monitoring window.

**Render's available timestamp pagination description does not establish stable snapshots, tie-breaking of records at equal timestamps, late-arrival bounds, retention completeness, or a cursor-level completeness certificate.** Therefore every result retains `coverage_status = incomplete_timestamp_only` and `read_checkpoint = null`. Even an empty terminal response is not upgraded to a missing-free coverage guarantee. Nothing here automatically skips to the next window or declares monitoring complete. A future integration should deliberately reread overlapping windows and tolerate deduplication. A timestamp cutoff or arbitrary `complete=true` input cannot unlock the checkpoint.

`linked_terminal` can coexist with rejected/out-of-range records or semantic conflicts. Inspect `counts` and the pending review records; it is not an all-clear flag. The script does not claim there were no errors merely because a page lacked known markers.

## Privacy and deduplication contract

- State contains a hashed resource binding, SHA-256 hashes of resource + NUL + provider log ID, canonical timestamps, fixed marker names, fixed allowed enum values or `unverified`, and fixed statuses/counts. It never persists a raw query/response, raw resource/log/instance ID, message, error body, PII, or credential.
- The five recognized markers are `UPLOAD_DELETE_FAILED`, `EMAIL_DELIVERY_FAILED`, `WEB_PUSH_SEND_FAILED`, `DOCUMENT_IMPORT_FAILED`, and `INVOICE_REVIEW_FAILED`.
- Unknown or duplicated classification fields retain their known marker with `unverified` values and review required. Multiple known markers in one record are retained as a fixed-name review item rather than silently dropped. A future `*_FAILED` marker is retained only as the fixed `unknown_failure_marker` category, never as the original name/text. When known and unknown markers occur together, the known classification is retained with `unknown_marker_present = true` and review required; a later same-ID appearance of that flag is a semantic conflict.
- IDs of valid unrelated records are also hashed and retained. This allows a later same-ID change from unrelated to known marker to be surfaced as a conflict. Unrelated items are omitted from the pending-notification projection.
- Replays increment `replayed_log_id`; semantic changes for the same ID preserve all safe variants and increment `conflicting_log_id`. `total_conflicting_ids` remains visible across later runs. **Only sanitized semantic differences are detectable.** Changes solely in discarded raw text are intentionally not fingerprinted. Hashes are pseudonymous identifiers, not anonymization or cryptographic authenticity.
- Same timestamp/different ID records remain distinct. Timestamp comparison preserves all nine RFC3339 fractional digits; equivalent timezone spellings deduplicate.
- Rejected records, out-of-query times, nonmonotonic ordering, API failures, missing pages, and malformed page/query shapes are counted. They never advance a complete-coverage checkpoint.
- Bounds: 4 MiB CLI input, 100 recorded pages per call, query limit 1–1,000, 10,000 unique log IDs, 8 safe variants per ID, 16 MiB saved state. Capacity failure does not evict records or discard unsent markers. This prototype is intentionally not an unbounded production store; exceeding a bound requires a planned review/retention design.

## Minimal integration input

Normalize a trusted connector result in memory to this schema. Copy the resource/type/direction/time/limit parameters actually used and verify that no additional narrowing filters were used; do not reconstruct a supposedly complete chain from the final page. Validate workspace routing separately, then omit routing metadata from this normalized query contract. Strip the connector wrapper only after checking tool/API success. Map failures to `{"ok": false}`. No original input file needs to be saved by the adapter.

```json
{
  "resource": "srv-synthetic12345678",
  "window": {"startTime": "2026-11-11T10:00:00Z", "endTime": "2026-11-11T12:00:00Z"},
  "direction": "forward",
  "pages": [{
    "query": {
      "resource": ["srv-synthetic12345678"], "type": ["app"],
      "direction": "forward", "startTime": "2026-11-11T10:00:00Z",
      "endTime": "2026-11-11T12:00:00Z", "limit": 1000
    },
    "reply": {"ok": true, "page": {"hasMore": false, "logs": []}}
  }]
}
```

All five markers are covered by an unfiltered application-log query. This prototype deliberately rejects text, severity, instance, and other filters so a narrower query cannot silently be counted as broader observation. In particular, warning-level web-push markers must not be lost by querying only errors. A recorder querying multiple resources/workspaces must split them into separately bound ledgers and validate its own workspace routing. The current supplied resource ID is the ledger identity; this module makes no new Render call.

Pure API:

```python
new_state, safe_report = observe(old_state_or_none, recorded_transcript)
pending = pending_notifications(new_state, expected_resource)
```

`observe` never mutates its inputs. The optional CLI atomically commits the new state under a cooperative writer lock. It requires a pre-created owner-only directory; the file is mode 0600, symlinks/hardlinked state are refused, and existing state is strictly validated before any rewrite. The writer fsyncs file and directory. A crash can leave a lock; the tool never steals or auto-deletes a stale lock. Directory ownership and local processes remain trusted. This is not tamper-proof storage, encryption, or an adversarial multi-user file service.

Synthetic demonstration only:

```sh
state_dir=$(mktemp -d)
env -i PATH=/usr/bin:/bin HOME=/nonexistent /usr/bin/python3 -B -E -s \
  log_ledger.py --state "$state_dir/state.json" < synthetic-example.json
```

Run the same transcript again to observe a replay without creating a second pending marker. When adding a later continuation page, replay the whole cumulative transcript from its original window. The input is kept in process memory only by this CLI. Production adapters must not tee raw input into logs, shared files, shell history, or notifications.

On CLI error, the output deliberately says `LEDGER_NOT_UPDATED_OR_OUTCOME_UNCERTAIN`, without echoing input, path, or exception text. Inspect private state and lock before retrying: a failure after atomic replacement can mean the state commit already happened. A replay is observation-idempotent but increments the run/replay counters. No delivery occurs during either attempt.

## Delivery and acknowledgment remain separate

New marker records start with `notification_status = not_sent` and `acknowledgment_status = not_received`. A validated existing `uncertain` notification status is preserved on every reread. `pending_notifications` returns fixed safe variants and review flags; **uncertain is not permission to retry sending**. The ledger does not implement status changes, transport IDs, recipient selection, notifications, acknowledgments, or a notification outbox. `delivery_status = not_attempted_by_ledger` describes this tool's activity only.

Before any operational use, separately authorize and implement: existing-resource scheduling, access/retention limits, overlap and late-arrival policy, single-writer/capacity handling, trusted source recording, notification recipients and a fixed safe template, idempotent delivery with durable transport receipts, uncertain-send reconciliation, and actual human acknowledgment evidence. Notification delivery and human receipt must never be inferred from a read checkpoint, zero matches, or API success. None of those remaining steps has been performed here.

## Reproduce focused checks

```sh
env -i PATH=/usr/bin:/bin HOME=/nonexistent /usr/bin/python3 -B -E -s \
  test_log_ledger.py
```

These checks exercise the new functions and CLI with synthetic fixtures and private temporary state only. They do not establish live Render completeness, scheduler operation, notification arrival, or human receipt.
