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

    def test_pointouts_page_size_matches_rendered_records(self):
        from flask import template_rendered

        m = self.m
        for number in range(24):
            m.db.session.add(m.PatrolResult(
                company_code="TEST", created_by_username="admin",
                target_type="user", target_username="admin",
                category="Good", content="Pagination " + str(number),
            ))
        m.db.session.commit()
        contexts = []

        def capture(sender, template, context, **extra):
            contexts.append(context)

        with template_rendered.connected_to(capture, m.app):
            for size in (5, 8, 10, 20, 50):
                with self.subTest(size=size):
                    response = self.client.get("/pointouts?page_size=" + str(size))
                    self.assertEqual(response.status_code, 200)
                    context = contexts[-1]
                    self.assertEqual(context["page_size"], size)
                    self.assertEqual(len(context["patrol_results"]), min(size, 24))
                    self.assertEqual(context["total_pages"], (24 + size - 1) // size)
            response = self.client.get("/pointouts?page_size=5&page=2")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(contexts[-1]["page"], 2)
            self.assertEqual(len(contexts[-1]["patrol_results"]), 5)

    def test_old_certificate_bookmark_uses_current_workflow(self):
        response = self.client.get("/master/vehicles/certificate")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location,
                         "/master/vehicles/register#registration-certificate-title")
        page = self.client.get(response.location)
        self.assertEqual(page.status_code, 200)
        text = page.get_data(as_text=True)
        self.assertIn('id="registration-choice-grid"', text)
        self.assertIn('id="certificate-review-shell"', text)
        self.assertEqual(self.m.Vehicle.query.count(), 1)

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

    def upload_inspection(self, streaming=False, data=None, source=None):
        from io import BytesIO
        from test_inspection_document_ai import extraction, pdf_bytes
        source = source or pdf_bytes()
        with patch.object(self.m, "extract_inspection_documents", return_value=data or extraction(source)):
            response = self.client.post("/vehicle/data-import" + ("/progress" if streaming else ""), data={
                "document_type": "inspection", "document_files": (BytesIO(source), "inspection.pdf"),
            })
            response.get_data()  # consume streaming response while patch is active
        return response

    def inspection_form(self, draft, vehicle=True):
        row = json.loads(draft.preview_json)["records"][0]
        key = draft.id + "_0"
        return {"include": key, "vehicle_" + key: str(self.vehicle.id) if vehicle else "",
                "date_" + key: row.get("record_date") or "", "inspection_type_" + key: row.get("inspection_type") or "",
                "mileage_" + key: row.get("mileage") or "", "content_" + key: row.get("content") or ""}

    def test_inspection_import_full_path_and_reupload_guard(self):
        m = self.m
        self.assertEqual(self.upload_inspection().status_code, 302)
        draft = m.VehicleDocumentImportDraft.query.one()
        preview = self.client.get(f"/vehicle/data-import/{draft.batch_id}/preview")
        self.assertEqual(preview.status_code, 200)
        text = preview.get_data(as_text=True)
        self.assertIn('data-document-type="inspection"', text)
        self.assertIn('data-invoice-source', text)
        self.assertIn('点検項目', text)
        self.assertNotIn('請求総額', text)
        form = self.inspection_form(draft)
        key = draft.id + "_0"
        form["inspection_item_" + key + "_0_raw_result"] = "△"
        form["inspection_company_" + key] = "修正後工場"
        form["next_inspection_date_" + key] = "2027-01-21"
        form["mileage_" + key] = "100,001.25"
        response = self.client.post(f"/vehicle/data-import/{draft.batch_id}/confirm", data=form)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/inspections', response.location)
        record = m.VehiclePeriodicInspectionRecord.query.one()
        self.assertEqual(str(record.mileage), "100001.25")
        self.assertEqual(record.inspection_company, "修正後工場")
        self.assertEqual(record.inspector_name, "点検者")
        self.assertIsNone(record.completion_date)
        self.assertEqual(record.next_inspection_date, "2027-01-21")
        details = json.loads(record.details_json)
        self.assertEqual(details["inspection_items"][0]["raw_result"], "△")
        self.assertEqual(json.loads(draft.preview_json)["original_records"][0]["inspection_items"][0]["raw_result"], "○")
        self.assertEqual(m.VehicleMaintenanceRecord.query.count(), 0)
        self.assertEqual(m.VehiclePartReplacement.query.count(), 0)
        history = self.client.get(response.location)
        self.assertEqual(history.status_code, 200)
        self.assertIn("ブレーキの効き", history.get_data(as_text=True))
        source = self.client.get(f"/vehicle/periodic-inspections/{record.id}/source")
        self.assertEqual(source.data, draft.source_file)
        self.assertIn("no-store", source.headers["Cache-Control"])
        self.assertEqual(self.client.post(f"/vehicle/data-import/{draft.batch_id}/confirm", data=form).status_code, 409)
        self.upload_inspection()
        again = m.VehicleDocumentImportDraft.query.filter_by(status="preview").one()
        self.assertEqual(self.client.post(f"/vehicle/data-import/{again.batch_id}/confirm", data=self.inspection_form(again)).status_code, 400)
        self.assertEqual(m.VehiclePeriodicInspectionRecord.query.count(), 1)

    def test_inspection_stream_progress_and_partial_failure(self):
        from io import BytesIO
        from test_inspection_document_ai import pdf_bytes, extraction
        source = pdf_bytes()
        with patch.object(self.m, "extract_inspection_documents", side_effect=[extraction(source), ValueError("NO_INSPECTION_FOUND")]):
            response = self.client.post("/vehicle/data-import/progress", data={"document_type": "inspection", "document_files": [
                (BytesIO(source), "good.pdf"), (BytesIO(source), "bad.pdf")]})
            events = [json.loads(line) for line in response.data.decode().splitlines()]
        self.assertEqual(events[-1]["phase"], "complete")
        draft = self.m.VehicleDocumentImportDraft.query.one()
        self.assertEqual(json.loads(draft.preview_json)["import_failures"][0]["filename"], "bad.pdf")
        self.assertIn("点検表", self.client.get(events[-1]["redirect_url"]).get_data(as_text=True))

    def test_inspection_all_failed_does_not_save_empty_records(self):
        from io import BytesIO
        from test_inspection_document_ai import pdf_bytes
        for streaming in (False, True):
            with patch.object(self.m, "extract_inspection_documents", side_effect=RuntimeError("OPENAI_NETWORK_OR_TIMEOUT")):
                response = self.client.post("/vehicle/data-import" + ("/progress" if streaming else ""), data={
                    "document_type": "inspection", "document_files": (BytesIO(pdf_bytes()), "retry.pdf")}, headers={"X-DKSS-Final-Submit": "1"})
                raw = response.get_data(as_text=True)
            raw = raw if streaming else json.dumps(response.get_json(), ensure_ascii=False)
            self.assertIn("時間切れ", raw)
            self.assertEqual(self.m.VehicleDocumentImportDraft.query.count(), 0)
        self.assertEqual(self.upload_inspection().status_code, 302)

    def test_inspection_company_owner_and_role_boundaries(self):
        self.upload_inspection()
        m = self.m; draft = m.VehicleDocumentImportDraft.query.one()
        form = self.inspection_form(draft)
        m.db.session.add(m.Company(company_code="OTHER", company_name="Other", active=True))
        foreign = m.Vehicle(company_code="OTHER", chassis_number="FOREIGN")
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for company, user in [("TEST", "other-admin"), ("OTHER", "admin")]:
            m.db.session.add(m.User(company_code=company, username=user, role="admin", password="unused", last_name="検証", first_name="管理者", password_changed_at=stamp))
        m.db.session.add(foreign); m.db.session.commit()
        form["vehicle_" + draft.id + "_0"] = str(foreign.id)
        self.assertEqual(self.client.post(f"/vehicle/data-import/{draft.batch_id}/confirm", data=form).status_code, 400)
        with patch.object(m, "require_master_admin", return_value=True):
            for field, value in [("username", "other-admin"), ("company_code", "OTHER")]:
                with self.client.session_transaction() as session:
                    saved = session[field]; session[field] = value
                for url in [f"/vehicle/data-import/{draft.batch_id}/preview", f"/vehicle/data-import/files/{draft.id}"]:
                    self.assertEqual(self.client.get(url).status_code, 404)
                with self.client.session_transaction() as session: session[field] = saved
        with patch.object(m, "require_master_admin", return_value=False):
            self.assertEqual(self.client.post(f"/vehicle/data-import/{draft.batch_id}/confirm", data=form).status_code, 403)
        self.assertEqual(m.VehiclePeriodicInspectionRecord.query.count(), 0)

    def test_inspection_failed_save_rolls_back_and_keeps_edits(self):
        self.upload_inspection()
        m = self.m; draft = m.VehicleDocumentImportDraft.query.one()
        form = self.inspection_form(draft)
        with patch.object(m, "build_vehicle_document_record", side_effect=ValueError("forced failure")):
            response = self.client.post(f"/vehicle/data-import/{draft.batch_id}/confirm", data=form)
        self.assertEqual(response.status_code, 500)
        m.db.session.expire_all()
        self.assertEqual(draft.status, "preview")
        self.assertEqual(m.VehiclePeriodicInspectionRecord.query.count(), 0)
        self.assertEqual(self.client.post(f"/vehicle/data-import/{draft.batch_id}/confirm", data=form).status_code, 302)
        self.assertEqual(m.VehiclePeriodicInspectionRecord.query.count(), 1)

    def test_inspection_validation_keeps_edits_and_original(self):
        self.upload_inspection()
        draft = self.m.VehicleDocumentImportDraft.query.one()
        form = self.inspection_form(draft)
        key = draft.id + "_0"
        form["date_" + key] = "2026-02-30"
        form["content_" + key] = '<script>alert("x")</script>'
        response = self.client.post(f"/vehicle/data-import/{draft.batch_id}/confirm", data=form)
        self.assertEqual(response.status_code, 400)
        stored = json.loads(draft.preview_json)
        self.assertEqual(stored["records"][0]["record_date"], "2026-02-30")
        self.assertEqual(stored["original_records"][0]["record_date"], "2026-10-21")
        text = self.client.get(f"/vehicle/data-import/{draft.batch_id}/preview").get_data(as_text=True)
        self.assertNotIn('<script>alert("x")</script>', text)
        self.assertIn('&lt;script&gt;', text)

    def test_inspection_pending_then_assign_without_reupload(self):
        self.upload_inspection()
        m = self.m; draft = m.VehicleDocumentImportDraft.query.one()
        response = self.client.post(f"/vehicle/data-import/{draft.batch_id}/confirm", data=self.inspection_form(draft, vehicle=False))
        self.assertEqual(response.status_code, 302)
        item = m.VehicleImportPendingRecord.query.one()
        self.assertEqual(item.source_kind, "inspection")
        self.assertEqual(m.VehiclePeriodicInspectionRecord.query.count(), 0)
        with m.app.test_request_context():
            from flask import session
            session.update(company_code="TEST", username="admin", role="admin")
            m.apply_vehicle_import_pending_documents(item.pending_id, self.vehicle.id, "TEST", "admin")
            m.db.session.commit()
        self.assertEqual(m.VehiclePeriodicInspectionRecord.query.count(), 1)
        self.assertEqual(m.VehiclePeriodicInspectionRecord.query.one().source_draft_id, draft.id)

    def test_inspection_multiple_records_same_page_and_two_drafts(self):
        from test_inspection_document_ai import extraction
        import copy
        data = extraction()
        row = copy.deepcopy(data["records"][0]); row["inspection_date"] = "2026-10-20"
        data["records"].append(row)
        self.upload_inspection(data=data)
        m = self.m; draft = m.VehicleDocumentImportDraft.query.one()
        form = self.inspection_form(draft)
        key = draft.id + "_1"
        form["include"] = [draft.id + "_0", key]
        form.update({"vehicle_" + key: str(self.vehicle.id), "date_" + key: "2026-10-20",
                     "inspection_type_" + key: "3month", "content_" + key: "点検"})
        self.assertEqual(self.client.post(f"/vehicle/data-import/{draft.batch_id}/confirm", data=form).status_code, 302)
        self.assertEqual(m.VehiclePeriodicInspectionRecord.query.count(), 2)

    def test_invoice_import_still_saves_cost_and_replacement(self):
        import hashlib
        from io import BytesIO
        import maintenance_invoice_ai as ai
        from test_inspection_document_ai import pdf_bytes
        source = pdf_bytes()
        row = {field: None for field in ai.record_properties}
        part = {field: None for field in ai.line_properties}
        part.update(category="部品", description="テストフィルター", quantity="1", parts_amount="2000",
                    source_page=1, replacement_action="replace", replacement_part_name="テストフィルター", replacement_category="消耗品")
        row.update(source_pages=[1], line_items=[part], fees=[], warnings=[], entry_date="2026-10-21",
                   chassis_number="TEST-001", total_cost="2200", parts_cost="2000", tax_amount="200", content="フィルター交換")
        data = {"schema_version": 1, "source_sha256": hashlib.sha256(source).hexdigest(), "records": [row], "warnings": []}
        with patch.object(self.m, "extract_maintenance_invoices", return_value=data):
            response = self.client.post("/vehicle/data-import", data={"document_type": "maintenance", "document_files": (BytesIO(source), "invoice.pdf")})
        self.assertEqual(response.status_code, 302)
        m = self.m; draft = m.VehicleDocumentImportDraft.query.one()
        self.assertEqual(self.client.get(response.location).status_code, 200)
        key = draft.id + "_0"
        form = {"include": key, "vehicle_" + key: str(self.vehicle.id), "date_" + key: "2026-10-21", "content_" + key: "フィルター交換"}
        response = self.client.post(f"/vehicle/data-import/{draft.batch_id}/confirm", data=form)
        self.assertEqual(response.status_code, 302)
        record = m.VehicleMaintenanceRecord.query.one()
        self.assertEqual(str(record.total_cost), "2200.00")
        self.assertEqual(m.VehiclePartReplacement.query.count(), 1)
        self.assertEqual(m.VehiclePeriodicInspectionRecord.query.count(), 0)

    def test_inspection_invalid_files_and_same_batch_duplicates(self):
        from io import BytesIO
        from test_inspection_document_ai import pdf_bytes, extraction
        for source, filename in [(b"", "empty.pdf"), (b"not a PDF", "fake.pdf"), (b"x", "bad.exe"),
                                 (b"%PDF-" + b"x" * (20*1024*1024), "large.pdf")]:
            with self.subTest(filename=filename):
                response = self.client.post("/vehicle/data-import", data={"document_type": "inspection", "document_files": (BytesIO(source), filename)})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.m.VehicleDocumentImportDraft.query.count(), 0)
        source = pdf_bytes()
        with patch.object(self.m, "extract_inspection_documents", return_value=extraction(source)):
            response = self.client.post("/vehicle/data-import", data={"document_type": "inspection", "document_files": [
                (BytesIO(source), "one.pdf"), (BytesIO(source), "copy.pdf")]})
        drafts = self.m.VehicleDocumentImportDraft.query.all()
        self.assertEqual(len(drafts), 2)
        form = self.inspection_form(drafts[0])
        second = self.inspection_form(drafts[1]); form.update(second)
        form["include"] = [draft.id + "_0" for draft in drafts]
        self.assertEqual(self.client.post(f"/vehicle/data-import/{drafts[0].batch_id}/confirm", data=form).status_code, 400)
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(), 0)

    def test_inspection_image_preview_uses_shared_pdf_converter(self):
        from io import BytesIO
        from PIL import Image
        from test_inspection_document_ai import extraction
        source = BytesIO(); Image.new("RGB", (100, 100), "white").save(source, format="PNG")
        source = source.getvalue()
        with patch.object(self.m, "extract_inspection_documents", return_value=extraction(source)):
            self.client.post("/vehicle/data-import", data={"document_type": "inspection", "document_files": (BytesIO(source), "scan.png")})
        draft = self.m.VehicleDocumentImportDraft.query.one()
        response = self.client.get(f"/vehicle/data-import/files/{draft.id}?preview=pdf")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.startswith(b"%PDF-"))
        self.assertEqual(draft.source_file, source)


    def test_imported_periodic_record_is_visible_in_history_header_and_inspection_view(self):
        self.upload_inspection()
        m = self.m; draft = m.VehicleDocumentImportDraft.query.one()
        form = self.inspection_form(draft)
        form['next_inspection_date_' + draft.id + '_0'] = '2027-01-21'
        self.assertEqual(self.client.post(f'/vehicle/data-import/{draft.batch_id}/confirm', data=form).status_code, 302)
        record = m.VehiclePeriodicInspectionRecord.query.one()
        response = self.client.get(f'/vehicle/karte/{self.vehicle.id}/inspections')
        text = response.get_data(as_text=True)
        self.assertIn(f'id="periodic-record-{record.id}"', text)
        self.assertIn('aria-current="page">すべての点検', text)
        self.assertIn('<h3>日常点検</h3>', text)
        self.assertIn('前回 2026-10-21', text)
        self.assertIn('2027-01-21', text)
        self.assertIn('100,000', text)
        daily = self.client.get(f'/vehicle/karte/{self.vehicle.id}/inspections?inspection_view=daily').get_data(as_text=True)
        self.assertIn('<h3>日常点検</h3>', daily)
        self.assertNotIn(f'id="periodic-record-{record.id}"', daily)
        history = self.client.get(f'/vehicle/karte/{self.vehicle.id}/history').get_data(as_text=True)
        self.assertIn('定期点検を実施', history)
        self.assertIn(f'/vehicle/periodic-inspections/{record.id}/source', history)
        self.assertIn('試験工場', history)
        self.assertIn('点検者', history)
        filtered = self.client.get(f'/vehicle/karte/{self.vehicle.id}/history?event_type=3か月点検&start_date=2026-10-21&end_date=2026-10-21').get_data(as_text=True)
        self.assertIn('定期点検を実施', filtered)
        excluded = self.client.get(f'/vehicle/karte/{self.vehicle.id}/history?start_date=2026-10-22').get_data(as_text=True)
        self.assertNotIn('定期点検を実施', excluded)
        documents = self.client.get(f'/vehicle/karte/{self.vehicle.id}/documents').get_data(as_text=True)
        self.assertIn('inspection.pdf', documents)

    def test_header_keeps_newer_meter_date_and_warns_about_distance_decrease(self):
        from test_inspection_document_ai import extraction
        data = extraction()
        data['records'][0].update(inspection_date='2026-09-12', mileage='351842')
        self.upload_inspection(data=data)
        m = self.m; draft = m.VehicleDocumentImportDraft.query.one()
        self.client.post(f'/vehicle/data-import/{draft.batch_id}/confirm', data=self.inspection_form(draft))
        m.db.session.add(m.VehicleOperationRecord(company_code='TEST', vehicle_record_id=self.vehicle.id,
            report_number='meter-evidence', operation_date='2026-09-16', arrival_meter='349867.05'))
        m.db.session.commit()
        text = self.client.get(f'/vehicle/karte/{self.vehicle.id}/inspections').get_data(as_text=True)
        self.assertIn('349,867.05', text)
        self.assertIn('前回 2026-09-12', text)
        self.assertIn('351,842', text)
        self.assertIn('過去の記録より距離が減少しています', text)
        self.assertIn('日付未登録', text)
        self.assertNotIn('2026-12-12', text)

    def test_periodic_header_uses_latest_same_company_inspection_without_calculating_next_date(self):
        self.upload_inspection()
        m = self.m; draft = m.VehicleDocumentImportDraft.query.one()
        self.client.post(f'/vehicle/data-import/{draft.batch_id}/confirm', data=self.inspection_form(draft))
        record = m.VehiclePeriodicInspectionRecord.query.one()
        record.next_inspection_date = '2027-01-21'
        m.db.session.add(m.VehiclePeriodicInspectionRecord(company_code='TEST', vehicle_record_id=self.vehicle.id,
            inspection_type='3month', inspection_date='2099-01-01', next_inspection_date='2099-04-01',
            details_json='{}', source_draft_id=draft.id, source_record_index=10, created_by_username='admin'))
        m.db.session.add(m.VehiclePeriodicInspectionRecord(company_code='OTHER', vehicle_record_id=self.vehicle.id,
            inspection_type='12month', inspection_date='2026-10-21', next_inspection_date='2027-10-21',
            details_json='{}', source_draft_id=draft.id, source_record_index=11, created_by_username='admin'))
        m.db.session.commit()
        got = m.get_vehicle_periodic_inspection_summary('TEST', self.vehicle.id)
        self.assertEqual(got['3month']['last_date'], '2026-10-21')
        self.assertEqual(got['3month']['next_date'], '2027-01-21')
        self.assertNotIn('12month', got)
        record.next_inspection_date = None; m.db.session.commit()
        self.assertIsNone(m.get_vehicle_periodic_inspection_summary('TEST', self.vehicle.id)['3month']['next_date'])



if __name__ == "__main__":
    unittest.main()
