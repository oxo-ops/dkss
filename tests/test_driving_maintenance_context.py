"""Vehicle cost/elapsed facts stay bounded, factual, and separate from driver blame."""
import json
import unittest
from decimal import Decimal
from types import SimpleNamespace
import test_driving_workspace as workspace_tests
from driving_report_data import payload
from driving_report_insights import driver_keys
from driving_report_maintenance import cost_summary, build
from dkss_app.models import VehicleMaintenanceRecord, VehiclePartReplacement


class MaintenanceContextTests(unittest.TestCase):
    setUpClass=classmethod(workspace_tests.WorkspaceTests.setUpClass.__func__)
    tearDownClass=classmethod(workspace_tests.WorkspaceTests.tearDownClass.__func__)
    setUp=workspace_tests.WorkspaceTests.setUp
    tearDown=workspace_tests.WorkspaceTests.tearDown
    save=workspace_tests.WorkspaceTests.save
    render=workspace_tests.WorkspaceTests.render

    def maintenance(self, **kwargs):
        values=dict(company_code='TEST',vehicle_record_id=self.vehicle.id,entry_date='2026-10-01',
                    completion_date='2026-10-01',status='完了',mileage=1000,content='クラッチ交換',total_cost=50000)
        values.update(kwargs)
        row=VehicleMaintenanceRecord(**values);self.m.db.session.add(row);self.m.db.session.flush()
        return row

    def part(self,parent,**kwargs):
        values=dict(company_code='TEST',vehicle_record_id=self.vehicle.id,maintenance_record_id=parent.id,
                    part_name='クラッチ',replacement_date='2026-10-01',mileage=1000,created_at='2026-10-01')
        values.update(kwargs)
        row=VehiclePartReplacement(**values);self.m.db.session.add(row);self.m.db.session.flush()
        return row

    def test_vehicle_context_elapsed_cost_and_future_exclusion(self):
        parent=self.maintenance();self.part(parent)
        future=self.maintenance(completion_date='2026-11-01',entry_date='2026-11-01',total_cost=900000)
        self.part(future,replacement_date='2026-11-01',mileage=1300)
        p=payload(self.a);p['mileage']='1200';self.a.details_json=json.dumps(p);self.m.db.session.commit()
        key=driver_keys([self.a])[0][self.a.id]
        _,context=self.render('/safety/driving-reports?period=custom&start=2026-10-01&end=2026-10-26&focus='+key)
        vehicle=context['vehicle_history'][0]['context']
        self.assertEqual(Decimal(vehicle['cost']['total']),50000)
        self.assertEqual(vehicle['parts'][0]['distance_since'],'200.00')
        self.assertEqual(vehicle['parts'][0]['days_since'],25)
        self.assertEqual(vehicle['parts'][0]['date'],'2026-10-01')
        export=self.client.get('/safety/driving-reports/export.csv?period=custom&start=2026-10-01&end=2026-10-26&view=maintenance&focus='+key)
        self.assertEqual(export.status_code,200)
        self.assertIn('50000',export.data.decode('utf-8-sig'))
        self.assertNotIn('900000',export.data.decode('utf-8-sig'))

    def test_duplicate_invoice_is_once_and_conflicting_amounts_are_held(self):
        first=self.maintenance(invoice_number='INVOICE-1',invoice_date='2026-10-01',maintenance_company='工場')
        second=self.maintenance(invoice_number='INVOICE-1',invoice_date='2026-10-01',maintenance_company='工場')
        summary=cost_summary([first,second],'2026-10-01','2026-10-26')
        self.assertEqual(Decimal(summary['total']),50000);self.assertEqual(summary['count'],1)
        second.total_cost=Decimal(60000)
        summary=cost_summary([first,second],'2026-10-01','2026-10-26')
        self.assertIsNone(summary['total']);self.assertEqual(summary['held'],2)

    def test_reset_or_parent_mismatch_holds_elapsed_distance(self):
        parent=self.maintenance();part=self.part(parent)
        op=SimpleNamespace(id=1,company_code='TEST',vehicle_record_id=self.vehicle.id,arrival_meter=900,
                           operation_date='2026-10-10',arrival_at='2026-10-10T09:00:00')
        context=build(self.vehicle,[parent],[part],[op],[],'2026-10-01','2026-10-26')
        self.assertIsNone(context['parts'][0]['distance_since'])
        part.mileage=Decimal(800)
        context=build(self.vehicle,[parent],[part],[op],[],'2026-10-01','2026-10-26')
        self.assertTrue(context['parts'][0]['needs_review'])
        self.assertIsNone(context['parts'][0]['days_since'])
        self.assertIsNone(context['parts'][0]['distance_since'])

    def test_synthetic_and_other_company_records_never_enter_context(self):
        synthetic=self.maintenance(notes='テスト用資料・支払不要(発行元・取引内容は架空です)')
        part=self.part(synthetic)
        foreign=self.maintenance(company_code='OTHER',total_cost=999999)
        context=build(self.vehicle,[synthetic,foreign],[part],[],[],'2026-10-01','2026-10-26')
        self.assertIsNone(context['cost']['total']);self.assertEqual(context['parts'],[])

    def test_part_change_invalidates_ai_input_even_without_report_change(self):
        parent=self.maintenance();part=self.part(parent);self.m.db.session.commit()
        key=driver_keys([self.a])[0][self.a.id]
        url='/safety/driving-reports/reflection?period=all&focus='+key
        first=self.client.get(url).json['key']
        part.mileage=Decimal(700);self.m.db.session.commit()
        self.assertNotEqual(first,self.client.get(url).json['key'])


if __name__=='__main__':unittest.main()
