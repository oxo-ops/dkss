"""Q10 transitions across real routes, with isolated SQLite and mocked delivery.

Reuse existing scenario builders without inheriting their collected test cases.
No production database, external OCR/delivery or browser is used here.
"""
import json
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError

import test_q02_daily_inspection_flow as daily
import test_document_import_queue as imports
import test_driving_identity_resolution as identity
from dkss_app import notifications_delivery


@contextmanager
def fail_next_commit(db):
    """Fail after the route has built its related rows, before commit."""
    hits = []
    session = db.session()

    def fail(current):
        hits.append(True)
        raise SQLAlchemyError('Q10 injected commit failure')

    event.listen(session, 'before_commit', fail)
    try:
        yield hits
    finally:
        event.remove(session, 'before_commit', fail)


@contextmanager
def fail_after_insert(db, table):
    """Prove that an already executed INSERT is rolled back on failure."""
    hits = []

    def fail(conn, cursor, statement, parameters, context, executemany):
        if not hits and statement.lstrip().lower().startswith('insert into ' + table + ' '):
            hits.append(True)
            raise SQLAlchemyError('Q10 injected post-insert failure')

    event.listen(db.engine, 'after_cursor_execute', fail)
    try:
        yield hits
    finally:
        event.remove(db.engine, 'after_cursor_execute', fail)


