# Frozen history presentation acceptance

A narrow real-Chromium suite for the history timeline date gutter and Karte sidebar selection. The application checkout is pinned separately from the validation harness. Based on PR #361, preserving startup recovery changes; no production or real-user data is involved.

- Both canonical and legacy history URLs select only Vehicle Karte, not Master management.
- Widths 1440, 1024, 901, 900, 769, 768 and 390 cover the desktop/mobile timeline boundary. Date marker gap and date-cell bounds are measured; mobile date labels and navigation drawer remain usable. Overlay dismissal is asserted through the 900px boundary.
- Category filtering, pagination, back/forward and empty history retain selection. Master-page navigation remains independent.
- 25 synthetic persisted history records remain unchanged. Normal notification polling remains active; only documented fixture notification-maintenance SQL is permitted after setup. No blanket ordinary-app read-only claim is made.
- Python socket connections and SQLite outside the disposable directory are forbidden. Browser external and non-GET requests fail acceptance; no secrets/profile are inherited by the runner.

The transport is real Flask GET responses fulfilled in-process to real Chromium. This is not a live HTTP/TLS, authentication/MFA, proxy or deployed-service acceptance test. Browser artifact screenshots are synthetic.

Use run-isolated.sh with the frozen application repo and an explicit Python executable. --preflight-only validates fixture/data/navigation without launching a browser. The identical-tree flag is permitted only for this local preflight. --run-browser requires the exact public SHA and installed Chromium. GitHub Actions performs the real browser run and preserves screenshots and JSON evidence. Failed runs are retained; no automatic retries.
