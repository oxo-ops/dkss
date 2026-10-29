"""Narrow HTML/fetch conflict responses; no existing acceptance suite rerun."""
import unittest
from flask import request
from werkzeug.routing import Rule
import test_q03_approval_versions as acceptance

class ConflictResponseTests(unittest.TestCase):
    setUpClass=classmethod(acceptance.ApprovalVersionTests.setUpClass.__func__)
    tearDownClass=classmethod(acceptance.ApprovalVersionTests.tearDownClass.__func__)
    setUp=acceptance.ApprovalVersionTests.setUp
    tearDown=acceptance.ApprovalVersionTests.tearDown
    login=acceptance.ApprovalVersionTests.login
    request=acceptance.ApprovalVersionTests.request
    record=acceptance.ApprovalVersionTests.record
    _vehicle=acceptance.ApprovalVersionTests._vehicle
    _snapshot=acceptance.ApprovalVersionTests._snapshot
    get_form=acceptance.ApprovalVersionTests.get_form
    setup_record=acceptance.ApprovalVersionTests.setup_record
    change_answers=acceptance.ApprovalVersionTests.change_answers

    def conflict(self,kind,headers):
        row,page,path=self.setup_record(kind);old=self.get_form(page,path)
        self.change_answers(kind,row);before=self._snapshot()
        for attempt in range(2):
            response=self.request('POST',path,data=old,headers=headers)
            self.assertEqual(response.status_code,409)
            self.assertEqual(response.headers['X-DKSS-Approval-Conflict'],'1')
            self.assertEqual(self._snapshot(),before)
        return row,page,path,response

    def test_safety_html_keeps_409_and_renders_current_detail(self):
        row,page,path,r=self.conflict('safety',{'Accept':'text/html'})
        text=r.get_data(as_text=True)
        self.assertIn('NEW_ANSWER_FROM_OTHER_OPERATION',text)
        self.assertIn('最新の回答と履歴を再表示',text)
        self.assertIn('data-approval-conflict-reload',text)
        self.assertNotIn('Location',r.headers)
        self.assertEqual(r.headers['X-DKSS-Approval-Reload'],page)

    def test_vehicle_fetch_keeps_specific_message_and_record_url(self):
        row,page,path,r=self.conflict('vehicle',{'Accept':'*/*'})
        self.assertEqual(r.mimetype,'text/plain')
        self.assertEqual(r.get_data(as_text=True),'点検記録が更新されています。最新の回答と履歴を確認してから承認してください。')
        self.assertEqual(r.headers['X-DKSS-Approval-Reload'],page+f'#vehicle-approval-result-{row.id}')

    def test_json_form_error_contract_remains_structured(self):
        row,page,path,r=self.conflict('safety',{'Accept':'text/html','X-DKSS-Final-Submit':'1'})
        self.assertEqual(r.json['errors'][0]['field'],'')
        self.assertIn('点検記録が更新',r.json['errors'][0]['message'])

    def test_other_html_errors_and_request_spoof_still_redirect(self):
        from dkss_app.http import redirect_form_errors
        for endpoint,code,response_marker,expected in [('other',409,True,302),('approve_checklist_result',400,True,302),('approve_checklist_result',500,True,302),('approve_checklist_result',409,False,302),('approve_checklist_result',409,True,409)]:
            with self.app.test_request_context('/synthetic',method='POST',headers={'Accept':'text/html','Referer':'http://localhost/synthetic','X-DKSS-Approval-Conflict':'1'}):
                request.url_rule=Rule('/synthetic',endpoint=endpoint)
                response=self.app.response_class('',status=code)
                if response_marker:response.headers['X-DKSS-Approval-Conflict']='1'
                self.assertEqual(redirect_form_errors(response).status_code,expected)
