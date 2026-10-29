"""Explicit additive CSV evidence migration on empty, owned disposable storage."""
import os
import subprocess
import sys
import unittest
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import make_url

from dkss_app.operation_csv_owner import upgrade_operation_csv_owners


class CsvOwnerStorageTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite:///:memory:')
        self.addCleanup(self.engine.dispose)
        self.seed()

    def seed(self):
        binary='BYTEA' if self.engine.dialect.name=='postgresql' else 'BLOB'
        with self.engine.begin() as c:
            c.execute(text('CREATE TABLE vehicle_operation_import_draft ('
                'id VARCHAR(36) PRIMARY KEY, company_code VARCHAR(50), created_by_username VARCHAR(50), '
                'source_file '+binary+', selection_json TEXT, result_json TEXT, status VARCHAR(20))'))
            c.execute(text('INSERT INTO vehicle_operation_import_draft VALUES '
                "('old','TEST','reused',:data,'{}','{}','preview')"),{'data':b'UNCHANGED-ORIGINAL'})

    def old_values(self):
        with self.engine.connect() as c:
            return c.execute(text('SELECT id,company_code,created_by_username,source_file,selection_json,result_json,status '
                                  'FROM vehicle_operation_import_draft')).all()

    def test_reapply_keeps_legacy_rows_unbound_and_original_bytes(self):
        before=self.old_values()
        for _ in range(2):upgrade_operation_csv_owners(self.engine)
        self.assertEqual(self.old_values(),before)
        with self.engine.connect() as c:
            self.assertIsNone(c.scalar(text("SELECT owner_identity FROM vehicle_operation_import_draft WHERE id='old'")))
            indexes=inspect(c).get_indexes('vehicle_operation_import_draft')
            found=[x for x in indexes if x['name']=='ix_operation_csv_company_owner']
            self.assertEqual(len(found),1)
            self.assertEqual(found[0]['column_names'],['company_code','owner_identity'])

    def test_incompatible_owner_type_is_rejected_without_changes(self):
        with self.engine.begin() as c:c.execute(text('ALTER TABLE vehicle_operation_import_draft ADD COLUMN owner_identity INTEGER'))
        before=self.old_values()
        with self.assertRaisesRegex(RuntimeError,'incompatible'):upgrade_operation_csv_owners(self.engine)
        self.assertEqual(self.old_values(),before)

    def test_conflicting_index_is_rejected_before_adding_column(self):
        with self.engine.begin() as c:c.execute(text('CREATE INDEX ix_operation_csv_company_owner ON vehicle_operation_import_draft (company_code)'))
        with self.assertRaisesRegex(RuntimeError,'index is incompatible'):upgrade_operation_csv_owners(self.engine)
        with self.engine.connect() as c:self.assertNotIn('owner_identity',{x['name'] for x in inspect(c).get_columns('vehicle_operation_import_draft')})

    def test_ddl_failure_rolls_back_column_and_index_then_retry_succeeds(self):
        before=self.old_values();hit=[]
        def fail(conn,cursor,statement,parameters,context,many):
            if statement.startswith('CREATE INDEX ix_operation_csv_company_owner'):
                hit.append(True);raise RuntimeError('Q03_CSV_MIGRATION_AFTER_INDEX')
        event.listen(self.engine,'after_cursor_execute',fail)
        try:
            with self.assertRaisesRegex(RuntimeError,'AFTER_INDEX'):upgrade_operation_csv_owners(self.engine)
        finally:event.remove(self.engine,'after_cursor_execute',fail)
        self.assertEqual(hit,[True]);self.assertEqual(self.old_values(),before)
        with self.engine.connect() as c:self.assertNotIn('owner_identity',{x['name'] for x in inspect(c).get_columns('vehicle_operation_import_draft')})
        upgrade_operation_csv_owners(self.engine)

    def test_order_with_existing_q02_owner_upgrade_is_independent(self):
        from dkss_app.import_owner import upgrade_import_owners
        with self.engine.begin() as c:
            c.execute(text('CREATE TABLE vehicle_document_import_draft (id VARCHAR(36) PRIMARY KEY, company_code VARCHAR(50))'))
            c.execute(text("INSERT INTO vehicle_document_import_draft VALUES ('ocr-old','TEST')"))
        for first,second in ((upgrade_import_owners,upgrade_operation_csv_owners),
                             (upgrade_operation_csv_owners,upgrade_import_owners)):
            first(self.engine);second(self.engine)
        with self.engine.connect() as c:
            self.assertIsNone(c.scalar(text("SELECT owner_identity FROM vehicle_document_import_draft WHERE id='ocr-old'")))
            self.assertIsNone(c.scalar(text("SELECT owner_identity FROM vehicle_operation_import_draft WHERE id='old'")))

    def test_cli_requires_separate_explicit_url_without_database_url_fallback(self):
        env=dict(os.environ,DATABASE_URL='sqlite:///:memory:')
        env.pop('Q03_CSV_OWNER_MIGRATION_DATABASE_URL',None)
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([sys.executable,str(root/'tools/upgrade_operation_csv_owners.py')],
            cwd=root,env=env,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Set Q03_CSV_OWNER_MIGRATION_DATABASE_URL explicitly',result.stdout+result.stderr)


@unittest.skipUnless(os.environ.get('Q03_CSV_POSTGRES_TEST_URL'),'explicit disposable CSV PostgreSQL required')
class PostgresCsvOwnerStorageTests(CsvOwnerStorageTests):
    def setUp(self):
        raw=os.environ['Q03_CSV_POSTGRES_TEST_URL'];url=make_url(raw)
        if url.get_backend_name()!='postgresql' or url.host not in {'127.0.0.1','localhost'} or url.database!='dkss_q03_csv_ci':
            raise RuntimeError('Only loopback dkss_q03_csv_ci is allowed')
        schema='q03_csv_storage_'+uuid4().hex
        admin=create_engine(raw,isolation_level='AUTOCOMMIT');self.addCleanup(admin.dispose)
        with admin.connect() as c:c.execute(text('CREATE SCHEMA "'+schema+'"'))
        def cleanup():
            with admin.connect() as c:c.execute(text('DROP SCHEMA "'+schema+'" CASCADE'))
        self.addCleanup(cleanup)
        self.engine=create_engine(raw,connect_args={'options':'-csearch_path='+schema})
        self.addCleanup(self.engine.dispose)
        self.seed()
