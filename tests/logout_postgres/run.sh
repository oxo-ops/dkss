#!/bin/bash
set -euo pipefail
ROOT=$(pwd)
test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD"
test -z "$(git status --porcelain --untracked-files=all)"
printf 'TESTED_HEAD=%s\nTESTED_TREE=%s\n' "$EXPECTED_HEAD" "$(git rev-parse HEAD^{tree})"
RUN=$(mktemp -d)
trap 'rm -rf "$RUN"' EXIT
mkdir -p "$RUN/repo" "$RUN/home"
git archive HEAD | tar -x -C "$RUN/repo"
(cd "$RUN/repo" && git apply --check tests/logout_postgres/candidate.patch && git apply tests/logout_postgres/candidate.patch)
python - "$RUN/repo" <<'PY'
import json,hashlib,sys
from pathlib import Path
p=Path(sys.argv[1]);m=json.loads((p/'tests/logout_postgres/manifest.json').read_text())
for f,expected in m['files'].items():assert hashlib.sha256((p/'dkss_app'/f).read_bytes()).hexdigest()==expected,f
print('CANDIDATE_7_HASHES_MATCH')
PY
PYTHON=$(command -v python)
env -i PATH="$PATH" HOME="$RUN/home" PYTHONDONTWRITEBYTECODE=1 "$PYTHON" "$RUN/repo/tests/logout_postgres/test_preflight.py"
env -i PATH="$PATH" HOME="$RUN/home" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$RUN/repo/tests/logout_postgres/guard:$RUN/repo/tests/logout_postgres:$RUN/repo:$RUN/repo/tests" Q02_POSTGRES_TEST_URL='postgresql+psycopg2://dkss_logout_ci:synthetic-ci-only@127.0.0.1:55432/dkss_q02_ci' Q02_REQUIRE_POSTGRES=1 AWS_EC2_METADATA_DISABLED=true AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_CONFIG_FILE=/dev/null OPENAI_API_KEY='' SMTP_HOST='' S3_BUCKET_NAME='' VAPID_PRIVATE_KEY='' VAPID_PUBLIC_KEY='' "$PYTHON" "$RUN/repo/tests/logout_postgres/test_postgres.py" "$RUN/repo"
