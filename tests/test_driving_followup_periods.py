"""Arbitrary before/after periods and due review records respect the selected scope."""
import json
import unittest
from datetime import date
from unittest.mock import patch
from driving_report_insights import periods
from driving_report_data import payload
import test_driving_workspace as workspace_tests


class FollowupPeriodTests(unittest.TestCase):
    setUpClass=classmethod(workspace_tests.WorkspaceTests.setUpClass.__func__)
    tearDownClass=classmethod(workspace_tests.WorkspaceTests.tearDownClass.__func__)
    setUp=workspace_tests.WorkspaceTests.setUp
    tearDown=workspace_tests.WorkspaceTests.tearDown
    save=workspace_tests.WorkspaceTests.save
    render=workspace_tests.WorkspaceTests.render

    def review(self,row,**values):
        p=payload(row);p['review']=values;row.details_json=json.dumps(p);self.m.db.session.commit()

    def test_custom_periods_are_explicit_prior_and_nonoverlapping(self):
        args=dict(period='custom',start='2026-10-01',end='2026-10-26',compare='custom',compare_start='2026-06-01',compare_end='2026-06-07')
        p=periods(args,date(2026,10,27))
        self.assertEqual((p['previous_start'],p['previous_end']),('2026-06-01','2026-06-07'))
        for change in [dict(compare_end='2026-10-02'),dict(compare_start='2026-06-08'),dict(compare_start=''),dict(compare_end='bad'),dict(period='all')]:
            with self.assertRaises(ValueError):periods(dict(args,**change),date(2026,10,27))

    def test_disjoint_windows_exclude_gap_identity_and_export_exact_dates(self):
        old=self.save(8,day='2026-06-02',distance='100',count='10')
        self.save(9,day='2026-08-15',name='比較対象外の期間の氏名',distance='999',count='999')
        url='/safety/driving-reports?period=custom&start=2026-10-01&end=2026-10-26&compare=custom&compare_start=2026-06-01&compare_end=2026-06-07&breakdown=people'
        response,context=self.render(url)
        rows=context['insights']['comparison']['rows']
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['change'],'-5')
        self.assertEqual(rows[0]['previous']['report_ids'],[old.id])
        self.assertIn('対象 26日間 ／ 比較 7日間',response.get_data(as_text=True))
        exported=self.client.get(url.replace('/safety/driving-reports?','/safety/driving-reports/export.csv?')+'&view=breakdown')
        text=exported.data.decode('utf-8-sig')
        self.assertIn('2026-06-01',text);self.assertIn('2026-06-07',text)
        self.assertNotIn('比較対象外の期間の氏名',text)

    def test_due_records_keep_office_company_and_completion_boundaries(self):
        self.review(self.a,state='followup',next_date='2020-01-01',action='早めの減速を確認')
        self.review(self.b,state='coaching',next_date='2020-01-02',action='別営業所の対応')
        self.review(self.secret,state='followup',next_date='2020-01-01',action='他社の対応')
        _,context=self.render(self.base)
        self.assertEqual([r['id'] for r in context['insights']['due_followups']],[self.a.id])
        _,context=self.render(self.base+'&scope=company&followup_due=due')
        self.assertEqual(context['total'],2)
        self.assertNotIn('他社の対応',str(context['insights']['due_followups']))
        self.review(self.a,state='completed',next_date='2020-01-01',action='早めの減速を確認')
        _,context=self.render(self.base+'&followup_due=due')
        self.assertEqual(context['total'],0)
        self.assertEqual(context['insights']['due_followups'],[])

    def test_cancelled_or_unknown_date_never_becomes_due(self):
        self.review(self.a,state='followup',next_date='2020-01-01')
        p=payload(self.a);p['lifecycle']='cancelled';self.a.details_json=json.dumps(p);self.m.db.session.commit()
        _,context=self.render(self.base+'&followup_due=due');self.assertEqual(context['total'],0)
        self.review(self.b,state='followup',next_date='bad')
        _,context=self.render(self.base+'&scope=company&followup_due=due');self.assertEqual(context['total'],0)
        self.assertEqual(self.client.get(self.base+'&followup_due=unknown').status_code,400)

    def test_upcoming_is_not_overdue_and_filter_change_invalidates_ai(self):
        self.review(self.a,state='followup',next_date='2099-01-01',action='継続確認')
        _,context=self.render(self.base+'&followup_due=upcoming')
        self.assertEqual(context['total'],1);self.assertEqual(context['insights']['due_followups'],[])
        first=self.client.get('/safety/driving-reports/reflection?period=all').json['key']
        second=self.client.get('/safety/driving-reports/reflection?period=all&followup_due=upcoming').json['key']
        self.assertNotEqual(first,second)


if __name__=='__main__':unittest.main()
