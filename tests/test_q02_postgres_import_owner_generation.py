"""Reuse the same owner lifecycle checks on native PostgreSQL."""
import unittest
from sqlalchemy import text
import test_q02_import_owner_generation as owners
import test_workflow_regressions as workflow
from test_q08_postgres_identity import DisposablePostgres
from dkss_app.import_owner import upgrade_import_owners


class PostgresImportOwnerGenerationTests(DisposablePostgres,owners.ImportOwnerGenerationTests):
    pass


class PostgresImportOwnerMigrationTests(DisposablePostgres,unittest.TestCase):
    setUp=workflow.WorkflowRegressionTests.setUp
    tearDown=workflow.WorkflowRegressionTests.tearDown

    def test_legacy_rows_are_not_assigned_to_a_current_same_username(self):
        with self.m.db.engine.begin() as c:
            c.execute(text('ALTER TABLE vehicle_document_import_draft DROP COLUMN owner_identity'))
            c.execute(text("INSERT INTO vehicle_document_import_draft (id,batch_id,company_code,created_by_username,document_type,source_filename,source_file,source_sha256,preview_json,status,result_json,created_at) VALUES ('old','batch','TEST','admin','inspection','fake.pdf',decode('010203','hex'),'hash','{}','preview','{}',CURRENT_TIMESTAMP)"))
        upgrade_import_owners(self.m.db.engine)
        upgrade_import_owners(self.m.db.engine)
        with self.m.db.engine.connect() as c:
            row=c.execute(text('SELECT created_by_username,source_file,preview_json,result_json,owner_identity FROM vehicle_document_import_draft')).one()
            self.assertEqual((row[0],bytes(row[1]),row[2],row[3],row[4]),('admin',b'\x01\x02\x03','{}','{}',None))
