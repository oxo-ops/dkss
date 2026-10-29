# Durable document intake and OCR

## Problem and change

A 184,053-byte, six-page maintenance invoice caused `WORKER TIMEOUT` while the
sync Gunicorn worker was waiting for OCR inside the progress response. The existing
5-second response heartbeat did not prevent the sync worker's timeout.

The current import page now posts to `/vehicle/data-import/jobs`. This request
validates and persists originals, then returns HTTP 202 with a receipt. A background
reader processes persisted drafts outside the HTTP request. The status page polls
short GET requests and provides the existing review screen when reading finishes.

- Upload: up to 50 PDF/PNG/JPEG files, 20 MiB per file, 200 MiB combined per batch.
  These are application admission bounds, not a production memory/throughput guarantee.
- Files are flushed and detached one at a time; an entire batch is not retained in
  the Python identity map. Status polling and review lists do not select source blobs.
- One background reader runs per Gunicorn worker process. Defaults are one process,
  four HTTP threads and one OCR reader; four HTTP threads do not mean four OCR jobs.
- Source format, SHA-256 and active company/user authority are checked before reading.
- A receipt belongs to its company and creator. Status, review, source and retry
  endpoints preserve the original authorization and CSRF protection.
- Successful files remain available when another file fails. Failed rows can be
  retried without rereading successful rows, including after the successful subset
  has been registered. Existing original-source deduplication still applies.
- Repeated submission of the same upload key does not create another set of drafts.
  Deterministic draft IDs and their primary-key constraint fence simultaneous retries.

## Persistence and restart behavior

No table or column was added. Existing `VehicleDocumentImportDraft` rows use the
additional statuses `queued`, `reading` and `read_error`. While OCR is pending,
`result_json.ocr_job` stores its progress, lease token and attempt count. The existing
preview schema and final registration-result schema remain unchanged.

Claim and renewal are conditional updates. A stale worker cannot overwrite a newer
owner's result. A separate heartbeat renews the 120-second lease every 15 seconds,
including while AI is waiting without producing output. Expired leases can be
reclaimed after restart; three interrupted attempts stop automatic recovery and
require an explicit retry. API errors themselves are not automatically retried.

Originals and accepted receipts survive a process replacement only if the existing
application database is persistent. Use the production PostgreSQL database or an
appropriately persistent database deployment. A Render Free web service can sleep
when idle; background work is then suspended until the service starts again. Use
an always-running service for uninterrupted bulk processing. This change does not
purchase a plan or add a separately billed service.

OCR calls are at-least-once across crashes: a process loss after sending a request
but before saving its result can cause an API call to be repeated during recovery.
Database ownership fencing and existing source deduplication protect saved business
records; they cannot guarantee that an external API is billed only once.

## Deployment

See [runtime operations](runtime_operations.md) for the Windows/Linux distinction,
required and optional settings, embedded versus explicit worker startup, stopping,
and safe diagnostics. The explicit worker CLI runs even when embedded automatic
startup is disabled by `DOCUMENT_IMPORT_WORKER_ENABLED=0`.

The intended Render Start Command is:

```
gunicorn -c gunicorn.conf.py app:app
```

The existing `gunicorn app:app` command also automatically loads a configuration file
with this default name from the project working directory. Check for `Using worker:
gthread` in startup logs. The post-worker-init hook starts the reader; local Flask
runs also start it after intake or status access. Factory/import alone does not
connect to or change the database.

- `WEB_CONCURRENCY=1` and `WEB_THREADS=4` are defaults. More web processes also mean
  more OCR readers and higher peak memory/API concurrency.
- `DOCUMENT_IMPORT_WORKER_ENABLED=0` disables the embedded reader, for maintenance.
- `DOCUMENT_AI_TIMEOUT_SECONDS` defaults to 600, with a permitted range of 30–1800.
  This is the AI socket/idle timeout, not an end-to-end batch completion promise.
- Gunicorn timeout is 120 seconds for worker health, not an OCR job duration limit.
- Previously cached pages and non-JavaScript callers retain legacy import routes;
  the gthread deployment also addresses their sync-worker timeout. New UI intake
  uses the durable queue. No automatic business-record registration was added.

## Validation

All 393 Python regression tests and all four Node controller tests passed.

- 50-file receipt processed sequentially with mocked AI, all results ready for review.
- Failure isolation, retry-after-partial-registration, raw-source integrity, revoked
  authority, creator/company boundaries, CSRF, size rejection/transaction rollback,
  duplicate receipt and stale-lease fencing are covered by isolated DB tests.
- Status SQL excludes the source BLOB column. A later request can resume a saved
  receipt without resending the original.
- Four Node tests cover receipt navigation, retry keys, batch admission bounds,
  duplicate clicks and server error display. They run in regression CI.
- Actual Gunicorn 26.2.0 was launched with a 30-second health timeout, gthread and
  one process. The original invoice was uploaded as part of a three-file batch.
  OCR was mocked to wait 36 seconds for one file and fail another. Acceptance
  returned in 0.017 seconds, status GETs took at most 0.012 seconds, and the batch
  finished after 36.5 seconds with two successes and one isolated failure. The
  review page returned HTTP 200. Original PDF preparation and its six pages were
  checked; actual paid AI extraction was not performed in this validation.
- This does not establish production Render memory capacity, 200-MiB proxy upload
  support, PostgreSQL multi-instance concurrency, or OCR accuracy on every invoice.
