"""Request-local reuse reduces database round trips without retaining permissions."""
from identity_fixture import identity_for
import json
import re
import unittest
from collections import Counter
from sqlalchemy import event
from dkss_app.models import DrivingReportReader
import test_driving_admin_self as admin_tests


class DrivingRequestReadTests(unittest.TestCase):
    setUpClass=classmethod(admin_tests.AdminSelfTests.setUpClass.__func__)
    tearDownClass=classmethod(admin_tests.AdminSelfTests.tearDownClass.__func__)
    setUp=admin_tests.AdminSelfTests.setUp
    tearDown=admin_tests.AdminSelfTests.tearDown
    save=admin_tests.AdminSelfTests.save
    bind=admin_tests.AdminSelfTests.bind
    render=admin_tests.AdminSelfTests.render

    def test_reference_lists_are_read_once_per_page(self):
        for scope,limit in [('company',24),('self',36),('office',24)]:
            with self.subTest(scope=scope):
                # Overview now reads correction evidence once to hold conflicting personal metrics.
                # Warm template compilation before counting the complete route.
                self.render(self.base+'&scope='+scope)
                statements=[]
                def capture(conn,cursor,statement,parameters,context,executemany):
                    if statement.lstrip().upper().startswith('SELECT'):statements.append(statement)
                event.listen(self.m.db.engine,'before_cursor_execute',capture)
                try:_,ctx=self.render('/safety/driving-reports?period=month&scope='+scope)
                finally:event.remove(self.m.db.engine,'before_cursor_execute',capture)
                tables=Counter(match.group(1) for sql in statements if (match:=re.search(r'\bFROM\s+(\w+)',sql,re.I)))
                self.assertEqual(tables['driver'],1);self.assertEqual(tables['office'],1)
                self.assertLessEqual(len(statements),limit)

    def test_new_report_office_is_visible_on_next_request(self):
        _,before=self.render(self.base+'&scope=company')
        self.assertNotIn('追加営業所',[o['name'] for o in before['insights']['office_choices']])
        payload=json.loads(self.own.details_json);payload['driver_office']='追加営業所'
        self.own.details_json=json.dumps(payload,ensure_ascii=False);self.m.db.session.commit()
        _,after=self.render(self.base+'&scope=company')
        self.assertIn('追加営業所',[o['name'] for o in after['insights']['office_choices']])

    def test_revocation_and_account_change_are_visible_on_next_request(self):
        _,before=self.render(self.base+'&scope=self');self.assertEqual(before['total'],1)
        grant=DrivingReportReader.query.filter_by(report_id=self.own.id).one()
        self.m.db.session.delete(grant);self.m.db.session.commit()
        _,after=self.render(self.base+'&scope=self');self.assertEqual(after['total'],0)
        with self.client.session_transaction() as state:state.update(account_identity=identity_for(state.get('company_code'), 'two', app=(self.client).application), username='two',role='user',password_changed_at='stamp')
        _,other=self.render(self.base+'&scope=company')
        self.assertEqual(other['total'],1);self.assertEqual(other['reports'][0]['row'].id,self.theirs.id)
        self.assertFalse(other['driving_can_manage'])


if __name__=='__main__':unittest.main()
