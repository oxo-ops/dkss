"""Run with writers stopped and a backup; never falls back to DATABASE_URL."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine
from dkss_app.checklist_event_storage import upgrade_checklist_event_timestamps


def main():
    raw = os.environ.get('Q02_TIMESTAMP_MIGRATION_DATABASE_URL')
    if not raw:
        raise SystemExit('Set Q02_TIMESTAMP_MIGRATION_DATABASE_URL explicitly; no DATABASE_URL fallback')
    engine = create_engine(raw)
    try:
        print('ChecklistEvent timestamp storage widened:', upgrade_checklist_event_timestamps(engine))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
