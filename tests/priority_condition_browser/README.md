# Synthetic condition-preview browser acceptance

Prepared against exact candidate `f0005bb4a7fe7b8674f4dfe1f319228ac4de1089`, tree `b4cddb88a6137855d0b0a03a579b0f2106f24592`. This is a narrow new browser suite, not a rerun or extension of previously accepted overview/history or PostgreSQL suites. The application checkout must be clean and match both the fixed SHA and complete tree. No application code is modified.

## Cases

- Calendar AND: 45 days and one calendar month retain each threshold and the later group date, 2026-12-15.
- Calendar OR: the same conditions retain the earlier group date, 2026-11-30.
- Mixed distance/calendar AND: 1000 km and one calendar month have no invented whole-group calendar date.
- Single calendar month: threshold one calendar month is distinct from 10 elapsed days and 20 remaining days; due 2026-11-30 from baseline 2026-10-31. No 90%-of-month score rule is created.
- At 1440 and 390 pixels, each case checks original quote as text, including markup-looking content and a long unbroken token; relation, thresholds, units, baseline/reference/due dates, elapsed/remaining/excess, disclaimer and panel overflow. Screenshots contain synthetic values only.
- One representative same-page refresh flow changes the host-registered reference version. The real API must invalidate only condition facts, remove the previous section and preserve valid score badges. Restoring the valid host registry restores one section, not duplicates.
- One intentional intercepted result-GET failure verifies old conditions and scores disappear and recover on the next real refresh. Playwright's clock advances the application's existing 60-second refresh timer; no DOM rewriting, hidden-control forcing or API-validation patching is used.

Every case compares the condition-free and condition-enabled analysis projections, and preserves saved analysis bytes, proposal identity/revision/action/feedback and the user's synthetic stored preference. A SQL listener remains attached throughout all measured GETs and requires zero mutations. Fixture setup and host-only registry changes are outside database mutation claims; no web endpoint can register those inputs.

## Isolation and execution prerequisites

Use an authorized isolated runner with Python 3.12, candidate requirements, Python Playwright 1.62.0 and official Chromium already installed. Do not retry a local browser launch in an environment where socket execution was denied. Installation requires distribution network access and is separate from the isolated test phase.

The runner clears inherited environment variables, external database URLs and integration credentials. It permits only newly created disposable SQLite. Python socket connections are forbidden. Chromium requests are intercepted: only GETs at `http://127.0.0.1:8765` are served through real Flask route responses and a synthetic authenticated test session. External origins and non-GETs are aborted and fail acceptance. The single deliberate result-fetch abort is counted separately. There is no server listener or production access. SQL diagnostics include only endpoint, operation and table, never query text or values.

This proves neither real HTTP/TLS transport nor live login/MFA, proxies, deployment or real data. Request interception is not a kernel-level network firewall. The numerical score boundaries are not being validated as maintenance policy here, and condition display remains separate from scores. AND scoring, a 90%-of-month policy and operational approval are not implied.

Fixture-only preparation, without launching a browser:

```sh
DKSS_BROWSER_ARTIFACT_DIR=/absolute/sidecar \
  bash tests/priority_condition_browser/run-isolated.sh \
  /absolute/fixed-candidate /absolute/venv/bin/python --preflight-only
```

Only in an authorized environment that supports browser execution:

```sh
DKSS_BROWSER_ARTIFACT_DIR=/absolute/sidecar \
  bash tests/priority_condition_browser/run-isolated.sh \
  /absolute/fixed-candidate /absolute/venv/bin/python \
  --run-browser --chromium /absolute/official/chromium
```

Successful preflight is `PREFLIGHT_PASS_BROWSER_NOT_RUN`, never browser acceptance. A browser pass requires exit zero, `PASS`, `browser_started=true`, `browser_acceptance_passed=true`, `saved_state_unchanged=true`, no SQL mutations or unexpected requests/errors, and the original screenshots. The runner creates and prints a new run-specific subdirectory under the requested artifact root, so a failed run cannot overwrite or masquerade as a previous pass. Primary failures and separately typed cleanup failures are retained in JSON; cleanup failure never produces a passing exit. Only safe reports/screenshots/logs should be retained, not SQLite or browser profile data.

## Publication boundary

The companion workflow is restricted to the dedicated `verify/priority-condition-browser-20261110` branch in `oxo-ops/dkss`, targeting `verify/quality-feature-20261110`. It checks out the fixed application source separately from the pull request head containing this harness. Only opening that dedicated pull request or an explicitly published new head can trigger the job; reopening or marking it ready does not. There is one browser invocation per run and no automatic retry. Publication and any subsequent head updates belong to the authorized CI coordinator. No existing accepted candidate, workflow, production service or data is changed. The job has read-only repository permissions, no deployment and no secrets.
