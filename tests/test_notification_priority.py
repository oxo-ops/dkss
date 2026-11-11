"""Owned, exact-event notification priority; all writes use disposable fixtures."""
from copy import deepcopy
import json
from unittest.mock import patch

import test_video_connected_flows as flows


class NotificationPriorityTests(flows.ConnectedInspectionFlowTests):
    # Reuse helpers, not already collected connected acceptance cases.
    test_inspection_notification_human_stop_and_recheck_keep_one_vehicle = None
    test_normal_50_keeps_shared_order_with_dashboard_safety_and_comparison_panels = None
    test_registered_recheck_waiting_25_is_not_an_automatic_operation_decision = None

    def prepare(self, recheck=False):
        self.begin_priority()
        self.decide('運行可' if recheck else '運行不可')
        if recheck:
            self.repair_priority()
        self.bundle, self.saved = self.generate('inspection_defect' if recheck else 'registered_operation_instruction')
        self.login('checker')
        query = self.models.Notification.query.filter_by(company_code='A', target_username='checker')
        if recheck:
            self.note = query.filter(self.models.Notification.title.like('%：再確認待ち')).one()
        else:
            self.note = query.filter_by(title='車両の運行判断：運行不可').one()
        return self.note

    def related(self):
        response = self.client.get('/api/notifications/recent')
        self.assertEqual(response.status_code, 200)
        return next(n['related_priority'] for n in response.json['notifications'] if n['id'] == self.note.id)

    def protected(self):
        return {name: [tuple(getattr(row, c.name) for c in getattr(self.models, name).__table__.columns)
                       for row in getattr(self.models, name).query.order_by(getattr(self.models, name).id)]
                for name in ('Notification', 'VehicleChecklistResult', 'ChecklistEvent',
                             'VehicleKarteAnalysis', 'VehicleAnalysisFeedback', 'VehicleMaintenanceRecord')}

    def test_exact_instruction_matches_api_list_detail_and_recent_without_writes_or_ai(self):
        self.prepare()
        api = self.current_analysis()['recommendations'][0]
        before = self.protected()
        with patch('dkss_app.analysis.get_vehicle_karte_analysis_job_data', side_effect=AssertionError('No rebuild')), \
                patch('dkss_app.analysis.get_vehicle_analysis_read_projection', side_effect=AssertionError('No cache rebuild')):
            related = self.related()
            html = self.client.get('/notifications').get_data(as_text=True)
            detail = self.client.get(f'/notifications/{self.note.id}?panel=1').json['html']
        item = related['items'][0]
        self.assertEqual((item['label'], item['score']), ('高', 60))
        self.assertEqual((item['proposal_id'], item['proposal_revision']), (api['proposal_id'], api['proposal_revision']))
        self.assertEqual(related['count'], 1)  # Other same-vehicle proposals do not leak in.
        for page in (html, detail):
            self.assertIn('関連する確認・対応優先度', page)
            self.assertIn('高 · 60点', page)
        self.assertIn('#proposal=' + api['proposal_id'], detail)
        self.assertIn('運行可否は人が判断', detail)
        self.assertEqual(self.protected(), before)
        self.assertFalse(self.note.read)

    def test_other_owner_company_deleted_vehicle_and_missing_saved_proof_are_absent(self):
        self.prepare()
        for username, company in [('outsider', 'A'), ('checker', 'B')]:
            self.login(username, company)
            self.assertEqual(self.client.get(f'/notifications/{self.note.id}?panel=1').status_code, 404)
            self.assertNotIn(self.note.id, [n['id'] for n in self.client.get('/api/notifications/recent').json['notifications']])
        self.login('checker')
        self.vehicle.deleted = True; self.db.session.commit()
        self.assertIsNone(self.related())
        self.vehicle.deleted = False
        bundle = deepcopy(self.bundle)
        bundle['sources'][f'inspection:{self.row.id}'].pop('priority_provenance')
        self.saved.result_json = json.dumps(bundle); self.db.session.commit()
        self.assertIsNone(self.related())

    def test_operation_event_context_link_and_explicit_ref_must_all_match(self):
        self.prepare()
        original_context, original_link = self.note.workflow_context_json, self.note.link
        for key, value in [('event_id', True), ('event_id', 0), ('event_id', 2147483648),
                           ('result_id', True), ('result_type', 'safety'), ('action', 'operation_judgment')]:
            with self.subTest(key=key, value=value):
                context = json.loads(original_context); context[key] = value
                self.note.workflow_context_json = json.dumps(context); self.db.session.commit()
                self.assertIsNone(self.related())
        self.note.workflow_context_json = original_context
        for bad in ('https://example.invalid' + original_link, original_link.replace('#vehicle-flow-judgment', '#other'),
                    original_link.replace('vehicle_record_id=', 'vehicle_record_id=99&vehicle_record_id=')):
            self.note.link = bad; self.db.session.commit(); self.assertIsNone(self.related())
        self.note.link = original_link
        for key, value in [('priority_input_ref', ''), ('target', 'ブレーキ')]:
            bundle = deepcopy(self.bundle); bundle['analysis']['recommendations'][0][key] = value
            self.saved.result_json = json.dumps(bundle); self.db.session.commit()
            self.assertIsNone(self.related())
        for key, value in [('vehicle_id', True), ('inspection_on', '2000-01-01'), ('record_id', 999)]:
            bundle = deepcopy(self.bundle)
            bundle['sources'][f'inspection:{self.row.id}']['priority_provenance'][key] = value
            self.saved.result_json = json.dumps(bundle); self.db.session.commit()
            self.assertIsNone(self.related())

    def test_old_operation_notice_cannot_take_a_new_instruction_version(self):
        self.prepare()
        old = self.note
        self.decide('判定保留'); self.decide('運行不可')
        self.models.VehicleKarteAnalysis.query.delete(); self.db.session.commit()
        self.bundle, self.saved = self.generate('registered_operation_instruction')
        self.login('checker'); self.note = old
        self.assertIsNone(self.related())
        self.note = self.models.Notification.query.filter_by(company_code='A', target_username='checker',
            title='車両の運行判断：運行不可').order_by(self.models.Notification.id.desc()).first()
        self.assertEqual(self.related()['items'][0]['score'], 60)

    def test_recheck_matches_only_that_defect_and_registered_repair_then_disappears(self):
        self.prepare(recheck=True)
        before = self.protected()
        related = self.related()
        self.assertEqual((related['count'], related['items'][0]['label'], related['items'][0]['score']), (1, '中', 25))
        self.assertEqual(self.protected(), before)
        original = self.note.created_at
        self.note.created_at = '2000-01-01T00:00:00Z'; self.db.session.commit()
        self.assertIsNone(self.related())
        self.note.created_at = original; self.db.session.commit()
        self.finish_recheck(); self.login('checker')
        self.assertIsNone(self.related())
        self.assertEqual(self.state()['status'], '未判定')

    def test_recheck_ambiguous_notice_or_changed_event_identity_is_not_rebound(self):
        self.prepare(recheck=True)
        n = self.models.Notification
        duplicate = n(company_code='A', owner_identity=self.note.owner_identity, target_username='checker', target_user=self.note.target_user,
            title=self.note.title, message=self.note.message, link=self.note.link, created_at=self.note.created_at)
        self.db.session.add(duplicate); self.db.session.commit()
        self.assertIsNone(self.related())
        self.db.session.delete(duplicate); self.db.session.commit()
        value = json.loads(self.row.operation_judgment_json)
        value['defects'][0]['reported_at'] = '2000-01-01 00:00:00'
        self.row.operation_judgment_json = json.dumps(value); self.db.session.commit()
        self.assertIsNone(self.related())

    def test_completed_exact_revision_is_not_reintroduced_as_pending(self):
        self.prepare()
        item = self.related()['items'][0]
        self.db.session.add(self.models.VehicleAnalysisFeedback(company_code='A', vehicle_record_id=self.vehicle.id,
            proposal_key=item['proposal_id'], proposal_revision=item['proposal_revision'], status='completed',
            comment='合成', snapshot_json='{}', created_by='checker', created_at=self.day.isoformat()))
        self.db.session.commit()
        self.assertIsNone(self.related())

    def test_missing_current_evidence_never_becomes_low_or_a_new_score(self):
        self.prepare()
        self.repair_priority(); self.login('checker')
        related = self.related()
        self.assertEqual(related['items'][0]['label'], '高')
        self.assertIsNone(related['items'][0]['score'])
        self.assertIn('保存区分', related['items'][0]['badge'])

    def test_current_account_revocation_blocks_new_related_data_like_analysis(self):
        self.prepare()
        user = self.models.User.query.filter_by(company_code='A', username='checker').one()
        user.login_locked = True; self.db.session.commit()
        response = self.client.get('/api/notifications/recent')
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('related_priority', response.get_data(as_text=True))
        self.assertIn(self.client.get(f'/vehicle/karte/{self.vehicle.id}/analysis/result').status_code, (302, 401))
        user.login_locked = False; self.db.session.commit(); self.login('checker')
        with self.client.session_transaction() as stored:
            stored['account_identity'] = 'replaced-account-generation'
        self.assertEqual(self.client.get('/api/notifications/recent').status_code, 401)
        self.assertEqual(self.db.session.get(self.models.Notification, self.note.id).read, False)

    def test_dirty_session_has_no_flush_and_errors_do_not_change_notifications(self):
        self.prepare()
        from dkss_app.notification_priority import related_notification_priority
        with self.client.session_transaction() as stored:
            identity = dict(stored)
        with self.app.test_request_context('/'):
            from flask import session
            session.update(identity)
            self.row.status = 'dirty'
            with patch.object(self.db.session, 'flush', side_effect=AssertionError('No flush')):
                self.assertIsNone(related_notification_priority(self.note))
        self.db.session.rollback()
        before = self.protected()
        from sqlalchemy.exc import OperationalError
        with patch('dkss_app.notification_priority._saved_projection',
                   side_effect=OperationalError('secret SQL', {}, Exception('secret'))):
            self.assertIsNone(self.related())
        self.assertEqual(self.protected(), before)
