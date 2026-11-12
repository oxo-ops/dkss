#!/usr/bin/env bash
set -euo pipefail
REPO=$(realpath "${1:?repo required}")
PYTHON=${2:?absolute Python required}
CHROMIUM=${3:?absolute Chromium required}
ARTIFACTS=${4:?absolute artifact path required}
[[ "$PYTHON" = /* && "$CHROMIUM" = /* && "$ARTIFACTS" = /* ]] || exit 2
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
RUN=$(mktemp -d "${TMPDIR:-/tmp}/dkss-comparison-XXXXXXXX")
mkdir -p "$RUN/tmp" "$RUN/home" "$ARTIFACTS"
exec env -i PATH="$(dirname "$PYTHON"):/usr/local/bin:/usr/bin:/bin" \
 HOME="$RUN/home" LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
 PYTHONPATH="$HERE/../quality_feature_browser/guard:$REPO:$REPO/tests${DKSS_PLAYWRIGHT_SITE:+:$DKSS_PLAYWRIGHT_SITE}" \
 TMPDIR="$RUN/tmp" DKSS_VALIDATION_TMP="$RUN/tmp" DKSS_BROWSER_ACCEPTANCE_ISOLATED=1 \
 DATABASE_URL='sqlite:///:memory:' SECRET_KEY='synthetic-ui5-only' RENDER='' \
 RATELIMIT_STORAGE_URI='memory://' AWS_EC2_METADATA_DISABLED=true \
 AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_CONFIG_FILE=/dev/null S3_BUCKET_NAME='' \
 OPENAI_API_KEY='' SMTP_HOST='' VAPID_PRIVATE_KEY='' VAPID_PUBLIC_KEY='' DOCUMENT_IMPORT_WORKER_ENABLED=0 \
 "$PYTHON" "$HERE/acceptance.py" --repo "$REPO" --artifacts "$ARTIFACTS" --chromium "$CHROMIUM"
