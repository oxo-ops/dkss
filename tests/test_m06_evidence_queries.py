"""Bound repeated provenance reads without caching across requests or writes."""
import unittest
from sqlalchemy import event
import test_m06_confirmed_periodic_notice as source


class EvidenceQueryTests(unittest.TestCase):
    setUpClass = classmethod(source.ConfirmedPeriodicNoticeTests.setUpClass.__func__)
    tearDownClass = classmethod(source.ConfirmedPeriodicNoticeTests.tearDownClass.__func__)
    setUp = source.ConfirmedPeriodicNoticeTests.setUp
    tearDown = source.ConfirmedPeriodicNoticeTests.tearDown
    upload_inspection = source.ConfirmedPeriodicNoticeTests.upload_inspection
    inspection_form = source.ConfirmedPeriodicNoticeTests.inspection_form
    confirmed_plan = source.ConfirmedPeriodicNoticeTests.confirmed_plan

    def test_annual_resolves_each_plan_once_and_refreshes_changed_evidence(self):
        plan, record, draft = self.confirmed_plan()
        url = '/api/vehicle/inspection-plans?scope=company&year=2026'
        queries = []
        def capture(conn, cursor, statement, parameters, context, many):
            if 'FROM vehicle_document_import_draft' in statement:
                queries.append(statement)
        event.listen(self.m.db.engine, 'before_cursor_execute', capture)
        try:
            response = self.client.get(url)
        finally:
            event.remove(self.m.db.engine, 'before_cursor_execute', capture)
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries), 3)
        row = next(p for p in response.json['plans'] if p['id'] == plan.id)
        self.assertEqual(row['kind'], '12month')
        # A later request must use current evidence, not an earlier classification.
        draft.status = 'preview'
        self.m.db.session.commit()
        response = self.client.get(url)
        row = next(p for p in response.json['plans'] if p['id'] == plan.id)
        self.assertEqual(row['kind'], 'annual_unconfirmed')
        self.assertEqual(plan.kind, '12month')
        self.assertEqual(record.inspection_type, '12month')
