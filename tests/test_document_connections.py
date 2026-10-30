"""Import-to-karte integration checks with an isolated DB and mocked OCR only."""
import hashlib
import json
from io import BytesIO
import unittest
from unittest.mock import patch

from test_workflow_regressions import WorkflowRegressionTests as Fixture


class DocumentConnectionTests(unittest.TestCase):
    setUpClass = classmethod(Fixture.setUpClass.__func__)
    tearDownClass = classmethod(Fixture.tearDownClass.__func__)
    setUp = Fixture.setUp
    tearDown = Fixture.tearDown
    upload_inspection = Fixture.upload_inspection
    inspection_form = Fixture.inspection_form

    def inspection(self):
        self.upload_inspection()
        draft = self.m.VehicleDocumentImportDraft.query.one()
        response = self.client.post(f"/vehicle/data-import/{draft.batch_id}/confirm",
                                    data=self.inspection_form(draft))
        self.assertEqual(response.status_code, 302)
        return self.m.VehiclePeriodicInspectionRecord.query.one()

    def invoice(self):
        import maintenance_invoice_ai as ai
        from test_inspection_document_ai import pdf_bytes
        source = pdf_bytes(2)
        row = {field: None for field in ai.record_properties}
        part = {field: None for field in ai.line_properties}
        part.update(category="部品", description="タイヤ", quantity="2", parts_amount="76000",
                    source_page=1, replacement_action="replace", replacement_part_name="タイヤ",
                    replacement_category="消耗品")
        row.update(source_pages=[1], line_items=[part], fees=[], warnings=[],
                   entry_date="2026-10-21", chassis_number="TEST-001",
                   total_cost="163900", parts_cost="100000", labor_cost="49000",
                   tax_amount="14900", invoice_number="TEST-INV", content="タイヤ交換")
        extraction = {"schema_version": 1, "source_sha256": hashlib.sha256(source).hexdigest(),
                      "records": [row], "warnings": []}
        with patch.object(self.m, "extract_maintenance_invoices", return_value=extraction):
            response = self.client.post("/vehicle/data-import", data={"document_type": "maintenance",
                "document_files": (BytesIO(source), "03_maintenance_invoice.pdf")})
        self.assertEqual(response.status_code, 302)
        draft = self.m.VehicleDocumentImportDraft.query.filter_by(document_type="maintenance").one()
        key = draft.id + "_0"
        form = {"include": key, "vehicle_" + key: str(self.vehicle.id),
                "date_" + key: "2026-10-21", "content_" + key: "タイヤ交換"}
        return draft, key, form

    def candidates(self, draft):
        return self.client.get(
            f"/vehicle/document-import/{draft.batch_id}/{draft.id}/0/maintenance-candidates",
            query_string={"vehicle_id": self.vehicle.id, "record_date": "2026-10-21"},
        ).get_json()["candidates"]

    def test_inspection_invoice_reaches_cost_parts_history_and_source_once(self):
        inspection = self.inspection()
        draft, key, form = self.invoice()
        choices = self.candidates(draft)
        choice = next(row for row in choices if row["kind"] == "inspection")
        form["service_match_" + key] = choice["token"]
        url = f"/vehicle/data-import/{draft.batch_id}/confirm"
        # The validation probe must not create a financial record.
        self.assertEqual(self.client.post(url, data=form,
            headers={"X-DKSS-Validation-Only": "1"}).status_code, 200)
        self.assertEqual(self.m.VehicleMaintenanceRecord.query.count(), 0)
        response = self.client.post(url, data=form)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/maintenance', response.location)
        invoice = self.m.VehicleMaintenanceRecord.query.one()
        self.assertEqual(str(invoice.total_cost), "163900.00")
        self.assertEqual(json.loads(invoice.invoice_details_json)["periodic_inspection_id"], inspection.id)
        self.assertEqual(self.m.VehiclePartReplacement.query.count(), 1)
        self.assertEqual(self.m.VehicleMaintenanceDocument.query.count(), 0)
        self.assertEqual(self.m.VehiclePeriodicInspectionRecord.query.count(), 1)
        detail = self.client.get(response.location).get_data(as_text=True)
        self.assertIn("関連する点検記録", detail)
        for path, expected in (("costs?year=2026", "163,900"), ("parts", "タイヤ"),
                               ("history", "タイヤ交換"), ("documents", "03_maintenance_invoice.pdf"),
                               ("inspections", "請求・整備内容を確認")):
            page = self.client.get(f"/vehicle/karte/{self.vehicle.id}/{path}")
            self.assertEqual(page.status_code, 200)
            self.assertIn(expected, page.get_data(as_text=True))
        self.assertEqual(self.client.post(url, data=form).status_code, 409)
        self.assertEqual(self.m.VehicleMaintenanceRecord.query.count(), 1)
        self.assertEqual(self.m.VehiclePartReplacement.query.count(), 1)

    def test_same_day_requires_explicit_selection_and_rejects_stale_token(self):
        inspection = self.inspection()
        draft, key, form = self.invoice()
        url = f"/vehicle/data-import/{draft.batch_id}/confirm"
        self.assertEqual(self.client.post(url, data=form).status_code, 400)
        token = self.candidates(draft)[0]["token"]
        inspection.content = "別の利用者による変更"
        self.m.db.session.commit()
        form["service_match_" + key] = token
        self.assertEqual(self.client.post(url, data=form).status_code, 400)
        self.assertEqual(self.m.VehicleMaintenanceRecord.query.count(), 0)

    def test_existing_invoice_costs_are_preserved_for_review(self):
        target = self.m.VehicleMaintenanceRecord(company_code="TEST", vehicle_record_id=self.vehicle.id,
            entry_date="2026-10-21", content="既存整備", total_cost="500")
        self.m.db.session.add(target)
        self.m.db.session.commit()
        draft, key, form = self.invoice()
        form["service_match_" + key] = self.candidates(draft)[0]["token"]
        response = self.client.post(f"/vehicle/data-import/{draft.batch_id}/confirm", data=form)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(str(target.total_cost), "500.00")
        self.assertEqual(self.m.VehicleMaintenanceRecord.query.count(), 1)
        self.assertEqual(self.m.VehicleMaintenanceDocument.query.one().financial_status, "pending")
        self.assertEqual(self.m.VehiclePartReplacement.query.count(), 0)

    def test_existing_english_filenames_classified_from_registered_facts(self):
        inspection = self.inspection()
        draft = self.m.VehicleDocumentImportDraft.query.one()
        draft.source_filename = "unrelated_invoice_photo.jpg"
        self.m.db.session.commit()
        page = self.client.get(f"/vehicle/karte/{self.vehicle.id}/documents?kind=inspection_3").get_data(as_text=True)
        self.assertIn("unrelated_invoice_photo.jpg", page)
        self.assertIn("3か月点検（1）", page)
        inspection.inspection_type = "12month"
        self.m.db.session.commit()
        page = self.client.get(f"/vehicle/karte/{self.vehicle.id}/documents?kind=inspection_unconfirmed").get_data(as_text=True)
        self.assertIn("車検／12か月点検・区分未確認（1）", page)
        self.assertIn("unrelated_invoice_photo.jpg", page)
        inspection.inspection_type = "periodic_12month"
        self.m.db.session.commit()
        page = self.client.get(f"/vehicle/karte/{self.vehicle.id}/documents?kind=inspection_12").get_data(as_text=True)
        self.assertIn("12か月点検（1）", page)
        self.assertIn("unrelated_invoice_photo.jpg", page)
        inspection.inspection_type = "vehicle_inspection"
        self.m.db.session.commit()
        response = self.client.get(f"/vehicle/karte/{self.vehicle.id}/documents?kind=inspection_vehicle")
        self.assertEqual(response.status_code, 200)
        self.assertIn("車検（1）", response.get_data(as_text=True))

    def test_driving_report_gets_own_category(self):
        from dkss_app.vehicle_karte import build_vehicle_karte_documents_context
        document = {"draft_id": "daily", "filename": "04_safe_driving_report.pdf",
                    "document_type": "driving_report", "records": []}
        with self.m.app.test_request_context('/'):
            context = build_vehicle_karte_documents_context(self.vehicle, [document])
        self.assertEqual(context["document_page"].items[0]["kind"], "driving_report")
        self.assertEqual(context["document_page"].items[0]["kind_label"], "安全運転日報")

    def test_failed_parts_write_rolls_back_invoice_and_keeps_preview_retryable(self):
        self.inspection()
        draft, key, form = self.invoice()
        form["service_match_" + key] = self.candidates(draft)[0]["token"]
        with patch.object(self.m, "save_vehicle_maintenance_replacement_parts", side_effect=ValueError("forced")):
            response = self.client.post(f"/vehicle/data-import/{draft.batch_id}/confirm", data=form)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.m.VehicleMaintenanceRecord.query.count(), 0)
        self.assertEqual(self.m.VehiclePartReplacement.query.count(), 0)
        self.m.db.session.refresh(draft)
        self.assertEqual(draft.status, "preview")


del Fixture  # Avoid collecting the imported fixture's tests a second time.

if __name__ == "__main__":
    unittest.main()
