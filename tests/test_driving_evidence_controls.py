"""Removal is presentation-only; real routes use isolated SQLite fixtures."""
from pathlib import Path
import unittest
from identity_fixture import identity_for
from test_driving_admin_self import AdminSelfTests

class EvidenceControlsTests(AdminSelfTests):
    def test_evidence_controls_removed_all_viewer_scopes(self):
        for scope in ('self','office','company'):
            response,ctx=self.render(self.base+'&scope='+scope)
            html=response.get_data(as_text=True)
            self.assertNotIn('id="driving-metric-sources"',html)
            self.assertNotIn('読取内容・比較条件を確認',html)
            self.assertIn('対象の日報を見る',html)
            self.assertIn('読取内容</a>',html)
            self.assertIn('driving-metrics',html)
        with self.client.session_transaction() as state:
            state.update(account_identity=identity_for('TEST','two',app=self.client.application),username='two',role='user',password_changed_at='stamp')
        response,ctx=self.render(self.base+'&scope=self')
        self.assertNotIn('id="driving-metric-sources"',response.get_data(as_text=True))
        self.assertEqual(ctx['total'],1)
    def test_readback_and_analysis_remain_accessible(self):
        for panel in ('data','reports','analysis'):
            response,ctx=self.render(self.base+'&scope=self&panel='+panel)
            self.assertEqual(ctx['total'],1)
    def test_no_device_or_demo_condition_added(self):
        root=Path(__file__).resolve().parents[1]
        metrics=(root/'templates/driving_workspace_metrics.html').read_text()
        self.assertNotIn('driving-metric-sources',metrics)
        self.assertIn('metric_value(entry)',metrics)
        self.assertIn('entry.metric.name',metrics)

    def test_all_related_disclosures_removed_without_losing_comparison(self):
        root=Path(__file__).resolve().parents[1]
        comparisons=(root/'templates/driving_workspace_comparisons.html').read_text()
        self.assertNotIn('記録量・計算・出典',comparisons)
        self.assertIn('row.current.display',comparisons)
        self.assertIn('row.change',comparisons)
        self.assertIn('driving_report_export',comparisons)
