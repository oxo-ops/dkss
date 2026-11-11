# PR377 final three browser cases

This disposable validation branch executes exactly three previously failing browser cases on the unchanged application: `invoice`, `confirmation_manufacturer`, and `confirmation_legal`. It executes no HTTP-only preflight and does not repeat any previously passing browser, Node, comparison or dashboard case. Previous failures remain failures in their original run; this is new supplemental evidence, not a relabeling of that run or of original PR CI.

## Frozen source and separate validation identity

- Application commit: `30d4dfeee97f69bd00650c6bf56a5ce234f34437`.
- Application tree: `31bb88b2d7a1a93f4c52f5aeefd59e97a8c8d3ea`.
- Requirements blob: `f29b6951157ecb12ef81490f42dfb5d57bdd9330`, 38 exact pins.
- Previous validation commit: `4c83b07efa9aeb8e9af4c41baa23034802d5df28`.
- Previous validation tree: `9b13b3646bcbc0d23c51f15ddd4b513897a9e827`.
- The new validation identity is the triggering `github.sha`, checked out separately and recorded with its tree and all seven file hashes.

The workflow checks out the frozen application into `application/` and this validation commit into `validation/`. Neither checkout receives an overlay. Both must remain clean; the exact application commit/tree, frozen harness hashes, validation commit/tree and byte equality of external harness copies are checked before, between and after cases. Checkout does not persist credentials. No product branch, main, product PR, merge, deploy, live service or existing database operation is included.

## Previous evidence is retained separately

