"""Read optimizations must preserve output, company boundaries and freshness."""
from datetime import date, datetime, timedelta
import json
import unittest
from unittest.mock import patch

from sqlalchemy import event
import test_workflow_regressions as workflow
from vehicle_analysis_dates import parse_record_date
from vehicle_read_snapshot import VehicleReadSnapshot


def legacy_date(value, *, normalize=False):
    text = str(value or "")
    text = text.strip()[:10].replace("/", "-") if normalize else text[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


class RecordDateTests(unittest.TestCase):
    def test_legacy_forms_and_invalid_dates_are_unchanged(self):
        values = [None, "", 0, False, "2026-10-25", "2026-1-2", "2024-02-29",
                  "2023-02-29", "0001-01-01", "2026/10/25", " 2026-10-25 ",
                  "2026-10-25 12:00", "2026-W43-7", "２０２６-１０-２５",
                  "2026-00-00", "2026-13-01", "2026-10-99", "not a date",
                  date(2026, 10, 25), datetime(2026, 10, 25, 12, 30)]
        for normalize in (False, True):
            for value in values:
                with self.subTest(value=value, normalize=normalize):
                    self.assertEqual(parse_record_date(value, normalize=normalize),
                                     legacy_date(value, normalize=normalize))

    def test_calendar_dates_match_existing_parser_across_leap_years(self):
        start = date(1999, 1, 1)
        for offset in range(0, 11000, 3):
            value = (start + timedelta(days=offset)).isoformat()
            self.assertEqual(parse_record_date(value), legacy_date(value))


class UncachedReads(VehicleReadSnapshot):
    def rows(self, model):
        return tuple(model.query.filter_by(company_code=self.company_code,
                                          vehicle_record_id=self.vehicle_record_id).all())


class ReadPathTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    setUp = workflow.WorkflowRegressionTests.setUp
    tearDown = workflow.WorkflowRegressionTests.tearDown

    def seed_records(self):
        m = self.m
        today = m.datetime.now(m.ZoneInfo("Asia/Tokyo")).date()
        self.vehicle.model_code = "READ-PATH"
        self.vehicle.first_registration_date = "2020-01"
        for code, content in (("TEST", "own-record"), ("OTHER", "foreign-record")):
            m.db.session.add(m.VehicleMaintenanceRecord(company_code=code,
                vehicle_record_id=self.vehicle.id, entry_date=str(today),
                completion_date=str(today), status="完了", content=content,
                mileage=1000, total_cost=12345))
        checklist = m.Checklist(company_code="TEST", name="Read test", target="車両管理",
                                active=True, items_json="[]")
        m.db.session.add(checklist)
        m.db.session.flush()
        m.db.session.add(m.VehicleChecklistResult(company_code="TEST",
            vehicle_record_id=self.vehicle.id, checklist_id=checklist.id,
            year=str(today.year), month=str(today.month), day=str(today.day),
            status="点検完了", answers_json="[]", operation_judgment_json="{}",
            checklist_snapshot_json=json.dumps({"items": [
                {"fixed_template_code": "daily_inspection_truck_trailer"}]})))
        m.db.session.add(m.VehicleOperationRecord(company_code="TEST",
            vehicle_record_id=self.vehicle.id, report_number="READ-1",
            operation_date=str(today), arrival_meter=1500, distance=500))
        m.db.session.commit()

    def overview(self):
        with self.m.app.test_request_context("/"):
            return self.m.get_vehicle_karte_overview_context(self.vehicle)

    def measured_overview(self):
        queries = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            queries.append(statement)
        engine = self.m.db.engine
        event.listen(engine, "before_cursor_execute", capture)
        try:
            result = self.overview()
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        return result, queries

    def test_overview_output_is_equal_with_and_without_shared_reads(self):
        self.seed_records()
        with patch("vehicle_karte_overview.VehicleReadSnapshot", UncachedReads):
            old, old_queries = self.measured_overview()
        new, new_queries = self.measured_overview()
        self.assertEqual(new, old)
        self.assertLessEqual(len(new_queries), len(old_queries) - 5)
        self.assertNotIn("foreign-record", repr(new))

    def test_next_build_sees_updated_data(self):
        self.seed_records()
        before = self.overview()["ko_cost"]["undated"]
        self.m.db.session.add(self.m.VehicleMaintenanceRecord(company_code="TEST",
            vehicle_record_id=self.vehicle.id, entry_date="", total_cost=999,
            content="new-record"))
        self.m.db.session.commit()
        self.assertEqual(self.overview()["ko_cost"]["undated"], before + 1)

    def test_snapshot_rejects_different_company_or_vehicle_before_query(self):
        snapshot = VehicleReadSnapshot("TEST", self.vehicle.id)
        for company, vid in (("OTHER", self.vehicle.id), ("TEST", self.vehicle.id + 1)):
            with self.subTest(company=company, vehicle=vid):
                with self.assertRaises(ValueError):
                    self.m.get_vehicle_karte_history_entries(company, vid, read_snapshot=snapshot)
                with self.assertRaises(ValueError):
                    self.m.get_vehicle_open_inspection_defects(company, vid, read_snapshot=snapshot)

    def test_snapshot_queries_once_and_does_not_include_foreign_rows(self):
        self.seed_records()
        snapshot = VehicleReadSnapshot("TEST", self.vehicle.id)
        first = snapshot.rows(self.m.VehicleMaintenanceRecord)
        with patch.object(self.m.VehicleMaintenanceRecord, "query") as query:
            self.assertEqual(snapshot.rows(self.m.VehicleMaintenanceRecord), first)
            query.filter_by.assert_not_called()
        self.assertEqual([row.content for row in first], ["own-record"])

    def test_analysis_payload_and_fingerprints_match_legacy_date_conversion(self):
        self.seed_records()
        with self.m.app.test_request_context("/"):
            with patch.object(self.m, "parse_record_date", legacy_date):
                old_payload, old_sources = self.m.get_vehicle_karte_analysis_job_data(self.vehicle)
            new_payload, new_sources = self.m.get_vehicle_karte_analysis_job_data(self.vehicle)
        self.assertEqual(new_payload, old_payload)
        self.assertEqual(new_sources, old_sources)


if __name__ == "__main__":
    unittest.main()
