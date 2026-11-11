"""UI⑤ boundary and real-route tests. Writes are synthetic temporary SQLite only."""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace as Row
import json
import unittest

from vehicle_comparison_presentation import cost_comparison, replacement_distance
from test_workflow_regressions import WorkflowRegressionTests as _Base


class ComparisonProjectionTests(unittest.TestCase):
    def reference(self, **values):
        return dict(value=Decimal('1200'), date='2026-09-30', as_of='2026-09-30',
                    distance_usable=True, conflict_dates=[], decrease_dates=[], **values)

    def distance(self, part=None, parent=None, reference=None, **kw):
        return replacement_distance(
            part or Row(replacement_date='2026-09-01', mileage=Decimal('1000')),
            parent or Row(status='完了', completion_date='', is_invoice_actual=False),
            reference or self.reference(), **kw)

    def test_decimal_distance_and_known_zero(self):
        self.assertEqual(self.distance()['distance_since'], Decimal('200'))
        got = self.distance(part=Row(replacement_date='2026-09-30', mileage=Decimal('1200')))
        self.assertEqual(got['distance_since'], Decimal('0'))
        self.assertIsNone(got['distance_note'])

    def test_invalid_and_missing_replacement_meter_is_held(self):
        for raw in [None, '', True, -1, 'NaN', 'Infinity']:
            with self.subTest(raw=raw):
                result = self.distance(part=Row(replacement_date='2026-09-01', mileage=raw))
                self.assertIsNone(result['distance_since'])
                self.assertIn('交換時距離', result['distance_note'])

    def test_source_boundaries_and_unusable_reference_are_not_hidden(self):
        cases = [({'date': '2026-08-31'}, '交換前'), ({'value': 900}, '小さい'),
                 ({'date': '2026-10-01'}, '基準日後'), ({'value': None}, '未取得'),
                 ({'value': 'NaN'}, '不正'), ({'value': 'Infinity'}, '不正'),
                 ({'date': None}, '未取得'), ({'distance_usable': False}, '根拠'),
                 ({'conflict_dates': ['2026-09-03']}, '不一致'),
                 ({'decrease_dates': ['2026-09-03']}, '逆転')]
        for changes, note in cases:
            with self.subTest(changes=changes):
                ref = self.reference(); ref.update(changes)
                result = self.distance(reference=ref)
                self.assertIsNone(result['distance_since'])
                self.assertIn(note, result['distance_note'])

    def test_actual_invoice_does_not_depend_on_work_status_or_completion(self):
        parent = Row(status='入庫中', completion_date=None, is_invoice_actual=True)
        self.assertEqual(self.distance(parent=parent)['distance_since'], Decimal('200'))
        parent.is_invoice_actual = False
        self.assertIn('実施未確認', self.distance(parent=parent)['distance_note'])
        parent.completion_date = '2026-09-01'
        self.assertEqual(self.distance(parent=parent)['distance_since'], Decimal('200'))

    def test_future_completion_and_replacement_are_held_even_if_invoice_actual(self):
        parent = Row(status='完了', completion_date='2026-10-01', is_invoice_actual=True)
        self.assertIsNone(self.distance(parent=parent)['distance_since'])
        self.assertIsNone(self.distance(part=Row(replacement_date='2026-10-01', mileage=0))['distance_since'])

    def test_same_day_conflicting_meters_are_held(self):
        self.assertIn('同日', self.distance(ambiguous_mileage=True)['distance_note'])

    def test_zero_missing_and_finite_cost_rates(self):
        for current, mean in [(0, 0), (Decimal('6.66'), Decimal('5.20')), (None, 3), (-2, 5)]:
            with self.subTest(current=current):
                result = cost_comparison({'cost_per_km': current}, {'metrics': [
                    dict(unit='円/km', average=mean, sample_count=2)]})
                self.assertEqual(result['rows'][0]['value'], current)
                self.assertEqual(result['rows'][1]['value'], mean)
                for row in result['rows']:
                    self.assertTrue(0 <= row['left'] <= 100)
                    self.assertTrue(0 <= row['width'] <= 100)
        result = cost_comparison({'cost_per_km': 'NaN'}, {'metrics': [dict(unit='円/km', average='Infinity')]})
        self.assertTrue(all(row['value'] is None for row in result['rows']))

    def test_projection_does_not_mutate_aggregates_and_keeps_own_value_without_peers(self):
        summary = dict(cost_per_km=Decimal('2'), total_cost=100, distance=50)
        comparison = dict(vehicle_count=0, metrics=[])
        before = deepcopy((summary, comparison))
        result = cost_comparison(summary, comparison)
        self.assertEqual((summary, comparison), before)
        self.assertEqual(result['rows'][0]['value'], 2)
        self.assertIsNone(result['rows'][1]['value'])
        self.assertEqual(result['sample_count'], 0)
        self.assertIsNone(cost_comparison(summary, {'vehicle_count': None})['sample_count'])


