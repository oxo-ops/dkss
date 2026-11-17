#!/usr/bin/env bash
set -euo pipefail
PY=$1; CHROMIUM=$2; REPO=$(git rev-parse --show-toplevel)
HERE="$REPO/tests/receipt_detail_browser"
[[ -n "$EXPECTED_HEAD" && "$(git rev-parse HEAD)" == "$EXPECTED_HEAD" ]]
[[ -z "$(git status --porcelain)" ]]
RUN=$(mktemp -d); mkdir -p "$RUN/home" "$RUN/tmp" "$DKSS_BROWSER_ARTIFACT_DIR"
COMMON=(env -i PATH="$(dirname "$PY"):/usr/local/bin:/usr/bin:/bin" HOME="$RUN/home" LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 TMPDIR="$RUN/tmp" DKSS_VALIDATION_TMP="$RUN/tmp" PYTHONPATH="$REPO/tests/history_presentation_browser/guard" DKSS_BROWSER_ACCEPTANCE_ISOLATED=1 DKSS_BROWSER_ARTIFACT_DIR="$DKSS_BROWSER_ARTIFACT_DIR" EXPECTED_HEAD="$EXPECTED_HEAD")
"${COMMON[@]}" "$PY" "$HERE/prepare.py"
cp "$HERE/manifest.json" "$DKSS_BROWSER_ARTIFACT_DIR/manifest.json"
"${COMMON[@]}" "$PY" "$HERE/browser.py" --chromium "$CHROMIUM"
"${COMMON[@]}" "$PY" "$HERE/normal.py" --chromium "$CHROMIUM"
