"""Master metadata and legacy upgrades on disposable SQLite only."""
import os
import unittest
from unittest.mock import patch

from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

import test_q04_master_rename as rename


class MasterUniquenessTests(unittest.TestCase):
    setUpClass = classmethod(rename.MasterRenameIntegrityTests.setUpClass.__func__)
    tearDownClass = classmethod(rename.MasterRenameIntegrityTests.tearDownClass.__func__)
    setUp = rename.MasterRenameIntegrityTests.setUp
    tearDown = rename.MasterRenameIntegrityTests.tearDown

    def upgrade(self):
        from dkss_app.database import init_db
        with patch.dict(os.environ, {'ITC_INITIAL_PASSWORD': 'Q04-Test-Only-742!'}):
            init_db()

    def remove_legacy_indexes(self):
        for name in ('uq_office_company_name', 'uq_vehicle_type_company_name'):
            self.m.db.session.execute(text('DROP INDEX ' + name))
        self.m.db.session.commit()

    def test_fresh_metadata_enforces_names_per_company_for_both_masters(self):
        m = self.m
        for model in (m.Office, m.VehicleType):
            with self.subTest(model=model.__name__):
                m.db.session.add_all([model(company_code='TEST', name='Same'),
                                      model(company_code='OTHER', name='Same')])
                m.db.session.commit()
                m.db.session.add(model(company_code='TEST', name='Same'))
                with self.assertRaises(IntegrityError):
                    m.db.session.commit()
                # This rollback clears the intentional constraint error, not
                # evidence about a failed HTTP request or request teardown.
                m.db.session.rollback()
                self.assertEqual(model.query.filter_by(name='Same').count(), 2)

    def test_legacy_upgrade_adds_indexes_and_can_run_twice(self):
        m = self.m
        self.remove_legacy_indexes()
        for model in (m.Office, m.VehicleType):
            m.db.session.add_all([model(company_code='TEST', name='Same'),
                                  model(company_code='OTHER', name='Same')])
        m.db.session.commit()
        self.upgrade()
        self.upgrade()
        inspector = inspect(m.db.engine)
        for model in (m.Office, m.VehicleType):
            indexes = inspector.get_indexes(model.__tablename__)
            self.assertTrue(any(index['unique'] and
                index['column_names'] == ['company_code', 'name'] for index in indexes))
            self.assertEqual(model.query.filter_by(name='Same').count(), 2)

    def test_legacy_duplicate_offices_stop_upgrade_without_rewriting_them(self):
        m = self.m
        self.remove_legacy_indexes()
        m.db.session.add_all([m.Office(company_code='TEST', name='Legacy'),
                              m.Office(company_code='TEST', name='Legacy')])
        self.vehicle.office = 'Legacy'
        m.db.session.commit()
        before = [(row.id, row.name) for row in m.Office.query.order_by(m.Office.id)]
        with self.assertRaisesRegex(RuntimeError, '\u55b6\u696d\u6240'):
            self.upgrade()
        m.db.session.expire_all()
        self.assertEqual([(row.id, row.name) for row in m.Office.query.order_by(m.Office.id)], before)
        self.assertEqual(self.vehicle.office, 'Legacy')
        self.assertNotIn('uq_office_company_name',
                         [index['name'] for index in inspect(m.db.engine).get_indexes('office')])


if __name__ == '__main__':
    unittest.main()
