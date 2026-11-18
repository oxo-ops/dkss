#!/bin/bash
set -euo pipefail
REPO=$(realpath "$1"); PY=$(realpath "$2")
[[ $(git -C "$REPO" rev-parse HEAD) == "$EXPECTED_HEAD" ]]
[[ -z $(git -C "$REPO" status --porcelain) ]]
RUN=$(mktemp -d);mkdir -p "$RUN/home" "$RUN/tmp"
env -i PATH="$(dirname "$PY"):/usr/bin:/bin" HOME="$RUN/home" TMPDIR="$RUN/tmp" PYTHONDONTWRITEBYTECODE=1 DEMO_CANDIDATE_REPO="$REPO" PYTHONPATH="$REPO/tests/demo_first_save/pg_guard" DEMO_POSTGRES_URL='postgresql+psycopg2://demo_cas_ci:synthetic-ci-only@127.0.0.1:55439/dkss_demo_cas_ci' AWS_EC2_METADATA_DISABLED=true AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_CONFIG_FILE=/dev/null "$PY" "$REPO/tests/demo_first_save/test_postgres.py"
