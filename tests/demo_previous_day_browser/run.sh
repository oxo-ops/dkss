#!/bin/bash
set -euo pipefail
PY=$1; CHROMIUM=$2; OUT=$3
ROOT=$(pwd)
test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD"
test -z "$(git status --porcelain --untracked-files=all)"
git merge-base --is-ancestor 145694c078f3fb2ff2ff6af33e2ad3e2b6f15183 HEAD
RUN=$(mktemp -d);trap 'rm -rf "$RUN"' EXIT
mkdir -p "$RUN/repo" "$RUN/home" "$RUN/tmp" "$OUT"
git archive HEAD | tar -x -C "$RUN/repo"
(cd "$RUN/repo" && git apply --check tests/demo_previous_day_browser/candidate.patch && git apply tests/demo_previous_day_browser/candidate.patch)
"$PY" tests/demo_previous_day_browser/preflight.py "$RUN/repo"
export SOURCE_HEAD=$EXPECTED_HEAD
CLEAN=(env -i PATH="$(dirname "$PY"):/usr/local/bin:/usr/bin:/bin" HOME="$RUN/home" TMPDIR="$RUN/tmp" LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DKSS_VALIDATION_TMP="$RUN/tmp" DKSS_BROWSER_ACCEPTANCE_ISOLATED=1 SOURCE_HEAD="$EXPECTED_HEAD" PYTHONPATH="$RUN/repo/tests/history_presentation_browser/guard:$RUN/repo/tests/demo_previous_day_browser:$RUN/repo:$RUN/repo/tests" DATABASE_URL=sqlite:///:memory: SECRET_KEY=synthetic-only RENDER='' RATELIMIT_STORAGE_URI=memory:// AWS_EC2_METADATA_DISABLED=true AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_CONFIG_FILE=/dev/null S3_BUCKET_NAME='' OPENAI_API_KEY='' SMTP_HOST='' VAPID_PRIVATE_KEY='' VAPID_PUBLIC_KEY='' DOCUMENT_IMPORT_WORKER_ENABLED=0)
cd "$RUN/repo"
"${CLEAN[@]}" "$PY" -c 'import sys,importlib.util,pathlib; root=pathlib.Path(sys.argv[1]).resolve(); spec=importlib.util.find_spec("dkss_app.demo_previous_day"); assert spec and pathlib.Path(spec.origin).resolve()==root/"dkss_app/demo_previous_day.py"; print("PATCHED_IMPORT_SOURCE_MATCH")' "$RUN/repo"
"${CLEAN[@]}" "$PY" -m unittest test_demo_seed_share test_demo_share_entry test_public_demo_workflow test_demo_inspection_compact -v
"${CLEAN[@]}" "$PY" "$RUN/repo/tests/demo_previous_day_browser/acceptance.py" --repo "$RUN/repo" --artifacts "$OUT/preflight" --preflight-only
"${CLEAN[@]}" "$PY" "$RUN/repo/tests/demo_previous_day_browser/acceptance.py" --repo "$RUN/repo" --artifacts "$OUT/browser" --expected-sha "$EXPECTED_HEAD" --chromium "$CHROMIUM"
