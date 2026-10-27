"""Read parity and invalidation across transactions, time and companies."""

from datetime import datetime, timedelta, timezone
import json
import os
from unittest.mock import patch
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from test_analysis_result_consistency import AnalysisResultConsistencyTests as _Uncached
from dkss_app.analysis_read_cache import AnalysisReadCacheRepository, upgrade_read_cache
from dkss_app.models import AnalysisInputEpoch as Epoch, AnalysisInputReadCache as Cache


class FrozenClock(datetime):
    current = datetime.now(timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)


class CachedAnalysisConsistencyTests(_Uncached):
    def setUp(self):
        super().setUp()
        upgrade_read_cache()

    def test_warm_read_matches_uncached_and_never_calls_paid_ai(self):
        self.saved_result()
        with patch.object(AnalysisReadCacheRepository, "token", return_value=None):
            baseline = self.result().json
        build = self.m.get_vehicle_karte_analysis_job_data
        with patch.object(
            self.m, "get_vehicle_karte_analysis_job_data", wraps=build
        ) as loader, patch.object(
            self.m, "analyze_vehicle_karte", side_effect=AssertionError("AI from GET")
        ):
            first, second = self.result(), self.result()
        self.assertEqual(first.json, baseline)
        self.assertEqual(second.json, baseline)
        self.assertEqual(loader.call_count, 1)
        self.assertEqual(Cache.query.count(), 1)
        self.assertIn("no-store", second.headers["Cache-Control"])

    def test_change_during_warm_lookup_rechecks_before_returning(self):
        record, _, _ = self.saved_result()
        self.result()
        original = AnalysisReadCacheRepository.get

        def concurrent_change(repository, *args):
            cached = original(repository, *args)
            with self.m.db.engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE vehicle_maintenance_record SET content=:v WHERE id=:id"
                    ),
                    dict(v="lookup中の更新", id=record.id),
                )
            return cached

        with patch.object(AnalysisReadCacheRepository, "get", concurrent_change):
            self.assertFalse(self.result().json["is_current"])

    def test_raw_sql_and_bulk_update_invalidate_immediately(self):
        record, _, _ = self.saved_result()
        self.assertTrue(self.result().json["is_current"])
        with self.m.db.engine.begin() as connection:
            connection.execute(
                text("UPDATE vehicle_maintenance_record SET content=:v WHERE id=:id"),
                dict(v="別プロセスの訂正", id=record.id),
            )
        self.assertFalse(self.result().json["is_current"])
        self.m.VehicleMaintenanceRecord.query.filter_by(id=record.id).update(
            {"content": "ブレーキ調整"}
        )
        self.m.db.session.commit()
        self.assertTrue(self.result().json["is_current"])

    def test_rollback_preserves_cache_and_committed_revision(self):
        record, _, _ = self.saved_result()
        self.result()
        build = self.m.get_vehicle_karte_analysis_job_data
        record.content = "取り消す"
        self.m.db.session.flush()
        self.m.db.session.rollback()
        with patch.object(
            self.m, "get_vehicle_karte_analysis_job_data", wraps=build
        ) as loader:
            self.assertTrue(self.result().json["is_current"])
        self.assertEqual(loader.call_count, 0)

    def test_other_company_does_not_evict_or_leak(self):
        self.saved_result()
        self.result()
        build = self.m.get_vehicle_karte_analysis_job_data
        self.m.db.session.add(
            self.m.VehicleMaintenanceRecord(
                company_code="OTHER",
                vehicle_record_id=self.vehicle.id,
                content="他社秘密",
                entry_date="2026-10-21",
            )
        )
        self.m.db.session.commit()
        with patch.object(
            self.m, "get_vehicle_karte_analysis_job_data", wraps=build
        ) as loader:
            data = self.result().json
        self.assertEqual(loader.call_count, 0)
        self.assertNotIn("他社秘密", json.dumps(data))

    def test_peer_changes_invalidate_company_comparison(self):
        self.vehicle.model_code = "PEER"
        peer = self.m.Vehicle(
            company_code="TEST", chassis_number="PEER", model_code="PEER"
        )
        self.m.db.session.add(peer)
        self.m.db.session.commit()
        self.saved_result()
        self.result()
        build = self.m.get_vehicle_karte_analysis_job_data
        self.m.db.session.add(
            self.m.VehicleMaintenanceRecord(
                company_code="TEST",
                vehicle_record_id=peer.id,
                content="比較車両整備",
                entry_date="2026-10-21",
                total_cost=100,
            )
        )
        self.m.db.session.commit()
        with patch.object(
            self.m, "get_vehicle_karte_analysis_job_data", wraps=build
        ) as loader:
            self.result()
        self.assertEqual(loader.call_count, 1)
        self.assertIsNotNone(
            Epoch.query.filter_by(
                company_code="TEST", bucket=f"vehicle:{peer.id}"
            ).first()
        )

    def test_source_deadline_forces_recheck_without_a_db_write(self):
        from zoneinfo import ZoneInfo
        from dkss_app.public_maintenance_knowledge_models import get_models

        _, File = get_models(self.m.db)
        FrozenClock.current = datetime(2026, 10, 27, 1, 0, tzinfo=timezone.utc)
        boundary = FrozenClock.current + timedelta(seconds=30)
        row = File(
            company_code="TEST",
            url="https://example.invalid/source",
            title="期限付き資料",
            status="ready",
            last_checked=(FrozenClock.current - timedelta(days=1))
            .astimezone(ZoneInfo("Asia/Tokyo"))
            .replace(tzinfo=None),
            next_check=boundary.astimezone(ZoneInfo("Asia/Tokyo")).replace(tzinfo=None),
        )
        self.m.db.session.add(row)
        self.m.db.session.commit()
        build = self.m.get_vehicle_karte_analysis_job_data
        with patch.object(self.m, "datetime", FrozenClock), patch.object(
            self.m, "get_vehicle_karte_analysis_job_data", wraps=build
        ) as loader:
            self.result()
            self.result()
            self.assertEqual(loader.call_count, 1)
            FrozenClock.current = boundary + timedelta(seconds=1)
            self.result()
            self.assertEqual(loader.call_count, 2)

    def test_day_rollover_and_settings_change_context(self):
        FrozenClock.current = datetime(2026, 10, 27, 14, 59, 30, tzinfo=timezone.utc)
        build = self.m.get_vehicle_karte_analysis_job_data
        with patch.object(self.m, "datetime", FrozenClock), patch.object(
            self.m, "get_vehicle_karte_analysis_job_data", wraps=build
        ) as loader:
            self.result()
            self.result()
            self.assertEqual(loader.call_count, 1)
            FrozenClock.current += timedelta(minutes=1)
            self.result()
            self.assertEqual(loader.call_count, 2)
            with patch.dict(
                os.environ, {"VEHICLE_KARTE_AI_PEER_REGISTRATION": "all_years"}
            ):
                self.result()
            self.assertEqual(loader.call_count, 3)

    def test_single_race_retries_with_a_fresh_session(self):
        record, _, _ = self.saved_result()
        build = self.m.get_vehicle_karte_analysis_job_data
        calls = []

        def racing(vehicle):
            value = build(vehicle)
            calls.append(1)
            if len(calls) == 1:
                with self.m.db.engine.begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE vehicle_maintenance_record SET content=:v WHERE id=:id"
                        ),
                        dict(v="更新後", id=record.id),
                    )
            return value

        with patch.object(
            self.m, "get_vehicle_karte_analysis_job_data", side_effect=racing
        ):
            data = self.result().json
        self.assertEqual(len(calls), 2)
        self.assertFalse(data["is_current"])
        self.assertEqual(Cache.query.count(), 1)

    def test_continuous_races_never_publish_or_claim_current(self):
        record, _, _ = self.saved_result()
        build = self.m.get_vehicle_karte_analysis_job_data
        calls = []

        def racing(vehicle):
            value = build(vehicle)
            calls.append(1)
            with self.m.db.engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE vehicle_maintenance_record SET content=:v WHERE id=:id"
                    ),
                    dict(v="更新" + str(len(calls)), id=record.id),
                )
            return value

        with patch.object(
            self.m, "get_vehicle_karte_analysis_job_data", side_effect=racing
        ):
            self.assertIsNot(self.result().json["is_current"], True)
        self.assertEqual(len(calls), 2)
        self.assertEqual(Cache.query.count(), 0)

    def test_cache_write_failure_does_not_commit_business_session_or_break_api(self):
        self.saved_result()
        engine = self.m.db.engine

        def failed_begin():
            raise OperationalError("write cache", {}, Exception("cache unavailable"))

        with patch.object(engine, "begin", side_effect=failed_begin), patch.object(
            self.m.db.session,
            "commit",
            side_effect=AssertionError("Business commit from GET"),
        ):
            self.assertTrue(self.result().json["is_current"])
        self.assertEqual(Cache.query.count(), 0)

    def test_moving_company_invalidates_old_and_new_scopes(self):
        now = datetime.now(timezone.utc)
        repo = AnalysisReadCacheRepository()
        before_old, before_new = repo.token("TEST", now), repo.token("OTHER", now)
        with self.m.db.engine.begin() as connection:
            connection.execute(
                text("UPDATE vehicle SET company_code='OTHER' WHERE id=:id"),
                dict(id=self.vehicle.id),
            )
        self.assertGreater(repo.token("TEST", now).revision, before_old.revision)
        self.assertGreater(repo.token("OTHER", now).revision, before_new.revision)

    def test_unassigned_document_uses_shared_bucket(self):
        from dkss_app.models import VehicleDocumentImportDraft

        self.m.db.session.add(
            VehicleDocumentImportDraft(
                id="unassigned",
                batch_id="batch",
                company_code="TEST",
                created_by_username="admin",
                document_type="inspection",
                source_filename="x.pdf",
                source_sha256="a" * 64,
                source_file=b"x",
                status="preview",
            )
        )
        self.m.db.session.commit()
        self.assertGreater(
            Epoch.query.filter_by(company_code="TEST", bucket="shared").one().revision,
            1,
        )

    def test_repeated_upgrade_keeps_saved_result_valid(self):
        _, state, _ = self.saved_result()
        self.result()
        original = state.result_json
        upgrade_read_cache()
        self.assertEqual(Cache.query.count(), 0)
        self.assertTrue(self.result().json["is_current"])
        self.assertEqual(state.result_json, original)

    def test_missing_migration_and_disabled_cache_keep_legacy_output(self):
        self.saved_result()
        with patch.dict(os.environ, {"ANALYSIS_READ_CACHE_ENABLED": "0"}):
            baseline = self.result().json
        with self.m.db.engine.begin() as connection:
            from dkss_app.analysis_read_cache import REVISION

            connection.execute(
                text("DELETE FROM domain_schema_revision WHERE revision=:r"),
                dict(r=REVISION),
            )
        self.assertEqual(self.result().json, baseline)
        self.assertEqual(Cache.query.count(), 0)


del _Uncached
