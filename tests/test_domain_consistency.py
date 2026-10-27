"""Historical costs, shared originals and cross-process OCR admission."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal
from io import BytesIO
import hashlib
import json
import unittest
from unittest.mock import patch
from uuid import uuid4
from test_workflow_regressions import WorkflowRegressionTests as _Base
from test_inspection_document_ai import pdf_bytes
from dkss_app import document_import_queue as queue
from dkss_app.document_sources import (
    compact_sources,
    upgrade_storage,
    restore_inline_sources,
)
from dkss_app.models import (
    VehicleDocumentImportDraft as Draft,
    VehicleDocumentSource as Source,
    DocumentQueueSchedule,
)


def today():
    return datetime.now(ZoneInfo("Asia/Tokyo")).date()


class DomainConsistencyTests(unittest.TestCase):
    setUpClass = classmethod(_Base.setUpClass.__func__)
    tearDownClass = classmethod(_Base.tearDownClass.__func__)
    setUp = _Base.setUp
    tearDown = _Base.tearDown

    def maintenance(self, amount=100, office="A", **kw):
        row = self.m.VehicleMaintenanceRecord(
            company_code="TEST",
            vehicle_record_id=self.vehicle.id,
            entry_date=today().isoformat(),
            total_cost=amount,
            cost_office=office,
            **kw,
        )
        self.m.db.session.add(row)
        self.m.db.session.commit()
        return row

    def trend(self, office="A"):
        from dkss_app.dashboard import get_dashboard_office_maintenance_trend

        return get_dashboard_office_maintenance_trend("TEST", office)

    def total(self, result):
        return sum(m["amount"] for m in result["months"])

    def enqueue(self, company="TEST", count=1):
        from werkzeug.datastructures import FileStorage

        return queue.enqueue(
            [
                FileStorage(stream=BytesIO(pdf_bytes()), filename=f"{i}.pdf")
                for i in range(count)
            ],
            "inspection",
            company,
            "admin",
        )

    def test_card_and_dashboard_adopt_same_factual_costs(self):
        from dkss_app.vehicle_costs import get_vehicle_maintenance_cost_summary

        self.maintenance()
        self.maintenance(
            1000, notes="テスト用資料・支払不要(発行元・取引内容は架空です)"
        )
        self.assertEqual(self.total(self.trend()), 100)
        self.assertEqual(
            get_vehicle_maintenance_cost_summary(
                self.m.VehicleMaintenanceRecord.query.all()
            )["total_cost"],
            100,
        )
        self.assertEqual(len(self.trend()["source_exclusions"]), 1)

    def test_transfer_and_retirement_keep_historical_costs(self):
        self.vehicle.office = "A"
        self.maintenance()
        self.vehicle.office = "B"
        self.vehicle.deleted = True
        self.m.db.session.commit()
        self.assertEqual(self.total(self.trend("A")), 100)
        self.assertEqual(self.total(self.trend("B")), 0)

    def test_unknown_legacy_office_is_not_invented(self):
        row = self.maintenance(office=None)
        row.invoice_details_json = "{}"
        self.vehicle.office = "A"
        self.m.db.session.commit()
        self.assertIsNone(row.cost_office)
        self.assertEqual(self.total(self.trend()), 0)
        self.assertEqual(self.trend()["unassigned_count"], 1)

    def test_scope_future_missing_and_zero_costs(self):
        self.maintenance(0)
        self.maintenance(None)
        foreign = self.maintenance(999)
        foreign.company_code = "OTHER"
        future = self.maintenance(999)
        future.entry_date = (today() + timedelta(days=1)).isoformat()
        self.m.db.session.commit()
        result = self.trend()
        self.assertTrue(result["available"])
        self.assertEqual(result["months"][-1]["known"], 1)
        self.assertEqual(result["months"][-1]["missing"], 1)
        self.assertEqual(result["months"][-1]["amount"], 0)

    def test_legacy_slash_date_remains_in_historical_month(self):
        row = self.maintenance(500)
        row.entry_date = today().strftime("%Y/%m/%d") + " 12:00:00"
        self.m.db.session.commit()
        self.assertEqual(self.total(self.trend()), 500)

    def test_office_change_preserves_invoice_provenance(self):
        row = self.maintenance()
        row.invoice_details_json = json.dumps(
            {"source": {"sha256": "original"}, "fees": [{"name": "fee"}]}
        )
        row.cost_office = "旧営業所"
        self.m.db.session.commit()
        self.assertEqual(
            json.loads(row.invoice_details_json)["source"]["sha256"], "original"
        )
        self.assertEqual(row.cost_office, "旧営業所")

    def test_manual_confirmation_records_history_and_rejects_stale_edits(self):
        from dkss_app.vehicle_karte import vehicle_maintenance_record_version

        row = self.maintenance(office=None, content="整備", status="整備中")
        token = vehicle_maintenance_record_version(row)
        url = f"/vehicle/karte/{self.vehicle.id}/maintenance/{row.id}/edit"
        self.assertIn("整備時の営業所", self.client.get(url).get_data(as_text=True))
        data = dict(
            content="整備",
            entry_date=row.entry_date,
            cost_office="当時の営業所",
            total_cost="100",
            record_version=token,
        )
        self.assertEqual(self.client.post(url, data=data).status_code, 302)
        self.m.db.session.expire_all()
        self.assertEqual(row.cost_office, "当時の営業所")
        self.assertEqual(
            self.client.post(url, data=dict(data, cost_office="誤上書き")).status_code,
            409,
        )
        self.assertTrue(
            any(
                "cost_office" in r.changes_json
                for r in self.m.VehicleMaintenanceRecordEvent.query.all()
            )
        )

    def test_invoice_confirmation_preserves_office_after_transfer(self):
        from test_document_connections import DocumentConnectionTests

        draft, key, form = DocumentConnectionTests.invoice(self)
        form["cost_office_" + key] = "当時の営業所"
        self.assertEqual(
            self.client.post(
                f"/vehicle/data-import/{draft.batch_id}/confirm", data=form
            ).status_code,
            302,
        )
        self.assertEqual(
            self.m.VehicleMaintenanceRecord.query.one().cost_office, "当時の営業所"
        )
        self.vehicle.office = "異動先"
        self.m.db.session.commit()
        self.assertEqual(self.total(self.trend("当時の営業所")), Decimal("163900"))

    def test_source_is_shared_only_within_one_company(self):
        self.enqueue(count=2)
        self.assertEqual(Source.query.count(), 1)
        self.assertTrue(
            all(
                r._source_file == b"" and r.source_file == pdf_bytes()
                for r in Draft.query.all()
            )
        )
        self.enqueue("OTHER")
        self.assertEqual(Source.query.count(), 2)

    def test_compaction_is_idempotent_and_company_scoped(self):
        source = pdf_bytes()
        digest = hashlib.sha256(source).hexdigest()
        for company in ("TEST", "OTHER"):
            self.m.db.session.add(
                Draft(
                    id=str(uuid4()),
                    batch_id=str(uuid4()),
                    company_code=company,
                    created_by_username="admin",
                    document_type="inspection",
                    source_filename="old.pdf",
                    source_file=source,
                    source_sha256=digest,
                    status="completed",
                )
            )
        self.m.db.session.commit()
        upgrade_storage()
        upgrade_storage()
        self.assertEqual(compact_sources(), 2)
        self.assertEqual(compact_sources(), 0)
        self.assertEqual(Source.query.count(), 2)
        self.assertTrue(
            all(
                r.source_file == source and r._source_file == b""
                for r in Draft.query.all()
            )
        )

    def test_deletion_only_purges_the_last_reference(self):
        first, second = self.enqueue(), self.enqueue()
        queue.delete_receipt(first, "TEST", "admin")
        self.assertEqual(Draft.query.filter_by(batch_id=first).one().source_file, b"")
        self.assertEqual(Source.query.count(), 1)
        self.assertEqual(
            Draft.query.filter_by(batch_id=second).one().source_file, pdf_bytes()
        )
        queue.delete_receipt(second, "TEST", "admin")
        self.assertEqual(Source.query.count(), 0)

    def test_old_deployment_falls_back_then_compacts_after_migration(self):
        with self.m.db.engine.begin() as connection:
            Source.__table__.drop(connection)
        self.m.app.extensions["dkss"]["document_sources_ready"] = False
        self.enqueue()
        self.assertEqual(Draft.query.one()._source_file, pdf_bytes())
        upgrade_storage()
        self.assertEqual(compact_sources(), 1)
        self.assertEqual(Draft.query.one().source_file, pdf_bytes())

    def test_rollback_restores_inline_bytes_without_reviving_deleted_rows(self):
        first, second = self.enqueue(), self.enqueue()
        queue.delete_receipt(second, "TEST", "admin")
        self.assertEqual(restore_inline_sources(), 1)
        self.assertEqual(restore_inline_sources(), 0)
        self.assertEqual(
            Draft.query.filter_by(batch_id=first).one()._source_file, pdf_bytes()
        )
        self.assertEqual(Draft.query.filter_by(batch_id=second).one().source_file, b"")

    def test_round_robin_and_company_concurrency_limits(self):
        self.enqueue(count=3)
        self.enqueue("OTHER")
        one, two = queue.claim_next(), queue.claim_next()
        self.assertNotEqual(
            Draft.query.filter_by(id=one[0]).one().company_code,
            Draft.query.filter_by(id=two[0]).one().company_code,
        )
        self.assertIsNone(queue.claim_next())
        queue.finish(*one, error=ValueError("NO_INSPECTION_FOUND"))
        self.assertIsNone(queue.claim_next())
        queue.finish(*two, error=ValueError("NO_INSPECTION_FOUND"))
        self.assertIsNotNone(queue.claim_next())

    def test_turn_and_lease_recovery_survive_new_sessions(self):
        self.enqueue(count=3)
        self.enqueue("OTHER", count=2)
        one = queue.claim_next()
        company = Draft.query.filter_by(id=one[0]).one().company_code
        queue.finish(*one, error=ValueError("NO_INSPECTION_FOUND"))
        self.m.db.session.remove()
        two = queue.claim_next()
        row = Draft.query.filter_by(id=two[0]).one()
        self.assertNotEqual(row.company_code, company)
        job = queue.metadata(row.result_json)
        job["lease_until"] = "2000-01-01"
        row.result_json = queue.result(job)
        self.m.db.session.commit()
        self.assertIsNotNone(queue.claim_next())
        self.assertGreater(DocumentQueueSchedule.query.one().version, 1)

    def test_global_limit_is_shared_across_workers(self):
        self.enqueue(count=3)
        with patch.dict(
            "os.environ",
            {
                "DOCUMENT_IMPORT_MAX_CONCURRENT": "1",
                "DOCUMENT_IMPORT_COMPANY_CONCURRENT": "2",
            },
        ):
            self.assertIsNotNone(queue.claim_next())
            self.assertIsNone(queue.claim_next())

    def test_two_sessions_cannot_claim_a_single_global_slot(self):
        from concurrent.futures import ThreadPoolExecutor

        self.enqueue(count=2)
        self.enqueue("OTHER")
        self.m.db.session.add(DocumentQueueSchedule(id=1, version=0))
        self.m.db.session.commit()

        def claim():
            with self.m.app.app_context():
                try:
                    return queue.claim_next()
                finally:
                    self.m.db.session.remove()

        with patch.dict(
            "os.environ", {"DOCUMENT_IMPORT_MAX_CONCURRENT": "1"}
        ), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: claim(), range(2)))
        self.assertEqual(sum(r is not None for r in results), 1)


del _Base
