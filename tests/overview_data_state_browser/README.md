# Ordinary overview saved-priority data-state acceptance

This narrow browser suite targets application commit `779c9f2f3ff1e8dc3574e12c82019bdd4e8d436c`, complete tree `9ce8508d28a03960f6c07eead1a1ba3ea13e7186`. The workflow checks out that fixed candidate separately from the current pull-request harness and requires exact commit, tree and a clean checkout before Chromium runs. Existing quality/priority browser and PostgreSQL supplemental workflows keep their original pins and paths; this suite does not repeat them.

## Scope

Two viewport widths, 1440 and 390 pixels, cover ordinary vehicle overview with exactly five synthetic saved proposals: high, medium, low, an invalid string and null. Assertions check only the three real priority badges, a separate data-state message for invalid/null values with no fourth priority badge or accessibility label, stable order, unchanged original proposal text, existing accepted/in-progress feedback, exact detail links, detail opening/closing and proposal-panel/text overflow. Real detail routes and saved source links are used, without weakening freshness or source guards.

Saved analysis JSON bytes, original priority values, proposal IDs/revisions, actions, feedback and the preseeded same-vehicle preference must remain unchanged. SQL mutation diagnostics contain endpoint, verb and table only, never raw SQL, parameters or row contents. Normal notification polling must run. Its existing company lock UPDATE and reminder-run INSERT/UPDATE are explicitly distinguished from proposal writes and are the only allowed writes in the synthetic flow. This is not a global read-only claim for the ordinary application. There is no preview-mode suppression or notification mocking.

## Isolation and limitations

The suite uses disposable synthetic SQLite with no real account, operational data, production URL or credentials. The isolated runner clears inherited environment variables and disables external integrations. Python socket connections and SQLite outside the new temporary root are forbidden. Every browser request is intercepted: only GET requests to `http://127.0.0.1:8765` are fulfilled through the real Flask test client and synthetic authenticated session; external origins and non-GETs are aborted and fail acceptance. There is no listening HTTP server. Service workers are disabled for this test context. No production or user-computer settings are changed.

The hosted workflow has read-only repository permissions, no repository secrets, and no deployment step. Official package/browser installation requires their distribution networks. Application request interception is not a kernel-level firewall and does not claim OS-wide Chromium background-network isolation.

Passing proves real Chromium rendering/interactions with real in-process Flask GET responses. It does not prove real HTTP/TLS transport, live login/MFA, proxy behavior, a deployed service or real-data acceptance. It does not certify unrelated features or replace PostgreSQL tests.

## Execution

Use Python 3.12 with candidate requirements and Python Playwright 1.62.0. For a fixture-only local checkout with identical complete tree but different commit metadata:

```sh
DKSS_BROWSER_ARTIFACT_DIR=/absolute/sidecar \
  bash tests/overview_data_state_browser/run-isolated.sh \
  /absolute/candidate /absolute/venv/bin/python \
  --preflight-only --allow-identical-tree-preflight
```

The tree-only option cannot start Chromium. A real browser run requires the exact fixed public commit and an installed official executable:

```sh
DKSS_BROWSER_ARTIFACT_DIR=/absolute/sidecar \
  bash tests/overview_data_state_browser/run-isolated.sh \
  /absolute/candidate /absolute/venv/bin/python \
  --run-browser --chromium /absolute/installed/chromium
```

Preflight reports `PREFLIGHT_PASS_BROWSER_NOT_RUN`. Browser acceptance requires exit zero and `browser-result.json` containing `PASS`, `browser_started=true`, `browser_acceptance_passed=true`, `saved_state_unchanged=true` and `normal_notification_polling_observed=true`. Preserve all failures for diagnosis rather than automatically retrying. Only synthetic reports/screenshots/logs are uploaded, not the temporary database.
