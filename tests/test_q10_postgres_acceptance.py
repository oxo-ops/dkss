"""Run existing business invariants on PostgreSQL, without copying their logic."""
import unittest
import json
from unittest.mock import patch

import test_q10_business_flows as q10
import test_q02_daily_inspection_flow as daily
import test_q02_checklist_boundaries as safety
import test_q07_invoice_lifecycle as invoices
import test_workflow_regressions as workflow
import test_q02_import_worker_access as worker
import test_document_import_queue as queue_tests
from dkss_app import notifications_delivery
from dkss_app import document_import_queue, vehicle_imports
from test_inspection_document_ai import extraction
from q10_postgres_support import PostgresFixture


class PostgresDailyFlows(PostgresFixture, q10.DailyFlowFailuresTests):
    test_defect_repair_recheck_and_clearance = daily.Q02DailyInspectionFlowTests.test_defect_repair_recheck_and_clearance_preserve_the_inspection_answer
    test_failed_recheck_then_repair = daily.Q02DailyInspectionFlowTests.test_failed_recheck_can_be_repaired_and_rechecked_again


class PostgresImportFlows(PostgresFixture, q10.QueuedImportFlowTests):
    pass


class PostgresDrivingFlow(PostgresFixture, q10.ImportedDrivingReadFlowTests):
    pass


class PostgresApprovalFlow(PostgresFixture, unittest.TestCase):
    setUp = safety.Q02ChecklistBoundaryTests.setUp
    tearDown = safety.Q02ChecklistBoundaryTests.tearDown
    login = safety.Q02ChecklistBoundaryTests.login
    request = safety.Q02ChecklistBoundaryTests.request
    record = safety.Q02ChecklistBoundaryTests.record
    url = safety.Q02ChecklistBoundaryTests.url
    snapshot = safety.Q02ChecklistBoundaryTests.snapshot
    approve = safety.Q02ChecklistBoundaryTests.approve
    reject = safety.Q02ChecklistBoundaryTests.reject
    test_partial_approval_rejection_and_replay = safety.Q02ChecklistBoundaryTests.test_rejection_resets_partial_approval_and_replay_has_no_effect

    def test_failed_push_and_email_preserve_submission_and_approval(self):
        self.models.User.query.filter_by(company_code='A', username='admin').one().email_notify_enabled = True
        self.models.User.query.filter_by(company_code='A', username='checker').one().email_notify_enabled = True
        self.db.session.commit()
        with patch.object(notifications_delivery, 'send_web_push_notification', return_value=False) as push, patch.object(
            notifications_delivery, 'send_email_notification', return_value=False
        ) as email:
            row = self.record(approvals=(False,), candidates={'approval_notify_users_0': 'admin'})
            self.assertEqual(self.approve(row).status_code, 302)
        self.db.session.refresh(row)
        self.assertEqual(row.status, '承認済み')
        self.assertEqual(json.loads(row.approvals_json)[0]['approved_by_username'], 'admin')
        self.assertGreater(push.call_count, 0)
        self.assertGreater(email.call_count, 0)
        notices = self.models.Notification.query.filter_by(company_code='A').all()
        self.assertTrue(any(n.target_username == 'admin' for n in notices))
        self.assertTrue(any(n.target_username == 'checker' for n in notices))


class PostgresInvoiceFlows(PostgresFixture, unittest.TestCase):
    setUp = workflow.WorkflowRegressionTests.setUp
    tearDown = workflow.WorkflowRegressionTests.tearDown
    target = invoices.InvoiceLifecycleTests.target
    invoice = invoices.InvoiceLifecycleTests.invoice
    review = invoices.InvoiceLifecycleTests.review
    assert_total = invoices.InvoiceLifecycleTests.assert_total
    assert_originals = invoices.InvoiceLifecycleTests.assert_originals
    test_addition_correction_and_replay = invoices.InvoiceLifecycleTests.test_initial_addition_correction_chain_and_replay
    test_failed_correction_preserves_history = invoices.InvoiceLifecycleTests.test_failed_correction_rolls_back_both_documents_and_history


