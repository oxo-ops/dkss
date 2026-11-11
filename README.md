# PR377 invoice full browser acceptance

This validation runs only the still-unpassed invoice browser case at 1440, 390 and 320px. It requires embedded preview readiness and visible canvas evidence on both maintenance screens, followed by the actual native original download at each width, in the same full invoice flow. No other previously passing browser case, separate HTTP preflight, Node, comparison or dashboard group is rerun.

Native downloads passed in an earlier run, but that invoice case still failed on six preview fetch cancellations. The subsequent 1440px diagnostic observed rendered preview DOM alongside those cancellations; it did not execute or pass full invoice acceptance. This new run must establish its own complete outcome. A new pass must not overwrite any earlier failed or diagnostic verdict.

## Frozen application and separate validation

- Application commit: `30d4dfeee97f69bd00650c6bf56a5ce234f34437`.
- Application tree: `31bb88b2d7a1a93f4c52f5aeefd59e97a8c8d3ea`.
- Requirements blob: `f29b6951157ecb12ef81490f42dfb5d57bdd9330`, 38 exact pins.
- Previous validation commit: `e5f3f3ecd4e27cfeb156b9caef70ece006db4445`.
- Previous validation tree: `529dcb5ef17e0c20beaa78692bce7eaed1d3ee0e`.
- The triggering `github.sha`, validation tree and every validation file hash are recorded separately.

Application and validation have separate clean checkouts, with no overlay. Runtime verifies source identity, original harness hashes, fixed helper bytes, copied wrapper/guard and import-shadow exclusions before and after execution and at aggregation. No product branch, main, PR, deployment, live service or existing database action is included.

## Prior evidence retains each original verdict

`harness/prior-evidence.json` has SHA-256 `7c976d288d385ac74af17c4fc8903d63d752ca11a714a0c94256f8c6eb418524`.

