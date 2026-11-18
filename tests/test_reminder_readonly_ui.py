"""Reminder settings are readable, not editable, for ordinary users."""
import unittest
from test_q03_form_generation import FormGenerationTests as Fixture

class ReminderReadonlyUiTests(unittest.TestCase):
    setUpClass=classmethod(Fixture.setUpClass.__func__)
    tearDownClass=classmethod(Fixture.tearDownClass.__func__)
    setUp=Fixture.setUp
    tearDown=Fixture.tearDown
    login=Fixture.login
    request=Fixture.request
    _vehicle=Fixture._vehicle
    _page=Fixture._page
    _snapshot=Fixture._snapshot

    def test_user_can_read_recipients_but_has_no_edit_controls_and_post_stays_forbidden(self):
        row,url=self._vehicle(); url=url.replace('active_day=23','active_day=24')
        self.login('admin')
        user=self.models.User.query.filter_by(company_code='A',username='admin').one()
        user.last_name='通知担当';user.first_name='太郎';self.db.session.commit()
        endpoint=f'/vehicle/checklists/{row.checklist_id}/reminder-notify-users'
        self.assertEqual(self.request('POST',endpoint,data={'vehicle_record_id':row.vehicle_record_id,
            'reminder_notify_users':'admin',**self._page(url)}).status_code,200)
        self.login('checker')
        page=self.request('GET',url)
        self.assertEqual(page.status_code,200)
        html=page.get_data(as_text=True)
        self.assertIn('data-reminder-readonly',html)
        self.assertIn('notify-user-selector reminder-readonly',html)
        readonly=html.split('data-reminder-readonly',1)[1].split('</div>',1)[0]
        self.assertIn('通知担当太郎',readonly)
        self.assertNotIn('>admin<',readonly)
        self.assertNotIn('<button',readonly)
        self.assertIn('通知先の変更は管理者に依頼してください。',html)
        self.assertNotIn('id="reminder_notify_user_search"',html)
        self.assertNotIn('id="selected_reminder_notify_users"',html)
        self.assertNotIn('class="remove-reminder-notify-user"',html)
        before=self._snapshot()
        self.assertEqual(self.request('POST',endpoint,data={'vehicle_record_id':row.vehicle_record_id}).status_code,403)
        self.assertEqual(self._snapshot(),before)

    def test_admin_keeps_edit_controls(self):
        row,url=self._vehicle(); url=url.replace('active_day=23','active_day=24')
        self.login('admin')
        page=self.request('GET',url)
        self.assertEqual(page.status_code,200)
        html=page.get_data(as_text=True)
        self.assertIn('id="reminder_notify_user_search"',html)
        self.assertIn('id="selected_reminder_notify_users"',html)
        self.assertNotIn('data-reminder-readonly',html)

del Fixture
