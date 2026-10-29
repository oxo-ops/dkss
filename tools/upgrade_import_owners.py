"""Add receipt UUID evidence with writers stopped; never infer legacy ownership."""
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine
from dkss_app.import_owner import upgrade_import_owners


def main():
    raw=os.environ.get('Q02_IMPORT_OWNER_MIGRATION_DATABASE_URL')
    if not raw:
        raise SystemExit('Set Q02_IMPORT_OWNER_MIGRATION_DATABASE_URL explicitly; no DATABASE_URL fallback')
    engine=create_engine(raw)
    try:
        upgrade_import_owners(engine)
        print('Receipt owner column ready; legacy ownership was not inferred')
    finally:
        engine.dispose()


if __name__=='__main__':
    main()