1. [Run 43069457448](https://github.com/oxo-ops/dkss/actions/runs/43069457448) completed a 1440px preview diagnostic only. It retains `PREVIEW_DIAGNOSTIC_COMPLETE_NOT_ACCEPTANCE`, HTTP/browser acceptance 0/0 and no native-download reexecution. Both maintenance-screen DOM observations were ready, with positive raster dimensions and no preview error, alongside two `ERR_ABORTED` fetches. The full-page screenshots did not themselves show the canvas in the viewport; that is distinct from DOM raster readiness. Artifact `13878495078`, SHA-256 `383bd14f62b79c040aada0bc402f282c15a3a45ca9dab116c7d0f49c998d1d36`.
2. [Run 43066261383](https://github.com/oxo-ops/dkss/actions/runs/43066261383) completed three native downloads with matching saved bytes, one completed receiver transfer per width and cleanup. The full invoice report still failed on six preview fetch cancellations; its exit 1 and failed verdict remain. Artifact `13876665717`, SHA-256 `65f6663bb490c2ff630297ac49d608c74768101d2f31e40d471c14ed12024cc3`.
3. Run `43061389706`: manufacturer passed; invoice failed with native Download `canceled`.
4. Run `43058463867`: legal passed; invoice/manufacturer failed.
5. Run `43053078956`: 3 HTTP and 10 browser cases passed; invoice/manufacturer/legal failed.
6. Run `43043343085`: Node 41 tests, comparison 14 cases and dashboard 6 widths passed; the run failed on the original companion fixture.

Every level preserves its artifact digest, original reports/exits/timestamps, manifest hashes and nested reference. The previous index SHA-256 `9c313472fcfe008ba25bbe49d43843c87fb064253dfcfc46c4d2af93e8d1fe30` is nested unchanged. The latest ZIP and every expanded file, source/harness identities, diagnostic report/exits, screenshot hashes and six manifests were checked before preparation. Diagnostic completion never counts as acceptance. Prior successes do not count as current results.

[Original PR run 43036556295, attempt 2](https://github.com/oxo-ops/dkss/actions/runs/43036556295/attempts/2) failed during dependency installation on Ubuntu-host DNS and was not rerun by this work. Supplemental acceptance does not replace original CI or full regression.

## Preview and cancellation evidence

For each width, the real maintenance tab and exact record link each require one complete preview: actual disclosure open/close, one-page current/count/status, positive page dimensions and raster, exact source and saved-record identity, no timeout or preview console error. The canvas is scrolled into view and must have 100% viewport intersection before a dedicated `invoice-preview-{stage}-{width}-visible.png`. The original full-page screenshot is retained too. Six ordered observations and all twelve screenshots are mandatory.

Each preview must correlate exactly four ordered source events to one distinct Request, the actual same main Frame/Page, exact scope/phase/page and original source: request, bridge response, browser response, then requestfinished or requestfailed. Both responses must be HTTP 200 with the original small PDF hash/length and identical selected inline, unencoded, non-range headers. Range/If-Range, other status/type/body, duplicate/late events, other frame/source or another error cannot qualify.

Only after verified visible rendering may the exact `net::ERR_ABORTED` entry for that identical Request move to `verified_invoice_preview_cancellations`. Its raw failure and all source events remain. Equal-valued failures from other Request objects stay fatal. Normal requestfinished must meet the same evidence requirements. `verified_invoice_preview_fetches` contains six distinct proof records; cancellations must equal only their failed subset. The outer aggregate independently checks these identities and evidence references, all visible/ready fields and screenshots, alongside unchanged native saved-download evidence.

All 51 conditions from the immediate helper baseline remain. The bridge, get, snapshot and actual native-download block are unchanged. The fixed helper passed 15 pure/static contracts with negative identity/frame/response/render/error cases and exact Request-object removal checks; read-only review found no static blockers. Those tests do not substitute for the new real-browser evidence.

The observable classification does not prove who called abort or assert an intentional PDF.js completion cancellation. It applies only to the exact evidence-supported preview request. Unknown, unmatched or otherwise failing requests remain fatal. Diagnostic mode cannot satisfy this full-acceptance aggregator.

## Actual native download in the same full flow

The command uses `--case invoice --run-browser --native-invoice-download-http` without the diagnostic flag. Each width retains the real source navigation, Back, maintenance tab, exact record, actual download click, Playwright Download, null failure and saved-file SHA-256/length match. Native download is rechecked only as part of this complete invoice acceptance with the new preview requirements, not as a separate successful-case rerun.

The unchanged response-only receiver freezes the actual synthetic original PDF response. It serves only one exact GET/Host/path/loopback peer on IPv4 `127.0.0.1:8765`, with a 15-second lifetime, 2-second accepted-socket timeout and bounded cleanup. No Flask dispatch, database/filesystem access, proxy, outbound connection or DNS in the receiver. Exactly one completed transfer per width, zero rejected/errors/expiry, correct body identity and complete cleanup remain mandatory. A source GET alone cannot satisfy native-download completion.

The outer runner retains the existing public GitHub/runtime/source checks and records official-CI experiment selection. These are location/provenance checks, not a new authentication or authorization system. The original wrapper receives only the explicit mode flag; no new credential, environment variable or permission is introduced.

## Fixed helpers, unchanged guards and strict aggregation

- `acceptance.py`: `512fcf2744d991246bee62433d43467ff7bc7573`.
- `confirmation_acceptance.py`: `44e1612f2ca59eca80a2c6a436426bc722af18a7`, unchanged and not invoked.
- `native_pdf_navigation.py`: `4573aa6f07666f1d4e508b7352cc4cd42df0a323`, unchanged.
- `exact_invoice_download.py`: `e84e269a1f72e9772bd33284024601f31644d1c0`, unchanged.

The original `run-isolated.sh` blob `f1be008f4e441e09b8f22ff41772d114fb0ba38d` and `sitecustomize.py` blob `fecc07a6a8d0ddbbe19cc2cbd4d234dc209e7cef` are copied byte-for-byte. The original `env -i`, disposable HOME/TMPDIR, disabled integrations, Python outbound-connection guard and SQLite restrictions remain unchanged. Helper copies execute outside both checkouts. No source, score, proposal, generated result or protection rule is patched or newly seeded.

The immutable current plan contains one invoice browser subprocess, no HTTP case. Original exit, report, exact source/scenario/isolation, browser-started/PASS, protected snapshot, unknown-error and all native-download requirements remain. The aggregate additionally enforces the reviewed preview evidence. Missing, duplicate, interrupted, skipped, nonzero or mismatched execution cannot pass. Source/guard/helper failures remain fatal. Prior diagnostic evidence cannot replace current acceptance.

The aggregate writes `remaining-summary.json`; current counts are HTTP 0/browser 1 only if the actual complete case passes. Previous run outcomes remain separate. Artifacts retain screenshots, full reports, exact exits, runtime/install records, source/harness provenance and CI experiment context for 14 days.

## Runtime and limitations

Official MCR Playwright image digest `aa81288e738725378becba5b3e06cb0f3a7f012a610e87e8d767a090ea3f740d`, Playwright 1.62.0, Node 24.22.2, 38 exact application pins and the 45-minute limit remain unchanged. Exact Python/runtime identity is recorded; previous container runs used Python 3.12.3, while original PR CI used 3.12.16. No apt/install-deps/browser install, new dependency, mirror, proxy/DNS/security change, privileged/browser option or safe.directory exception.

Native PDF viewer rendering remains outside coverage; verified embedded preview raster is a separate path. Native HTTP notification redirect is also not covered by the existing synthetic same-origin meta-refresh relay. This does not certify live AI/OCR, external delivery, production data, concurrency, professional acceptance or full regression.

Preparation and review use static/pure tests only, with no local browser/listener or remote write. The parent publishes only after independent review. Report the actual new result and its limitations without changing historical verdicts or implying that preparation is a browser pass.
