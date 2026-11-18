#!/bin/bash
set -euo pipefail
REPO=$(realpath "$1"); PY=$(realpath "$2"); MODE=${3:-http}
[[ $MODE == http || $MODE == browser ]]
[[ $(git -C "$REPO" rev-parse HEAD) == "$EXPECTED_HEAD" ]]
[[ -z $(git -C "$REPO" status --porcelain) ]]
RUN=$(mktemp -d); mkdir -p "$RUN/tmp" "$RUN/home"; OUT=${ARTIFACTS:-$RUN/artifacts}; mkdir -p "$OUT"
HERE="$REPO/tests/demo_first_save"
if [[ $MODE == http ]]; then
 for file in test_ui.cjs test_detail_flight.cjs test_unknown.cjs test_complete_pending.cjs; do DEMO_CANDIDATE_REPO="$REPO" node "$HERE/$file"; done
 FILE=test_http.py
else FILE=browser.py; fi
env -i PATH="$(dirname "$PY"):/usr/bin:/bin" HOME="$RUN/home" TMPDIR="$RUN/tmp" DKSS_VALIDATION_TMP="$RUN/tmp" ARTIFACTS="$OUT" EXPECTED_HEAD="$EXPECTED_HEAD" PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/tmp/dkss-synthetic-browser}" DEMO_CANDIDATE_REPO="$REPO" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$REPO/tests/quality_feature_browser/guard" AWS_EC2_METADATA_DISABLED=true AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_CONFIG_FILE=/dev/null "$PY" "$HERE/$FILE"
