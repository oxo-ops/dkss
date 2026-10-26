"""Dashboard output contracts and scoped batch reads using an isolated database."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import unittest
from sqlalchemy import event
import test_workflow_regressions as workflow
from dkss_app import dashboard as module
from dkss_app.dashboard_scoring import DashboardScoring


class FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 26, 12, tzinfo=tz)


class DashboardServiceTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = workflow.WorkflowRegressionTests.setUp
    tearDown = workflow.WorkflowRegressionTests.tearDown

    def seed(self, extra=0):
        m = self.m
        self.vehicle.office = "Tokyo"
        self.vehicle.plate_number = "1111"
        self.vehicle.inspection_expiry = "2026-11-01"
        others = [
            m.Vehicle(
                company_code=c,
                chassis_number="fixture-" + str(i),
                office=o,
                deleted=deleted,
                plate_number=str(2000 + i),
            )
            for i, (c, o, deleted) in enumerate(
                [("TEST", "Osaka", False), ("TEST", "Tokyo", True), ("OTHER", "Tokyo", False)]
            )
        ]
        m.db.session.add_all(others)
        m.db.session.flush()
        self.other_office, self.deleted, self.foreign = others
        self.user = m.User.query.filter_by(company_code="TEST", username="admin").one()
        self.user.office = "Tokyo"
        # The saved preference must not override the actual office assignment.
        self.user.dashboard_settings_json = json.dumps({"office": "Osaka", "period": "30d"})
        m.db.session.add_all(
            [m.Office(company_code="TEST", name=name) for name in ["Tokyo", "Osaka"]]
        )
        m.db.session.add(
            m.Driver(
                company_code="TEST",
                employee_id="admin",
                name="本人",
                office="Tokyo",
                safe_start_date="2026-01-01",
                vehicles_json=json.dumps(
                    [
                        str(self.vehicle.id),
                        str(self.other_office.id),
                        str(self.deleted.id),
                        str(self.foreign.id),
                    ]
                ),
            )
        )
        m.db.session.add(
            m.Driver(
                company_code="OTHER",
                employee_id="foreign",
                name="FOREIGN",
                office="Tokyo",
                safe_start_date="2020-01-01",
            )
        )
        item = {
            "item_type": "check",
            "input_type": "select",
            "category": " 安全 ",
            "content": "ブレーキ",
            "choices": ["○", "△", "×"],
            "score_enabled": True,
        }
        self.items = [item, dict(item, content="灯火", category="装置")]
        self.vehicle_check = m.Checklist(
            company_code="TEST",
            name="日常点検",
            target="車両管理",
            frequency_unit="day",
            frequency_value="1",
            display_type="month",
            items_json=json.dumps(self.items),
        )
        self.safety_check = m.Checklist(
            company_code="TEST",
            name="安全",
            target="安全管理",
            frequency_unit="month",
            frequency_value="1",
            items_json=json.dumps(self.items),
        )
        foreign_check = m.Checklist(
            company_code="OTHER",
            name="FOREIGN",
            target="車両管理",
            items_json=json.dumps(self.items),
        )
        m.db.session.add_all([self.vehicle_check, self.safety_check, foreign_check])
        m.db.session.flush()
        snapshot = json.dumps({"items": [dict(item, content="旧点検", choices=["4", "2", "0"])]})
        for index, vehicle in enumerate(
            [self.vehicle, self.vehicle, self.other_office, self.deleted, self.foreign]
        ):
            m.db.session.add(
                m.VehicleChecklistResult(
                    company_code=vehicle.company_code,
                    checklist_id=self.vehicle_check.id,
                    vehicle_record_id=vehicle.id,
                    checked_date="2026-10-" + str(10 + index),
                    year="2026",
                    month="10",
                    day=str(10 + index),
                    answers_json=json.dumps([{"value": str(index % 3)}, {"value": "△"}]),
                    checklist_snapshot_json=snapshot if index == 0 else "",
                )
            )
        for i, (kind, username, office, vehicle_id) in enumerate(
            [
                ("user", "admin", "Tokyo", None),
                ("user", "peer", "Tokyo", None),
                ("office", None, "Tokyo", None),
                ("vehicle", None, "Tokyo", self.vehicle.id),
                ("user", "admin", "Osaka", None),
                ("vehicle", None, "Tokyo", self.foreign.id),
            ]
        ):
            m.db.session.add(
                m.ChecklistResult(
                    company_code="TEST",
                    checklist_id=self.safety_check.id,
                    target_type=kind,
                    target_username=username,
                    target_user=username,
                    target_office=office,
                    target_vehicle_record_id=vehicle_id,
                    checked_date="2026-10-15",
                    answers_json=json.dumps([{"value": "×"}, {"value": "○"}]),
                )
            )
        for i in range(extra):
            m.db.session.add(
                m.VehicleChecklistResult(
                    company_code="TEST",
                    checklist_id=self.vehicle_check.id,
                    vehicle_record_id=self.vehicle.id,
                    checked_date="2026-10-20",
                    year="2026",
                    month="10",
                    day="20",
                    answers_json=json.dumps([{"value": "○"}, {"value": "×"}]),
                )
            )
        m.db.session.commit()

    def capture(self, handler=None, *, role="admin", office="Tokyo", period="30d", driver=True):
        self.user.role = role
        self.user.office = office
        self.user.dashboard_settings_json = json.dumps({"office": "Osaka", "period": period})
        if not driver:
            self.m.Driver.query.filter_by(company_code="TEST", employee_id="admin").delete()
        self.m.db.session.commit()
        queries = []

        def record(conn, cursor, statement, parameters, context, many):
            if statement.lstrip().upper().startswith("SELECT"):
                queries.append(statement)

        engine = self.m.db.engine
        with self.m.app.test_request_context("/"):
            self.m.session.update(company_code="TEST", username="admin", role=role, name="本人")
            event.listen(engine, "before_cursor_execute", record)
            try:
                with patch.object(module._dkss_common, "datetime", FixedClock), patch.object(
                    module._dkss_common, "render_template", side_effect=lambda template, **kw: kw
                ):
                    context = (handler or module.dashboard)()
            finally:
                event.remove(engine, "before_cursor_execute", record)

        def encode(value):
            if hasattr(value, "__table__"):
                return {
                    "model": type(value).__name__,
                    "id": value.id,
                    "company_code": value.company_code,
                }
            raise TypeError(type(value).__name__)

        # The cost helper is unchanged and uses the actual local month.
        context.pop("dashboard_office_trend")
        return json.loads(json.dumps(context, default=encode, sort_keys=True)), queries

    def test_recorded_outputs_match_pre_refactor_contract(self):
        self.seed()
        expected = json.loads(
            (Path(__file__).parent / "fixtures/dashboard_context.json").read_text()
        )
        for name, args in [
            ("admin", {}),
            ("user", {"role": "user"}),
            ("itc", {"role": "itc"}),
            ("missing_office", {"office": ""}),
            ("other_office", {"office": "Osaka"}),
            ("short_period", {"period": "7d"}),
            ("invalid_period", {"period": "invalid"}),
        ]:
            with self.subTest(name=name):
                context, _ = self.capture(**args)
                self.assertEqual(context, expected[name])

    def test_company_office_and_assignment_scopes_remain_distinct(self):
        self.seed()
        context, _ = self.capture(role="user")
        self.assertEqual(context["dashboard_scope_office"], "Tokyo")
        self.assertNotIn("FOREIGN", json.dumps(context))
        self.assertEqual(
            [r["id"] for r in context["my_vehicles"]], [self.vehicle.id, self.other_office.id]
        )
        self.assertTrue(context["my_vehicle_analysis"][str(self.other_office.id)]["result_count"])
        summary = next(r for r in context["checklist_score_summaries"] if r["name"] == "安全")
        self.assertFalse(any(r["target_type"] == "user" for r in summary["target_analysis"]))

    def test_vehicle_lookups_do_not_grow_with_result_count(self):
        self.seed()
        _, before = self.capture()
        m = self.m
        for i in range(80):
            m.db.session.add(
                m.VehicleChecklistResult(
                    company_code="TEST",
                    checklist_id=self.vehicle_check.id,
                    vehicle_record_id=self.vehicle.id,
                    checked_date="2026-10-20",
                    year="2026",
                    month="10",
                    day="20",
                    answers_json='[{"value":"○"},{"value":"×"}]',
                )
            )
        m.db.session.commit()
        _, after = self.capture()

        def vehicle_queries(rows):
            return [q for q in rows if "FROM vehicle " in q or "FROM vehicle\n" in q]

        self.assertEqual(len(vehicle_queries(after)), len(vehicle_queries(before)))

    def test_missing_driver_and_next_request_updates_are_visible(self):
        self.seed()
        first, _ = self.capture()
        self.vehicle.plate_number = "CHANGED"
        self.m.db.session.commit()
        second, _ = self.capture()
        self.assertNotEqual(first["my_checklist_summaries"], second["my_checklist_summaries"])
        missing, _ = self.capture(driver=False)
        self.assertEqual(missing["my_vehicles"], [])
        self.assertIsNone(missing["my_safe_days"])


class DashboardScoreTests(unittest.TestCase):
    def test_symbols_and_missing_choices_keep_existing_scoring(self):
        scoring = DashboardScoring()
        self.assertEqual(
            [scoring.score_value(v) for v in ["○", "✓", "△", "×", " 3.5 ", None, "未回答"]],
            [2, 2, 1, 0, 3.5, None, None],
        )
