import re,unittest
from pathlib import Path
R=Path(__file__).resolve().parents[1]
class CreateActions(unittest.TestCase):
 def test_entry_labels_and_links(self):
  items={'office_master':'/master/offices/new','vehicle_type_master':'/master/vehicle-types/new','license_type_master':'/master/license-types/new','delivery_place_master':'/master/delivery-places/new','manual_master':'/master/manuals/new','patrol_content_type_master':'/master/patrol-content-types/new','vehicle_patrols':'/vehicle-patrols/new','pointouts':"url_for('new_pointout', target_type=view_type)",'safety_checklist_results':'/safety/checklists/{{ checklist_index }}/new'}
  for name,url in items.items():
   with self.subTest(name=name):
    text=(R/'templates'/f'{name}.html').read_text()
    tags=re.findall(r'<a\b[^>]*>.*?</a>',text,re.S)
    tag=next(x for x in tags if url in x)
    self.assertIn('entry-add-icon',tag);self.assertIn('aria-label=',tag);self.assertIn('title=',tag)
    self.assertIn('<span aria-hidden="true">＋</span>',tag)
    self.assertNotRegex(text,r'>\s*(?:＋\s*)?新規登録\s*</a>')
 def test_compact_master_row(self):
  for name in ['office_master','vehicle_type_master','license_type_master']:
   text=(R/'templates'/f'{name}.html').read_text()
   self.assertIn('master-list-actions',text);self.assertNotIn('class="page-header"',text)
 def test_no_backend_changes_required(self):
  css=(R/'static/css/entry_add_icon.css').read_text()
  self.assertIn('min-width:44px',css);self.assertIn(':focus-visible',css)
if __name__=='__main__':unittest.main()
