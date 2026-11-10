# Frozen history presentation acceptance

A narrow real-Chromium suite for the history timeline date gutter and Karte sidebar selection. The application checkout is pinned separately from the validation harness. Based on PR #361, preserving startup recovery changes; no production or real-user data is involved.

- Both canonical and legacy history URLs select only Vehicle Karte, not Master management.
- Widths 1440, 1024, 901, 900, 769, 768 and 390 cover the desktop/mobile timeline boundary. Date marker gap and date-cell bounds are measured; mobile date labels and navigation drawer remain usable. Overlay dismissal is asserted through the 900px boundary.
- Category filtering, pagination, back/forward and empty history retain selection. Master-page navigation remains independent.
- 25 synthetic persisted history records remain unchanged. Normal notification polling remains active; only documented fixture notification-maintenance SQL is permitted after setup. No blanket ordinary-app read-only claim is made.
- Python socket connections and SQLite outside the disposable directory are forbidden. Browser external and non-GET requests fail acceptance; no secrets/profile are inherited by the runner.

The transport is real Flask GET responses fulfilled in-process to real Chromium. This is not a live HTTP/TLS, authentication/MFA, proxy or deployed-service acceptance test. Browser artifact screenshots are synthetic.

Use run-isolated.sh with the frozen application repo and an explicit Python executable. --preflight-only validates fixture/data/navigation without launching a browser. The identical-tree flag is permitted only for this local preflight. --run-browser requires the exact public SHA and installed Chromium. GitHub Actions performs the real browser run and preserves screenshots and JSON evidence. Failed runs are retained; no automatic retries.

## Short-height regression (2026-11-10)

The desktop history panel previously capped itself to the remaining viewport. Its
non-shrinking filters, categories and help text could consume nearly all of that
height, leaving the history table as a thin strip. The history-specific stylesheet
now treats the available height as a minimum, allowing ordinary page scrolling.

The workflow compares the pinned release `8ee31738b68b486a86ef9c48f67a0182b5a9f376`
with the exact PR-head candidate. Baseline mode must reproduce a collapsed table;
candidate mode requires room for the table header and at least one full record,
non-overlapping footer, scroll-reachable rows and controls, working category,
filter and pagination navigation, and repeated resize without recollapse.

Coverage includes the observed 1180x757 viewport, 1165x747, heights 600/650/700/800/850 at 1165px, the 960/961px
boundary, 1440x650, 1024x650 and 390x600, with both dense and two-row synthetic
history. The original seven-width, 1000px-high date-gutter and navigation suite
still runs on the candidate. Full-page screenshots and measured geometry for each
short viewport are artifacts. No real data is copied into fixtures or artifacts.

`--expected-sha` binds the candidate to the trusted CI PR-head SHA. Without it,
the updated harness requires the pinned pre-fix release SHA and tree.
`--baseline-collapse` is allowed only for that pinned release. Local preflight can
still use an identical baseline tree; browser execution does not permit that flag.

The same synthetic dense/two-row fixture is also measured at 1180x757 on the
pre-category release `008ed6e41352a852828f10193972e6e415f9a20e`. This is a
geometry-only causal comparison, not a claim that the old UI passes new
category/navigation requirements. Its distinct report status is
`HISTORICAL_HEIGHT_MEASURED`; baseline reproduction is
`BASELINE_COLLAPSE_REPRODUCED`, and only candidate acceptance reports `PASS`.