class DailyFlowFailuresTests(unittest.TestCase):
    setUpClass = classmethod(daily.Q02DailyInspectionFlowTests.setUpClass.__func__)
    tearDownClass = classmethod(daily.Q02DailyInspectionFlowTests.tearDownClass.__func__)
    setUp = daily.Q02DailyInspectionFlowTests.setUp
    tearDown = daily.Q02DailyInspectionFlowTests.tearDown
    login = daily.Q02DailyInspectionFlowTests.login
    request = daily.Q02DailyInspectionFlowTests.request
    begin = daily.Q02DailyInspectionFlowTests.begin
    save = daily.Q02DailyInspectionFlowTests.save
    complete = daily.Q02DailyInspectionFlowTests.complete
    state = daily.Q02DailyInspectionFlowTests.state
    decision_data = daily.Q02DailyInspectionFlowTests.decision_data
    decide = daily.Q02DailyInspectionFlowTests.decide
    repair = daily.Q02DailyInspectionFlowTests.repair
    snapshot = daily.Q02DailyInspectionFlowTests.snapshot
    assert_integrity = daily.Q02DailyInspectionFlowTests.assert_integrity

    def test_configured_required_daily_answer_blocks_submit_then_can_resume(self):
        self.request('GET', '/vehicle/checklists')
        self.checklist = self.models.Checklist.query.filter_by(company_code='A').one()
        items = json.loads(self.checklist.items_json)
        checks = [item for item in items if item['item_type'] == 'check']
        # The shipped template does not require every check. Exercise the
        # supported required-item configuration explicitly, without changing it.
        required = 0
        checks[required]['answer_required'] = True
        self.checklist.items_json = json.dumps(items, ensure_ascii=False)
        self.db.session.commit()
        vehicle = self.models.Vehicle.query.filter_by(company_code='A').one()
        self.form = dict(vehicle_record_id=vehicle.id, year='2026', month='10', day='23')
        self.login('checker')
        for i, _ in enumerate(checks):
            if i != required:
                self.save(i, '✓')
        self.row = self.models.VehicleChecklistResult.query.one()
        before = self.snapshot()
        with patch.object(notifications_delivery, 'dispatch_external_notification') as send:
            response = self.request('POST', f'/vehicle/checklists/{self.checklist.id}/complete',
                                    data={**self.form, 'approval_notify_users_0': 'admin'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.snapshot(), before)
        send.assert_not_called()
        self.save(required, '✓')
        self.complete()
        self.db.session.refresh(self.row)
        self.assertEqual(self.row.status, '承認待ち')

    def test_judgment_commit_failure_preserves_answers_events_and_notice_then_retries(self):
        self.begin()
        self.login('admin')
        data = self.decision_data()
        before = self.snapshot()
        with fail_next_commit(self.db) as hits, patch.object(
            notifications_delivery, 'dispatch_external_notification'
        ) as send:
            response = self.request('POST', f'/vehicle/checklist-results/{self.row.id}/operation-judgment', data=data)
        self.assertEqual(hits, [True])
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.snapshot(), before)
        send.assert_not_called()
        self.decide()
        self.assertEqual(self.state()['status'], '運行可')
        self.assertEqual(self.models.ChecklistEvent.query.filter_by(event_type='運行判断').count(), 1)

    def test_repair_post_insert_failure_rolls_back_maintenance_and_can_retry_once(self):
        self.begin(defect=True)
        self.decide('運行不可')
        self.login('reviewer')
        data = dict(judgment_version=str(self.state()['version']), repair_status='再確認待ち',
                    repair_note='Q10 isolated repair', repair_performed_date='2026-10-23')
        before = self.snapshot()
        with fail_after_insert(self.db, 'vehicle_maintenance_record') as hits, patch.object(
            notifications_delivery, 'dispatch_external_notification'
        ) as send:
            response = self.request('POST', f'/vehicle/checklist-results/{self.row.id}/defects/1/repair', data=data)
        self.assertEqual(hits, [True])
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.snapshot(), before)
        send.assert_not_called()
        self.repair()
        self.assertEqual(self.models.VehicleMaintenanceRecord.query.count(), 1)
        self.assertEqual(self.state()['defects'][0]['status'], '再確認待ち')
        before = self.snapshot()
        replay = self.request('POST', f'/vehicle/checklist-results/{self.row.id}/defects/1/repair', data=data)
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(self.snapshot(), before)
        self.repair('異常なし')
        self.decide()
        self.assertEqual(self.state()['status'], '運行可')

    def test_external_judgment_delivery_failure_keeps_committed_notice_and_replay_is_fenced(self):
        self.begin()
        self.login('admin')
        data = self.decision_data()
        before_notices = {n.id for n in self.models.Notification.query.all()}
        committed_statuses = []

        def fail_delivery(*args, **kwargs):
            # Observe through a separate connection: the business commit already happened.
            with self.db.engine.connect() as connection:
                status = connection.execute(self.models.VehicleChecklistResult.__table__.select().where(
                    self.models.VehicleChecklistResult.id == self.row.id)).mappings().one()['status']
                committed_statuses.append(status)
            raise RuntimeError('Q10 external transport unavailable')

        with patch.object(notifications_delivery, 'dispatch_external_notification', side_effect=fail_delivery) as send:
            response = self.request('POST', f'/vehicle/checklist-results/{self.row.id}/operation-judgment', data=data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(committed_statuses, ['承認済み'])
        self.assertEqual(self.state()['status'], '運行可')
        new = [n for n in self.models.Notification.query.all() if n.id not in before_notices]
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0].target_username, 'checker')
        before = self.snapshot()
        with patch.object(notifications_delivery, 'dispatch_external_notification') as send:
            replay = self.request('POST', f'/vehicle/checklist-results/{self.row.id}/operation-judgment', data=data)
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(self.snapshot(), before)
        send.assert_not_called()

    def test_recheck_event_insert_failure_keeps_defect_open_then_retry_clears_it(self):
        self.begin(defect=True)
        self.decide('運行不可')
        self.repair()
        self.login('checker')
        data = dict(judgment_version=str(self.state()['version']), repair_status='再確認待ち',
                    repair_note='Q10 isolated recheck', repair_performed_date='2026-10-23',
                    recheck_result='異常なし')
        before = self.snapshot()
        with fail_after_insert(self.db, 'checklist_event') as hits, patch.object(
            notifications_delivery, 'dispatch_external_notification'
        ) as send:
            response = self.request('POST', f'/vehicle/checklist-results/{self.row.id}/defects/1/repair', data=data)
        self.assertEqual(hits, [True])
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.state()['defects'][0]['status'], '再確認待ち')
        send.assert_not_called()
        self.repair('異常なし')
        self.assertEqual(self.state()['defects'][0]['status'], '解消')
        self.assertEqual(self.models.VehicleMaintenanceRecord.query.count(), 1)
        before = self.snapshot()
        self.assertEqual(self.request('POST', f'/vehicle/checklist-results/{self.row.id}/defects/1/repair',
                                     data=data).status_code, 409)
        self.assertEqual(self.snapshot(), before)
        self.decide()
        self.assertEqual(next(a for a in json.loads(self.row.answers_json) if a['item_no'] == 0)['value'], '×')

    def test_generated_judgment_notice_preview_read_delete_restore_keeps_business_result(self):
        self.begin()
        self.decide()
        notice = next(n for n in self.models.Notification.query.filter_by(target_username='checker').all()
                      if json.loads(n.workflow_context_json or '{}').get('action') == 'operation_result')
        notice_id = notice.id
        business_before = self.snapshot()[0:2]
        self.login('checker')
        self.assertEqual(self.request('GET', f'/notifications/{notice_id}?panel=1').status_code, 200)
        self.db.session.refresh(notice)
        self.assertFalse(notice.read)
        self.assertEqual(self.request('POST', f'/api/notifications/{notice_id}/read').status_code, 200)
        deleted = self.request('POST', f'/api/notifications/{notice_id}/delete')
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.request('POST', f'/api/notifications/{notice_id}/read').status_code, 409)
        restored = self.request('POST', f'/api/notifications/{notice_id}/undo-delete',
                                json={'deleted_at': deleted.json['deleted_at']})
        self.assertEqual(restored.status_code, 200)
        self.db.session.refresh(notice)
        self.assertIsNone(notice.deleted_at)
        self.assertTrue(notice.read)
        self.assertEqual(self.snapshot()[0:2], business_before)
        self.assertEqual(self.state()['status'], '運行可')


