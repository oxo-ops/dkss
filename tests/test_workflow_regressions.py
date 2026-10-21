"""Real Flask/DB regression tests; all writes use a temporary SQLite database."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch


class WorkflowRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="dkss-route-tests-")
        module_path = Path(__file__).resolve().parents[1] / "app.py"
        env = {
            "SECRET_KEY": "isolated-regression-test-key",
            "ITC_INITIAL_PASSWORD": "Isolated-Only-742!",
            "DATABASE_URL": "sqlite:///" + str(Path(cls.temp.name) / "test.db"),
            "MFA_ENABLED": "false", "RENDER": "", "OPENAI_API_KEY": "",
            "SMTP_HOST": "", "S3_BUCKET_NAME": "",
            "VAPID_PRIVATE_KEY": "", "VAPID_PUBLIC_KEY": "",
        }
        spec = importlib.util.spec_from_file_location("dkss_regression_app", module_path)
        cls.m = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.m
        with patch.dict(os.environ, env):
            spec.loader.exec_module(cls.m)
        cls.m.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        cls.m.limiter.enabled = False

    @classmethod
    def tearDownClass(cls):
        with cls.m.app.app_context():
            cls.m.db.session.remove()
            cls.m.db.engine.dispose()
        sys.modules.pop("dkss_regression_app", None)
        cls.temp.cleanup()

    def setUp(self):
        m = self.m
        self.ctx = m.app.app_context()
        self.ctx.push()
        m.db.drop_all()
        m.db.create_all()
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        m.db.session.add(m.Company(company_code="TEST", company_name="Test", vehicle_limit=10, active=True))
        m.db.session.add(m.User(company_code="TEST", username="admin", role="admin", password="unused", last_name="検証", first_name="管理者", password_changed_at=stamp))
        self.vehicle = m.Vehicle(company_code="TEST", chassis_number="TEST-001")
        m.db.session.add(self.vehicle)
        m.db.session.commit()
        self.client = m.app.test_client()
        with self.client.session_transaction() as session:
            session.update(company_code="TEST", username="admin", role="admin", password_changed_at=stamp)

    def tearDown(self):
        self.m.db.session.remove()
        self.ctx.pop()

    def test_empty_vehicle_report_is_validation_error(self):
        response = self.client.post("/vehicle-patrols/new", data={})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.m.VehiclePatrol.query.count(), 0)

    def test_invalid_report_category_is_not_saved(self):
        response = self.client.post("/vehicle-patrols/new", data={
            "vehicle_record_id": self.vehicle.id, "category": "invalid",
            "priority": "中", "status": "未対応",
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.m.VehiclePatrol.query.count(), 0)

    def test_invalid_report_edit_keeps_previous_values(self):
        row = self.m.VehiclePatrol(company_code="TEST", vehicle_record_id=self.vehicle.id, category="不具合", priority="中", status="未対応")
        self.m.db.session.add(row)
        self.m.db.session.commit()
        response = self.client.post(f"/vehicle-patrols/{row.id}/edit", data={
            "vehicle_record_id": self.vehicle.id, "category": "不具合",
            "priority": "中", "status": "invalid", "repair_person": "x" * 101,
        })
        self.assertEqual(response.status_code, 400)
        self.m.db.session.expire_all()
        self.assertEqual(row.status, "未対応")
        self.assertFalse(row.repair_person)

    def maintenance(self, linked=True, arrival=None):
        m = self.m
        row = m.VehicleMaintenanceRecord(company_code="TEST", vehicle_record_id=self.vehicle.id, content="整備", status="完了", entry_date=arrival, completion_date="2026-10-01")
        m.db.session.add(row)
        m.db.session.flush()
        if linked:
            checklist = m.Checklist(company_code="TEST", name="日常点検", target="車両管理", active=True, items_json="[]")
            m.db.session.add(checklist)
            m.db.session.flush()
            snapshot = {"items": [{"fixed_template_code": "daily_inspection_truck_trailer"}]}
            inspection = m.VehicleChecklistResult(company_code="TEST", checklist_id=checklist.id, vehicle_record_id=self.vehicle.id, year="2026", month="10", day="01", status="承認済み", answers_json="[]", checklist_snapshot_json=json.dumps(snapshot), operation_judgment_json=json.dumps({"version": 1, "status": "未判定", "defects": [{"defect_no": 1, "item_no": "0", "status": "解消"}]}))
            m.db.session.add(inspection)
            m.db.session.flush()
            m.db.session.add(m.VehicleMaintenanceInspectionLink(company_code="TEST", vehicle_record_id=self.vehicle.id, maintenance_record_id=row.id, inspection_result_id=inspection.id, defect_no=1))
        m.db.session.commit()
        data = {"content": "整備内容を訂正", "entry_date": "", "completion_date": "2026-10-01", "record_version": m.vehicle_maintenance_record_version(row)}
        if linked:
            data["inspection_defect"] = f"{inspection.id}:1:1"
        return row, data

    def test_excel_save_returns_normal_result_navigation(self):
        self.m.db.session.add(self.m.VehicleType(company_code="TEST", name="トラック"))
        self.m.db.session.add(self.m.Office(company_code="TEST", name="本社"))
        self.m.db.session.commit()
        data = {
            "vehicle_type_code": "1", "vehicle_type": "トラック",
            "plate_area": "品川", "plate_class": "100", "plate_kana": "す",
            "plate_number": "7001", "gross_vehicle_weight": "7995",
            "chassis_number": "EXCEL-001", "model_code": "2KG-XZU720M",
            "first_registration_date": "2024-04", "inspection_expiry": "2027-04-15",
            "vehicle_name": "日野", "body_type": "キャブオーバ",
            "max_payload": "3000", "office": "本社", "active_status": "有効",
        }
        response = self.client.post("/master/vehicles/import/confirm", data=data,
                                    headers={"X-DKSS-Final-Submit": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["redirect_url"], "/master/vehicles/import?complete=1")
        result = self.client.get(response.json["redirect_url"])
        self.assertEqual(result.status_code, 200)
        self.assertIn("Excel一括登録が完了しました", result.get_data(as_text=True))
        self.assertEqual(self.client.get(response.json["redirect_url"]).status_code, 200)
        row = self.m.Vehicle.query.filter_by(chassis_number="EXCEL-001").one()
        self.assertEqual(row.first_registration_date, "2024-04")
        # Non-JavaScript submissions keep the existing HTML result response.
        response = self.client.post("/master/vehicles/import/confirm", data={
            **data, "chassis_number": "EXCEL-002", "plate_number": "7002",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("Excel一括登録が完了しました", response.get_data(as_text=True))

    def test_inspection_repair_can_be_edited_without_invented_arrival(self):
        row, data = self.maintenance()
        url = f"/vehicle/karte/{self.vehicle.id}/maintenance/{row.id}/edit"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        from html.parser import HTMLParser
        class ArrivalInput(HTMLParser):
            required = None
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "input" and attrs.get("name") == "entry_date":
                    self.required = "required" in attrs
        parser = ArrivalInput()
        parser.feed(response.get_data(as_text=True))
        self.assertIs(parser.required, False)
        self.assertEqual(self.client.post(url, data=data).status_code, 302)
        self.m.db.session.expire_all()
        self.assertIsNone(row.entry_date)
        self.assertEqual(row.content, "整備内容を訂正")

    def test_unlinked_record_still_requires_arrival(self):
        row, data = self.maintenance(linked=False)
        response = self.client.post(f"/vehicle/karte/{self.vehicle.id}/maintenance/{row.id}/edit", data=data)
        self.assertEqual(response.status_code, 400)

    def test_known_arrival_cannot_be_erased(self):
        row, data = self.maintenance(arrival="2026-10-01")
        response = self.client.post(f"/vehicle/karte/{self.vehicle.id}/maintenance/{row.id}/edit", data=data)
        self.assertEqual(response.status_code, 400)
        self.m.db.session.expire_all()
        self.assertEqual(row.entry_date, "2026-10-01")


if __name__ == "__main__":
    unittest.main()
