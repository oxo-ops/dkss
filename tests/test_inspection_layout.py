"""Vehicle search and PPT inspection workspace regressions on real Flask routes."""
import json
import unittest
from test_inspection_plans import InspectionPlanTests as _Base


class InspectionLayoutTests(unittest.TestCase):
    setUpClass = classmethod(_Base.setUpClass.__func__)
    tearDownClass = classmethod(_Base.tearDownClass.__func__)
    setUp = _Base.setUp
    tearDown = _Base.tearDown
    upload_inspection = _Base.upload_inspection
    inspection_form = _Base.inspection_form
    import_record = _Base.import_record

    def daily(self, day='01', answer='○'):
        m = self.m
        checklist = m.Checklist(company_code='TEST', name='日常点検', target='車両管理', active=True, items_json='[]')
        m.db.session.add(checklist);m.db.session.flush()
        row = m.VehicleChecklistResult(company_code='TEST', checklist_id=checklist.id, vehicle_record_id=self.vehicle.id,
            year='2026', month='10', day=day, checked_date=f'2026-10-{day} 09:00', status='承認済み',
            answers_json=json.dumps([{'content':'制動装置','value':answer}]), checklist_snapshot_json='{}')
        m.db.session.add(row);m.db.session.commit()
        return row

    def test_plate_search_matches_full_registration_spacing_width_and_last_digits(self):
        m = self.m
        for n in range(25):
            m.db.session.add(m.Vehicle(company_code='TEST', chassis_number='EARLY-'+str(n)))
        m.db.session.commit()
        self.vehicle.plate_area='とちぎ';self.vehicle.plate_class='130';self.vehicle.plate_kana='あ';self.vehicle.plate_number='5306'
        m.db.session.commit()
        for keyword in ['とちぎ130あ5306','とちぎ 130 あ 5306','とちぎ１３０あ５３０６','５３０６','TEST-001']:
            response=self.client.get('/api/vehicles',query_string={'q':keyword})
            self.assertEqual(response.status_code,200)
            self.assertIn(self.vehicle.id,[r['id'] for r in response.json['results']],keyword)

    def test_search_excludes_other_companies_and_deleted_vehicles_and_searches_past_limit(self):
        m = self.m
        for n in range(25):m.db.session.add(m.Vehicle(company_code='TEST',chassis_number='EARLY-'+str(n)))
        m.db.session.commit()
        match=m.Vehicle(company_code='TEST',plate_number='5306',chassis_number='LAST-MATCH')
        m.db.session.add_all([match,m.Vehicle(company_code='FOREIGN',plate_number='5306',chassis_number='OTHER'),m.Vehicle(company_code='TEST',plate_number='5306',chassis_number='DELETED',deleted=True)])
        m.db.session.commit()
        response=self.client.get('/api/vehicles?q=5306')
        self.assertEqual([r['id'] for r in response.json['results']],[match.id])
        self.assertEqual(len(self.client.get('/api/vehicles').json['results']),20)

    def test_default_displays_both_tables_and_category_navigation(self):
        self.daily();record=self.import_record()
        html=self.client.get(f'/vehicle/karte/{self.vehicle.id}/inspections').get_data(as_text=True)
        self.assertIn('aria-current="page">すべての点検',html)
        self.assertIn('<h3>日常点検</h3>',html)
        self.assertIn('id="periodic-record-'+str(record.id)+'"',html)
        for label in ['3か月点検','12か月点検','車検','実施者・整備会社','次回予定']:self.assertIn(label,html)
        self.assertNotIn('点検の予定はヘッダーから編集できます',html)

    def test_type_and_date_filters_select_records_on_server(self):
        record=self.import_record('2026-09-12','2026-12')
        second=self.import_record('2026-10-12','2027-01');second.inspection_type='12month';self.m.db.session.commit()
        self.daily('01');self.daily('12')
        base=f'/vehicle/karte/{self.vehicle.id}/inspections'
        html=self.client.get(base+'?inspection_view=3month').get_data(as_text=True)
        self.assertIn(f'id="periodic-record-{record.id}"',html);self.assertNotIn(f'id="periodic-record-{second.id}"',html)
        html=self.client.get(base+'?start_date=2026-10-01&end_date=2026-10-05').get_data(as_text=True)
        workspace=html.split('class="vi-workspace"',1)[1]
        self.assertIn('2026-10-01 09:00',workspace);self.assertNotIn('2026-10-12 09:00',workspace)
        self.assertNotIn(f'id="periodic-record-{record.id}"',workspace);self.assertNotIn(f'id="periodic-record-{second.id}"',workspace)
        self.assertIn('name="start_date" value="2026-10-01"',workspace)

    def test_incomplete_daily_answers_are_not_labeled_normal(self):
        self.daily(answer='')
        workspace=self.client.get(f'/vehicle/karte/{self.vehicle.id}/inspections?inspection_view=daily').get_data(as_text=True).split('class="vi-workspace"',1)[1]
        self.assertNotIn('>問題なし<',workspace)
        self.assertIn('回答なし',workspace)

    def test_certificate_view_uses_registered_expiry_without_inventing_completion(self):
        self.vehicle.inspection_expiry='2027-03-22';self.m.db.session.commit()
        workspace=self.client.get(f'/vehicle/karte/{self.vehicle.id}/inspections?inspection_view=certificate').get_data(as_text=True).split('class="vi-workspace"',1)[1]
        self.assertIn('2027-03-22',workspace);self.assertIn('車検証・書類を開く',workspace)
        self.assertNotIn('>良好<',workspace);self.assertNotIn('<h3>日常点検</h3>',workspace)


del _Base