[Run 43053078956](https://github.com/oxo-ops/dkss/actions/runs/43053078956), attempt 1, completed with `FAILED_OR_INCOMPLETE`. It verified the unchanged application and passed all 3 HTTP preflights plus 10 of the 13 browser cases. Invoice, manufacturer confirmation and legal confirmation failed. The exact artifact is `13870588160`, SHA-256 `1541a86ebfe0bbe06515f56a104d4f23553b9a93041683caa0aface6ed4ee83a`.

`harness/prior-evidence.json` indexes the original 16 case statuses, process exits, report SHA-256 values and timestamps, plus the original runtime/source/provenance manifest hashes. Its pinned SHA-256 is `226dd630b9077a0e473ea790c63b3b00fdfeac62726f43df9443306e02eb0475`. The archive digest and all 16 report identities/exits/statuses were checked against the downloaded artifact before preparing this index. The index preserves both the 13 passing invocations and the three failures, including the original run's failed aggregate status. It is a reference to previous evidence, not current-run output.

Earlier [run 43043343085](https://github.com/oxo-ops/dkss/actions/runs/43043343085) passed Node 41 tests, comparison 14 cases and dashboard 6 widths on the same application. Its overall run failed on the original companion-certificate fixture. The three earlier artifact IDs and digests are retained in the same index. None is rerun here.

[Original PR run 43036556295, attempt 2](https://github.com/oxo-ops/dkss/actions/runs/43036556295/attempts/2) failed on Ubuntu package-host DNS before HTTP/browser verification. This work does not rerun or change that result. Original CI, previous supplemental runs and this new three-case run must be reported separately.

## External harness corrections

The failed invoice case searched the history page for a maintenance-detail URL, but the real rendered arrow links to the preserved invoice PDF. The corrected external acceptance helper binds the expected source draft and SHA-256 to the actual fixture record, clicks the sole rendered history arrow, checks the exact PDF navigation/HTTP 200/type/bytes, uses Back, and follows the real maintenance tab and record link to the existing detail/download checks. Its three widths, original download hash, connected views and protected-data checks remain. The isolated HTTP/rendered-link observation verified these links and bytes; it was not a browser pass.

The two failed confirmation browsers reached their final assertion after recording blocked resource paths associated with Chromium's native PDF viewer. The old report omitted schemes and frame information, so those observations alone cannot prove every resource's precise origin. The new shared `native_pdf_navigation.py` therefore records actual full URL, scheme, resource type, frame/parent URL and source identity, and fails closed rather than broadly ignoring the old paths.

The shared helper never loads or allows a native resource: it still aborts every classified request. It classifies only five exact built-in asset URLs with the expected GET/resource type, during a deliberately opened same-page main-frame PDF navigation whose real source response is already verified as HTTP 200/application/pdf with matching bytes. Frame checks bind the PDF embedder to that main frame and viewer assets to its exact direct-child `index.html`. Unknown URL, scheme, query, fragment, method, resource type, page, frame or unverified response stays an ordinary failure. A subsequent `net::ERR_FAILED` is separated only when its Request object is the exact request this helper already aborted; all other failed requests remain fatal. The confirmation helper adds failed-request accounting rather than relaxing it.

Native-viewer aborts are recorded separately in `blocked_native_pdf_viewer_resources` and `failed_native_pdf_viewer_requests`; the actual source navigations are in `original_pdf_navigations`. Original PDF link/status/type/bytes and Back navigation are asserted. `native_pdf_viewer_rendering_covered` is explicitly false: these aborted assets mean native PDF rendering is not certified. Manufacturer historical missing-source text also receives a dedicated viewport-verified screenshot; its existing assertions are retained.

Reviewed external Git blobs:

- `acceptance.py`: `f006c811340844eb2f435a0e35493b9f0141aab1` (invoice correction plus PDF accounting).
- `confirmation_acceptance.py`: `7168dd213cf261d34230c8e4f83db2e085940e2e` (retains the previous TESTMODEL fixture correction).
- `native_pdf_navigation.py`: `4573aa6f07666f1d4e508b7352cc4cd42df0a323`.

Nine shared-helper contract tests cover exact assets, response/hash/navigation identity, request-failure correlation and negative/spoof cases without launching a browser. This is test-harness evidence, not successful browser execution.

The external harness contains two explicitly changed validation-side files, `harness/acceptance.py` and `harness/confirmation_acceptance.py`. Together with the added shared PDF helper, their exact reviewed Git blobs are enforced by `harness/validate_remaining.py`. The original application versions remain untouched and are separately recorded in the provenance manifest.

Only these original files are copied byte-for-byte from the frozen app into the external execution directory:

- `tests/video_connected_browser/run-isolated.sh`: Git blob `f1be008f4e441e09b8f22ff41772d114fb0ba38d`.
- `tests/history_presentation_browser/guard/sitecustomize.py`: Git blob `fecc07a6a8d0ddbbe19cc2cbd4d234dc209e7cef`.

The directory is outside both checkouts. The original wrapper still passes the frozen application as `--repo`, clears the environment with `env -i`, uses a disposable HOME/TMPDIR and disables integrations. The unchanged guard rejects Python network connects and SQLite connections outside the disposable fixture root. Application imports resolve to the frozen application; potential shadow confirmation/PDF-helper modules are rejected. Browser access continues through the existing in-process Flask bridge, not a live server.

No source reader, product guard, score, generated proposal, job result, API assertion, database protection or browser security setting is relaxed. The previously verified synthetic-model fixture correction is retained only in the external confirmation helper. Existing deliberately scoped fixture revision/restore and saved-source omission operations remain explicit and unchanged.

## Strict three-case accounting

The runner's immutable case list contains exactly invoice, manufacturer confirmation and legal confirmation, all in browser mode. Commands for previously passing or arbitrary cases are rejected. All three run as independent original-wrapper subprocesses with separate disposable fixtures; ordinary failure or launch failure in one does not skip the others. Source or harness-integrity failure stops further execution.

The ledger retains each exit code and started/finished state. Aggregation requires exactly the three expected entries, zero exits and matching report JSON with the frozen application SHA/tree, correct scenario, `fixture_only: true`, `production_accessed: false`, `browser_started: true`, `browser_acceptance_passed: true` and `status: PASS`. Missing, duplicate, interrupted, skipped, mismatched or failing cases cannot yield success.

Current-run counts are explicitly HTTP 0 and browser 3. Previous passes are nested under a separate prior-evidence reference and never added to these current-run counts. The aggregate step still runs after ordinary scenario failure and writes `remaining-summary.json`; cancellation or infrastructure failure cannot create a pass.

The current artifact is named `pr377-final-three-container-30d4dfe-RUN-ATTEMPT` and retains the original scenario JSON/screenshots/logs, individual exits, runtime/install records and separate harness provenance for 14 days. Do not substitute orchestration self-test output for application acceptance results.

## Runtime and boundaries unchanged

- Official image: `mcr.microsoft.com/playwright/python@sha256:aa81288e738725378becba5b3e06cb0f3a7f012a610e87e8d767a090ea3f740d` (`v1.62.0-noble`).
- [Official registry](https://mcr.microsoft.com/en-us/artifact/mar/playwright/python/tag/v1.62.0-noble), [versioned Dockerfile](https://github.com/microsoft/playwright-python/blob/v1.62.0/utils/docker/Dockerfile.noble), [vendor documentation](https://playwright.dev/python/docs/docker).
- Python 3.12 with exact runtime recorded; previous container run used 3.12.3, distinct from original PR CI's 3.12.16.
- Playwright 1.62.0, Node 24.22.2 and all 38 exact application pins checked at runtime. The existing image-provided virtualenv and isolated pip procedure are unchanged.
- No apt, install-deps, playwright install, new dependencies, custom package mirrors, DNS/proxy/security changes, privileged container flags, new browser flags or safe.directory exceptions.
- Job timeout remains 45 minutes. It is an outer limit, not a guarantee of completed acceptance.

These tests do not certify native HTTP redirect transport: the notification navigation remains the original synthetic same-origin meta-refresh relay. They do not certify live AI/OCR accuracy, external delivery, production data, PostgreSQL concurrency, professional acceptance, every original workflow or full regression.

## Publication boundary

Exactly seven files are permitted in the validation branch:

1. `.github/workflows/pr377-supplemental-browser.yml`.
2. `README.md`.
3. `harness/validate_remaining.py`.
4. `harness/acceptance.py`.
5. `harness/confirmation_acceptance.py`.
6. `harness/prior-evidence.json`.
7. `harness/native_pdf_navigation.py`.

Preparation is not publication or successful execution. Independent review must precede any validation-ref update. Only the dedicated validation branch push triggers this workflow, with `contents: read`. Verify the published commit/tree and actual run before reporting results; keep prior failure and success evidence linked to its original run.
