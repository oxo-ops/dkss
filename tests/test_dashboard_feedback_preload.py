"""Dashboard read optimization, with synthetic SQLite denials and old feedback states."""
from collections import Counter
import json
import unittest
from unittest.mock import patch
from sqlalchemy import event

from dkss_app import dashboard
from dkss_app.analysis_feedback import vehicle_analysis_proposal_ids
from identity_fixture import identity_for
import test_dashboard_saved_proposals as fixture_module


class DashboardFeedbackPreloadTests(unittest.TestCase):
    setUpClass = classmethod(fixture_module.DashboardSavedProposalTests.setUpClass.__func__)
    tearDownClass = classmethod(fixture_module.DashboardSavedProposalTests.tearDownClass.__func__)
    setUp = fixture_module.DashboardSavedProposalTests.setUp
    tearDown = fixture_module.DashboardSavedProposalTests.tearDown
    configure = fixture_module.DashboardSavedProposalTests.configure
    save = fixture_module.DashboardSavedProposalTests.save
    recommendations = staticmethod(fixture_module.DashboardSavedProposalTests.recommendations)

    def vehicle_in(self, company, office, label, *, deleted=False):
        v = self.m.Vehicle(company_code=company, office=office, chassis_number=label, deleted=deleted)
        self.m.db.session.add(v)
        self.m.db.session.flush()
        return v

    def feedback(self, vehicle, item, status, *, revision=None, snapshot="{}", company=None):
        key, current_revision = vehicle_analysis_proposal_ids(item)
        row = self.m.VehicleAnalysisFeedback(
            company_code=vehicle.company_code if company is None else company,
            vehicle_record_id=vehicle.id, proposal_key=key,
            proposal_revision=revision if revision is not None else current_revision,
            status=status, snapshot_json=snapshot,
            created_by="another_team_member", created_at="2026-11-18 10:00",
        )
        self.m.db.session.add(row)

    def assert_scope(self, groups, *, public=False):
        my = groups["mine"]
        office = groups["office"]
        my_status = {row["title"]:row["feedback_status"] for row in my["items"]}
        office_status = {row["title"]:row["feedback_status"] for row in office["items"]}
        self.assertEqual(my_status, {} if public else {
            "保存済み候補02":"in_progress", "保存済み候補03":"completed",
            "保存済み候補04":"open", "保存済み候補05":"accepted", "保存済み候補06":"open",
        })
        if public:
            # Same status of proposal keys on the actor's assigned vehicle is
            # visible in the established office group, not treated as "own".
            self.assertIn("保存済み候補05",office_status)
        self.assertEqual(office_status["保存済み候補00"],"open")
        self.assertEqual(office_status["営業所だけ"],"dismissed")
        self.assertTrue(all("非表示" not in row["title"] for group in groups.values() for row in group["items"]))

    def seed_mixed(self):
        admin = self.configure()
        own = self.vehicle
        outside = self.vehicle_in("TEST","別営業所","OUT")
        office = self.vehicle_in("TEST", own.office, "OFFICE")
        missing = self.vehicle_in("TEST", own.office, "EMPTY")
        deleted = self.vehicle_in("TEST", own.office, "DELETED", deleted=True)
        foreign = self.vehicle_in("OTHER", own.office, "FOREIGN")
        items = self.recommendations(7)
        outsider_item = dict(items[0], title="非表示・別営業所", target="別営業所")
        private_item = dict(items[0], title="非表示・他社", target="他社")
        deleted_item = dict(items[0], title="非表示・削除済み", target="削除済み")
        office_item = dict(items[2], title="営業所だけ", target="共通営業所")
        own_state = self.save(own, items, status="running")
        office_state = self.save(office, [items[0],office_item], status="error")
        office_result = json.loads(office_state.result_json)
        office_result["analysis_method"]="record_check"
        office_state.result_json=json.dumps(office_result)
        own_saved_before=own_state.result_json
        self.save(outside,[outsider_item])
        self.save(foreign,[private_item])
        self.save(deleted,[deleted_item])
        bad = self.save(missing,[])
        bad.result_json="legacy invalid JSON"
        self.feedback(own,items[0],"completed")
        self.feedback(own,items[1],"dismissed")
        self.feedback(own,items[2],"completed")
        self.feedback(own,items[2],"in_progress")  # higher ID wins
        self.feedback(own,items[3],"completed",revision="old")
        self.feedback(own,items[4],"completed")
        self.feedback(own,items[4],"dismissed",snapshot='{"source_withdrawn":true}')
        self.feedback(own,items[5],"accepted",snapshot="legacy invalid JSON")
        self.feedback(own,items[6],"completed",company="OTHER")  # inconsistent legacy row
        self.feedback(office,office_item,"dismissed",revision="old")
        for vehicle in [outside, foreign, deleted, missing]:
            self.feedback(vehicle,items[6],"completed")
        opposite = self.m.User(company_code="TEST",username="observer",role="user",office=own.office,
                               password="unused",last_name="架空", first_name="閲覧者",
                               password_changed_at=admin.password_changed_at)
        self.m.db.session.add(opposite)
        self.m.db.session.commit()
        return own,office,opposite,own_state,own_saved_before

    def request(self, url):
        meter=Counter()
        selects=[]
        def count(_, __, statement, parameters, *___):
            upper=statement.upper().lstrip()
            verb=upper.split(maxsplit=1)[0]
            meter[verb] += 1
            if verb=="SELECT" and "VEHICLE_ANALYSIS_FEEDBACK" in upper:
                meter["feedback_select"] += 1
                selects.append(parameters)
        m=self.m
        event.listen(m.db.engine,"before_cursor_execute",count)
        try:
            if url is None:
                with m.app.test_request_context():
                    result=dashboard.get_dashboard_vehicle_attention("TEST","試験営業所",[self.vehicle.id])
            else:
                from flask import template_rendered
                contexts=[]
                def read(_,template,context,**kwargs):
                    contexts.append(context["dashboard_vehicle_attention"])
                with template_rendered.connected_to(read,m.app):
                    with self.client.get(url) as response:
                        self.assertEqual(response.status_code,200)
                result=contexts[-1]
        finally:
            event.remove(m.db.engine,"before_cursor_execute",count)
        return result,meter,selects

    def test_mixed_active_revisions_scope_and_assigned_vs_office_groups(self):
        own,office,opposite,state,before=self.seed_mixed()
        groups,meter,selects=self.request("/")
        self.assert_scope(groups)
        self.assertEqual(meter["feedback_select"],1)
        self.assertEqual(selects,[("TEST","TEST",own.id,office.id)])
        self.assertEqual([groups["mine"][k] for k in ("vehicles","missing","updating","errors","insufficient")],
                         [1,0,1,0,0])
        self.assertEqual([groups["office"][k] for k in ("vehicles","missing","updating","errors","insufficient")],
                         [2,1,0,1,1])
        with self.client.session_transaction() as session:
            session.update(username=opposite.username,role="user",
                account_identity=identity_for("TEST",opposite.username,app=self.m.app))
        regular,meter,_=self.request("/")
        self.assert_scope(regular,public=True)
        self.assertEqual(regular["office"]["vehicles"],3)
        self.assertEqual(meter["feedback_select"],1)
        self.assertEqual(state.result_json,before)

    def test_missing_empty_and_non_dict_items_never_query_feedback(self):
        self.configure()
        empty=self.vehicle_in("TEST",self.vehicle.office,"EMPTY")
        malformed=self.vehicle_in("TEST",self.vehicle.office,"MALFORMED")
        self.save(empty,[])
        self.save(malformed,[False,"retired",None])
        groups,meter,_=self.request(None)
        self.assertEqual(meter["feedback_select"],0)
        self.assertEqual(len(groups["mine"]["items"])+len(groups["office"]["items"]),0)
        self.assertEqual((groups["mine"]["missing"],groups["office"]["missing"]),(1,0))
        self.assertEqual(sum(meter[k] for k in ["INSERT","UPDATE","DELETE"]),0)

    def test_next_request_observes_new_feedback_without_persisting_a_cache(self):
        self.configure()
        original = self.recommendations(1)[0]
        self.save(self.vehicle, [original])
        self.assertEqual(self.request("/")[0]["mine"]["items"][0]["feedback_status"], "open")
        self.feedback(self.vehicle,original,"completed")
        self.m.db.session.commit()
        self.assertEqual(self.request("/")[0]["mine"]["items"], [])

    def test_feedback_chunks_keep_latest_key_per_company_and_vehicle(self):
        self.configure()
        vehicles=[self.vehicle]
        for i in range(400):
            vehicles.append(self.vehicle_in("TEST", self.vehicle.office, f"T-{i}"))
        first,last=vehicles[0],vehicles[-1]
        item=self.recommendations(1)[0]
        self.feedback(first,item,"accepted")
        self.feedback(last,item,"in_progress")
        self.feedback(last,item,"open",company="OTHER")
        self.m.db.session.commit()
        count=0
        def tracker(_, __, statement, *___):
            nonlocal count
            if "VEHICLE_ANALYSIS_FEEDBACK" in statement.upper():
                count+=1
        event.listen(self.m.db.engine,"before_cursor_execute",tracker)
        try:
            rows=dashboard._dashboard_latest_vehicle_feedback("TEST",[v.id for v in vehicles]+[first.id])
        finally:
            event.remove(self.m.db.engine,"before_cursor_execute",tracker)
        key,_=vehicle_analysis_proposal_ids(item)
        self.assertEqual(count,2)
        self.assertEqual({v:proposals[key].status for v,proposals in rows.items()},
                         {first.id:"accepted",last.id:"in_progress"})
