#!/usr/bin/env bash
set -euo pipefail
: "${PRODUCT_REPO:?}" "${ARTIFACTS:?}" "${EXPECTED_SHA:?}" "${PLAYWRIGHT_MODULE:?}"
[[ $(git -C "$PRODUCT_REPO" rev-parse HEAD) == "$EXPECTED_SHA" ]]
[[ -z $(git -C "$PRODUCT_REPO" status --porcelain) ]]
R=$(mktemp -d); trap 'rm -rf "$R"' EXIT
mkdir -p "$R/home" "$R/tmp" "$ARTIFACTS"
HERE="$PRODUCT_REPO/tests/master_compact_browser"
BROWSERS="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"
[[ -d "$BROWSERS" ]]
env -i PATH="$PATH" HOME="$R/home" LANG=C.UTF-8 TMPDIR="$R/tmp" DKSS_VALIDATION_TMP="$R/tmp" DKSS_BROWSER_ACCEPTANCE_ISOLATED=1 PYTHONPATH="$PRODUCT_REPO/tests/history_presentation_browser/guard" PRODUCT_REPO="$PRODUCT_REPO" HTML_OUT="$R/html" python "$HERE/render_pages.py"
env -i PATH="$PATH" HOME="$R/home" LANG=C.UTF-8 PRODUCT_REPO="$PRODUCT_REPO" HTML_OUT="$R/html" ARTIFACTS="$ARTIFACTS" PLAYWRIGHT_MODULE="$PLAYWRIGHT_MODULE" PLAYWRIGHT_BROWSERS_PATH="$BROWSERS" node "$HERE/browser.cjs"
printf '%s\n' "$EXPECTED_SHA" > "$ARTIFACTS/source-sha.txt"
