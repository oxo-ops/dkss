#!/usr/bin/env bash
set -euo pipefail
[[ $# -ge 2 ]] || { echo 'Usage: run-isolated-tests.sh ABSOLUTE_REPO ABSOLUTE_PYTHON [UNITTEST_SELECTOR...]' >&2; exit 2; }
REPO=$(realpath "$1")
PYTHON=$2
shift 2
if [[ $# = 0 ]]; then set -- test_video_connected_flows; fi
[[ "$PYTHON" = /* && -x "$PYTHON" ]] || exit 2
RUN=$(mktemp -d "${TMPDIR:-/tmp}/dkss-video-connected-XXXXXXXX")
mkdir -p "$RUN/home" "$RUN/tmp"
cd "$REPO"
exec env -i PATH="$(dirname "$PYTHON"):/usr/local/bin:/usr/bin:/bin" \
 HOME="$RUN/home" LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
 PYTHONPATH="$REPO/tests/history_presentation_browser/guard:$REPO:$REPO/tests" \
 TMPDIR="$RUN/tmp" DKSS_VALIDATION_TMP="$RUN/tmp" DATABASE_URL='sqlite:///:memory:' \
 SECRET_KEY='synthetic-video-connected-only' RENDER='' RATELIMIT_STORAGE_URI='memory://' \
 AWS_EC2_METADATA_DISABLED=true AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_CONFIG_FILE=/dev/null \
 S3_BUCKET_NAME='' OPENAI_API_KEY='' SMTP_HOST='' VAPID_PRIVATE_KEY='' VAPID_PUBLIC_KEY='' \
 DOCUMENT_IMPORT_WORKER_ENABLED=0 "$PYTHON" -m unittest "$@" -v