class QueuedImportFlowTests(unittest.TestCase):
    setUpClass = classmethod(imports.DocumentImportQueueTests.setUpClass.__func__)
    tearDownClass = classmethod(imports.DocumentImportQueueTests.tearDownClass.__func__)
    setUp = imports.DocumentImportQueueTests.setUp
    tearDown = imports.DocumentImportQueueTests.tearDown
    send = imports.DocumentImportQueueTests.send
    worker = imports.DocumentImportQueueTests.worker
    status = imports.DocumentImportQueueTests.status
    inspection_form = imports.DocumentImportQueueTests.inspection_form

    def queued_preview(self):
        receipt = self.send().json
        self.assertTrue(self.worker())
        self.assertTrue(self.status(receipt)['preview_ready'])
        draft = self.m.VehicleDocumentImportDraft.query.one()
        self.assertEqual(draft.status, 'preview')
        self.assertEqual(self.client.get(self.status(receipt)['preview_url']).status_code, 200)
        return draft, self.inspection_form(draft)

    def test_queue_to_confirmation_sql_failure_keeps_source_then_retry_and_replay(self):
        draft, form = self.queued_preview()
        draft_id, original = draft.id, draft.source_file
        key = draft_id + '_0'
        form['inspection_item_' + key + '_0_raw_result'] = '△'
        url = f'/vehicle/data-import/{draft.batch_id}/confirm'
        with fail_after_insert(self.m.db, 'vehicle_periodic_inspection_record') as hits:
            response = self.client.post(url, data=form)
        self.assertEqual(hits, [True])
        self.assertEqual(response.status_code, 500)
        self.m.db.session.expire_all()
        self.assertEqual(draft.status, 'preview')
        self.assertEqual(draft.source_file, original)
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(), 0)
        response = self.client.post(url, data=form)
        self.assertEqual(response.status_code, 302)
        self.m.db.session.expire_all()
        record = self.m.VehiclePeriodicInspectionRecord.query.one()
        self.assertEqual(record.source_draft_id, draft_id)
        self.assertEqual(json.loads(record.details_json)['inspection_items'][0]['raw_result'], '△')
        self.assertEqual(json.loads(draft.preview_json)['original_records'][0]['inspection_items'][0]['raw_result'], '○')
        self.assertEqual(self.client.get(f'/vehicle/periodic-inspections/{record.id}/source').data, original)
        saved = record.details_json
        self.assertEqual(self.client.post(url, data=form).status_code, 409)
        self.m.db.session.expire_all()
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(), 1)
        self.assertEqual(record.details_json, saved)
        self.assertEqual(draft.source_file, original)

    def test_queue_to_confirmation_missing_date_preserves_original_and_resumes(self):
        draft, form = self.queued_preview()
        original = draft.source_file
        url = f'/vehicle/data-import/{draft.batch_id}/confirm'
        missing = {**form, 'date_' + draft.id + '_0': ''}
        self.assertEqual(self.client.post(url, data=missing).status_code, 400)
        self.m.db.session.expire_all()
        self.assertEqual(draft.status, 'preview')
        self.assertEqual(draft.source_file, original)
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(), 0)
        self.assertEqual(self.client.post(url, data=form).status_code, 302)
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(), 1)

    def test_registered_vehicle_keeps_imported_history_and_original_after_master_renames(self):
        office = self.m.Office(company_code='TEST', name='Q10 Office')
        kind = self.m.VehicleType(company_code='TEST', name='Q10 Type')
        self.m.db.session.add_all([office, kind])
        self.m.db.session.commit()
        response = self.client.post('/master/vehicles/new', data={
            'vehicle_form_action': 'save', 'chassis_number': 'Q10-NEW-001',
            'office': office.name, 'type': kind.name,
        })
        self.assertEqual(response.status_code, 302)
        self.vehicle = self.m.Vehicle.query.filter_by(company_code='TEST', chassis_number='Q10-NEW-001').one()
        vehicle_id = self.vehicle.id
        draft, form = self.queued_preview()
        original = draft.source_file
        self.assertEqual(self.client.post(f'/vehicle/data-import/{draft.batch_id}/confirm', data=form).status_code, 302)
        record = self.m.VehiclePeriodicInspectionRecord.query.one()
        record_id, details = record.id, record.details_json
        for master, row_id, name in [('offices', office.id, 'Q10 Renamed Office'),
                                     ('vehicle-types', kind.id, 'Q10 Renamed Type')]:
            self.assertEqual(self.client.post(f'/master/{master}/{row_id}/edit', data={'name': name}).status_code, 302)
        self.m.db.session.expire_all()
        self.assertEqual(self.vehicle.id, vehicle_id)
        self.assertEqual(self.vehicle.office, 'Q10 Renamed Office')
        self.assertEqual(self.vehicle.type, 'Q10 Renamed Type')
        self.assertEqual(record.vehicle_record_id, vehicle_id)
        self.assertEqual(record.details_json, details)
        self.assertEqual(record.source_draft_id, draft.id)
        self.assertEqual(draft.source_file, original)
        self.assertEqual(self.client.get(f'/vehicle/periodic-inspections/{record_id}/source').data, original)
        history = self.client.get(f'/vehicle/karte/{vehicle_id}/history')
        self.assertEqual(history.status_code, 200)
        self.assertIn(record.content, history.get_data(as_text=True))
        detail = self.client.get(f'/vehicle/karte/{vehicle_id}/inspections')
        self.assertEqual(detail.status_code, 200)
        self.assertIn('ブレーキの効き', detail.get_data(as_text=True))
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(), 1)


