# Q04 vehicle master selection browser acceptance

This is the first browser acceptance suite for the new selection-proof fix. It does not rerun the earlier Q04 PR acceptance suites or the full application tests. PostgreSQL locking/concurrency remains in the existing Q04 PostgreSQL workflow; this suite tests only disposable SQLite.

The workflow checks out the exact PR head (or the exact dispatch commit), verifies HEAD, uses `contents: read` and `persist-credentials: false`, Python 3.12 with pinned `requirements.txt`, Node 22, and the same official Playwright 1.62.1/Chromium setup as existing browser workflows. Dependency setup may download those official packages. The test processes receive a cleared environment with no external credentials.

Six cases at one desktop viewport:

1. Edit → confirmation → Back → change name-valued office/type choices → reconfirm → save.
2. New → confirmation → browser Back/Forward → rapid double save → explicit duplicate POST, ensuring one vehicle.
3. Stale office: independent private context deletes the current master, re-registers the same name with different ID/generation, then attempts the held save.
4. Equivalent stale vehicle-type flow.
5. JavaScript-disabled manual new/back/change/confirm/save.
6. Shipped certificate registration JavaScript consumes an intercepted synthetic result, passes the selection proof to the common new-vehicle route, confirms and saves. No real extractor, OCR or AI endpoint is executed.

Stale JSON requests must return 409 with all DB tables unchanged. Ordinary HTML POSTs use the existing 302 → GET recovery: the affected choice is blank, other input and the unaffected choice remain, and reconfirmation must not select the same-name replacement. Every case compares foreign-company rows and records HTTP steps, console/page errors, sanitized snapshots and screenshots. Screenshot artifacts still need human visual inspection; passing DOM assertions is not a visual-review claim.

Each case uses a new SQLite file and private browser contexts. The Python fixture rejects other database connections, external socket/DNS traffic, urllib, SMTP, boto3, webpush, subprocesses, external writes and application background workers. The fixture marks IPv6 unavailable before importing urllib3 so no IPv6 capability listener is attempted. Only the harmless in-memory limiter expiry timer and the preflight HTTP-server thread are allowed. CSRF is on; fixture-only MFA and rate limiting are off. Browser requests are restricted to that fixture origin with service workers blocked, a rejecting proxy for nonloopback traffic, and background networking disabled. No production database, existing profile, CI secret, paid service or external document is used.

Run HTTP preflight without launching a browser (choose a new, nonexistent work directory):

```sh
env -i PATH="$PATH" LANG=C.UTF-8 HOME="$TMPDIR" \
  PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 \
  "$(command -v python)" -B tests/q04_vehicle_master_selection_browser_server.py \
  --work-dir "$TMPDIR/q04-preflight-new" --preflight
```

After installing the pinned test runtime in a separate test-only directory, set the same `PLAYWRIGHT_BROWSERS_PATH` for both installation and execution:

```sh
env -i PATH="$PATH" LANG=C.UTF-8 HOME="$TMPDIR" \
  NODE_PATH="$TMPDIR/q04-selection-node/node_modules" \
  PLAYWRIGHT_BROWSERS_PATH="$TMPDIR/q04-selection-browsers" \
  Q04_PYTHON="$(command -v python)" Q04_SOURCE_SHA="$(git rev-parse HEAD)" \
  "$(command -v node)" tests/q04_vehicle_master_selection_browser.cjs \
  "$TMPDIR/q04-browser-new"
```

The runner fails unless all six cases complete. The workflow has finite job/step/process timeouts and always uploads focused evidence, excluding SQLite databases and browser profiles. Local Chromium previously failed before app startup with socket `EPERM`; that is not a browser pass. Initial CI results must be reviewed before acceptance is claimed.
