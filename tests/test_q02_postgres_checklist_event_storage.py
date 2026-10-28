"""Native VARCHAR(30) rejection, lossless widening and normal daily workflows."""
import unittest
from sqlalchemy import text
from sqlalchemy.exc import DataError
from test_q08_postgres_identity import DisposablePostgres
import test_workflow_regressions as workflow
import test_q02_daily_inspection_flow as daily
from dkss_app.checklist_event_storage import upgrade_checklist_event_timestamps


class PostgresChecklistStorageTests(DisposablePostgres, unittest.TestCase):
    setUp=workflow.WorkflowRegressionTests.setUp
    tearDown=workflow.WorkflowRegressionTests.tearDown

    def test_existing_varchar30_is_widened_without_changing_legacy_text(self):
        engine=self.m.db.engine
        old='2026-10-22 10:00:00'
        precise='2026-10-29T07:00:38.516391+09:00'
        with engine.begin() as c:
            c.execute(text('DROP TABLE checklist_event'))
            c.execute(text('CREATE TABLE checklist_event (id INTEGER PRIMARY KEY, created_at VARCHAR(30) NOT NULL)'))
            c.execute(text('INSERT INTO checklist_event VALUES (1,:value)'),dict(value=old))
        with self.assertRaises(DataError):
            with engine.begin() as c:
                c.execute(text('INSERT INTO checklist_event VALUES (2,:value)'),dict(value=precise))
        self.assertTrue(upgrade_checklist_event_timestamps(engine))
        self.assertFalse(upgrade_checklist_event_timestamps(engine))
        with engine.begin() as c:
            c.execute(text('INSERT INTO checklist_event VALUES (2,:value)'),dict(value=precise))
            self.assertEqual(c.execute(text('SELECT created_at FROM checklist_event ORDER BY id')).scalars().all(),[old,precise])


class PostgresChecklistDailyFlowTests(DisposablePostgres, daily.Q02DailyInspectionFlowTests):
    @classmethod
    def setUpClass(cls):
        DisposablePostgres.setUpClass.__func__(cls)
        from dkss_app import models
        cls.app, cls.db, cls.models = cls.m.app, cls.m.db, models

    @classmethod
    def tearDownClass(cls):
        DisposablePostgres.tearDownClass.__func__(cls)