class ImportedDrivingReadFlowTests(unittest.TestCase):
    setUpClass = classmethod(identity.DrivingIdentityTests.setUpClass.__func__)
    tearDownClass = classmethod(identity.DrivingIdentityTests.tearDownClass.__func__)
    setUp = identity.DrivingIdentityTests.setUp
    tearDown = identity.DrivingIdentityTests.tearDown
    add_user = identity.DrivingIdentityTests.add_user
    upload_driving_report = identity.DrivingIdentityTests.upload_driving_report
    inspection_form = identity.DrivingIdentityTests.inspection_form
    import_matching = identity.DrivingIdentityTests.import_matching
    login = identity.DrivingIdentityTests.login
    context = identity.DrivingIdentityTests.context

    def test_confirmed_report_auto_identity_person_admin_and_unrelated_reader(self):
        admin = self.m.User.query.filter_by(company_code='TEST', username='admin').one()
        unrelated = self.add_user('unrelated', '別の', '利用者')
        response, record, draft = self.import_matching()
        self.assertEqual(response.status_code, 302)
        grant = identity.DrivingReportReader.query.filter_by(report_id=record.id).one()
        self.assertEqual(grant.user_id, self.person.id)
        record_id, original, details = record.id, draft.source_file, record.details_json
        url = f'/safety/driving-reports/{record_id}'
        self.login(self.person)
        self.assertEqual(self.client.get(url).status_code, 200)
        _, own = self.context('/safety/driving-reports?period=all')
        self.assertEqual(own['total'], 1)
        self.login(unrelated)
        self.assertEqual(self.client.get(url).status_code, 404)
        _, other = self.context('/safety/driving-reports?period=all')
        self.assertEqual(other['total'], 0)
        self.login(admin)
        self.assertEqual(self.client.get(url).status_code, 200)
        _, manager = self.context('/safety/driving-reports?period=all&scope=company&office=__company__')
        self.assertEqual(manager['total'], 1)
        self.m.db.session.expire_all()
        self.assertEqual(record.details_json, details)
        self.assertEqual(draft.source_file, original)
        self.assertEqual(self.m.VehicleDrivingReportRecord.query.count(), 1)
