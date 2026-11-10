# Frozen candidate browser acceptance

The workflow checks out application commit `3ca0f38e36f47ad94a625e71492bedbdd2f11841`, tree `cc05950a0ef99241ac1a80b320ddcafd0944c710`, into `candidate`. It reads the acceptance harness from the pull request head in a separate `validation` checkout. Later harness/CI commits do not silently change the application under test. A real browser run requires the exact candidate commit, complete tree identity and a clean worktree.

The narrow workflow runs on relevant pull-request changes for PR 361 from this repository only. It uses read-only repository permissions, no repository secrets, no deployment and no production service. Candidate Python dependencies and Playwright 1.62.1 are freshly installed on the hosted runner, then official Chromium is installed. These installation steps need access to their public distribution services.

## Test isolation

The fixture has disposable SQLite only: synthetic vehicles, six saved proposals, feedback, 30 maintenance rows, one inspection, one driving-report row, and a synthetic other-company sentinel that must not display. No real account, credentials, company records or browser profile are supplied.

The browser requests `http://127.0.0.1:8765`; every request is intercepted and fulfilled in-process through Flask's authenticated synthetic test client. There is no HTTP listener. Only GET requests to that exact loopback origin are served. Other origins and non-GET requests are blocked and recorded. Python socket connections and SQLite paths outside the new temporary fixture root are independently forbidden. The runner clears inherited environment variables before application startup. Temporary databases and HOME are outside both checkouts and are not uploaded.

This validates real Chromium rendering/interaction with real Flask route responses. It does not validate live authentication, network transport, TLS, proxy headers, service workers, real operational data or a deployed service. Request interception is not an OS-wide network firewall; no claim is made that Chromium background network traffic is kernel-isolated. The tested application requests are all intercepted, and only synthetic input exists in this job.

## Executable cases

- Overview at 1440/1024/390 pixels: five visible proposals, saved total six, order, remaining-item link, touch-target height and no panel overflow.
- First/fifth proposal details: correct target, Escape/Close, Back/Forward without reopening stale detail.
- Persisted history: counts across three categories, page size, category/page navigation, retained date filters and narrow-width category display.
- Synthetic priority: high/medium/low, numeric score and separate evidence status/disclaimer, original proposal identity, period/comparison/overview/vehicle navigation retaining trial mode, missing fixture blocked rather than assigned low.
- During all trial navigation: zero SQL mutation, no non-GET requests, unchanged saved analysis, feedback and last-vehicle preference. Page JavaScript errors fail the run.
- Reports include the candidate commit/tree, Python, Playwright and Chromium versions. Screenshots cover ordinary and priority views at three widths plus history at desktop/mobile widths.

## Standalone commands

Use Python 3.12 with the candidate requirements and Playwright 1.62.1. Supply an installed official Chromium executable. Preserve the virtual-environment Python path instead of resolving its symlink.

```sh
bash tests/quality_feature_browser/run-isolated.sh \
  /absolute/frozen-candidate /absolute/venv/bin/python --preflight-only

bash tests/quality_feature_browser/run-isolated.sh \
  /absolute/frozen-candidate /absolute/venv/bin/python \
  --run-browser --chromium /absolute/installed/chromium
```

Set `DKSS_BROWSER_ARTIFACT_DIR` to an absolute sidecar directory to control report output. Otherwise the runner prints a fresh temporary artifact path. A pass requires `browser-result.json` with `status=PASS`, `browser_started=true` and `browser_acceptance_passed=true`, plus exit zero. Preserve failure reports instead of blindly rerunning.

For fixture-only validation of a clean commit with the **identical complete tree** but different commit metadata, `--preflight-only --allow-identical-tree-preflight` is available. That flag cannot launch Chromium and is not used by the workflow. Preflight success is explicitly `PREFLIGHT_PASS_BROWSER_NOT_RUN` and is not browser acceptance.

Dedicated PostgreSQL tests, existing patrol-form browser cases, dependency vulnerability audits, real-data normalization and maintenance-expert approval remain independent acceptance checks.
