#!/bin/sh
set -eu
cd /app
export RATELIMIT_STORAGE_URI=redis://127.0.0.1:6379/0
python - <<'PY'
import os, re, sys
from urllib.parse import urlsplit
d=urlsplit(os.environ.get('DATABASE_URL',''))
h=os.environ.get('STAGING_DB_HOST','')
sha=os.environ.get('STAGING_PACKAGE_SHA','')
bad=('SMTP_HOST','VAPID_PUBLIC_KEY','VAPID_PRIVATE_KEY','OPENAI_API_KEY','S3_BUCKET_NAME','AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY')
ok=(os.environ.get('ALSEON_STAGING_ONLY')=='1' and os.environ.get('RENDER')=='true' and bool(re.fullmatch(r'[0-9a-f]{40}',sha)) and os.environ.get('RENDER_GIT_COMMIT')==sha and d.scheme=='postgresql' and d.path=='/alseon_staging' and d.username=='alseon_staging' and d.hostname==h and bool(re.fullmatch(r'dpg-[a-z0-9]+(?:-a)?',h)) and not any(os.environ.get(k) for k in bad))
if not ok: sys.exit('STAGING_ONLY_GUARD_REJECTED')
PY
redis-server --bind 127.0.0.1 --port 6379 --protected-mode yes --save "" --appendonly no --maxmemory 24mb --maxmemory-policy allkeys-lru --dir /tmp &
rp=$!
trap 'kill "$rp" 2>/dev/null || true' EXIT INT TERM
n=0
until redis-cli -h 127.0.0.1 ping 2>/dev/null | grep -qx PONG; do
  kill -0 "$rp"
  n=$((n+1)); [ "$n" -lt 15 ] || exit 1
  sleep 1
done
if [ "${1:-}" = init ]; then
  flask --app app init-db
else
  exec gunicorn --bind "0.0.0.0:${PORT:-10000}" app:app
fi
