"""Fail-closed, output-sanitized runner for the additive invite-purpose migration.

Run: python tools/predeploy_company_invites.py --expected-sha <reviewed full SHA>
The expected SHA is pinned in the deployment command, not inferred from runtime.
No reset, account creation, URL issuance, or network/security setting changes.
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

HOST = 'dpg-dbkk5juc6qcc73am01r0-a.oregon-postgres.render.com'
DATABASE = 'dkss_db_new_20261103'
TABLES = ('company_registration_invite', 'company_registration_application')


def guarded_environment(source, expected_sha, ca_path):
    if not re.fullmatch(r'[0-9a-f]{40}', expected_sha or ''):
        raise ValueError('guard')
    if source.get('RENDER_GIT_COMMIT') != expected_sha:
        raise ValueError('guard')
    u = urlsplit(source.get('DATABASE_URL', ''))
    q = parse_qs(u.query, keep_blank_values=True)
    # Reject every query override except an explicitly verified TLS mode.
    if (u.scheme not in ('postgresql', 'postgresql+psycopg2') or
            u.hostname != HOST or u.path != '/' + DATABASE or
            u.port not in (None, 5432) or u.fragment or
            set(q) - {'sslmode'} or q.get('sslmode', ['verify-full']) != ['verify-full']):
        raise ValueError('guard')
    if not Path(ca_path).is_file() or not os.access(ca_path, os.R_OK):
        raise ValueError('guard')
    env = dict(source)
    # Do not inherit libpq routing, option or service overrides.
    for key in list(env):
        if key.startswith('PG'):
            del env[key]
    env.update(PGSSLMODE='verify-full', PGSSLROOTCERT=str(ca_path),
               PGCONNECT_TIMEOUT='10',
               PGOPTIONS='-c lock_timeout=5000 -c statement_timeout=60000',
               PYTHONUNBUFFERED='1')
    return env


def snapshot(connection):
    from sqlalchemy import inspect, text
    inspector = inspect(connection)
    if any(not inspector.has_table(table) for table in TABLES):
        raise ValueError('missing existing table')
    cols = {c['name']: c for c in inspector.get_columns(TABLES[0])}
    purpose = cols.get('purpose')
    if purpose and (str(purpose['type']).upper() != 'VARCHAR(20)' or
                    purpose['nullable'] or str(purpose.get('default')).strip() not in {"'legacy'", "'legacy'::character varying", "'legacy'::text"}):
        raise ValueError('unexpected purpose shape')
    counts = tuple(connection.execute(text('SELECT count(*) FROM ' + table)).scalar_one()
                   for table in TABLES)
    legacy = (connection.execute(text("SELECT count(*) FROM company_registration_invite WHERE purpose = 'legacy'")).scalar_one()
              if purpose else counts[0])
    typed = (connection.execute(text("SELECT count(*) FROM company_registration_invite WHERE purpose <> 'legacy'")).scalar_one()
             if purpose else 0)
    return bool(purpose), counts, legacy, typed


def worker(expected_sha):
    # Suppress imports, framework logging, SQL errors and exception text at OS level.
    with open(os.devnull, 'wb') as sink:
        os.dup2(sink.fileno(), 1)
        os.dup2(sink.fileno(), 2)
    try:
        import certifi
        guarded = guarded_environment(os.environ, expected_sha, certifi.where())
        os.environ.clear()
        os.environ.update(guarded)
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from dkss_app import create_app
        from dkss_app.extensions import db
        from sqlalchemy import text
        app = create_app(initialize_database=False)
        with app.app_context():
            with db.engine.connect() as connection:
                if connection.execute(text('SELECT current_database()')).scalar_one() != DATABASE:
                    return 20
                if not connection.execute(text('SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()')).scalar_one():
                    return 20
                before = snapshot(connection)
            # Execute the candidate's registered CLI, never init-db/create_all.
            app.cli.main(args=['upgrade-company-invites'], prog_name='flask', standalone_mode=False)
            with db.engine.connect() as connection:
                after = snapshot(connection)
            if not after[0] or before[1:] != after[1:]:
                return 22
        return 0
    except BaseException:
        # Migration may have committed before a post-check failure. Never retry/reset.
        return 21


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--expected-sha', required=True)
    args = parser.parse_args(argv)
    try:
        import certifi
        env = guarded_environment(os.environ, args.expected_sha, certifi.where())
    except BaseException:
        print('INVITE_MIGRATION_STOP_GUARD')
        return 10
    try:
        result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()),
                                 '--worker', args.expected_sha], env=env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=120, check=False)
    except subprocess.TimeoutExpired:
        print('INVITE_MIGRATION_STOP_TIMEOUT_STATE_REQUIRES_CHECK')
        return 11
    except BaseException:
        print('INVITE_MIGRATION_STOP_RUNNER')
        return 12
    if result.returncode:
        print('INVITE_MIGRATION_STOP_STATE_REQUIRES_CHECK')
        return 13
    print('INVITE_MIGRATION_VERIFIED')
    return 0


if __name__ == '__main__':
    # Worker is private to the guarded parent; independently invoking it is unsafe.
    if len(sys.argv) == 3 and sys.argv[1] == '--worker':
        sys.exit(worker(sys.argv[2]))
    sys.exit(main())
