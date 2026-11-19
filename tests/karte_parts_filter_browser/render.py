"""Disposable SQLite parts rows for native filter acceptance; no deployed data."""
import importlib.util,os,sys,unittest
from pathlib import Path
root=Path(os.environ['PRODUCT_REPO']);spec=importlib.util.spec_from_file_location('parts_filter_base',root/'tests/header_mobile_browser/render_pages.py');base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
class Parts(base.ActionPages):
 def test_parts(self):
  super().test_action_pages()
  self.demo_active=True;self.login('admin');m=self.models
  parent=m.VehicleMaintenanceRecord.query.filter_by(company_code='AONAGI',vehicle_record_id=self.vehicle_id).first()
  self.db.session.add(m.VehiclePartReplacement(company_code='AONAGI',vehicle_record_id=self.vehicle_id,maintenance_record_id=parent.id,part_name='タイヤ',replacement_date='2026-11-18',mileage=1000,created_at='2026-11-18',updated_at='2026-11-18'))
  self.db.session.commit()
  response=self.client.get(f'/vehicle/karte/{self.vehicle_id}/parts');self.assertEqual(response.status_code,200);self.assertIn('kp-part-link',response.text)
  (Path(os.environ['HTML_OUT'])/'vehicle_karte_parts.html').write_text(response.text)
if __name__=='__main__':
 result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([Parts('test_parts')]));sys.exit(not result.wasSuccessful())
