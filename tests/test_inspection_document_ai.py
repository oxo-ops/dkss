"""OCR parsing and safety boundaries with synthetic documents; no network calls."""
import copy
import hashlib
import json
import os
from io import BytesIO
import unittest
from unittest.mock import patch

import inspection_document_ai as ai
from pypdf import PdfWriter


def pdf_bytes(pages=1):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def extraction(source=None):
    row = {key: None for key in ai.TEXT_FIELDS}
    row.update(registration_number="品川 010 あ 0012", chassis_number="TEST-001",
               inspection_type="3month", inspection_type_raw="3か月定期点検",
               inspection_date="2026-10-21", inspection_company="試験工場",
               inspector_name="点検者", mileage="100000", content="定期点検を実施",
               symbol_legend="○：点検／×：交換／空欄：未記入", source_pages=[1],
               inspection_items=[{"category": "制動装置", "item_name": "ブレーキの効き",
                   "raw_result": "○", "result_text": None, "notes": None, "source_page": 1}],
               warnings=[])
    return {"schema_version": 1, "source_sha256": hashlib.sha256(source or pdf_bytes()).hexdigest(),
            "records": [row], "warnings": []}


class Response:
    def __init__(self, value): self.value = value
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, *args): return json.dumps(self.value).encode()


class InspectionDocumentAITests(unittest.TestCase):
    def test_shared_transport_extracts_and_preserves_source(self):
        source = pdf_bytes(2)
        data = extraction(source)
        result = {"status": "completed", "output": [{"content": [{"type": "output_text", "text": json.dumps(data)}]}]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch("maintenance_invoice_ai.urllib.request.urlopen", return_value=Response(result)) as call:
            got = ai.extract_inspection_documents(source, "inspection.pdf")
        sent = json.loads(call.call_args.args[0].data)
        self.assertEqual(sent["text"]["format"]["name"], "periodic_inspections")
        self.assertFalse(sent["store"])
        self.assertEqual(got["source_sha256"], hashlib.sha256(source).hexdigest())
        self.assertEqual(got["records"][0]["registration_number"], "品川 010 あ 0012")
        self.assertTrue(got["needs_review"])

    def test_shared_stream_reports_inspection_items(self):
        from maintenance_invoice_ai import _read_maintenance_stream
        raw = json.dumps(extraction(), ensure_ascii=False)
        events = [{"type": "response.created"}]
        events += [{"type": "response.output_text.delta", "delta": raw[i:i+23]}
                   for i in range(0, len(raw), 23)]
        events.append({"type": "response.completed", "response": {"status": "completed"}})
        lines = [line for event in events for line in (
            ("data: " + json.dumps(event) + "\n").encode(), b"\n")]
        progress = []
        result = _read_maintenance_stream(lines, progress.append)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(progress[0]["phase"], "ai_accepted")
        self.assertEqual(progress[-1]["received_lines"], 1)

    def test_invoice_transport_still_uses_invoice_schema(self):
        import maintenance_invoice_ai as invoice
        row = {key: None for key in invoice.record_properties}
        row.update(source_pages=[1], line_items=[], fees=[], warnings=[])
        data = {"records": [row], "warnings": []}
        result = {"status": "completed", "output": [{"content": [{"type": "output_text", "text": json.dumps(data)}]}]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch.object(invoice.urllib.request, "urlopen", return_value=Response(result)) as call:
            got = invoice.extract_maintenance_invoices(pdf_bytes())
        payload = json.loads(call.call_args.args[0].data)
        self.assertEqual(payload["text"]["format"]["name"], "maintenance_invoices")
        self.assertEqual(payload["instructions"], invoice.INSTRUCTIONS)
        self.assertEqual(got["records"], [row])

    def test_schema_rejects_malformed_data(self):
        for key, value in [("inspection_date", "2026-02-30"), ("mileage", "NaN"), ("mileage", "-1"), ("inspection_type", "normal"), ("source_pages", [True])]:
            with self.subTest(key=key, value=value):
                data = extraction()
                data["records"][0][key] = value
                with self.assertRaises(ValueError): ai._validate(data)
        data = extraction()
        data["records"][0]["inspection_items"][0]["source_page"] = 2
        with self.assertRaises(ValueError): ai._validate(data)
        with self.assertRaisesRegex(ValueError, "NO_INSPECTION_FOUND"):
            ai._validate({"records": [], "warnings": []})

    def test_page_bounds_and_invalid_pdf(self):
        source = pdf_bytes()
        data = extraction(source)
        data["records"][0]["source_pages"] = [1, 2]
        with patch.object(ai, "extract_vehicle_document", return_value=data):
            with self.assertRaisesRegex(ValueError, "INVALID_SOURCE_PAGES"):
                ai.extract_inspection_documents(source)
        with self.assertRaises(ValueError): ai.extract_inspection_documents(b"%PDF-broken")
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.encrypt("secret")
        out = BytesIO(); writer.write(out)
        with self.assertRaises(ValueError): ai.extract_inspection_documents(out.getvalue())

    def test_unknown_dates_and_symbols_stay_unknown(self):
        data = extraction(); data["records"][0]["inspection_date"] = None
        data["records"][0]["inspection_type"] = None
        got = ai.build_inspection_preview(data, [])
        row = got["records"][0]
        self.assertEqual(row["record_date"], "")
        self.assertIsNone(row["completion_date"])
        self.assertIsNone(row["next_inspection_date"])
        self.assertEqual(row["inspection_items"][0]["raw_result"], "○")
        self.assertNotIn("operation_judgment", row)
        self.assertNotIn("line_items", row)

    def test_matching_conflicts_ambiguous_and_inactive(self):
        data = extraction()
        choice = {"id": 1, "number": "品川010あ0012", "chassis_number": "TEST-001"}
        self.assertEqual(ai.build_inspection_preview(data, [choice])["records"][0]["vehicle_record_id"], 1)
        for choices, state in [([{**choice, "deleted": True}], "unmatched"),
                               ([choice, {**choice, "id": 2}], "ambiguous"),
                               ([{**choice, "number": "品川999あ9999"}], "conflict")]:
            got = ai.build_inspection_preview(data, choices)["records"][0]
            self.assertIsNone(got["vehicle_record_id"])
            self.assertEqual(got["vehicle_match_status"], state)

    def test_multiple_records_on_same_page(self):
        data = extraction(); row = copy.deepcopy(data["records"][0])
        row.update(chassis_number="TEST-002", registration_number="品川010あ0013")
        data["records"].append(row)
        ai._validate(data)
        preview = ai.build_inspection_preview(data, [])
        preview["records"][0]["inspection_items"][0]["raw_result"] = "×"
        self.assertEqual(preview["original_records"][0]["inspection_items"][0]["raw_result"], "○")


if __name__ == "__main__": unittest.main()
