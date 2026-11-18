#!/usr/bin/env bash
set -euo pipefail
REPO=$(realpath "$1"); PY=$(realpath "$2"); OUT=$(realpath -m "$3"); CHROME=$(realpath "$4"); NODE=$(command -v node)
: "${PLAYWRIGHT_MODULE:?explicit package required}"
RUN=$(mktemp -d); PID=''; trap '[[ -z "$PID" ]] || kill "$PID" 2>/dev/null || true; rm -rf "$RUN"' EXIT
mkdir -p "$RUN/repo" "$RUN/home" "$RUN/tmp" "$OUT"
rm -f "$OUT/ready" "$OUT/cookies.json"
SHA=$(git -C "$REPO" rev-parse HEAD);git -C "$REPO" archive "$SHA" | tar -x -C "$RUN/repo"
printf '%s\n' "$SHA" > "$OUT/source-head.txt"
cd "$RUN"
GUARD="$RUN/repo/tests/driving_office_summary_browser/guard"; CASES="$RUN/repo/tests/driving_office_summary_browser"
E=(env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="$RUN/home" TMPDIR="$RUN/tmp" LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$GUARD:$RUN/repo:$RUN/repo/tests:$CASES")
"${E[@]}" DKSS_OFFICE_PG_ISOLATED=1 "$PY" "$CASES/test_pg.py" > "$OUT/pg.log" 2>&1
"${E[@]}" "$PY" "$CASES/server.py" --repo "$RUN/repo" --out "$OUT" --preflight > "$OUT/preflight.log" 2>&1
"${E[@]}" "$PY" "$CASES/server.py" --repo "$RUN/repo" --out "$OUT" > "$OUT/server.log" 2>&1 & PID=$!
for i in {1..60}; do [[ -f "$OUT/ready" ]] && break; kill -0 "$PID" || { cat "$OUT/server.log"; exit 1; }; sleep .5; done
[[ -f "$OUT/ready" ]]
env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="$RUN/home" TMPDIR="$RUN/tmp" LANG=C.UTF-8 PLAYWRIGHT_MODULE="$PLAYWRIGHT_MODULE" CHROMIUM_EXECUTABLE="$CHROME" "$NODE" "$CASES/browser.cjs" "$OUT"
