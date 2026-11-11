# PR377 invoice preview diagnostic only

This branch collects **preview evidence only**, at 1440px, on the actual maintenance-tab and maintenance-record screens. It does not run full invoice acceptance, native downloads, original-PDF navigation, other browser scenarios or separate HTTP preflights. A successful diagnostic job means evidence collection completed, **not invoice/browser acceptance**. The invoice case remains failed in the prior evidence until a separate acceptance result establishes otherwise.

## Frozen application and separate validation

- Application commit: `30d4dfeee97f69bd00650c6bf56a5ce234f34437`.
- Application tree: `31bb88b2d7a1a93f4c52f5aeefd59e97a8c8d3ea`.
- Requirements blob: `f29b6951157ecb12ef81490f42dfb5d57bdd9330`, 38 exact pins.
- Previous validation commit: `5ab8b973df9ef762a48555ff374b04c5fd97c5cd`.
- Previous validation tree: `30cb619f2b1b84ee2490f7eedec6326a0e3f6597`.
- Current validation identity is the triggering `github.sha`; its tree and eight file hashes are recorded separately.

Clean application and validation checkouts remain separate. Neither receives an overlay. Source identity, original harness hashes, validation files and external copies are checked before/after execution and at aggregation. No product, main, product PR, deployment, live service or existing database change is included.

## Retain successful components and the failed invoice verdict

