#!/usr/bin/env bash
set -euo pipefail
export PRODUCT_REPO="${PRODUCT_REPO:?checkout required}"
export ARTIFACTS="${ARTIFACTS:?artifact directory required}"
export HTML_OUT="$ARTIFACTS/html"
HERE="$(cd "$(dirname "$0")" && pwd)"
"${PYTHON:-python}" "$HERE/render_real.py"
node "$HERE/browser.cjs"