class VehicleComparisonRouteTests(unittest.TestCase):
    setUpClass = classmethod(_Base.setUpClass.__func__)
    tearDownClass = classmethod(_Base.tearDownClass.__func__)
    setUp = _Base.setUp
    tearDown = _Base.tearDown

    def seed(self):
        m = self.m
        self.vehicle.model_code = 'MODEL-A'
        self.vehicle.first_registration_date = '2021-06'
        self.vehicle.deleted = False
        peers = []
        for chassis, company, year, inactive in [('P1','TEST','2021-02',False),
                    ('P2','TEST','2021-04',False), ('EMPTY','TEST','2021-01',False),
                    ('INACTIVE','TEST','2021-03',True), ('YEAR','TEST','2022-04',False),
                    ('FOREIGN','OTHER','2021-05',False)]:
            peer = m.Vehicle(company_code=company,chassis_number=chassis,model_code='MODEL-A',
                             first_registration_date=year,deleted=inactive)
            m.db.session.add(peer); peers.append(peer)
        m.db.session.flush()
        self.peers = peers
        # Current 6円/km, peers 0 and 10円/km: simple mean 5, not pooled 8.
        for index, (vehicle, cost, distance) in enumerate([(self.vehicle,600,100),
                      (peers[0],0,100),(peers[1],4000,400),(peers[3],2000,100),
                      (peers[4],3000,100),(peers[5],999999,100)]):
            m.db.session.add(m.VehicleMaintenanceRecord(company_code=vehicle.company_code,
                vehicle_record_id=vehicle.id,entry_date='2026-09-01',status='完了',total_cost=cost))
            m.db.session.add(m.VehicleOperationRecord(company_code=vehicle.company_code,
                vehicle_record_id=vehicle.id,report_number=f'UI5-{index}',
                operation_date='2026-09-30',arrival_at='2026-09-30T18:00:00+09:00',
                distance=distance,arrival_meter=1200))
        parent = m.VehicleMaintenanceRecord(company_code='TEST',vehicle_record_id=self.vehicle.id,
            entry_date='2026-09-01',total_cost=0,status='入庫中',completion_date=None,
            invoice_details_json=json.dumps({'source':{'draft_id':'synthetic-confirmed-invoice'}}))
        m.db.session.add(parent); m.db.session.flush()
        self.parent = parent
        for index,(name,meter) in enumerate([('エンジンオイル',1000),('実測差0',1200),
                                            ('未取得部品',None),('逆転部品',1500)]):
            m.db.session.add(m.VehiclePartReplacement(company_code='TEST',vehicle_record_id=self.vehicle.id,
                maintenance_record_id=parent.id,part_name=name,replacement_date='2026-09-01',
                mileage=meter,created_at='2026-09-01T00:00:00+09:00'))
        m.db.session.add(m.VehiclePartReplacement(company_code='OTHER',vehicle_record_id=self.vehicle.id,
            maintenance_record_id=parent.id,part_name='PRIVATE_FOREIGN_PART',replacement_date='2026-09-01',
            mileage=0,created_at='2026-09-01T00:00:00+09:00'))
        m.db.session.commit()
        return self.url()

    def url(self, query=''):
        return f'/vehicle/karte/{self.vehicle.id}/analysis?start_date=2026-09-01&end_date=2026-09-30' + query

    def context(self, query=''):
        from flask import template_rendered
        captured = []
        def receive(sender, template, context, **extra):
            if template.name == 'vehicle_karte_analysis.html': captured.append(context)
        template_rendered.connect(receive, self.m.app)
        try:
            response = self.client.get(self.url(query))
            self.assertEqual(response.status_code, 200)
        finally:
            template_rendered.disconnect(receive, self.m.app)
        return response.get_data(as_text=True), captured[0]

    def test_real_route_rates_boundaries_and_invoice_replacement_distance(self):
        self.seed()
        html, ctx = self.context()
        comparison = ctx['analysis_cost_comparison']
        self.assertEqual([r['value'] for r in comparison['rows']], [Decimal('6'), Decimal('5')])
        self.assertEqual(comparison['sample_count'], 2)
        self.assertEqual(ctx['analysis_comparison']['vehicle_count'],3)
        parts = {r['part_name']:r for r in ctx['analysis_part_history']}
        self.assertEqual(parts['エンジンオイル']['distance_since'],200)
        self.assertEqual(parts['実測差0']['distance_since'],0)
        self.assertIsNone(parts['未取得部品']['distance_since'])
        self.assertIsNone(parts['逆転部品']['distance_since'])
        self.assertNotIn('PRIVATE_FOREIGN_PART', html)
        self.assertIn('6.00',html);self.assertIn('5.00',html)
        self.assertIn('交換後距離',html)
        self.assertIn(f'/maintenance/{self.parent.id}',html)
        self.assertIn('2026-09-30の記録',html)
        self.assertIn('運行実績',html)
        foreign=self.peers[-1]
        self.assertEqual(self.client.get(f'/vehicle/karte/{foreign.id}/analysis').status_code,404)

    def test_conditions_and_existing_period_change_cohort(self):
        self.seed()
        _, ctx=self.context('&peer_registration=all_years&peer_inactive=1')
        self.assertEqual(ctx['analysis_comparison']['vehicle_count'],5)
        self.assertEqual(ctx['analysis_cost_comparison']['sample_count'],4)
        self.assertEqual(ctx['analysis_cost_comparison']['rows'][1]['value'],15)
        html,_=self.context()
        self.assertIn('name="start_date" value="2026-09-01"',html)
        self.assertIn('name="end_date" value="2026-09-30"',html)
        invalid=self.client.get(self.url().replace('2026-09-01','2026-10-01'))
        self.assertEqual(invalid.status_code,400)

    def test_missing_and_month_mismatch_do_not_become_zero(self):
        self.seed()
        m=self.m
        operation=m.VehicleOperationRecord.query.filter_by(vehicle_record_id=self.vehicle.id).one()
        operation.operation_date='2026-08-31';m.db.session.commit()
        html,ctx=self.context()
        self.assertIsNone(ctx['analysis_cost_comparison']['rows'][0]['value'])
        self.assertIn('算出保留',html)
        # No sample can be calculated for a cost record containing a missing value.
        m.db.session.add(m.VehicleMaintenanceRecord(company_code='TEST',vehicle_record_id=self.peers[0].id,
            entry_date='2026-09-02',status='完了',total_cost=None))
        m.db.session.commit()
        _,ctx=self.context()
        self.assertEqual(ctx['analysis_cost_comparison']['sample_count'],1)
        self.assertEqual(ctx['analysis_cost_comparison']['rows'][1]['value'],10)

    def test_same_day_conflict_and_parent_child_boundaries(self):
        self.seed();m=self.m
        m.db.session.add(m.VehiclePartReplacement(company_code='TEST',vehicle_record_id=self.vehicle.id,
            maintenance_record_id=self.parent.id,part_name='エンジンオイル',replacement_date='2026-09-01',
            mileage=1050,created_at='2026-09-01T00:00:00+09:00'))
        m.db.session.commit()
        _,ctx=self.context(); part=next(r for r in ctx['analysis_part_history'] if r['part_name']=='エンジンオイル')
        self.assertIsNone(part['distance_since']);self.assertIn('同日',part['distance_note'])
        self.parent.company_code='OTHER';m.db.session.commit()
        _,ctx=self.context();self.assertEqual(ctx['analysis_part_history'],[])

    def test_empty_panels_model_missing_and_xss_are_server_rendered(self):
        html,ctx=self.context()
        self.assertIn('対象期間の部品交換登録はありません',html)
        self.assertIn('型式が未登録',html)
        self.assertIn('ka5-rate-bars',html)
        self.seed();m=self.m
        part=m.VehiclePartReplacement.query.filter_by(company_code='TEST').first()
        part.part_name='<script>window.UI5_XSS=true</script>'
        part.part_number='<img src=x onerror=alert(1)>'
        m.db.session.commit()
        html,_=self.context()
        self.assertIn('&lt;script&gt;window.UI5_XSS=true&lt;/script&gt;',html)
        self.assertNotIn('<script>window.UI5_XSS=true</script>',html)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;',html)

# Do not rediscover the borrowed fixture class as unrelated tests.
del _Base