Latest [run 43066261383](https://github.com/oxo-ops/dkss/actions/runs/43066261383) completed all three native downloads, at 1440/390/320px. Each Download had null failure, a saved 470-byte file matching the original SHA-256, exactly one completed receiver transfer, no receiver errors/rejections/expiry and complete cleanup. These observations are retained and **not rerun**.

The invoice report nevertheless ended `FAILED`, process exit 1. Its remaining six `net::ERR_ABORTED` requests were PDF fetches, one on each maintenance-tab and maintenance-record screen at each width. The report lacks terminal embedded-preview raster/error state and caught PDF.js console detail. This does not establish that the aborts are normal, nor that the preview rendered successfully. No cancellation exemption or product fix is proposed.

`harness/prior-evidence.json`, SHA-256 `9c313472fcfe008ba25bbe49d43843c87fb064253dfcfc46c4d2af93e8d1fe30`, preserves each run separately:

1. Run `43066261383`: invoice failed, HTTP/browser acceptance counts 0/0, source unchanged. Artifact `13876665717`, SHA-256 `65f6663bb490c2ff630297ac49d608c74768101d2f31e40d471c14ed12024cc3`. The original report hash, exit/timestamps and six manifest hashes are retained. Native-download component observations do not change this failed verdict.
2. Run `43061389706`: manufacturer passed; invoice failed with native Download `canceled`. Artifact `13872389972`, SHA-256 `18be1a2d32611875c893a0ac82fc250784522d2d492020b0bd81676f48628534`.
3. Run `43058463867`: legal passed; invoice/manufacturer failed. Artifact `13873565921`, SHA-256 `40c871f5329bb4a0c6343a8ec52afd541915368360bedee730b9d933f9cf03c7`.
4. Run `43053078956`: 3 HTTP and 10 browser cases passed; invoice/manufacturer/legal failed. Artifact `13870588160`, SHA-256 `1541a86ebfe0bbe06515f56a104d4f23553b9a93041683caa0aface6ed4ee83a`.
5. Run `43043343085`: Node 41 tests, comparison 14 cases and dashboard 6 widths passed; the run failed on the original companion fixture. Its original artifact references remain intact.

The exact previous index, SHA-256 `340201a9e19ddcfdc8896fc2e6b612b095c1a3605e8f479d5edf9a27ef0a64d7`, is nested unchanged. No prior status is rewritten, flattened into a new pass or counted as a current result. The latest ZIP, report/exits, source/harness manifests and nested evidence were checked against the actual artifact.

[Original PR run 43036556295, attempt 2](https://github.com/oxo-ops/dkss/actions/runs/43036556295/attempts/2) failed during dependency installation on Ubuntu-host DNS. It has not been rerun by this work. Supplemental diagnostics do not replace original CI or full regression.

## Bounded observation without replaying completed native paths

The runner passes only `--case invoice --run-browser --invoice-preview-observe-only`. That flag excludes `--native-invoice-download-http`. The helper retains ordinary disposable fixture setup and source checks, then follows a small early-return branch before the unchanged full three-width acceptance loop:

- At 1440px, click the actual maintenance tab and the exact same saved record link.
- On each screen, open the real initially closed preview disclosure using its summary. Wait up to 10 seconds for ready/raster or explicit error state, then record DOM state and a screenshot even on timeout. Close the disclosure afterward.
- Observe one-page count/current-page/status, positive page dimensions, actual canvas dimensions, source/record identity and disclosure state. Readiness follows the existing Q12-style criteria; it is an observation, not acceptance.
- Record the specific `Invoice PDF preview failed` console detail, selected request/response headers and correlated source events. Headers are limited to Range/If-Range, Accept, Sec-Fetch metadata, type/length/range/encoding/disposition/cache/nosniff. No cookies, credentials or response bodies are added to evidence.

It does not click the history PDF arrow or download card, construct/start the receiver, enter the full three-width loop, change browser APIs, forward additional response headers, alter routing or exempt a failed request. The native receiver and PDF helper remain present and hash-pinned because the acceptance entry point imports them; the receiver is not invoked.

Outer checks reuse the existing public GitHub repository/run and runtime/source identity before selecting this mode through the original wrapper. `invoice-preview-context.json` records this official-CI diagnostic selection, not a new authorization mechanism. No new credentials, environment variables or permissions are introduced.

## Diagnostic completion is never acceptance

A complete helper report must have:

- `status: PREVIEW_DIAGNOSTIC_COMPLETE_NOT_ACCEPTANCE` and `diagnostic_only: true`.
- `browser_acceptance_passed: false`, `full_invoice_browser_executed: false`, `native_download_reexecuted: false`, and `native_invoice_http_experiment: false`.
- Two 1440px observations, in maintenance-tab/maintenance-record order, plus both screenshots and unchanged protected records.
- Empty native download/transfer/original-PDF navigation arrays.

`previews_ready` records observed readiness only. Error DOM, bounded-wait timeout, console exceptions and all failed/blocked requests remain in the report and are copied into the diagnostic summary. They are not reclassified or silently discarded. Evidence collection may complete with those findings; it cannot certify the invoice case.

The separate `preview-diagnostic-summary.json` uses `PREVIEW_DIAGNOSTIC_COMPLETE_NOT_ACCEPTANCE` or `PREVIEW_DIAGNOSTIC_FAILED_OR_INCOMPLETE`, never `PASS`. It always reports full-browser acceptance required/passed 0/0, HTTP 0/0, invoice acceptance false and native-download reexecution false. Diagnostic browser required/completed counts are separate. Exactly one diagnostic subprocess, zero exit, matching source/isolation/scope, complete observations and both PNG artifacts are required for collection completion. Missing, duplicate, interrupted, mismatched or failing execution/evidence cannot complete. Source/guard/copy failures remain failures.

Artifacts and workflow names explicitly identify diagnostic-only work. A green diagnostic job is evidence-collection success, not a change to the prior invoice failure. Cancellation/infrastructure failure cannot manufacture completion.

## Fixed helpers and unchanged isolation/runtime

Runtime-enforced Git blobs:

- `acceptance.py`: `7b1ef09ca54fb545c44fb85bf78bfd68f36637b2`, reviewed observation-only early-return mode. The prior full three-width loop is AST-identical and all 48 prior required conditions remain.
- `confirmation_acceptance.py`: `44e1612f2ca59eca80a2c6a436426bc722af18a7`, retained, not invoked.
- `native_pdf_navigation.py`: `4573aa6f07666f1d4e508b7352cc4cd42df0a323`, unchanged.
- `exact_invoice_download.py`: `e84e269a1f72e9772bd33284024601f31644d1c0`, unchanged and not invoked.

External copies reside outside both checkouts. The original `tests/video_connected_browser/run-isolated.sh` blob `f1be008f4e441e09b8f22ff41772d114fb0ba38d` and `tests/history_presentation_browser/guard/sitecustomize.py` blob `fecc07a6a8d0ddbbe19cc2cbd4d234dc209e7cef` are copied byte-for-byte. All copies and earlier-path module shadows are checked. The original `env -i` isolation, disposable HOME/TMPDIR, disabled integrations, Python outbound-connection guard and SQLite restrictions remain unchanged. No source, score, proposal, computed result or database protection is patched or newly seeded.

The pinned official MCR Playwright image, Playwright 1.62.0, Node 24.22.2, 38 application pins, recorded Python identity and 45-minute limit are unchanged. No apt/install-deps/browser installation, added dependency, DNS/proxy/security change, privileged/browser option or safe.directory exception. Prior container Python was 3.12.3; original PR CI Python was 3.12.16.

Native PDF viewer rendering and native HTTP redirect transport remain outside coverage. The unchanged notification relay is synthetic same-origin meta-refresh. These diagnostics do not certify live AI/OCR, external delivery, production data, concurrency, professional acceptance or full regression.

The branch contains exactly this README, the workflow and six harness files (runner, acceptance, confirmation, native PDF helper, receiver and prior index). Artifacts are kept for 14 days. Permissions remain `contents: read`, credentials are not persisted, and only the dedicated validation branch push triggers execution. Preparation used static/pure tests only, with no local browser/listener or remote write. Parent publication follows independent review. Actual preview state and the abort cause remain unknown until official diagnostic evidence is read.
