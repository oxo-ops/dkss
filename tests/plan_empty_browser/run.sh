#!/usr/bin/env bash
set -euo pipefail
REPO=$(realpath "$1"); PY=$(realpath "$2"); OUT=$(realpath -m "$3"); CHROME=$(realpath "$4")
HERE=$(cd "$(dirname "$0")" && pwd)
RUN=$(mktemp -d); mkdir -p "$RUN/home" "$RUN/tmp" "$OUT"
trap '[[ -z "${SERVER:-}" ]] || kill "$SERVER" 2>/dev/null || true; rm -rf "$RUN"' EXIT
GUARD="$REPO/tests/history_presentation_browser/guard"
env -i PATH="$PATH" HOME="$RUN/home" LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$GUARD" TMPDIR="$RUN/tmp" DKSS_VALIDATION_TMP="$RUN/tmp" DKSS_BROWSER_ACCEPTANCE_ISOLATED=1 "$PY" "$HERE/server.py" --repo "$REPO" --out "$RUN/server" > "$OUT/server.log" 2>&1 &
SERVER=$!
for i in $(seq 1 60); do [[ -f "$RUN/server/ready" ]] && break; kill -0 "$SERVER" || { cat "$OUT/server.log"; exit 1; }; sleep 1; done
[[ -f "$RUN/server/ready" ]]
env -i PATH="$PATH" HOME="$RUN/home" Q12_BROWSER_EXECUTABLE="$CHROME" PLAYWRIGHT_MODULE="${PLAYWRIGHT_MODULE:?}" node "$HERE/browser.cjs" "$RUN/server/fixture.json" "$OUT"
