#!/usr/bin/env bash
set -euo pipefail
export PRODUCT_REPO="${PRODUCT_REPO:?explicit product checkout required}"
export HTML_OUT="${ARTIFACTS:?artifact directory required}/html"
HERE="$(cd "$(dirname "$0")" && pwd)"
"${PYTHON:-python}" "$HERE/render_pages.py"
node "$HERE/capture_inspection.cjs"
"${PYTHON:-python}" "$HERE/attach_inspection_image.py"
node "$HERE/capture_ai_drawer.cjs"
"${PYTHON:-python}" "$HERE/attach_ai_image.py"
"${PYTHON:-python}" "$HERE/render_pages.py"
node "$HERE/browser_pages.cjs"
