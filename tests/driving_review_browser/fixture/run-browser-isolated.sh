#!/bin/bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "${1:?exact candidate checkout required}" && pwd)
PYTHON=${2:?Python environment with declared app dependencies and Playwright required}
EXPECTED=${3:?exact candidate commit SHA required}
CHROMIUM=${4:-/usr/bin/chromium}
OUTPUT=${5:-"$HERE/browser-output"}
RUN=$(mktemp -d)
mkdir -p "$RUN/home" "$RUN/tmp"
exec env -i PATH="$(dirname "$PYTHON"):/usr/bin:/bin" HOME="$RUN/home" TMPDIR="$RUN/tmp" PYTHONDONTWRITEBYTECODE=1 LANG=C.UTF-8 \
 PYTHONPATH="$REPO/tests/history_presentation_browser/guard:$REPO:$REPO/tests" DKSS_VALIDATION_TMP="$RUN/tmp" DKSS_BROWSER_ACCEPTANCE_ISOLATED=1 DKSS_EXPECTED_SHA="$EXPECTED" DKSS_CHROMIUM="$CHROMIUM" \
 DATABASE_URL=sqlite:///:memory: SECRET_KEY=synthetic-only RENDER='' RATELIMIT_STORAGE_URI=memory:// AWS_EC2_METADATA_DISABLED=true \
 AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_CONFIG_FILE=/dev/null OPENAI_API_KEY='' SMTP_HOST='' S3_BUCKET_NAME='' VAPID_PRIVATE_KEY='' VAPID_PUBLIC_KEY='' DOCUMENT_IMPORT_WORKER_ENABLED=0 \
 "$PYTHON" "$HERE/browser_bridge.py" "$REPO" "$OUTPUT"
