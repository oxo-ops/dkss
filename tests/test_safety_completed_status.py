"""No approval slots means completed, not waiting: real isolated Flask routes."""
import html
import json
import re
import unittest
from test_q02_checklist_boundaries import Q02ChecklistBoundaryTests as Fixture

class SafetyCompletedStatusTests(unittest.TestCase):
    setUpClass = classmethod(Fixture.setUpClass.__func__)
    tearDownClass = classmethod(Fixture.tearDownClass.__func__)
    setUp = Fixture.setUp
    tearDown = Fixture.tearDown
    login = Fixture.login
    request = Fixture.request
    record = Fixture.record
    url = Fixture.url

    def test_no_approval_submission_is_complete_on_detail_and_both_list_layouts(self):
        checklist = self.models.Checklist(company_code='A', name='No approval', target='安全管理',
            frequency_unit='day', display_type='month', active=True,
            items_json=json.dumps([{'item_type':'check','category':'Safety','content':'Check',
                                   'input_type':'text','answer_required':False}]))
        self.db.session.add(checklist)
        self.db.session.commit()
        self.login('checker')
        url=f'/safety/checklists/{checklist.id}/new'
        page=self.request('GET',url).get_data(as_text=True)
        token=html.unescape(re.search(r'name="person_selection_token"\s+value="([^"]+)"',page)[1])
        response=self.request('POST',url,data={'answer_0':'ok','person_selection_token':token})
        self.assertEqual(response.status_code,302)
        row=self.models.ChecklistResult.query.one()
        self.assertEqual(row.status,'点検完了')
        self.assertEqual(json.loads(row.approvals_json),[])
        for path,count in [(self.url(row),1),(f'/safety/checklists/{checklist.id}',2)]:
            response=self.request('GET',path)
            self.assertEqual(response.status_code,200)
            text=response.get_data(as_text=True)
            badges=re.findall(r'<span class="status-badge[^\"]*">\s*([^<]+?)\s*</span>',text)
            self.assertEqual(badges.count('点検完了'),count)
            self.assertNotIn('承認待ち',badges)
            self.assertNotIn('承認済み',badges)

    def test_actual_approval_states_remain_distinct(self):
        row=self.record((False,))
        for status in ('承認待ち','承認済み','差し戻し'):
            row.status=status
            self.db.session.commit()
            for path,count in [(self.url(row),1),(f'/safety/checklists/{row.checklist_id}',2)]:
                response=self.request('GET',path)
                self.assertEqual(response.status_code,200)
                badges=re.findall(r'<span class="status-badge[^\"]*">\s*([^<]+?)\s*</span>',response.get_data(as_text=True))
                self.assertEqual(badges.count(status),count)
                self.assertNotIn('点検完了',badges)

del Fixture