class PostgresWorkerRevocation(PostgresFixture, unittest.TestCase):
    setUp = workflow.WorkflowRegressionTests.setUp
    tearDown = workflow.WorkflowRegressionTests.tearDown
    enqueue = worker.Q02ImportWorkerAccessTests.enqueue
    owner = worker.Q02ImportWorkerAccessTests.owner
    revoke_during_processing = worker.Q02ImportWorkerAccessTests.revoke_during_processing
    assert_midflight_revocation = worker.Q02ImportWorkerAccessTests.assert_midflight_revocation
    test_lock_during_classification = worker.Q02ImportWorkerAccessTests.test_lock_during_classification_stops_rerouting_and_extraction
    test_delete_during_extraction = worker.Q02ImportWorkerAccessTests.test_delete_during_extraction_ignores_foreign_same_username
    test_demotion_during_extraction = worker.Q02ImportWorkerAccessTests.test_demotion_during_extraction_does_not_publish_preview

    def test_recreated_same_username_during_ocr_cannot_inherit_receipt(self):
        old_identity = self.owner().account_identity
        ident = self.enqueue()
        replacements = []

        def replace_owner(source, **kwargs):
            with self.m.app.app_context():
                previous = self.owner()
                self.m.db.session.delete(previous)
                self.m.db.session.flush()
                replacement = self.m.User(company_code='TEST', username='admin', role='admin',
                    password='unused', last_name='Different synthetic person',
                    password_changed_at='2026-10-27 10:00:00')
                self.m.db.session.add(replacement)
                self.m.db.session.commit()
                replacements.append(replacement.account_identity)
            return extraction(source)

        with patch.object(document_import_queue, 'detect_document_types', return_value={
            'types':['inspection'], 'certainty':'clear', 'supported':True
        }), patch.object(vehicle_imports, 'vehicle_document_extractor', return_value=replace_owner):
            self.assertTrue(document_import_queue.process_one(self.m.app))
        self.assertEqual(len(replacements), 1)
        self.assertNotEqual(replacements[0], old_identity)
        self.m.db.session.expire_all()
        receipt = self.m.VehicleDocumentImportDraft.query.filter_by(id=ident).one()
        with self.client.session_transaction() as state:
            state.update(company_code='TEST', username='admin', role='admin',
                         account_identity=replacements[0], password_changed_at='2026-10-27 10:00:00')
        preview = self.client.get(f'/vehicle/data-import/{receipt.batch_id}/preview')
        original = self.client.get('/vehicle/data-import/files/' + ident)
        print('Q10_OWNER_EVIDENCE:', json.dumps(dict(different_generation=old_identity != replacements[0],
            worker_status=receipt.status, preview_status=preview.status_code, original_status=original.status_code,
            original_bytes_exposed=original.data == receipt.source_file)), flush=True)
        self.assertEqual((receipt.status, preview.status_code, original.status_code), ('read_error', 404, 404),
                         'A replacement account must not authorize or read the previous account receipt')
        self.assertEqual(json.loads(receipt.preview_json or '{}'), {})


class PostgresPartialRetry(PostgresFixture, unittest.TestCase):
    setUp = workflow.WorkflowRegressionTests.setUp
    tearDown = workflow.WorkflowRegressionTests.tearDown
    send = queue_tests.DocumentImportQueueTests.send
    worker = queue_tests.DocumentImportQueueTests.worker
    status = queue_tests.DocumentImportQueueTests.status
    inspection_form = queue_tests.DocumentImportQueueTests.inspection_form
    test_retry_after_partial_registration = queue_tests.DocumentImportQueueTests.test_retry_after_successful_registration_only_registers_newly_ready_file


class PostgresExistingInspectionRepair(PostgresFixture, unittest.TestCase):
    """Downstream acceptance from an existing synthetic inspection, not a fix for entry."""
    setUp = daily.Q02DailyInspectionFlowTests.setUp
    tearDown = daily.Q02DailyInspectionFlowTests.tearDown
    login = daily.Q02DailyInspectionFlowTests.login
    request = daily.Q02DailyInspectionFlowTests.request
    complete = daily.Q02DailyInspectionFlowTests.complete
    state = daily.Q02DailyInspectionFlowTests.state
    decision_data = daily.Q02DailyInspectionFlowTests.decision_data
    decide = daily.Q02DailyInspectionFlowTests.decide
    repair = daily.Q02DailyInspectionFlowTests.repair

    def test_existing_inspection_repair_recheck_keeps_answer_and_history(self):
        from dkss_app.checklist_common import checklist_to_dict
        self.request('GET', '/vehicle/checklists')
        self.checklist = self.models.Checklist.query.filter_by(company_code='A').one()
        snapshot = checklist_to_dict(self.checklist)
        checks = [item for item in snapshot['items'] if item['item_type'] == 'check']
        answers = [{'item_no': i, 'value': '×' if i == 0 else '✓', 'comment': ''}
                   for i in range(len(checks))]
        vehicle = self.models.Vehicle.query.filter_by(company_code='A').one()
        self.form = dict(vehicle_record_id=vehicle.id, year='2026', month='10', day='23')
        # Valid pre-existing data is seeded outside an HTTP request. The failing
        # new-entry route and its listener remain enabled and separately tested.
        self.row = self.models.VehicleChecklistResult(company_code='A', checklist_id=self.checklist.id,
            vehicle_record_id=vehicle.id, year='2026', month='10', day='23',
            checked_by='Test checker', checked_by_username='checker', checked_date='2026-10-23 10:00',
            status='入力中', approvals_json='[]', answers_json=json.dumps(answers),
            checklist_snapshot_json=json.dumps(snapshot), operation_judgment_json='{}')
        self.db.session.add(self.row)
        self.db.session.commit()
        self.login('checker')
        self.complete()
        self.decide('運行不可')
        self.repair()
        self.repair('異常なし')
        self.decide()
        self.db.session.refresh(self.row)
        self.assertEqual(self.state()['status'], '運行可')
        self.assertEqual(self.state()['defects'][0]['status'], '解消')
        self.assertEqual(json.loads(self.row.answers_json), answers)
        self.assertEqual(self.models.VehicleMaintenanceRecord.query.count(), 1)
        events = self.models.ChecklistEvent.query.filter_by(result_id=self.row.id).all()
        types = [row.event_type for row in events]
        self.assertEqual(types.count('運行判断'), 2)
        self.assertIn('再確認待ち', types)
        self.assertIn('解消', types)
