#!/usr/bin/env bash
set -euo pipefail
: "${POSTGRES_SERVICE_CONTAINER:?Must be the job-owned disposable service ID}"
# No DSN is accepted. Only docker exec into the exact service supplied by Actions.
marker=$(docker exec "$POSTGRES_SERVICE_CONTAINER" psql -U restore_ci -d dkss_restore_ci -Atc "SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()")
test "$marker" = 'WORLEX_RESTORE_SYNTHETIC_ONLY'
docker exec "$POSTGRES_SERVICE_CONTAINER" createdb -U restore_ci windows_render_synthetic
docker exec -i "$POSTGRES_SERVICE_CONTAINER" psql -U restore_ci -d windows_render_synthetic -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE public.synthetic_render_fixture (id integer PRIMARY KEY, company_code text NOT NULL, marker text NOT NULL, payload text NOT NULL);
INSERT INTO public.synthetic_render_fixture VALUES (1, 'WORLEX', 'WINDOWS_RENDER_SYNTHETIC_ONLY_20261104', E'line1\nline2\t\\slash');
SQL
docker exec "$POSTGRES_SERVICE_CONTAINER" pg_dump -U restore_ci -d windows_render_synthetic --format=directory --compress=0 --file=/tmp/windows_render_synthetic_dump
docker exec "$POSTGRES_SERVICE_CONTAINER" pg_restore --file=/tmp/windows_render_synthetic.sql /tmp/windows_render_synthetic_dump
mkdir -p windows-fixture
docker cp "$POSTGRES_SERVICE_CONTAINER:/tmp/windows_render_synthetic.sql" windows-fixture/linux-rendered.sql
docker cp "$POSTGRES_SERVICE_CONTAINER:/tmp/windows_render_synthetic_dump" './windows-fixture/synthetic:2026-11-04'
python - <<'PY'
import hashlib,json,pathlib,tarfile
import worlex_restore
root=pathlib.Path('windows-fixture')
with tarfile.open(root/'synthetic.tar.gz','w:gz') as tar:
    tar.add(root/'synthetic:2026-11-04',arcname='synthetic:2026-11-04')
(root/'fixture-manifest.json').write_text(json.dumps({'kind':'synthetic-only','copy_sha256':worlex_restore.copy_digest(root/'linux-rendered.sql'),'archive_sha256':hashlib.sha256((root/'synthetic.tar.gz').read_bytes()).hexdigest(),'source':'job-owned PostgreSQL 18 disposable service; windows_render_synthetic database'},indent=2))
PY
