# PR377 invoice document-scroll acceptance

This validation runs only the still-unpassed invoice browser case at 1440, 390 and 320px. It requires embedded preview readiness and visible canvas evidence on both maintenance screens, followed by the actual native original download at each width, in the same full invoice flow. No other previously passing browser case, separate HTTP preflight, Node, comparison or dashboard group is rerun.

Native downloads passed in an earlier run, but that invoice case still failed on six preview fetch cancellations. The subsequent 1440px diagnostic observed rendered preview DOM alongside those cancellations; it did not execute or pass full invoice acceptance. This new run must establish its own complete outcome. A new pass must not overwrite any earlier failed or diagnostic verdict.

## Frozen application and separate validation

- Application commit: `30d4dfeee97f69bd00650c6bf56a5ce234f34437`.
- Application tree: `31bb88b2d7a1a93f4c52f5aeefd59e97a8c8d3ea`.
- Requirements blob: `f29b6951157ecb12ef81490f42dfb5d57bdd9330`, 38 exact pins.
- Previous validation commit: `1fe03a294cf68105c06b3a434a93886ce80b7af4`.
- Previous validation tree: `636d8c649739fee4df109f243262d9fabdc62f43`.
- The triggering `github.sha`, validation tree and every validation file hash are recorded separately.

Application and validation have separate clean checkouts, with no overlay. Runtime verifies source identity, original harness hashes, fixed helper bytes, copied wrapper/guard and import-shadow exclusions before and after execution and at aggregation. No product branch, main, PR, deployment, live service or existing database action is included.

## Prior evidence retains each original verdict

`harness/prior-evidence.json` has SHA-256 `3d135f66de36f03aeeb38abd05890f6d0eb343cd5979123ee3502e445f7cc4d9`.

