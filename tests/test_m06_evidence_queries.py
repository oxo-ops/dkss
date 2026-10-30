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

    def test_same_request_edits_flush_rollback_and_bulk_commit_are_visible(self):
        plan, record, draft = self.confirmed_plan()
        db = self.m.db
        with self.m.app.test_request_context('/api/notifications/unread-count'):
            kind = self.m.inspection_plans.plan_kind
            self.assertEqual(kind(plan), '12month')
            with db.session.no_autoflush:
                draft.status = 'preview'
                self.assertEqual(kind(plan), 'annual_unconfirmed')
            db.session.flush()
            self.assertEqual(kind(plan), 'annual_unconfirmed')
            db.session.rollback()
            self.assertEqual(kind(plan), '12month')
            self.m.VehicleDocumentImportDraft.query.filter_by(id=draft.id).update({'status': 'preview'})
            self.assertEqual(kind(plan), 'annual_unconfirmed')
            db.session.commit()
            self.assertEqual(kind(plan), 'annual_unconfirmed')
            db.session.execute(db.text('UPDATE vehicle_document_import_draft SET status=:status WHERE id=:id'),
                               {'status': 'completed', 'id': draft.id})
            db.session.expire(draft)
            self.assertEqual(kind(plan), '12month')
            db.session.rollback()
            self.assertEqual(kind(plan), 'annual_unconfirmed')

    def test_cached_evidence_never_crosses_vehicle_company_or_original(self):
        plan, record, draft = self.confirmed_plan()
        with self.m.app.test_request_context('/api/notifications/unread-count'):
            kind = self.m.inspection_plans.plan_kind
            self.assertEqual(kind(plan), '12month')
            for obj, field, wrong in ((plan, 'company_code', 'OTHER'),
                                       (plan, 'vehicle_record_id', self.vehicle.id + 99),
                                       (record, 'source_draft_id', 'missing-original')):
                old = getattr(obj, field)
                with self.m.db.session.no_autoflush:
                    setattr(obj, field, wrong)
                    self.assertEqual(kind(plan), 'annual_unconfirmed')
                    setattr(obj, field, old)
                    self.assertEqual(kind(plan), '12month')


class NoticeHistoryWithRequestCacheTests(source.ConfirmedPeriodicNoticeTests):
    """Run the existing receipt contract with the request cache actually enabled."""
    def run_alerts(self, *args, **kwargs):
        with self.m.app.test_request_context('/api/notifications/unread-count'):
            return super().run_alerts(*args, **kwargs)
