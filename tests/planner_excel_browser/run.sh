#!/usr/bin/env bash
set -euo pipefail
REPO=$(realpath "$1"); PY=$(realpath "$2"); OUT=$(realpath -m "$3"); CHROME=$(realpath "$4")
HERE=$(cd "$(dirname "$0")" && pwd)
RUN=$(mktemp -d); mkdir -p "$RUN/home" "$RUN/tmp" "$OUT"
trap '[[ -z "${SERVER:-}" ]] || kill "$SERVER" 2>/dev/null || true; rm -rf "$RUN"' EXIT
GUARD="$REPO/tests/history_presentation_browser/guard"
env -i PATH="$PATH" HOME="$RUN/home" LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$GUARD" TMPDIR="$RUN/tmp" DKSS_VALIDATION_TMP="$RUN/tmp" DKSS_BROWSER_ACCEPTANCE_ISOLATED=1 "$PY" "$REPO/tests/inspection_calendar_browser/server.py" --repo "$REPO" --out "$RUN/server" > "$OUT/server.log" 2>&1 &
SERVER=$!
for i in $(seq 1 60); do [[ -f "$RUN/server/ready" ]] && break; kill -0 "$SERVER" || { cat "$OUT/server.log"; exit 1; }; sleep 1; done
[[ -f "$RUN/server/ready" ]]
env -i PATH="$PATH" HOME="$RUN/home" Q12_BROWSER_EXECUTABLE="$CHROME" PLAYWRIGHT_MODULE="${PLAYWRIGHT_MODULE:?}" node "$HERE/browser.cjs" "$RUN/server/fixture.json" "$OUT"

# Validate the actual native downloads, not Chromium's provisional name.
"$PY" - "$OUT" <<'PYBOOK'
from pathlib import Path
from openpyxl import load_workbook
import sys
files=list(Path(sys.argv[1]).glob('download-*.xlsx'))
assert len(files)==12,len(files)
for file in files:
 w=load_workbook(file)
 assert w.sheetnames==['年間点検計画','点検明細'],w.sheetnames
 assert w.active['A1'].value=='2025年度 点検計画'
 assert '試験営業所' in w.active['A2'].value
 assert '1台' in w.active['A3'].value and '対象1件' in w.active['A3'].value
print('NATIVE_WORKBOOKS_OK',len(files))
PYBOOK
