#!/usr/bin/env bash
set -euo pipefail
: "${PRODUCT_REPO:?exact isolated checkout required}"
: "${ARTIFACTS:?artifact path required}"
: "${EXPECTED_SHA:?official commit SHA required}"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]]
[[ "$(git -C "$PRODUCT_REPO" rev-parse HEAD)" == "$EXPECTED_SHA" ]]
[[ -z "$(git -C "$PRODUCT_REPO" status --porcelain)" ]]
mkdir -p "$ARTIFACTS"
printf '{"head":"%s","clean_before_fixture":true}\n' "$EXPECTED_SHA" > "$ARTIFACTS/target-report.json"
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-$(command -v python)}"
export HTML_OUT="$ARTIFACTS/html"
env -i PATH="$PATH" HOME="$HOME" LANG=C.UTF-8 PRODUCT_REPO="$PRODUCT_REPO" HTML_OUT="$HTML_OUT" "$PY" "$HERE/render_pages.py"
for test in browser components; do
  env -i PATH="$PATH" HOME="$HOME" LANG=C.UTF-8 PRODUCT_REPO="$PRODUCT_REPO" HTML_OUT="$HTML_OUT" ARTIFACTS="$ARTIFACTS" PLAYWRIGHT_MODULE="$PLAYWRIGHT_MODULE" node "$HERE/$test.cjs"
done
