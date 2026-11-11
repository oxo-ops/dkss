# PR377 remaining two browser cases

This disposable validation branch runs exactly two browser cases on the unchanged application: `invoice` and `confirmation_manufacturer`. It runs no separate HTTP preflight and does not repeat legal confirmation or any other previously passing case. It combines a manufacturer interaction correction with **invoice observation-only instrumentation**. The invoice failure is not fixed or explained yet and may fail again. Such a failure must remain a failed case and failed aggregate, even if useful diagnostic evidence is collected.

## Frozen application and separate validation identity

- Application commit: `30d4dfeee97f69bd00650c6bf56a5ce234f34437`.
- Application tree: `31bb88b2d7a1a93f4c52f5aeefd59e97a8c8d3ea`.
- Requirements blob: `f29b6951157ecb12ef81490f42dfb5d57bdd9330`, 38 exact pins.
- Previous validation commit: `43b03d244e5483aaa8a68f27bfe9c002c82877fa`.
- Previous validation tree: `f2171c6d5206be6f954cec36d0fe1783d893bb6b`.
- This validation commit is the triggering `github.sha`; its exact commit, tree and seven file hashes are recorded separately from application identity.

The workflow uses separate `application/` and `validation/` checkouts. Neither receives an overlay. Both remain clean; the application commit/tree, frozen harness hashes, validation identity and external copies are checked before, between and after cases. No product branch, main, product PR, merge, deployment, live service or existing database action is included.

## Preserve each run's evidence and failures

`harness/prior-evidence.json` is a hierarchical index, pinned to SHA-256 `5d11217430be095c2e35069e4ad63272aeebb9134fc25bfa8b46d9bec057a9a3`. It never replaces an earlier failed status with a later success.

