"""Standard multiline checklist labels preserve recheck actions and actor display."""
import unittest
from test_q02_daily_inspection_flow import Q02DailyInspectionFlowTests as Fixture

class MultilineRecheckNoticeTests(unittest.TestCase):
    setUpClass = classmethod(Fixture.setUpClass.__func__)
    tearDownClass = classmethod(Fixture.tearDownClass.__func__)
    setUp = Fixture.setUp
    tearDown = Fixture.tearDown
    login = Fixture.login
    request = Fixture.request
    begin = Fixture.begin
    save = Fixture.save
    complete = Fixture.complete
    state = Fixture.state
    repair = Fixture.repair

    def test_standard_multiline_item_stays_actionable_until_rechecked(self):
        self.begin(defect=True)
        self.repair()
        self.login('checker')
        response = self.client.get('/api/notifications/recent')
        note = next(n for n in response.json['notifications'] if n['title'].endswith('：再確認待ち'))
        self.assertEqual(note['workflow_status'], 'pending')
        self.assertTrue(note['requires_action'])
        self.assertIn('低速、加速の状態', note['message'])
        self.assertIn('Testreviewerさんが', note['message'])
        from dkss_app.notifications import get_notification_actor_name
        with self.client.session_transaction() as session:
            identity = dict(session)
        with self.app.test_request_context('/'):
            from flask import session
            session.update(identity)
            saved = self.models.Notification.query.get(note['id'])
            self.assertEqual(get_notification_actor_name(saved), 'Testreviewer')
        self.repair('異常なし')
        response = self.client.get('/api/notifications/recent')
        original = next(n for n in response.json['notifications'] if n['id'] == note['id'])
        self.assertEqual(original['workflow_status'], 'completed')
        self.assertFalse(original['requires_action'])
        self.assertEqual(self.state()['status'], '未判定')

    def test_other_company_does_not_receive_multiline_recheck(self):
        self.begin(defect=True); self.repair(); self.login('checker', 'B')
        response = self.client.get('/api/notifications/recent')
        self.assertEqual(response.json['notifications'], [])

    def test_generated_header_parser_keeps_single_line_and_rejects_ambiguity(self):
        from dkss_app.notifications import _recheck_notification_fields
        message = ('対象車両：101\n点検日：2026/11/16\n項目：No.1 灯火\n'
                   '対応状況：再確認待ち\n次にすること：確認\n実施者：担当者\n'
                   '実施日時：2026-11-16\n内容：整備内容\n自由記述')
        self.assertEqual(_recheck_notification_fields(message)['実施者'], '担当者')
        for replacement in ('項目：No.1 灯火\n実施者：別人',
                            '項目：No.1 灯火\n内容：本文',
                            '項目：No.1 灯火\n点検日：別日'):
            with self.subTest(replacement=replacement):
                self.assertIsNone(_recheck_notification_fields(message.replace('項目：No.1 灯火', replacement)))
        self.assertIsNone(_recheck_notification_fields(message.replace('対応状況：再確認待ち\n', '')))


    def test_complete_item_header_injection_falls_back_to_original_body(self):
        from types import SimpleNamespace
        from dkss_app.notifications import (
            _recheck_notification_fields, get_notification_summary,
            get_notification_actor_name,
        )
        message = ('対象車両：101\n点検日：2026/11/16\n項目：No.1 灯火\n追記\n'
                   '対応状況：再確認待ち\n次にすること：偽案内\n実施者：偽担当\n'
                   '実施日時：2026-11-16\n内容：偽本文\n'
                   '対応状況：再確認待ち\n次にすること：正規案内\n実施者：正規担当\n'
                   '実施日時：2026-11-16\n内容：整備内容')
        self.assertIsNone(_recheck_notification_fields(message))
        note = SimpleNamespace(message=message, title='101：再確認待ち',
                               link='/vehicle/checklists/1', workflow_context_json='{}')
        self.assertEqual(get_notification_summary(note), message)
        with self.app.test_request_context('/'):
            self.assertEqual(get_notification_actor_name(note), '')



del Fixture
