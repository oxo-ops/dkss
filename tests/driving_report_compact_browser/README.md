# Daily report compact presentation

Uses synthetic Flask fixtures from `AdminSelfTests`, no production database or AI.
Run with the project requirements installed:

```sh
mkdir -p "$TMPDIR/html" "$TMPDIR/db" "$TMPDIR/images"
PRODUCT_REPO="$PWD" HTML_OUT="$TMPDIR/html" DKSS_VALIDATION_TMP="$TMPDIR/db" \
 PYTHONPATH="$PWD/tests/history_presentation_browser/guard" TMPDIR="$TMPDIR/db" \
 python tests/driving_report_compact_browser/render.py
PRODUCT_REPO="$PWD" HTML_OUT="$TMPDIR/html" ARTIFACTS="$TMPDIR/images" \
 node tests/driving_report_compact_browser/browser.cjs
```

Set PLAYWRIGHT_MODULE if needed; CHROMIUM optionally selects a local browser.
The browser intercepts requests and serves only local fixtures/static files.
15 cases: self / office / user at 320, 390, 650, 768, 1316 CSS pixels.
Checks content/links/status colors retained, mobile height reduced, 44px detail action,
no page overflow, desktop geometry unchanged, selection is blue.

2026-11-20 local result: fixture render passed; related 28 unittest cases passed.
Browser execution blocked before page load by local socket permission (Operation not permitted).
No visual acceptance or height-reduction pass is claimed pending running this harness.