1. [Run 43058463867](https://github.com/oxo-ops/dkss/actions/runs/43058463867), attempt 1, is the latest indexed run. Its overall status remains `FAILED_OR_INCOMPLETE`: legal confirmation passed; invoice and manufacturer confirmation failed. Application source stayed unchanged. Artifact `13873565921` has SHA-256 `40c871f5329bb4a0c6343a8ec52afd541915368360bedee730b9d933f9cf03c7`. All three report hashes, original statuses, process exits and timestamps are retained. Legal's pass is not rerun or counted as a current-run result.
2. Its `previous_evidence_reference` retains [run 43053078956](https://github.com/oxo-ops/dkss/actions/runs/43053078956) unchanged: 3 HTTP preflights and 10 browser cases passed, while invoice/manufacturer/legal browser cases failed. Its overall failed status, all 16 original records, artifact `13870588160` and SHA-256 `1541a86ebfe0bbe06515f56a104d4f23553b9a93041683caa0aface6ed4ee83a` remain intact. The previous index's exact SHA-256 is `226dd630b9077a0e473ea790c63b3b00fdfeac62726f43df9443306e02eb0475`.
3. That earlier reference retains [run 43043343085](https://github.com/oxo-ops/dkss/actions/runs/43043343085): Node 41 tests, comparison 14 cases and dashboard 6 widths passed, while its overall run failed on the original companion fixture. Those artifact IDs/digests are unchanged and none of those groups is rerun.

Latest and earlier archive digests, report identities/exits/statuses and the nested index were verified before preparation. Each level retains its runtime/source/provenance manifest hashes. The new aggregate reports only current HTTP 0 and browser 2, with prior evidence nested separately. It does not flatten these runs into a new all-pass report.

[Original PR run 43036556295, attempt 2](https://github.com/oxo-ops/dkss/actions/runs/43036556295/attempts/2) failed on Ubuntu package-host DNS before HTTP/browser verification. This work does not rerun or change its conclusion. Supplemental results do not replace original CI or full regression.

## Manufacturer: open the actual disclosure before verifying visibility

The latest failed manufacturer's five original PDF navigations completed with HTTP 200, matching PDF bytes/type, exact same-page URL and Back verification. Its later viewport assertion failed because the missing-source paragraph was inside a separate, initially closed `details.ka-action-evidence`. The screenshot/ARIA snapshot and frozen JavaScript confirmed that closed ancestor. The harness had opened the different priority-assessment disclosure; scrolling did not open the source-evidence disclosure.

The external confirmation helper now locates the single source-evidence disclosure, asserts that it starts closed, clicks its real direct-child summary, asserts that it is open and the gap is visible, then retains the existing scroll, viewport assertion and screenshot. No content, styles, open-state assignment, viewport threshold or product code changes. This is a correction to the test interaction, not evidence that expanded content already passed.

The browser recheck must still complete all five source-gap viewport assertions/screenshots and the remaining historical/current companion/cancellation checks. Existing source readers, real jobs, protected snapshots, source revision/restore and one-key saved-source omission behavior are unchanged.

## Invoice: observe the native download failure without bypassing it

The latest invoice case passed the repaired history navigation, exact source PDF GET/type/hash, Back, actual maintenance tab, record link and corrected-detail assertion. It then received a Download whose `failure()` was non-null. The failure string was not logged. One original-source GET had `net::ERR_ABORTED`, but the old report lacked phase/request correlation; it cannot identify that request's role or establish the download's cause.

The new external invoice helper adds only:

- The exact Download failure result, URL, suggested filename, rendered href/download attribute, viewport and phase.
- Phase-tagged request, bridge-response, browser-response, request-finished and request-failed events for the exact original-source URL. Stable Request identities correlate events; source response metadata includes status, content disposition, type, length and hash, not bodies or credentials.
- The concrete failure string in the existing assertion message.

Every non-null Download failure still fails. The downloaded-file hash assertion and unexpected-failed-request policy remain. All original routing, response headers/body, link targets, clicks, Back/Forward, viewport checks, saved-data assertions and guards remain unchanged. No retry, sleep, alternate download URL, response rewrite, native-error exemption, live server or added network capability is introduced. A plain source GET/hash check is not native download completion. This run may therefore deliver useful observations while correctly remaining failed.

## Pinned external helpers and unchanged isolation

The three helper Git blobs are enforced at runtime:

- `harness/acceptance.py`: `7862711860f8131cecf02caca7d06a43d5a3413e` (invoice observation only, based on previously used `f006c811340844eb2f435a0e35493b9f0141aab1`).
- `harness/confirmation_acceptance.py`: `44e1612f2ca59eca80a2c6a436426bc722af18a7` (manufacturer disclosure interaction, based on `7168dd213cf261d34230c8e4f83db2e085940e2e`).
- `harness/native_pdf_navigation.py`: `4573aa6f07666f1d4e508b7352cc4cd42df0a323`, unchanged from the legal-passing run.

The helpers execute from a new directory outside both checkouts. The original application helper versions remain unchanged and separately hashed. Only the original `tests/video_connected_browser/run-isolated.sh` (blob `f1be008f4e441e09b8f22ff41772d114fb0ba38d`) and `tests/history_presentation_browser/guard/sitecustomize.py` (blob `fecc07a6a8d0ddbbe19cc2cbd4d234dc209e7cef`) are copied byte-for-byte from the frozen app. All copies are rechecked between cases and at aggregation. Earlier-path shadow confirmation/PDF modules are rejected.

The original `env -i` wrapper still supplies the exact frozen `--repo`, disposable HOME/TMPDIR and disabled integrations. The unchanged guard rejects Python network connections and SQLite outside the disposable fixture root. No application file, source reader, computed score, proposal, generated result or database-protection rule is patched or newly seeded.

The unchanged native-PDF helper continues to abort all recognized internal assets. It separately records only exact known URLs/methods/types with verified same-page PDF response identity and strict frame ancestry. Unknown requests remain fatal. `net::ERR_FAILED` is separated only for the identical Request that this helper already aborted; the invoice's source `net::ERR_ABORTED` is not exempted. The latest run supplies real scheme/frame evidence; older failed reports that lacked it remain failed. Native PDF viewer rendering is explicitly not covered, even when source navigation and byte checks pass.

## Strict two-case execution and aggregation

The immutable current-case list contains only invoice and manufacturer confirmation in browser mode. Commands for legal or any earlier successful case are rejected. Both cases use independent subprocesses and fresh original isolation wrappers. An ordinary failure or launch failure in one does not skip the other. Source or harness-integrity failure stops further execution.

The ledger retains exact process exit codes and started/finished states. Aggregation requires exactly the two expected entries, zero exits and original report JSON with the frozen application SHA/tree, correct scenario, synthetic-only/no-production flags, browser started/acceptance flags and `status: PASS`. Missing, duplicated, skipped, interrupted, mismatched or failing cases cannot pass. Invoice diagnostic output has no special success status or exemption. Current counts remain HTTP 0/browser 2 regardless of historical successes.

The aggregate runs after ordinary scenario failure and writes `remaining-summary.json`. Cancellation or infrastructure failure cannot manufacture a pass. Artifact `pr377-final-two-container-30d4dfe-RUN-ATTEMPT` retains current reports/screenshots/logs, exits, runtime/install records and harness provenance for 14 days. Orchestration/static contract tests are not application acceptance results.

## Runtime and publication boundary

The official image, dependency installation, 45-minute outer job limit and default container security are unchanged:

- `mcr.microsoft.com/playwright/python@sha256:aa81288e738725378becba5b3e06cb0f3a7f012a610e87e8d767a090ea3f740d` (`v1.62.0-noble`).
- Playwright 1.62.0, Node 24.22.2 and all 38 exact application pins verified. Exact Python/runtime/install identity recorded; prior container runs used Python 3.12.3, distinct from original PR CI's 3.12.16.
- No apt, install-deps, browser installation, dependency addition, mirror, proxy/DNS/security change, privileged flags, new browser flags or safe.directory exception.

The original notification navigation remains a synthetic same-origin meta-refresh relay, not native HTTP redirect transport coverage. These tests do not certify live AI/OCR, external delivery, production data, PostgreSQL concurrency, professional acceptance or full regression.

The branch contains exactly the workflow, this README and five harness files: `validate_remaining.py`, `acceptance.py`, `confirmation_acceptance.py`, `native_pdf_navigation.py`, and `prior-evidence.json`. Only the dedicated validation branch push triggers the workflow; permissions remain `contents: read` and credentials are not persisted.

Preparation is not publication, a proven invoice fix or a successful browser run. Independent review must precede a validation-ref update. Verify the remote commit/tree and actual run, then report each failed, passed and never-run case against its own run. Do not change the product, original CI conclusions or earlier evidence to obtain a green status.
