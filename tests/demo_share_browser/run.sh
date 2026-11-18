#!/usr/bin/env bash
set -euo pipefail
R=$(realpath "$1"); PY=$2; MODE=$3; shift 3
[[ "$PY" = /* && -x "$PY" ]]
HERE=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d); mkdir -p "$T/home" "$T/tmp"
if [[ "$MODE" == unit ]]; then set -- -m unittest test_demo_share_entry -v
elif [[ "$MODE" == https ]]; then set -- "$HERE/https_acceptance.py" --repo "$R" "$@"
elif [[ "$MODE" == browser ]]; then set -- "$HERE/acceptance.py" --repo "$R" "$@"
else exit 2; fi
exec env -i PATH="$(dirname "$PY"):/usr/local/bin:/usr/bin:/bin" HOME="$T/home" TMPDIR="$T/tmp" \
 LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DKSS_VALIDATION_TMP="$T/tmp" DKSS_BROWSER_ACCEPTANCE_ISOLATED=1 \
 PYTHONPATH="$R/tests/history_presentation_browser/guard:$R:$R/tests" DATABASE_URL=sqlite:///:memory: SECRET_KEY=synthetic-ui-only \
 RENDER='' RATELIMIT_STORAGE_URI=memory:// AWS_EC2_METADATA_DISABLED=true AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_CONFIG_FILE=/dev/null \
 S3_BUCKET_NAME='' OPENAI_API_KEY='' SMTP_HOST='' VAPID_PRIVATE_KEY='' VAPID_PUBLIC_KEY='' DOCUMENT_IMPORT_WORKER_ENABLED=0 "$PY" "$@"