Latest [run 43075650114](https://github.com/oxo-ops/dkss/actions/runs/43075650114), validation `1fe03a294cf68105c06b3a434a93886ce80b7af4`, completed the two 1440px preview proofs, one real native saved-file/receiver transfer and that width's routes. It stopped at 390px maintenance-tab geometry. All full acceptance remains failed/zero; the final protected-record check was not reached. Completed components, partial arrays and completion flags are retained separately. Artifact `13882316519`, SHA-256 `9d0d2a452f3ab54fe092f151fb0d260e01845e6a393dc5301ee24722baf0b016`.

The 390px record contained a final clipping rectangle y−1663…−883, exactly 780px high, which made the intersection inverted. The old report did not record node identity, so those numbers alone do not prove which ancestor it was. The new collector must record the actual standards-mode document-root identity before using viewport coordinates. No prior failure is erased or converted into a pass by synthetic regression metadata.

Previous [run 43072294744](https://github.com/oxo-ops/dkss/actions/runs/43072294744), validation `431a29e94e27a6a295f926801d806a8856805be1`, stopped at the first 1440px maintenance-tab whole-canvas viewport assertion. The final attached canvas was 337×477, while its overflow:auto scroll window exposed about 400px vertically. The reported 119×169 state had been captured before the resize. A 520px outer viewer with toolbar/status and default width-fit cannot simultaneously show that whole page. This evidence does not establish a product defect.

The run remains failed with zero accepted cases. Preview classification, native download and final protected-record confirmation were not reached: proof/cancellation/download/transfer arrays are empty, and the final protected field is absent. Its old eager `full_invoice_browser_executed`/`native_download_reexecuted` booleans represented mode intent, not completion; the index explicitly records that distinction. Artifact `13878337943`, SHA-256 `9767c1a2a73686f877b35332493bc6361310836082f9241db6a7db90acf38620`. Original report/exit/times, six manifests and the complete nested index are retained.

Earlier hierarchy, preserved unchanged:

1. [Run 43069457448](https://github.com/oxo-ops/dkss/actions/runs/43069457448) completed a 1440px preview diagnostic only. It retains `PREVIEW_DIAGNOSTIC_COMPLETE_NOT_ACCEPTANCE`, HTTP/browser acceptance 0/0 and no native-download reexecution. Both maintenance-screen DOM observations were ready, with positive raster dimensions and no preview error, alongside two `ERR_ABORTED` fetches. The full-page screenshots did not themselves show the canvas in the viewport; that is distinct from DOM raster readiness. Artifact `13878495078`, SHA-256 `383bd14f62b79c040aada0bc402f282c15a3a45ca9dab116c7d0f49c998d1d36`.
2. [Run 43066261383](https://github.com/oxo-ops/dkss/actions/runs/43066261383) completed three native downloads with matching saved bytes, one completed receiver transfer per width and cleanup. The full invoice report still failed on six preview fetch cancellations; its exit 1 and failed verdict remain. Artifact `13876665717`, SHA-256 `65f6663bb490c2ff630297ac49d608c74768101d2f31e40d471c14ed12024cc3`.
3. Run `43061389706`: manufacturer passed; invoice failed with native Download `canceled`.
4. Run `43058463867`: legal passed; invoice/manufacturer failed.
5. Run `43053078956`: 3 HTTP and 10 browser cases passed; invoice/manufacturer/legal failed.
6. Run `43043343085`: Node 41 tests, comparison 14 cases and dashboard 6 widths passed; the run failed on the original companion fixture.

Every level preserves its artifact digest, original reports/exits/timestamps, manifest hashes and nested reference. The previous index SHA-256 `756a19a2731cf3c68679ee396ad0c4d12a187bf987a7436a98fd482400904892` is nested unchanged. Its diagnostic and older references remain intact. The latest ZIP and every expanded file, source/harness identities, failed report/exits and six manifests were checked before preparation. Diagnostic completion never counts as acceptance. Prior successes do not count as current results.

[Original PR run 43036556295, attempt 2](https://github.com/oxo-ops/dkss/actions/runs/43036556295/attempts/2) failed during dependency installation on Ubuntu-host DNS and was not rerun by this work. Supplemental acceptance does not replace original CI or full regression.

## Preview and cancellation evidence

For each width, the real maintenance tab and exact record link require one complete preview: disclosure open/close, one-page current/count/status, positive page dimensions and raster, exact source/record identity and no timeout or preview console error.

The corrected visibility check verifies reachability through the existing scroll window, without changing zoom, layout, rendering, DOM, CSS or scroll values:

- After bringing the inner scroller into view, wait for seven equal ready/raster/geometry samples at 50ms intervals spanning at least 300ms, within a five-second bound. Refresh final reported dimensions after settling.
- Hover the actual inner scroller and use native mouse-wheel input to its top and bottom. Wait for each real endpoint and settle again.
- Intersect the viewport with every clipping ancestor, measure the actual paper-local visible region, and verify visible corners/center are not obscured by an unrelated overlay.
- Both endpoint captures must use the same stable final paper/raster size, expose the full page width and together cover its entire height continuously, from the real top to the real bottom. One CSS pixel permits fractional border/scroll rounding only; no percentage visibility exemption is introduced.
- Save three PNGs per preview: the original `invoice-preview-{stage}-{width}.png`, top `-visible.png` and bottom `-visible-bottom.png`. All six observations and eighteen PNGs are required.

`canvas_regions_reachable=true` replaces simultaneous whole-canvas visibility. `preview_regions` contains ordered top/bottom paper, viewport, clipping ancestors/intersection, visible region, unobscured check, raster, actual scroll geometry and stability evidence. The outer runner recomputes geometry using the exact reviewed pure predicate (source SHA-256 `4789553d18d8bc965e932ab0127dc606367eed1a227d5439d882c900e08a5fee`) and rejects stale/changing raster, clipped width, gaps, unreachable endpoints or missing evidence. Reachability over two user scroll positions does not mean the entire page was visible simultaneously. The synthetic PDF page is blank: this proves rendered page access, not text or visual-content fidelity.

The only new collector/predicate correction concerns the standards-mode document scroller. Viewport bounds are used only when `document.compatMode === "CSS1Compat"` and the ancestor is both the exact `document.documentElement` and exact `document.scrollingElement`. Its viewport-special clientWidth/clientHeight must not be offset by a document-scrolled bounding-box origin. Every ordinary ancestor, including BODY, keeps its raw client box and original clipping axes.

Each sample now records `document_compat_mode` and `document_viewport`. Each clipping entry records `box_kind`, `tag_name`, actual document/scroller/BODY identity booleans and `raw_client_box` alongside applied bounds. The aggregate requires exact viewport semantics for the qualified HTML root; all other applied bounds must equal the raw client box. It does not skip a tag, discard BODY or relax occlusion/continuous coverage. New real CI must establish that runtime identity. Regression identities were explicitly synthetic even where numeric rectangles came from the earlier artifact.

Each preview must correlate exactly four ordered source events to one distinct Request, the actual same main Frame/Page, exact scope/phase/page and original source: request, bridge response, browser response, then requestfinished or requestfailed. Both responses must be HTTP 200 with the original small PDF hash/length and identical selected inline, unencoded, non-range headers. Range/If-Range, other status/type/body, duplicate/late events, other frame/source or another error cannot qualify.

Only after verified rendered-page scroll reachability may the exact `net::ERR_ABORTED` entry for that identical Request move to `verified_invoice_preview_cancellations`. Its raw failure and all source events remain. Equal-valued failures from other Request objects stay fatal. Normal requestfinished must meet the same evidence requirements. `verified_invoice_preview_fetches` contains six distinct proof records; cancellations must equal only their failed subset. The outer aggregate independently checks these identities and evidence references, all reachability/ready geometry and screenshots, alongside unchanged native saved-download evidence.

The fixed helper retains all 73 prior require conditions and nine unchanged source/observer/callback/acceptor/scroll/bridge/get/snapshot function ASTs. Only the geometry collector and pure predicate change. It passed 26 pure/static contracts plus 21 portable contracts, including actual-root versus HTML-lookalike, BODY, wrong scroller, quirks-mode, ordinary clipping and metadata-tampering negatives. Independent read-only review found no static blockers; actual new root identity and three-width behavior still need official CI.

The observable classification does not prove who called abort or assert an intentional PDF.js completion cancellation. It applies only to the exact evidence-supported preview request. Unknown, unmatched or otherwise failing requests remain fatal. Diagnostic mode cannot satisfy this full-acceptance aggregator.

## Actual native download in the same full flow

The command uses `--case invoice --run-browser --native-invoice-download-http` without the diagnostic flag. `full_invoice_browser_selected` records intent separately. `native_download_attempted` changes only upon reaching that path; full execution and native-download completion markers stay false until final full PASS. Partial arrays remain the actual reached evidence if a run fails. Each width retains the real source navigation, Back, maintenance tab, exact record, actual download click, Playwright Download, null failure and saved-file SHA-256/length match. Native download is rechecked only as part of this complete invoice acceptance with the new preview requirements, not as a separate successful-case rerun.

The unchanged response-only receiver freezes the actual synthetic original PDF response. It serves only one exact GET/Host/path/loopback peer on IPv4 `127.0.0.1:8765`, with a 15-second lifetime, 2-second accepted-socket timeout and bounded cleanup. No Flask dispatch, database/filesystem access, proxy, outbound connection or DNS in the receiver. Exactly one completed transfer per width, zero rejected/errors/expiry, correct body identity and complete cleanup remain mandatory. A source GET alone cannot satisfy native-download completion.

The outer runner retains the existing public GitHub/runtime/source checks and records official-CI experiment selection. These are location/provenance checks, not a new authentication or authorization system. The original wrapper receives only the explicit mode flag; no new credential, environment variable or permission is introduced.

## Fixed helpers, unchanged guards and strict aggregation

- `acceptance.py`: `81840fd3ea281fd198ce1101794c1c887eb7d9c3`.
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
