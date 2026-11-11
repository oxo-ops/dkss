#!/usr/bin/env bash
set -euo pipefail
if [[ $# -lt 3 ]]; then
  echo 'Usage: run-isolated.sh ABSOLUTE_REPO ABSOLUTE_PYTHON --preflight-only|--run-browser [--chromium ABSOLUTE_EXECUTABLE]' >&2
  exit 2
fi
REPO=$(realpath "$1")
PYTHON=$2
[[ "$PYTHON" = /* && -x "$PYTHON" ]] || { echo 'Use an absolute executable Python path.' >&2; exit 2; }
shift 2
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
RUN=$(mktemp -d "${TMPDIR:-/tmp}/dkss-ui-acceptance-XXXXXXXX")
ARTIFACTS=${DKSS_BROWSER_ARTIFACT_DIR:-"$RUN/artifacts"}
[[ "$ARTIFACTS" = /* ]] || { echo 'Use an absolute artifact path.' >&2; exit 2; }
mkdir -p "$RUN/tmp" "$RUN/home" "$ARTIFACTS"
echo "ARTIFACTS=$ARTIFACTS"
# No inherited credentials, external DB URLs, proxy, integrations or user profile.
exec env -i PATH="$(dirname "$PYTHON"):/usr/local/bin:/usr/bin:/bin" \
  HOME="$RUN/home" LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
  PYTHONPATH="$HERE/../history_presentation_browser/guard:$REPO:$REPO/tests" TMPDIR="$RUN/tmp" \
  DKSS_VALIDATION_TMP="$RUN/tmp" DKSS_BROWSER_ACCEPTANCE_ISOLATED=1 \
  DATABASE_URL='sqlite:///:memory:' SECRET_KEY='synthetic-ui-acceptance-only' \
  RENDER='' RATELIMIT_STORAGE_URI='memory://' AWS_EC2_METADATA_DISABLED=true \
  AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_CONFIG_FILE=/dev/null S3_BUCKET_NAME='' \
  OPENAI_API_KEY='' SMTP_HOST='' VAPID_PRIVATE_KEY='' VAPID_PUBLIC_KEY='' \
  DOCUMENT_IMPORT_WORKER_ENABLED=0 \
  "$PYTHON" "$HERE/acceptance.py" --repo "$REPO" --artifacts "$ARTIFACTS" "$@"
