#!/bin/bash
set -euo pipefail
ROOT=$(pwd)
test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD"
test -z "$(git status --porcelain --untracked-files=all)"
git merge-base --is-ancestor 24e5d814e3cf564bfedfa0a3c1c8ae9e85fd647e HEAD
printf 'TESTED_HEAD=%s\nTESTED_TREE=%s\n' "$EXPECTED_HEAD" "$(git rev-parse HEAD^{tree})"
RUN=$(mktemp -d); trap 'rm -rf "$RUN"' EXIT
mkdir -p "$RUN/repo" "$RUN/home" "$RUN/tmp"
git archive HEAD | tar -x -C "$RUN/repo"
python - "$RUN/repo" <<'PY'
import sys,json,hashlib
from pathlib import Path
p=Path(sys.argv[1]);m=json.loads((p/'tests/demo_previous_day_pg/manifest.json').read_text())
for f,h in m['files'].items():assert hashlib.sha256((p/f).read_bytes()).hexdigest()==h,f
print('PUBLISHED_CANDIDATE_HASHES_MATCH')
PY
PYTHON=$(command -v python)
env -i PATH="$PATH" HOME="$RUN/home" PYTHONDONTWRITEBYTECODE=1 "$PYTHON" "$RUN/repo/tests/demo_previous_day_pg/preflight.py"
env -i PATH="$PATH" HOME="$RUN/home" TMPDIR="$RUN/tmp" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$RUN/repo/tests/demo_previous_day_pg/guard:$RUN/repo/tests/demo_previous_day_pg:$RUN/repo:$RUN/repo/tests" SEED_ISOLATED_PG=1 DATABASE_URL='postgresql+psycopg2://seed_fixture:synthetic_only@127.0.0.1:55433/seed_fixture' SECRET_KEY='synthetic-fixture-only' AWS_EC2_METADATA_DISABLED=true AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_CONFIG_FILE=/dev/null OPENAI_API_KEY='' SMTP_HOST='' S3_BUCKET_NAME='' VAPID_PRIVATE_KEY='' VAPID_PUBLIC_KEY='' DOCUMENT_IMPORT_WORKER_ENABLED=0 "$PYTHON" "$RUN/repo/tests/demo_previous_day_pg/test_pg.py"
