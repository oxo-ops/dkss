"""Bound maintenance display work without changing whole-history summaries."""
from datetime import date, timedelta
from unittest.mock import patch
import test_read_path_performance as read_tests
import dkss_app.vehicle_karte as karte

class RecentPreviewTests(read_tests.ReadPathTests):
    def test_preview_matches_full_history_for_date_and_cost_edges(self):
        self.seed_records()
        m=self.m
        today=m.datetime.now(m.ZoneInfo('Asia/Tokyo')).date()
        values=[str(today), str(today), str(today), str(today), str(today), str(today),
                str(today-timedelta(days=2)), str(today+timedelta(days=2)),
                '', 'bad', '2026/01/02', '2026-1-2', ' 2026-01-02 ', '2023-02-29']
        for i,value in enumerate(values):
            m.db.session.add(m.VehicleMaintenanceRecord(company_code='TEST',
                vehicle_record_id=self.vehicle.id,entry_date=value,completion_date=value,
                status='整備中' if i%3==0 else '完了', content=f'edge-{i}',
                total_cost=None if i%3==0 else (-50 if i%3==1 else 100),mileage=i*100,
                files_json='["original.png"]',invoice_details_json='{}'))
        m.db.session.commit()
        original=karte.get_vehicle_karte_history_entries
        def legacy(*args,**kwargs):
            kwargs.pop('maintenance_preview',None)
            return original(*args,**kwargs)
        with patch.object(karte,'get_vehicle_karte_history_entries',legacy):
            expected=self.overview()
        actual=self.overview()
        self.assertEqual(actual,expected)
        self.assertNotIn('foreign-record',repr(actual))
        with m.app.test_request_context('/'):
            complete=original('TEST',self.vehicle.id)
            preview=original('TEST',self.vehicle.id,maintenance_preview=(
                {r.id for r in m.VehicleMaintenanceRecord.query.all()},str(today),5))
        self.assertGreater(len(complete),5)
        self.assertLessEqual(sum(x['key'].startswith('maintenance:') for x in preview),5)
        self.assertNotIn('foreign-record',repr(preview))
