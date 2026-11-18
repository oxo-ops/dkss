#!/usr/bin/env bash
set -euo pipefail
: "${PRODUCT_REPO:?}" "${ARTIFACTS:?}" "${EXPECTED_SHA:?}" "${PLAYWRIGHT_MODULE:?}"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]]
[[ "$(git -C "$PRODUCT_REPO" rev-parse HEAD)" == "$EXPECTED_SHA" ]]
[[ -z "$(git -C "$PRODUCT_REPO" status --porcelain)" ]]
HERE="$(cd "$(dirname "$0")" && pwd)"
RUN="$(mktemp -d)";trap 'rm -rf "$RUN"' EXIT
mkdir -p "$RUN/home" "$RUN/tmp" "$ARTIFACTS"
printf '{"head":"%s","synthetic":true,"live":false}\n' "$EXPECTED_SHA" > "$ARTIFACTS/target-report.json"
PY="${PYTHON:-$(command -v python)}"
env -i PATH="$PATH" HOME="$RUN/home" LANG=C.UTF-8 TMPDIR="$RUN/tmp" DKSS_VALIDATION_TMP="$RUN/tmp" PYTHONPATH="$PRODUCT_REPO/tests/quality_feature_browser/guard" PRODUCT_REPO="$PRODUCT_REPO" HTML_OUT="$ARTIFACTS/html" "$PY" "$PRODUCT_REPO/tests/demo_guide/render_pages.py"
env -i PATH="$PATH" HOME="$HOME" LANG=C.UTF-8 PRODUCT_REPO="$PRODUCT_REPO" HTML_OUT="$ARTIFACTS/html" ARTIFACTS="$ARTIFACTS" PLAYWRIGHT_MODULE="$PLAYWRIGHT_MODULE" node "$HERE/browser.cjs"
