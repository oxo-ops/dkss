"""Overview data consistency, state separation and source boundaries."""
import json
import unittest
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch
from test_workflow_regressions import WorkflowRegressionTests as _Workflow


class OverviewTests(unittest.TestCase):
    setUpClass = classmethod(_Workflow.setUpClass.__func__)
    tearDownClass = classmethod(_Workflow.tearDownClass.__func__)
    setUp = _Workflow.setUp
    tearDown = _Workflow.tearDown

    def context(self):
        with self.m.app.test_request_context('/'):
            return self.m.get_vehicle_karte_overview_context(self.vehicle)

    def inspection(self, performed, state='運行可', status='承認済み'):
        m = self.m
        checklist = m.Checklist(company_code='TEST', name='日常点検', target='車両管理', active=True, items_json='[]')
        m.db.session.add(checklist); m.db.session.flush()
        row = m.VehicleChecklistResult(company_code='TEST', vehicle_record_id=self.vehicle.id,
            checklist_id=checklist.id, year=str(performed.year), month=str(performed.month), day=str(performed.day),
            status=status, answers_json='[]', checklist_snapshot_json=json.dumps({'items':[
                {'fixed_template_code':'daily_inspection_truck_trailer'}]}),
            operation_judgment_json=json.dumps({'status':state,'judged_by':'判断者','judged_at':str(performed)+' 08:20:00'}))
        m.db.session.add(row); m.db.session.commit(); return row

    def test_previous_day_permission_is_not_todays_permission(self):
        today = self.m.datetime.now(self.m.ZoneInfo('Asia/Tokyo')).date()
        self.inspection(today-timedelta(days=1))
        state = self.context()['ko_inspection']
        self.assertEqual(state['judgment'], '未判定')
        self.assertEqual(state['label'], '本日の記録なし')
        self.assertEqual(state['previous_date'], str(today-timedelta(days=1)))

    def test_conflicting_today_records_do_not_select_favourable_judgment(self):
        today = self.m.datetime.now(self.m.ZoneInfo('Asia/Tokyo')).date()
        self.inspection(today,'運行不可'); self.inspection(today,'運行可')
        state = self.context()['ko_inspection']
        self.assertEqual(state['judgment'], '記録間の判断を確認')
        self.assertEqual(state['by'], '')
        self.assertIn('運行不可',state['judgment_summary'])
        self.assertTrue(state['has_unavailable'])

    def test_today_approved_is_separate_from_judgment(self):
        today = self.m.datetime.now(self.m.ZoneInfo('Asia/Tokyo')).date()
        self.inspection(today,'未判定')
        state = self.context()['ko_inspection']
        self.assertEqual(state['label'], '点検完了')
        self.assertEqual(state['judgment'], '未判定')

    def test_old_judgment_timestamp_is_not_current_even_on_today_record(self):
        today = self.m.datetime.now(self.m.ZoneInfo('Asia/Tokyo')).date()
        row = self.inspection(today)
        row.operation_judgment_json = json.dumps({'status':'運行可','judged_at':str(today-timedelta(days=1))+' 08:00:00'})
        self.m.db.session.commit()
        state = self.context()['ko_inspection']
        self.assertEqual(state['judgment'],'判断日時を確認')
        self.assertEqual(state['by'],'')

    def test_elapsed_parts_distance_and_parent_correction(self):
        m = self.m
        today = m.datetime.now(m.ZoneInfo('Asia/Tokyo')).date()
        performed = str(today-timedelta(days=30))
        parent = m.VehicleMaintenanceRecord(company_code='TEST', vehicle_record_id=self.vehicle.id,
            entry_date=performed, completion_date=performed, status='完了', mileage=1000)
        m.db.session.add(parent); m.db.session.flush()
        m.db.session.add(m.VehiclePartReplacement(company_code='TEST', vehicle_record_id=self.vehicle.id,
            maintenance_record_id=parent.id, part_name='ファンベルト', replacement_date=performed, mileage=1000, created_at=performed, updated_at=performed))
        m.db.session.add(m.VehicleOperationRecord(company_code='TEST', vehicle_record_id=self.vehicle.id,
            report_number='overview-meter', operation_date=str(today), arrival_meter=1500))
        m.db.session.commit()
        self.assertEqual(self.context()['ko_parts'][0]['distance_since'], Decimal('500'))
        parent.mileage=1200; m.db.session.commit()
        self.assertIsNone(self.context()['ko_parts'][0]['distance_since'])
        self.assertTrue(self.context()['ko_parts'][0]['needs_review'])

    def test_cost_period_matches_cost_tab_and_keeps_missing_separate(self):
        m=self.m
        today=m.datetime.now(m.ZoneInfo('Asia/Tokyo')).date()
        start=today.replace(day=1).replace(year=today.year-1)
        for stamp,amount in [(str(start),100),(str(today),900),(str(start),None),('',500)]:
            m.db.session.add(m.VehicleMaintenanceRecord(company_code='TEST', vehicle_record_id=self.vehicle.id,
                entry_date=stamp, total_cost=amount))
        m.db.session.commit()
        cost=self.context()['ko_cost']
        self.assertEqual(cost['total'],Decimal('100'))
        self.assertEqual((cost['count'],cost['missing'],cost['undated']),(2,1,1))
        with m.app.test_request_context('/'):
            detailed=m.get_vehicle_maintenance_cost_details(m.VehicleMaintenanceRecord.query.all(),today.year)
        self.assertEqual(cost['total'],detailed['rolling_average']*12)

    def test_files_are_limited_business_rows_and_registration_date_is_labelled(self):
        m=self.m
        stamp=m.datetime.now(m.ZoneInfo('UTC'))
        docs=[dict(draft_id=f'doc{i}',filename=f'file{i}.pdf',created_by_username='admin',
                   document_type='inspection',completed_at=stamp,records=[]) for i in range(5)]
        docs.insert(0,dict(draft_id='csv',filename='report.csv',created_by_username='admin',
                          document_type='operation_csv',completed_at=stamp,records=[]))
        with patch.object(m,'get_vehicle_karte_documents',return_value=docs):
            result=self.context()
        self.assertEqual(result['karte_document_count'],6)
        self.assertEqual(result['ko_business_document_count'],5)
        self.assertEqual(len(result['karte_recent_documents']),3)
        self.assertTrue(all(r['kind']!='operation_csv' for r in result['karte_recent_documents']))
        self.assertTrue(all(r['date_kind']=='登録日' and r['business_date'] is None for r in result['karte_recent_documents']))

    def test_standalone_open_maintenance_and_failure_are_not_omitted(self):
        m=self.m
        for status in ('整備中','完了'):
            m.db.session.add(m.VehicleMaintenanceRecord(company_code='TEST',vehicle_record_id=self.vehicle.id,
                status=status,content='独立整備'+status,entry_date='2026-09-01'))
        for status in ('未対応','修理完了'):
            m.db.session.add(m.VehiclePatrol(company_code='TEST',vehicle_record_id=self.vehicle.id,
                status=status,content='故障'+status,priority='高',occurred_date='2026-09-01'))
        m.db.session.commit()
        actions=self.context()['ko_actions']
        self.assertEqual(len(actions),2)
        self.assertEqual(actions[0]['label'],'故障未対応')
        self.assertEqual({row['status'] for row in actions},{'未対応','整備中'})

    def test_overview_read_does_not_schedule_or_execute_ai(self):
        with patch.object(self.m,'analyze_vehicle_karte',side_effect=AssertionError('No AI')), \
             patch.object(self.m,'queue_vehicle_karte_analysis',side_effect=AssertionError('No scheduling')):
            response=self.client.get(f'/vehicle/karte/{self.vehicle.id}')
        self.assertEqual(response.status_code,200)
        html=response.get_data(as_text=True)
        self.assertIn('次の点検・入庫予定',html)
        self.assertIn('予防整備の提案',html)
        self.assertNotIn('vehicle_karte_mileage_chart',html)
        self.assertNotIn('部品交換の回数',html)
        self.assertEqual(self.m.VehicleKarteAnalysis.query.count(),0)

    def test_parts_group_only_same_documented_exchange(self):
        m = self.m
        parents = []
        for i in range(2):
            row = m.VehicleMaintenanceRecord(company_code='TEST', vehicle_record_id=self.vehicle.id,
                entry_date='2026-09-01', completion_date='2026-09-01', status='完了', mileage=1000)
            m.db.session.add(row); m.db.session.flush(); parents.append(row)
        for parent, name in [(parents[0], '部品A'), (parents[0], '部品B'), (parents[1], '部品C')]:
            m.db.session.add(m.VehiclePartReplacement(company_code='TEST', vehicle_record_id=self.vehicle.id,
                maintenance_record_id=parent.id, part_name=name, replacement_date='2026-09-01',
                mileage=1000, created_at='2026-09-01', updated_at='2026-09-01'))
        m.db.session.commit()
        batches = self.context()['ko_part_batches']
        self.assertEqual(sorted(len(b['parts']) for b in batches), [1, 2])
        self.assertEqual({p['part_name'] for b in batches for p in b['parts']}, {'部品A', '部品B', '部品C'})

    def test_cost_bars_use_period_total_and_hide_signed_amounts(self):
        m = self.m
        today = m.datetime.now(m.ZoneInfo('Asia/Tokyo')).date()
        stamp = str(today.replace(day=1) - timedelta(days=1))
        rows = []
        for amount in (900, 100):
            row = m.VehicleMaintenanceRecord(company_code='TEST', vehicle_record_id=self.vehicle.id,
                entry_date=stamp, total_cost=amount)
            m.db.session.add(row); rows.append(row)
        m.db.session.commit()
        self.assertEqual([b['share'] for b in self.context()['ko_cost']['bars']], [90.0, 10.0])
        rows[1].total_cost = -100; m.db.session.commit()
        self.assertTrue(all(b['share'] is None for b in self.context()['ko_cost']['bars']))

    def test_elapsed_reservation_requires_confirmation_not_completion(self):
        m = self.m
        today = m.datetime.now(m.ZoneInfo('Asia/Tokyo')).date()
        plans = {'3month': {'reservation_date': str(today - timedelta(days=1))},
                 '12month': {'planned_month': today.strftime('%Y-%m')}}
        with patch.object(m.inspection_plans, 'summary', return_value=plans), \
             patch.object(m.inspection_plans, 'latest', return_value={}):
            appointments = self.context()['ko_appointments']
        self.assertEqual(appointments[0]['state'], '予約済み')
        self.assertEqual(appointments[0]['relative'], '予約日経過・実施確認')
        self.assertEqual(appointments[0]['actual'], {})
        self.assertEqual(appointments[1]['relative'], '今月の予定')
        self.assertEqual(appointments[2]['state'], '未設定')

    def test_overview_rejects_other_company(self):
        m=self.m
        other=m.Vehicle(company_code='OTHER',chassis_number='PRIVATE')
        m.db.session.add(other);m.db.session.commit()
        self.assertEqual(self.client.get(f'/vehicle/karte/{other.id}').status_code,404)


if __name__ == '__main__':
    unittest.main()
