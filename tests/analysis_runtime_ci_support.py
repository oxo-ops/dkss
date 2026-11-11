"""Fail-closed boundary for the owned synthetic PostgreSQL/Gunicorn CI job."""
import os
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

MARKER = 'DKSS_ANALYSIS_RUNTIME_SYNTHETIC_ONLY'
URL = 'postgresql+psycopg2://analysis_runtime_ci:analysis-runtime-disposable-ci-only@127.0.0.1:5432/dkss_analysis_runtime_ci'
CONNECT_ARGS = {'hostaddr': '127.0.0.1', 'connect_timeout': 5,
                'options': '-c lock_timeout=5000 -c statement_timeout=10000'}


def validate_service_url(raw, environment):
    if environment.get('GITHUB_ACTIONS') != 'true' or environment.get('GITHUB_REPOSITORY') != 'oxo-ops/dkss':
        raise RuntimeError('Only the explicitly provisioned GitHub Actions service is allowed')
    value = make_url(raw)
    expected = make_url(URL)
    if value != expected or value.query:
        raise RuntimeError('Only the exact dedicated loopback analysis CI service is allowed')
    for name in environment:
        if name.upper().startswith('PG'):
            raise RuntimeError('Ambient PostgreSQL overrides are forbidden')
    return value


def verify_owned_service(raw, environment):
    url = validate_service_url(raw, environment)
    engine = create_engine(url, connect_args=CONNECT_ARGS)
    try:
        with engine.connect() as connection:
            marker = connection.scalar(text("SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname=current_database()"))
            if marker != MARKER:
                raise RuntimeError('The disposable analysis database ownership marker is required')
    finally:
        engine.dispose()
    return raw


def acceptance_root():
    if os.environ.get('ANALYSIS_RUNTIME_GUNICORN_TEST') != '1':
        raise RuntimeError('Explicit synthetic Gunicorn acceptance flag is required')
    root = Path(os.environ['DKSS_VALIDATION_TMP']).resolve()
    if not root.is_dir() or not root.is_relative_to(Path(os.environ['RUNNER_TEMP']).resolve()):
        raise RuntimeError('Only this CI job temporary directory is allowed')
    return root
