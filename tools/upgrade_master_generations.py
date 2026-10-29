"""Explicit Q04 generation metadata upgrade on an approved nonproduction copy.

Stop all master writers before running. Existing IDs, names and business/history
rows are never changed. No default DATABASE_URL, bootstrap or automatic repair.
"""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from dkss_app.master_generations import upgrade_storage, validate_storage
from tools.q04_master_preflight import read_only_connection


def migration_engine(url, expected_database):
    parsed = make_url(url)
    if parsed.query or not expected_database:
        raise ValueError('Explicit target without URL query overrides is required')
    if parsed.drivername in {'sqlite', 'sqlite+pysqlite'}:
        import sqlite3
        path = Path(parsed.database or '').resolve()
        if not path.is_file() or path.name != expected_database:
            raise ValueError('Existing explicitly named SQLite copy is required')
        return create_engine('sqlite://', creator=lambda: sqlite3.connect(
            path.as_uri() + '?mode=rw', uri=True, timeout=2))
    if (parsed.drivername not in {'postgresql', 'postgresql+psycopg2'}
            or parsed.host not in {'localhost', '127.0.0.1', '::1'}
            or parsed.database != expected_database
            or not (expected_database.startswith('q04_') or expected_database == 'dkss_q04_ci')):
        raise ValueError('Only an explicitly named loopback Q04 PostgreSQL copy is allowed')
    return create_engine(parsed, connect_args={'connect_timeout': 5})


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-database', required=True)
    parser.add_argument('--schema')
    parser.add_argument('--confirm-nonproduction', required=True, action='store_true')
    parser.add_argument('--check', action='store_true', help='Read-only readiness check, no migration')
    args = parser.parse_args(argv)
    url = os.environ.get('Q04_MASTER_GENERATION_DATABASE_URL', '')
    if not url:
        parser.error('Q04_MASTER_GENERATION_DATABASE_URL must explicitly select the nonproduction copy')
    try:
        if args.check:
            with read_only_connection(url, args.expected_database) as connection:
                validate_storage(connection, args.schema)
            report = {'ready': True}
        else:
            engine = migration_engine(url, args.expected_database)
            try:
                report = upgrade_storage(engine, args.schema)
            finally:
                engine.dispose()
    except (ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    except (SQLAlchemyError, OSError):
        print('Master generation upgrade/check failed; transaction rolled back. Check target, locks and privileges.',
              file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
