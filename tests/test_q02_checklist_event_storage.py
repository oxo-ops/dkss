"""No timestamp conversion, trimming or legacy-row rewriting."""
import unittest
from sqlalchemy import create_engine, text
from dkss_app.checklist_event_storage import upgrade_checklist_event_timestamps


class ChecklistEventStorageTests(unittest.TestCase):
    def test_sqlite_legacy_width_preserves_old_and_full_precision_values(self):
        engine=create_engine('sqlite:///:memory:')
        self.addCleanup(engine.dispose)
        values=['2026-10-22 10:00:00','2026-10-29T07:00:38.516391+09:00']
        with engine.begin() as c:
            c.execute(text('CREATE TABLE checklist_event (id INTEGER PRIMARY KEY, created_at VARCHAR(30) NOT NULL)'))
            for i,value in enumerate(values):
                c.execute(text('INSERT INTO checklist_event VALUES (:id,:value)'),dict(id=i,value=value))
        self.assertFalse(upgrade_checklist_event_timestamps(engine))
        self.assertFalse(upgrade_checklist_event_timestamps(engine))
        with engine.connect() as c:
            self.assertEqual(c.execute(text('SELECT created_at FROM checklist_event ORDER BY id')).scalars().all(),values)

    def test_nontext_schema_is_rejected_without_rewriting(self):
        engine=create_engine('sqlite:///:memory:')
        self.addCleanup(engine.dispose)
        with engine.begin() as c:
            c.execute(text('CREATE TABLE checklist_event (id INTEGER PRIMARY KEY, created_at INTEGER)'))
            c.execute(text('INSERT INTO checklist_event VALUES (1,42)'))
        with self.assertRaises(RuntimeError):
            upgrade_checklist_event_timestamps(engine)
        with engine.connect() as c:
            self.assertEqual(c.scalar(text('SELECT created_at FROM checklist_event')),42)
