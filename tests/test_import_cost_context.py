"""Keep accepted receipt context across maintenance/cost tabs without writes."""
import json
import unittest
from test_q07_cost_display_consistency import CostDisplayConsistencyTests as Fixture
from dkss_app.models import VehicleDocumentImportDraft as Draft

class ImportCostContextTests(unittest.TestCase):
    setUpClass = classmethod(Fixture.setUpClass.__func__)
    tearDownClass = classmethod(Fixture.tearDownClass.__func__)
    setUp = Fixture.setUp
    tearDown = Fixture.tearDown
    maintenance = Fixture.maintenance
    page = Fixture.page

    def receipt(self, row, **kwargs):
        values = dict(id='cost-receipt', batch_id='cost-batch', company_code='TEST',
            created_by_username='admin', document_type='maintenance', status='completed',
            source_filename='fixture.pdf', source_sha256='0'*64, source_file=b'', result_json=json.dumps({'records':[
                {'document_type':'maintenance','record_id':row.id,'vehicle_record_id':row.vehicle_record_id}]}))
        values.update(kwargs)
        receipt = Draft(**values)
        self.m.db.session.add(receipt); self.m.db.session.commit()
        return receipt

    def test_valid_context_preserves_tabs_year_and_detail_and_does_not_write(self):
        row = self.maintenance(3080, content='電球交換')
        self.receipt(row)
        before = Draft.query.one().result_json
        context, html = self.page('costs', import_batch='cost-batch')
        self.assertEqual([r.id for r in context['imported_records']], [row.id])
        self.assertIn('今回取り込んだ整備の費用', html)
        self.assertIn('name="import_batch" value="cost-batch"', html)
        self.assertIn(f'/vehicle/karte/{self.vehicle.id}/maintenance/{row.id}?import_batch=cost-batch', html)
        self.assertIn(f'/vehicle/karte/{self.vehicle.id}/maintenance?import_batch=cost-batch', html)
        _, maintenance_html = self.page('maintenance', import_batch='cost-batch')
        self.assertIn(f'/vehicle/karte/{self.vehicle.id}/costs?import_batch=cost-batch', maintenance_html)
        self.page('costs', import_batch='cost-batch')
        self.assertEqual(before, Draft.query.one().result_json)
        self.assertEqual(self.m.VehicleMaintenanceRecord.query.count(), 1)

    def test_other_annual_records_remain_accessible_outside_receipt_scope(self):
        imported = self.maintenance(100, content='今回登録')
        other = self.maintenance(200, content='以前の整備')
        self.receipt(imported)
        _, html = self.page('costs', import_batch='cost-batch')
        imported_link = f'/vehicle/karte/{self.vehicle.id}/maintenance/{imported.id}?import_batch=cost-batch'
        other_link = f'/vehicle/karte/{self.vehicle.id}/maintenance/{other.id}'
        self.assertIn(f'href="{imported_link}"', html)
        self.assertIn(f'href="{other_link}"', html)
        self.assertNotIn(f'{other_link}?import_batch=', html)
        self.assertEqual(self.client.get(imported_link).status_code, 200)
        self.assertEqual(self.client.get(other_link).status_code, 200)

    def test_default_page_unchanged_and_unknown_amount_not_invented(self):
        row = self.maintenance(None)
        self.receipt(row)
        _, normal = self.page('costs')
        self.assertNotIn('今回取り込んだ整備の費用', normal)
        context, html = self.page('costs', import_batch='cost-batch')
        self.assertIsNone(context['imported_records'][0].total_cost)
        self.assertNotIn('登録前の累計', html)
        self.assertIn('kc-unset', html)

    def test_guest_and_other_company_vehicle_cannot_open_context(self):
        row = self.maintenance(1234)
        self.receipt(row)
        other = self.m.Vehicle(company_code='FOREIGN', chassis_number='FOREIGN-001')
        self.m.db.session.add(other); self.m.db.session.commit()
        self.assertEqual(self.client.get(f'/vehicle/karte/{other.id}/costs?import_batch=cost-batch').status_code, 404)
        with self.client.session_transaction() as session:
            session.clear()
        self.assertIn(self.client.get(f'/vehicle/karte/{self.vehicle.id}/costs?import_batch=cost-batch').status_code, (302, 303))

    def test_unknown_foreign_owner_company_and_vehicle_are_not_disclosed(self):
        row = self.maintenance(1234)
        path = f'/vehicle/karte/{self.vehicle.id}/costs'
        self.assertEqual(self.client.get(path+'?import_batch=missing').status_code,404)
        draft = self.receipt(row, created_by_username='someone-else')
        self.assertEqual(self.client.get(path+'?import_batch=cost-batch').status_code,404)
        self.m.db.session.delete(draft);self.m.db.session.commit()
        draft = self.receipt(row, company_code='FOREIGN')
        self.assertEqual(self.client.get(path+'?import_batch=cost-batch').status_code,404)
        self.m.db.session.delete(draft);self.m.db.session.commit()
        self.receipt(row)
        other = self.m.Vehicle(company_code='TEST', chassis_number='OTHER')
        self.m.db.session.add(other);self.m.db.session.commit()
        self.assertEqual(self.client.get(f'/vehicle/karte/{other.id}/costs?import_batch=cost-batch').status_code,404)

if __name__ == '__main__': unittest.main()
