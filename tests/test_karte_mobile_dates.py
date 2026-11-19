import unittest
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
import re
from html import unescape
class Dates(unittest.TestCase):
 def setUp(self):
  self.env=Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[1]/'templates'),autoescape=select_autoescape())
 def test_date_and_time_shortened_mobile_only(self):
  macro=self.env.get_template('vehicle_karte_date.html').module.karte_date
  for value,expected in [('2026-11-23','11/23'),('2026-11-23 10:24:59','11/23'),('2025/01/02','01/02'),(None,'—'),('未定','未定')]:
   with self.subTest(value=value):
    html=str(macro(value))
    self.assertEqual(unescape(re.search(r'<span class="karte-date-mobile"[^>]*>(.*?)</span>',html).group(1)),expected)
    self.assertEqual(unescape(re.search(r'<span class="karte-date-desktop"[^>]*>(.*?)</span>',html).group(1)),value or '—')
 def test_untrusted_text_escaped(self):
  html=str(self.env.get_template('vehicle_karte_date.html').module.karte_date('<script>bad</script>'))
  self.assertNotIn('<script>',html)
 def test_mobile_scope_and_original_data_preserved(self):
  root=Path(__file__).resolve().parents[1]
  css=(root/'static/css/vehicle_karte_dates.css').read_text()
  self.assertIn('@media(max-width:768px)',css)
  maintenance=(root/'templates/vehicle_karte_maintenance.html').read_text()
  self.assertIn('record.entry_date',maintenance)
  self.assertIn('record.completion_date',maintenance)
  self.assertIn('karte-date-duplicate',maintenance)
if __name__=='__main__':unittest.main()
