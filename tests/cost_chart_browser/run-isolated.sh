#!/usr/bin/env bash
set -euo pipefail
PY=$1; CHROMIUM=$2; OUT=$3
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
[[ "$PY" = /* && -x "$PY" && "$CHROMIUM" = /* && "$OUT" = /* ]]
ROOT=$(cd "$HERE/../.." && pwd)
: "${EXPECTED_HEAD:?exact approved head required}"
[[ "$EXPECTED_HEAD" =~ ^[0-9a-f]{40}$ ]]
ACTUAL_HEAD=$(git -C "$ROOT" rev-parse HEAD)
[[ "$ACTUAL_HEAD" = "$EXPECTED_HEAD" ]]
[[ -z "$(git -C "$ROOT" status --porcelain --untracked-files=all)" ]]
RUN=$(mktemp -d); mkdir -p "$RUN/home" "$RUN/tmp" "$OUT"
env -i PATH="$(dirname "$PY"):/usr/local/bin:/usr/bin:/bin" HOME="$RUN/home" TMPDIR="$RUN/tmp" LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 "$PY" "$HERE/prepare.py"
exec env -i PATH="$(dirname "$PY"):/usr/local/bin:/usr/bin:/bin" HOME="$RUN/home" TMPDIR="$RUN/tmp" LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 DKSS_BROWSER_ACCEPTANCE_ISOLATED=1 DKSS_COST_VERIFIED_HEAD="$ACTUAL_HEAD" "$PY" "$HERE/browser.py" --chromium "$CHROMIUM" --artifacts "$OUT"
