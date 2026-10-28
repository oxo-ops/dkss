"""Explicit Q03 schema-only migration; never falls back to an application's DB.

Set Q03_MIGRATION_DATABASE_URL or pass --database-url. New installations use
the normal init-db command; existing installations run this before new code.
"""
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask
from sqlalchemy import inspect
from dkss_app.extensions import db
from dkss_app.safety_identity import IDENTITY_FIELDS, upgrade_storage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url', default=os.environ.get('Q03_MIGRATION_DATABASE_URL'))
    args = parser.parse_args()
    if not args.database_url:
        parser.error('An explicit Q03_MIGRATION_DATABASE_URL or --database-url is required')
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = args.database_url
    db.init_app(app)
    with app.app_context():
        if not set(IDENTITY_FIELDS).issubset(inspect(db.engine).get_table_names()):
            raise RuntimeError('Existing safety tables are required; no bootstrap is performed')
        upgrade_storage()
        print('SAFETY_IDENTITIES_UPGRADED; existing identities were not backfilled')
        db.session.remove()
        db.engine.dispose()


if __name__ == '__main__':
    main()
