# PR377 invoice native-download experiment

This disposable validation branch runs **only the invoice browser case**, at its original three widths (1440, 390 and 320). It runs no separate HTTP preflight or other browser case. It selects a confined response-only HTTP receiver for the actual invoice download in official CI. The latest observed Download failure was `canceled`; its cause is not established. This is an experiment, not a proven fix or a promise of success. Any incomplete native download remains a failed case and failed aggregate.

## Frozen application and separate validation identity

- Application commit: `30d4dfeee97f69bd00650c6bf56a5ce234f34437`.
- Application tree: `31bb88b2d7a1a93f4c52f5aeefd59e97a8c8d3ea`.
- Requirements blob: `f29b6951157ecb12ef81490f42dfb5d57bdd9330`, 38 exact pins.
- Previous validation commit: `9124fa74b8bb9eea7479ed556bbf9fac65302556`.
- Previous validation tree: `1e554cc21a69a433c392f310415ddcc23ed71510`.
- This validation commit is the triggering `github.sha`; its commit, tree and eight file hashes are recorded separately from application identity.

The workflow uses separate, clean `application/` and `validation/` checkouts. Neither receives an overlay. Application commit/tree, frozen harness hashes, validation identity and external copies are checked before and after execution and during aggregation. No product branch, main, product PR, deployment, live service or existing database action is included.

## Preserve the run hierarchy and original failures

`harness/prior-evidence.json` has SHA-256 `340201a9e19ddcfdc8896fc2e6b612b095c1a3605e8f479d5edf9a27ef0a64d7`. Each level retains its original statuses, exits, report hashes, timestamps, runtime/source/provenance manifest hashes and earlier evidence reference. A later pass never overwrites an earlier failure.

