"""Actual isolated Flask rendering; no live requests or external delivery."""
import unittest
from html.parser import HTMLParser
from test_demo_inspection_compact import CompactDemoTests

class FormControls(HTMLParser):
    def __init__(self):
        super().__init__();self.form='';self.controls=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='form':self.form=a.get('class','')
        if tag in ('input','img','div','button'):self.controls.append((tag,a,self.form))
    def handle_endtag(self,tag):
        if tag=='form':self.form=''

class GuideRoleRendering(CompactDemoTests):
    def test_actual_role_controls_and_no_data_changes(self):
        target=f'/vehicle/checklists/{self.app.config["PUBLIC_DEMO_CHECKLIST_ID"]}?vehicle_record_id={self.vehicle_id}'
        for role in ('driver','manager'):
            token,_=self.enter();self.client.post('/demo/role',data={'role':role,'csrf_token':token})
            before=self.models.VehicleChecklistResult.query.count()
            page=self.client.get(target)
            self.assertEqual(page.status_code,200)
            p=FormControls();p.feed(page.text)
            approvers=[a for tag,a,form in p.controls if 'approval-user-search' in a.get('class','').split() and 'vehicle-check-complete-form' in form.split()]
            self.assertTrue(approvers)
            self.assertTrue(all(a.get('data-guide-title')=='運行判断の依頼先を選ぶ' for a in approvers))
            self.assertFalse(any(a.get('id')=='operation_notify_user_search' for a in approvers))
            reminder=any(a.get('id')=='reminder_notify_user_search' for tag,a,form in p.controls)
            readonly=any('reminder-readonly' in a.get('class','').split() for tag,a,form in p.controls)
            self.assertEqual(reminder,role=='manager');self.assertEqual(readonly,role=='driver')
            self.assertIn('guide/inspection-detail-open.png',page.text)
            self.assertEqual(before,self.models.VehicleChecklistResult.query.count())

def load_tests(loader,tests,pattern):
    return unittest.TestSuite([GuideRoleRendering('test_actual_role_controls_and_no_data_changes')])
