"""Existing index-name collisions and interrupted builds, owned private schema."""
import os
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from q04_pg_helpers import PrivatePostgresCase


class MasterIndexAcceptanceTests(PrivatePostgresCase):
    def setUp(self):
        super().setUp()
        with self.app.app_context():
            self.upgrade()

    def upgrade(self):
        from dkss_app.database import init_db
        with self.app.app_context(), patch.dict(os.environ, {'ITC_INITIAL_PASSWORD': 'Q04-Disposable-Only-742!'}):
            init_db()

    def check_definition(self, table, defect):
        name = 'uq_' + table + '_company_name'
        suffix = {'nonunique': '(company_code, name)', 'wrong_columns': '(company_code, id)',
                  'partial': "(company_code, name) WHERE name <> 'Unprotected'"}[defect]
        with self.app.app_context():
            self.db.session.execute(text('DROP INDEX ' + name))
            self.db.session.execute(text('CREATE ' + ('' if defect == 'nonunique' else 'UNIQUE ')
                                         + 'INDEX ' + name + ' ON ' + table + ' ' + suffix))
            self.db.session.commit()
            index_oid = self.db.session.scalar(text('SELECT to_regclass(:name)::oid'), {'name': name})
        before = self.snapshot(self.company), self.snapshot(self.other)
        try:
            with self.assertRaisesRegex(RuntimeError, name):
                self.upgrade()
            self.assertEqual((self.snapshot(self.company), self.snapshot(self.other)), before)
            with self.app.app_context():
                self.assertEqual(self.db.session.scalar(text('SELECT to_regclass(:name)::oid'), {'name': name}), index_oid,
                                 'Application must not silently replace an existing index')
        finally:
            # Test-owned malformed DDL only; never application auto-repair.
            with self.app.app_context():
                self.db.session.execute(text('DROP INDEX ' + name))
                self.db.session.commit()
            self.upgrade()

    def test_invalid_index_left_by_failed_concurrent_build_is_rejected(self):
        name = 'uq_office_company_name'
        with self.app.app_context():
            self.db.session.execute(text('DROP INDEX ' + name))
            self.db.session.add_all([self.m.Office(company_code=self.company, name='Build-only'),
                                     self.m.Office(company_code=self.company, name='Build-only')])
            self.db.session.commit()
        try:
            with self.engine.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
                with self.assertRaises(IntegrityError):
                    connection.execute(text('CREATE UNIQUE INDEX CONCURRENTLY ' + name + ' ON office (company_code, name)'))
            with self.app.app_context():
                duplicate = self.m.Office.query.filter_by(company_code=self.company, name='Build-only').order_by(self.m.Office.id.desc()).first()
                self.db.session.delete(duplicate)
                self.db.session.commit()
                self.assertFalse(self.db.session.scalar(text('SELECT indisvalid FROM pg_index WHERE indexrelid=to_regclass(:name)'), {'name': name}))
            before = self.snapshot(self.company), self.snapshot(self.other)
            with self.assertRaisesRegex(RuntimeError, name):
                self.upgrade()
            self.assertEqual((self.snapshot(self.company), self.snapshot(self.other)), before)
        finally:
            with self.app.app_context():
                self.db.session.execute(text('DROP INDEX IF EXISTS ' + name))
                self.db.session.commit()
            self.upgrade()


def case(table, defect):
    def check(self):
        self.check_definition(table, defect)
    return check


for _table in ('office', 'vehicle_type', 'delivery_place', 'license_type', 'patrol_content_type'):
    for _defect in ('nonunique', 'wrong_columns', 'partial'):
        setattr(MasterIndexAcceptanceTests, 'test_' + _table + '_' + _defect, case(_table, _defect))
