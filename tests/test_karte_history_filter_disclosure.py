import unittest
from pathlib import Path
class HistoryFilterDisclosureTests(unittest.TestCase):
 def test_fields_and_category_contract_preserved(self):
  import hashlib
  p='templates/vehicle_karte_history.html'
  new=Path(p).read_text()
  def form(s):return s[s.index('        <form\n'):s.index('        </form>')+len('        </form>')]
  self.assertEqual(hashlib.sha256(form(new).encode()).hexdigest(),'48e35dfe6903dc549002bdcd2e86fb8cd52a44a24c5976a9634170023ca03751')
  for marker in ['vehicle-history-categories','history-category-help']:
   self.assertIn(marker,new)
 def test_progressive_enhancement(self):
  s=Path('templates/vehicle_karte_history.html').read_text()
  self.assertIn('<details class="karte-history-filter-disclosure" open>',s)
  self.assertIn('selected_event_type or selected_status or selected_start_date or selected_end_date',s)
  j=Path('static/js/karte_history_filter_disclosure.js').read_text()
  self.assertIn('panel.open=!mobile.matches',j)
  self.assertNotIn('fetch(',j)
if __name__=='__main__':unittest.main()
