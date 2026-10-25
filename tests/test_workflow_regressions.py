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

    def test_operation_csv_module_keeps_shared_upload_error_and_names(self):
        import vehicle_operation_csv as parser
        from upload_validation import UploadValidationError
        self.assertIs(self.m.UploadValidationError, UploadValidationError)
        for name in ("normalize_vehicle_operation_plate", "parse_vehicle_operation_csv_row",
                     "read_vehicle_operation_csv", "parse_vehicle_operation_date",
                     "parse_vehicle_operation_decimal"):
            self.assertIs(getattr(self.m, name), getattr(parser, name))

    def test_invalid_operation_csv_returns_validation_error_without_saving(self):
        import io
        response = self.client.post("/vehicle/operation-import", data={
            "csv_file": (io.BytesIO("日報番号,運行日,車両,車両\n".encode()), "bad.csv"),
        }, headers={"X-DKSS-Validation-Only": "1"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json, {"errors": [
            {"field": "csv_file", "message": "CSVの項目名が重複しています。"},
        ]})
        self.assertEqual(self.m.VehicleOperationImportDraft.query.count(), 0)

    def test_overview_connects_maintenance_periodic_mileage_and_files(self):
        m = self.m
        m.db.session.add(m.VehicleMaintenanceRecord(
            company_code="TEST", vehicle_record_id=self.vehicle.id,
            entry_date="2026-09-01", completion_date="2026-09-01",
            content="概要整備接続", status="完了", mileage=10000, total_cost=12345,
        ))
        m.db.session.commit()
        self.upload_inspection()
        draft = m.VehicleDocumentImportDraft.query.one()
        self.client.post(f"/vehicle/data-import/{draft.batch_id}/confirm", data=self.inspection_form(draft))
        record = m.VehiclePeriodicInspectionRecord.query.one()
        record.content = "概要点検接続"
        record.mileage = 10100
        m.db.session.commit()
        text = self.client.get(f"/vehicle/karte/{self.vehicle.id}").get_data(as_text=True)
        for expected in ("概要整備接続", "概要点検接続", "12,345", "10,100", "inspection.pdf", "直近の履歴"):
            self.assertIn(expected, text)
        self.assertNotIn("未実装", text)
        with m.app.test_request_context('/'):
            context = m.get_vehicle_karte_overview_context(self.vehicle)
        document = next(item for item in context['karte_recent_documents'] if item['filename'] == 'inspection.pdf')
        self.assertEqual(document['date_kind'], '実施日')
        self.assertEqual(document['business_date'], record.inspection_date)
        self.assertIn(f'#periodic-record-{record.id}', document['related_url'])
        Path(self.temp.name, "overview.html").write_text(text, encoding="utf-8")

    def test_overview_note_save_escape_clear_and_conflict(self):
        url = f"/vehicle/karte/{self.vehicle.id}/note"
        self.assertEqual(self.client.post(url, data={"version":0,"content":"<script>alert(1)</script>"}).status_code, 302)
        text = self.client.get(f"/vehicle/karte/{self.vehicle.id}").get_data(as_text=True)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", text)
        self.assertEqual(self.client.post(url, data={"version":0,"content":"stale"}).status_code, 409)
        self.assertEqual(self.m.VehicleKarteNote.query.one().version, 1)
        self.assertEqual(self.client.post(url, data={"version":1,"content":""}).status_code, 302)
        self.assertEqual(self.m.VehicleKarteNote.query.one().content, "")
        self.assertEqual(self.client.post(url, data={"version":2,"content":"a"*10001}).status_code, 400)

    def test_overview_note_company_and_role_boundaries(self):
        m = self.m
        other = m.Vehicle(company_code="OTHER", chassis_number="OTHER-1")
        m.db.session.add(other); m.db.session.commit()
        self.assertEqual(self.client.post(f"/vehicle/karte/{other.id}/note", data={"version":0,"content":"no"}).status_code, 404)
        m.User.query.filter_by(company_code="TEST", username="admin").one().role = "user"
        m.db.session.commit()
        self.assertEqual(self.client.post(f"/vehicle/karte/{self.vehicle.id}/note", data={"version":0,"content":"no"}).status_code, 403)
        self.assertEqual(m.VehicleKarteNote.query.count(), 0)

    def test_overview_mileage_conflicts_are_gaps(self):
        m = self.m
        for value in (10000, 11000):
            m.db.session.add(m.VehicleMaintenanceRecord(
                company_code="TEST", vehicle_record_id=self.vehicle.id,
                entry_date="2026-09-01", mileage=value,
            ))
        m.db.session.commit()
        with m.app.test_request_context():
            context = m.get_vehicle_karte_overview_context(self.vehicle)
        self.assertEqual(context["karte_mileage_points"], [{"date":"2026-09-01", "mileage":None}])
        self.assertEqual(context["karte_mileage_reference"]["conflict_dates"], ["2026-09-01"])

    def test_vehicle_deletion_cleans_up_overview_note(self):
        m = self.m
        m.db.session.add(m.VehicleKarteNote(company_code="TEST", vehicle_record_id=self.vehicle.id, content="note"))
        m.db.session.commit()
        m.delete_vehicle_related_data(self.vehicle)
        m.db.session.delete(self.vehicle); m.db.session.commit()
        self.assertEqual(m.VehicleKarteNote.query.count(), 0)

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

    def mixed_pending_import(self):
        """Use original CSV/PDF bytes; only OCR is mocked by upload_inspection."""
        m = self.m
        from test_inspection_document_ai import extraction
        data = extraction()
        data["records"][0]["registration_number"] = "横浜100あ1234"
        self.upload_inspection(data=data)
        draft = m.VehicleDocumentImportDraft.query.one()
        self.assertEqual(self.client.post(
            f"/vehicle/data-import/{draft.batch_id}/confirm",
            data=self.inspection_form(draft, vehicle=False),
        ).status_code, 302)
        document = m.VehicleImportPendingRecord.query.one()
        pending_id = document.pending_id
        source = ("日報番号,運行日,車両コード,車両,入庫メータ,走行距離\n"
                  "MIXED-001,2026/10/21,DTG-001,横浜100あ1234,100020,20\n").encode("utf-8-sig")
        operation_draft = m.VehicleOperationImportDraft(
            id="mixed-csv", company_code="TEST", created_by_username="admin",
            source_filename="operations.csv", source_file=source, status="completed",
        )
        m.db.session.add(operation_draft)
        m.db.session.flush()
        row = m.read_vehicle_operation_csv(source)[0]
        values = m.parse_vehicle_operation_csv_row(row["source_row"], row["line_number"])
        item, _ = m.save_vehicle_import_pending_record(
            company_code="TEST", username="admin", source_kind="operation",
            source_draft_id=operation_draft.id, source_record_index=row["line_number"],
            group_identity={"source": "dtg7", "vehicle_code": "DTG-001", "plate": "横浜100あ1234"},
            identity={"source_vehicle_number": "横浜100あ1234", "source_vehicle_code": "DTG-001"},
            record_identity={"report_number": values["report_number"]},
            payload=values, record_date="2026-10-21",
        )
        self.assertEqual(item.pending_id, pending_id)
        m.db.session.commit()
        return pending_id, document, operation_draft

    def assert_mixed_import_pending(self, pending_id):
        m = self.m
        m.db.session.expire_all()
        self.assertEqual(m.VehicleImportPending.query.filter_by(id=pending_id).one().status, "pending")
        self.assertEqual(m.VehicleImportPendingRecord.query.filter_by(
            pending_id=pending_id, status="pending").count(), 2)
        self.assertEqual(m.VehicleOperationRecord.query.count(), 0)
        self.assertEqual(m.VehiclePeriodicInspectionRecord.query.count(), 0)
        self.assertEqual(m.VehicleOperationVehicleMapping.query.count(), 0)
        self.assertEqual(json.loads(m.VehicleOperationImportDraft.query.one().result_json), {})

    def test_mixed_pending_sources_apply_together_and_replay_is_not_duplicated(self):
        pending_id, document, operation_draft = self.mixed_pending_import()
        m = self.m
        form = {"vehicle_record_id": str(self.vehicle.id)}
        response = self.client.post(f"/master/vehicles/pending/{pending_id}", data=form)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, f"/vehicle/karte/{self.vehicle.id}")
        self.assertEqual(m.VehicleOperationRecord.query.one().vehicle_record_id, self.vehicle.id)
        inspection = m.VehiclePeriodicInspectionRecord.query.one()
        self.assertEqual(inspection.vehicle_record_id, self.vehicle.id)
        self.assertEqual(m.VehicleImportPendingRecord.query.filter_by(status="applied").count(), 2)
        pending = m.VehicleImportPending.query.one()
        self.assertEqual(pending.status, "resolved")
        self.assertEqual(pending.resolved_vehicle_id, self.vehicle.id)
        self.assertEqual(json.loads(operation_draft.result_json)["imported_vehicle_ids"], [self.vehicle.id])
        draft = m.VehicleDocumentImportDraft.query.one()
        self.assertEqual(json.loads(draft.result_json)["pending_count"], 0)
        self.assertEqual(self.client.get(f"/vehicle/periodic-inspections/{inspection.id}/source").data,
                         draft.source_file)
        self.assertEqual(self.client.get(f"/master/vehicles/pending/{pending_id}/sources/{operation_draft.id}").data,
                         operation_draft.source_file)
        self.assertEqual(self.client.post(f"/master/vehicles/pending/{pending_id}", data=form).status_code, 302)
        self.assertEqual(m.VehicleOperationRecord.query.count(), 1)
        self.assertEqual(m.VehiclePeriodicInspectionRecord.query.count(), 1)

    def test_mixed_pending_document_failure_rolls_back_csv_and_mapping_then_retries(self):
        pending_id, document, _ = self.mixed_pending_import()
        m = self.m
        draft = m.VehicleDocumentImportDraft.query.one()
        original = draft.source_sha256
        draft.source_sha256 = "invalid"
        m.db.session.commit()
        form = {"vehicle_record_id": str(self.vehicle.id)}
        self.assertEqual(self.client.post(f"/master/vehicles/pending/{pending_id}", data=form).status_code, 400)
        self.assert_mixed_import_pending(pending_id)
        draft.source_sha256 = original
        m.db.session.commit()
        self.assertEqual(self.client.post(f"/master/vehicles/pending/{pending_id}", data=form).status_code, 302)
        self.assertEqual(m.VehicleOperationRecord.query.count(), 1)
        self.assertEqual(m.VehiclePeriodicInspectionRecord.query.count(), 1)

    def test_mixed_pending_validation_only_rolls_back_every_source(self):
        pending_id, _, _ = self.mixed_pending_import()
        response = self.client.post(f"/master/vehicles/pending/{pending_id}",
            data={"vehicle_record_id": str(self.vehicle.id)},
            headers={"X-DKSS-Validation-Only": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        self.assert_mixed_import_pending(pending_id)

    def test_mixed_pending_rejects_foreign_vehicle_and_foreign_group(self):
        pending_id, _, _ = self.mixed_pending_import()
        m = self.m
        foreign = m.Vehicle(company_code="OTHER", chassis_number="OTHER-001")
        m.db.session.add(foreign)
        m.db.session.commit()
        self.assertEqual(self.client.post(f"/master/vehicles/pending/{pending_id}",
            data={"vehicle_record_id": str(foreign.id)}).status_code, 400)
        self.assert_mixed_import_pending(pending_id)
        pending = m.VehicleImportPending.query.one()
        pending.company_code = "OTHER"
        m.db.session.commit()
        self.assertEqual(self.client.post(f"/master/vehicles/pending/{pending_id}",
            data={"vehicle_record_id": str(self.vehicle.id)}).status_code, 404)
        self.assertEqual(m.VehicleOperationRecord.query.count(), 0)
        self.assertEqual(m.VehiclePeriodicInspectionRecord.query.count(), 0)

    def test_mixed_pending_new_vehicle_is_rolled_back_when_document_fails(self):
        pending_id, _, _ = self.mixed_pending_import()
        m = self.m
        pending = m.VehicleImportPending.query.one()
        pending.identity_json = json.dumps({"source_vehicle_number": "横浜100あ1234"})
        draft = m.VehicleDocumentImportDraft.query.one()
        draft.source_sha256 = "invalid"
        m.db.session.commit()
        self.assertEqual(self.client.post(f"/master/vehicles/pending/{pending_id}",
            data={"pending_action": "create"}).status_code, 400)
        self.assert_mixed_import_pending(pending_id)
        self.assertEqual(m.Vehicle.query.count(), 1)

    def test_mixed_pending_invoice_answer_applies_csv_and_preserves_existing_costs(self):
        import hashlib
        from flask import session
        from test_inspection_document_ai import pdf_bytes
        pending_id, _, _ = self.mixed_pending_import()
        m = self.m
        target = m.VehicleMaintenanceRecord(company_code="TEST", vehicle_record_id=self.vehicle.id,
            entry_date="2026-10-21", content="既存整備", total_cost="500")
        m.db.session.add(target)
        source = pdf_bytes(2)
        payload = {"vehicle_record_id": None, "record_date": "2026-10-21",
                   "content": "請求書", "total_cost": "2200", "line_items": [],
                   "registration_number": "横浜100あ1234", "chassis_number": "TEST-001"}
        draft = m.VehicleDocumentImportDraft(id="mixed-invoice", batch_id="invoice-batch",
            company_code="TEST", created_by_username="admin", document_type="maintenance",
            source_filename="invoice.pdf", source_file=source, source_sha256=hashlib.sha256(source).hexdigest(),
            preview_json=json.dumps({"records": [payload]}), status="completed")
        m.db.session.add(draft)
        m.db.session.flush()
        with m.app.test_request_context():
            session.update(company_code="TEST", username="admin", role="admin")
            invoice, _ = m.save_vehicle_document_pending_record(draft, 0, payload)
        self.assertEqual(invoice.pending_id, pending_id)
        m.db.session.commit()
        form = {"vehicle_record_id": str(self.vehicle.id)}
        url = f"/master/vehicles/pending/{pending_id}"
        response = self.client.post(url, data=form)
        self.assertEqual(response.status_code, 200)
        self.assertIn("この整備に対応する請求書ですか", response.get_data(as_text=True))
        self.assertEqual(m.VehicleOperationRecord.query.count(), 0)
        self.assertEqual(m.VehiclePeriodicInspectionRecord.query.count(), 0)
        form["invoice_choice_" + invoice.id] = f"maintenance:{target.id}"
        response = self.client.post(url, data=form)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(m.VehicleOperationRecord.query.count(), 1)
        self.assertEqual(m.VehiclePeriodicInspectionRecord.query.count(), 1)
        self.assertEqual(m.VehicleMaintenanceRecord.query.count(), 1)
        self.assertEqual(str(target.total_cost), "500.00")
        saved = m.VehicleMaintenanceDocument.query.one()
        self.assertEqual(saved.maintenance_record_id, target.id)
        self.assertEqual(saved.financial_status, "pending")
        self.assertEqual(saved.parts_status, "pending")
        self.assertEqual(m.VehiclePartReplacement.query.count(), 0)
        self.assertEqual(m.VehicleImportPendingRecord.query.filter_by(status="applied").count(), 3)

    def test_cross_source_grouping_rejects_conflicts_partial_plates_and_ambiguity(self):
        pending_id, _, _ = self.mixed_pending_import()
        m = self.m
        find = m.find_vehicle_pending_cross_source_group
        valid = {"source_vehicle_number": "横浜100あ1234", "chassis_number": "TEST-001"}
        self.assertEqual(find("TEST", "maintenance", valid).id, pending_id)
        for identity in (
            {**valid, "chassis_number": "DIFFERENT"},
            {**valid, "source_vehicle_code": "DIFFERENT"},
            {**valid, "source_vehicle_number": "1234"},
        ):
            self.assertIsNone(find("TEST", "maintenance", identity))
        self.assertIsNone(find("OTHER", "maintenance", valid))
        m.db.session.add(m.VehicleImportPending(id="ambiguous", company_code="TEST",
            match_key="ambiguous", identity_json=json.dumps(valid), created_by_username="admin"))
        m.db.session.flush()
        self.assertIsNone(find("TEST", "maintenance", valid))

    def test_mixed_pending_create_applies_all_records_to_one_new_vehicle(self):
        pending_id, _, _ = self.mixed_pending_import()
        m = self.m
        pending = m.VehicleImportPending.query.one()
        pending.identity_json = json.dumps({"source_vehicle_number": "横浜100あ1234"})
        m.db.session.commit()
        response = self.client.post(f"/master/vehicles/pending/{pending_id}",
            data={"pending_action": "create"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(m.Vehicle.query.count(), 2)
        new_id = m.VehicleImportPending.query.one().resolved_vehicle_id
        self.assertNotEqual(new_id, self.vehicle.id)
        self.assertEqual(m.VehicleOperationRecord.query.one().vehicle_record_id, new_id)
        self.assertEqual(m.VehiclePeriodicInspectionRecord.query.one().vehicle_record_id, new_id)

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
    def workflow_checklist(self, target="安全管理", approvals=None, content="確認"):
        items = [{"item_type": "check", "category": "点検", "content": content,
                  "input_type": "text", "answer_required": False}]
        for general in ([False, False] if approvals is None else approvals):
            items.append({"item_type": "approval", "approval_label": "確認",
                          "approval_allow_general": general})
        row = self.m.Checklist(company_code="TEST", name="業務確認", target=target,
            frequency_unit="day", display_type="month", active=True,
            items_json=json.dumps(items, ensure_ascii=False))
        self.m.db.session.add(row); self.m.db.session.commit()
        return row

    def safety_record(self, approvals=None, candidates=None):
        checklist = self.workflow_checklist(approvals=approvals)
        data = {"answer_0": "確認済み", **(candidates or {})}
        response = self.client.post(f"/safety/checklists/{checklist.id}/new", data=data)
        self.assertEqual(response.status_code, 302)
        return self.m.ChecklistResult.query.one(), data

    def safety_edit_token(self, record):
        import re
        page = self.client.get(f"/safety/checklist-results/{record.id}/edit")
        self.assertEqual(page.status_code, 200)
        return re.search(r'name="record_version" value="([a-f0-9]{64})"',
                         page.get_data(as_text=True)).group(1)

    def workflow_user_client(self):
        stamp = self.m.User.query.filter_by(username="admin").one().password_changed_at
        self.m.db.session.add(self.m.User(company_code="TEST", username="reviewer",
            role="user", password="unused", last_name="確認", first_name="担当",
            password_changed_at=stamp))
        self.m.db.session.commit()
        client = self.m.app.test_client()
        with client.session_transaction() as session:
            session.update(company_code="TEST", username="reviewer", role="user",
                           password_changed_at=stamp)
        return client

    def test_stale_safety_edit_cannot_erase_partial_approval_or_send_notices(self):
        row, data = self.safety_record(candidates={"approval_notify_users_0": "admin"})
        token = self.safety_edit_token(row)
        self.client.post(f"/safety/checklist-results/{row.id}/approve/0")
        self.m.db.session.refresh(row)
        before = row.approvals_json
        events, notices = self.m.ChecklistEvent.query.count(), self.m.Notification.query.count()
        response = self.client.post(f"/safety/checklist-results/{row.id}/edit",
            data={**data, "record_version": token}, headers={"X-DKSS-Final-Submit": "1"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("記録が更新", response.json["errors"][0]["message"])
        self.m.db.session.refresh(row)
        self.assertEqual(row.approvals_json, before)
        self.assertEqual(self.m.ChecklistEvent.query.count(), events)
        self.assertEqual(self.m.Notification.query.count(), notices)

    def test_identical_safety_edit_replay_is_rejected_even_with_same_timestamp(self):
        row, data = self.safety_record(candidates={"approval_notify_users_0": "admin"})
        token = self.safety_edit_token(row)
        payload = {**data, "record_version": token}
        url = f"/safety/checklist-results/{row.id}/edit"
        self.assertEqual(self.client.post(url, data=payload).status_code, 302)
        self.m.db.session.refresh(row)
        # The only new revision may be the event: checked_date has minute precision.
        events, notices = self.m.ChecklistEvent.query.count(), self.m.Notification.query.count()
        self.assertEqual(self.client.post(url, data=payload).status_code, 409)
        self.assertEqual(self.m.ChecklistEvent.query.count(), events)
        self.assertEqual(self.m.Notification.query.count(), notices)

    def test_fresh_safety_resubmission_still_resets_all_approval_slots(self):
        row, data = self.safety_record()
        self.client.post(f"/safety/checklist-results/{row.id}/approve/0")
        self.client.post(f"/safety/checklist-results/{row.id}/reject", data={"reject_reason": "再確認"})
        token = self.safety_edit_token(row)
        response = self.client.post(f"/safety/checklist-results/{row.id}/edit",
            data={**data, "answer_0": "訂正済み", "record_version": token})
        self.assertEqual(response.status_code, 302)
        self.m.db.session.refresh(row)
        self.assertEqual(row.status, "承認待ち")
        self.assertEqual(json.loads(row.answers_json)[0]["value"], "訂正済み")
        self.assertTrue(all(not slot["approved_by_username"] for slot in json.loads(row.approvals_json)))
        self.assertEqual(self.m.ChecklistEvent.query.filter_by(event_type="再申請").count(), 1)

    def test_safety_edit_requires_valid_revision_and_keeps_previous_answers(self):
        row, data = self.safety_record()
        before = row.answers_json
        for token in ("", "invalid", "日本語", "0" * 64):
            with self.subTest(token=token):
                response = self.client.post(f"/safety/checklist-results/{row.id}/edit",
                    data={**data, "answer_0": "変更", "record_version": token})
                self.assertEqual(response.status_code, 409)
                self.m.db.session.refresh(row)
                self.assertEqual(row.answers_json, before)

    def test_general_approver_can_read_result_excel_attachments_and_finished_result(self):
        client = self.workflow_user_client()
        row, _ = self.safety_record(approvals=[True], candidates={"approval_notify_users_0": "reviewer"})
        row.answers_json = json.dumps([{"item_no": 0, "value": "確認済み", "files": ["review-evidence.pdf"]}])
        self.m.db.session.commit()
        url = f"/safety/checklist-results/{row.id}"
        self.assertEqual(client.get(url).status_code, 200)
        self.assertEqual(client.get(url + "/excel").status_code, 200)
        with self.m.app.test_request_context("/"):
            self.m.session.update(company_code="TEST", username="reviewer", role="user")
            self.assertTrue(self.m.file_belongs_to_current_company("review-evidence.pdf", "uploads"))
        # Viewing/approving grants neither editing nor deletion.
        before = row.answers_json
        client.post(url + "/edit", data={"answer_0": "unauthorized"})
        client.post(url + "/delete")
        self.m.db.session.refresh(row); self.assertEqual(row.answers_json, before)
        self.assertEqual(client.post(url + "/approve/0").status_code, 302)
        self.m.db.session.refresh(row); self.assertEqual(row.status, "承認済み")
        self.assertEqual(client.get(url).status_code, 200)

    def test_general_approval_visibility_matches_current_slot_without_candidate_requirement(self):
        client = self.workflow_user_client()
        row, _ = self.safety_record(approvals=[False, True])
        url = f"/safety/checklist-results/{row.id}"
        self.assertEqual(client.get(url).status_code, 302)
        self.client.post(url + "/approve/0")
        self.assertEqual(client.get(url).status_code, 200)
        self.assertEqual(client.post(url + "/approve/1").status_code, 302)
        self.m.db.session.refresh(row); self.assertEqual(row.status, "承認済み")
        self.assertEqual(client.get(url).status_code, 200)

    def test_future_selected_general_approver_can_read_but_cannot_approve_out_of_order(self):
        client = self.workflow_user_client()
        row, _ = self.safety_record(approvals=[False, True], candidates={"approval_notify_users_1": "reviewer"})
        url = f"/safety/checklist-results/{row.id}"
        self.assertEqual(client.get(url).status_code, 200)
        before = row.approvals_json
        client.post(url + "/approve/1")
        self.m.db.session.refresh(row); self.assertEqual(row.approvals_json, before)

    def test_general_approval_visibility_uses_legacy_snapshot_and_keeps_company_boundary(self):
        client = self.workflow_user_client()
        row, _ = self.safety_record(approvals=[True])
        row.approvals_json = "[]"; self.m.db.session.commit()
        url = f"/safety/checklist-results/{row.id}"
        self.assertEqual(client.get(url).status_code, 200)
        row.company_code = "OTHER"; self.m.db.session.commit()
        self.assertEqual(client.get(url).status_code, 302)
        self.assertEqual(client.get(url + "/excel").status_code, 302)
        client.post(url + "/approve/0")
        self.m.db.session.refresh(row); self.assertEqual(row.status, "承認待ち")

    def test_vehicle_checklist_item_html_is_escaped_and_newlines_remain(self):
        content = '<b id="injected">点検</b>\n次の行 & <img src=x onerror=alert(1)>'
        checklist = self.workflow_checklist("車両管理", [], content)
        page = self.client.get(f"/vehicle/checklists/{checklist.id}", query_string={
            "vehicle_record_id": self.vehicle.id, "year": "2026", "month": "10"})
        self.assertEqual(page.status_code, 200)
        text = page.get_data(as_text=True)
        self.assertNotIn('<b id="injected">', text)
        self.assertNotIn('<img src=x', text)
        self.assertIn('&lt;b id=&#34;injected&#34;&gt;点検&lt;/b&gt;<br>', text)
        self.assertIn('次の行 &amp; &lt;img', text)

    def test_vehicle_completion_replay_does_not_send_another_notice_but_edited_result_can_complete(self):
        checklist = self.workflow_checklist("車両管理", [])
        data = {"vehicle_record_id": self.vehicle.id, "year": "2026", "month": "10", "day": "23"}
        url = f"/vehicle/checklists/{checklist.id}"
        # Optional, entirely unanswered inspections can still be explicitly completed.
        self.assertEqual(self.client.post(url + "/complete", data={**data, "notify_users": "admin"}).status_code, 302)
        row = self.m.VehicleChecklistResult.query.one()
        self.assertEqual(json.loads(row.answers_json), [])
        before = (row.status, row.checked_date, row.operation_judgment_json)
        notices = self.m.Notification.query.count()
        self.assertEqual(self.client.post(url + "/complete", data={**data, "notify_users": "admin"}).status_code, 409)
        self.m.db.session.refresh(row)
        self.assertEqual((row.status, row.checked_date, row.operation_judgment_json), before)
        self.assertEqual(self.m.Notification.query.count(), notices)
        self.assertEqual(self.m.VehicleChecklistResult.query.count(), 1)
        self.assertEqual(self.client.post(url + "/save-one", data={**data, "item_no": "0", "value": "0"}).status_code, 302)
        self.assertEqual(self.client.post(url + "/complete", data={**data, "notify_users": "admin"}).status_code, 302)
        self.assertEqual(self.m.Notification.query.count(), notices + 1)


if __name__ == "__main__":
    unittest.main()
