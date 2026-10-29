"""Explicit, additive Q03 CSV owner migration. No automatic username backfill."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine
from dkss_app.operation_csv_owner import upgrade_operation_csv_owners


def main():
    raw = os.environ.get('Q03_CSV_OWNER_MIGRATION_DATABASE_URL')
    if not raw:
        raise SystemExit('Set Q03_CSV_OWNER_MIGRATION_DATABASE_URL explicitly; no DATABASE_URL fallback')
    engine = create_engine(raw)
    try:
        upgrade_operation_csv_owners(engine)
        print('CSV owner column ready; legacy receipts remain unbound and unchanged')
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