1. [Run 43061389706](https://github.com/oxo-ops/dkss/actions/runs/43061389706), attempt 1: manufacturer confirmation passed; invoice failed with native Download failure `canceled`. Source stayed unchanged and the overall status remains `FAILED_OR_INCOMPLETE`. Artifact `13872389972` has SHA-256 `18be1a2d32611875c893a0ac82fc250784522d2d492020b0bd81676f48628534`. Both original reports are indexed. Manufacturer is not rerun or counted as current.
2. Its exact nested previous index, SHA-256 `5d11217430be095c2e35069e4ad63272aeebb9134fc25bfa8b46d9bec057a9a3`, retains [run 43058463867](https://github.com/oxo-ops/dkss/actions/runs/43058463867): legal confirmation passed; invoice and manufacturer failed. Artifact `13873565921`, SHA-256 `40c871f5329bb4a0c6343a8ec52afd541915368360bedee730b9d933f9cf03c7`. Legal is not rerun.
3. That hierarchy retains [run 43053078956](https://github.com/oxo-ops/dkss/actions/runs/43053078956): 3 HTTP preflights and 10 browser cases passed; invoice/manufacturer/legal browser cases failed. All 16 original entries remain intact. Artifact `13870588160`, SHA-256 `1541a86ebfe0bbe06515f56a104d4f23553b9a93041683caa0aface6ed4ee83a`.
4. It also retains [run 43043343085](https://github.com/oxo-ops/dkss/actions/runs/43043343085): Node 41 tests, comparison 14 cases and dashboard 6 widths passed, while the run failed on the original companion fixture. Their artifact IDs/digests remain unchanged. None of these groups is rerun.

The latest archive digest, two reports/exits and nested index were verified against the actual artifact before preparation. The new summary reports only current HTTP 0/browser 1; historical evidence remains separate, not flattened into a new all-pass report.

[Original PR run 43036556295, attempt 2](https://github.com/oxo-ops/dkss/actions/runs/43036556295/attempts/2) failed on Ubuntu package-host DNS before HTTP/browser verification. It has not been rerun by this work. Supplemental results do not replace original CI or full regression.

## Confined native-download transport experiment

The invoice helper retains the actual rendered link click, Playwright Download event, `failure()` check, saved-file hash assertion and source-request observations. All ordinary Flask bridge routing is unchanged. The source URL, link attributes, response headers/body and existing browser error policy are unchanged. No `route.continue`, fallback, retry, alternate URL, response rewrite or `ERR_ABORTED` exemption is introduced.

Only the explicit `--native-invoice-download-http` selection enables the receiver, and only for `--case invoice --run-browser`. The outer runner checks its existing GitHub repository/run identity and runtime/source manifests first, then passes this flag through the **byte-identical original `env -i` wrapper**. It records `invoice-experiment-context.json`. These public checks record the requested official-CI experiment location and selection; they are not a security or authorization mechanism. No new environment variable, credential, permission or wrapper change is needed.

For each actual download, the helper obtains the real synthetic fixture's original PDF response on the main thread and freezes its bytes and response headers. A short-lived, response-only receiver serves only that exact resource:

- IPv4 `127.0.0.1:8765`; exact original-source path, exact single Host, GET and loopback peer. No query, body, transfer encoding, other resource or second accepted transfer.
- Maximum 15-second lifetime, 2-second accepted-socket read/write timeout and bounded thread cleanup. It is armed only around this download and closed afterward.
- No Flask request dispatch, database/filesystem access, proxy, outbound connection or DNS lookup in the receiver. The immutable body must retain its original type, length and SHA-256.
- Actual Download URL and suggested filename must match the rendered source link. `failure()` must be null and the saved file's bytes/length must match the original PDF.
- Exactly one completed accepted transfer per width, no rejected requests, errors or expiry, and completed cleanup are mandatory. A plain source GET is not successful native-download completion.

The helper records all three `invoice_http_transfers` and `invoice_downloads`. Aggregation independently requires the expected widths, exact receiver/response/Download/saved-file identities, one transfer each and cleanup. Missing data, a canceled Download, unexpected browser failure or receiver anomaly fails the aggregate. The outcome may still be a failure and must be reported as such. No local listener or browser was started during preparation or static review.

## Pinned external helpers and unchanged isolation

Runtime-enforced Git blobs:

- `harness/acceptance.py`: `58217339bde1f0c08151b6af99642a6490495847`, reviewed invoice experiment.
- `harness/exact_invoice_download.py`: `e84e269a1f72e9772bd33284024601f31644d1c0`, reviewed confined response-only receiver.
- `harness/native_pdf_navigation.py`: `4573aa6f07666f1d4e508b7352cc4cd42df0a323`, unchanged.
- `harness/confirmation_acceptance.py`: `44e1612f2ca59eca80a2c6a436426bc722af18a7`, retained unchanged for provenance; not invoked in this run.

Helpers execute from a new directory outside both checkouts. Original application helper bytes remain unchanged and separately hashed. Original `tests/video_connected_browser/run-isolated.sh` (blob `f1be008f4e441e09b8f22ff41772d114fb0ba38d`) and `tests/history_presentation_browser/guard/sitecustomize.py` (blob `fecc07a6a8d0ddbbe19cc2cbd4d234dc209e7cef`) are copied byte-for-byte from the frozen app and rechecked. Earlier-path shadows of confirmation, PDF navigation and exact invoice receiver modules are rejected.

The original wrapper still supplies the frozen `--repo`, disposable HOME/TMPDIR and disabled integrations. The unchanged guard rejects Python outbound connections and SQLite outside the disposable fixture root. No application file, source reader, score, proposal, generated result or database-protection rule is patched or newly seeded. Original page/request failure and protected-record assertions remain.

The unchanged native-PDF helper aborts recognized internal assets with exact URL/method/type, verified PDF response and strict frame ancestry. Unknown requests remain fatal. Only an identical Request already aborted by that helper can have its expected `net::ERR_FAILED` separated. Source `net::ERR_ABORTED` is not exempted. Older reports without actual scheme/frame evidence remain failed. Native PDF viewer rendering is explicitly not covered.

## Strict scope, evidence and runtime

The immutable current plan is one invoice browser subprocess. Commands for manufacturer, legal, any other successful case or HTTP-only execution are rejected. The ledger retains started/finished state and exact exit code. A launch failure, nonzero exit, missing/duplicate/skipped/interrupted entry, wrong source/scenario/isolation flags, absent browser PASS or incomplete download evidence cannot pass. Source and helper integrity are rechecked before aggregation. Original failures remain failures even when useful diagnostic evidence is collected.

The aggregate writes `remaining-summary.json` after ordinary scenario failure. Cancellation or infrastructure failure cannot manufacture a pass. Artifact `pr377-invoice-experiment-30d4dfe-RUN-ATTEMPT` retains reports/screenshots/logs, ledger, runtime/install records, source/harness provenance and experiment context for 14 days. Orchestration and pure/static contracts are not application/browser acceptance results.

The official image, installation, 45-minute job limit and default container security are unchanged:

- `mcr.microsoft.com/playwright/python@sha256:aa81288e738725378becba5b3e06cb0f3a7f012a610e87e8d767a090ea3f740d` (`v1.62.0-noble`).
- Playwright 1.62.0, Node 24.22.2 and all 38 exact application pins verified. Exact runtime identity is recorded; previous container runs used Python 3.12.3, distinct from original PR CI's 3.12.16.
- No apt, install-deps, browser installation, new dependency, mirror, proxy/DNS/security change, privileged option, new browser flag or safe.directory exception.

Original notification navigation remains a synthetic same-origin meta-refresh relay, not native HTTP redirect coverage. These tests do not certify live AI/OCR, external delivery, production data, PostgreSQL concurrency, professional acceptance or full regression.

The branch contains exactly this README, the workflow and six harness files: runner, acceptance, confirmation, native-PDF helper, exact invoice receiver and prior-evidence index. Only the dedicated validation branch push triggers it; permissions remain `contents: read` and credentials are not persisted. Independent review precedes publication by the parent. Verify remote identities and actual run evidence before reporting any new pass. Preparation is not execution, a confirmed diagnosis or a successful download.
