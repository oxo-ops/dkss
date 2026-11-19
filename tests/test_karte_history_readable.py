from pathlib import Path
import unittest
from jinja2 import Environment,FileSystemLoader,select_autoescape
class HistoryReadable(unittest.TestCase):
 def test_two_character_units(self):
  root=Path(__file__).resolve().parents[1]
  macro=Environment(loader=FileSystemLoader(root/'templates'),autoescape=select_autoescape()).get_template('vehicle_history_symbol.html').module.history_symbol
  for word,a,b in [('日常点検','日常','点検'),('点検予定','点検','予定')]:
   value=str(macro(word));self.assertIn('>'+a+'</span><wbr><span class="history-kind-unit">'+b+'</span>',value)
  self.assertNotIn('history-kind-unit',str(macro('異常・指摘')))
  self.assertIn('&lt;script&gt;',str(macro('<script>')))
 def test_links_and_warnings_are_not_removed(self):
  root=Path(__file__).resolve().parents[1]
  css=(root/'static/css/karte_history_readable.css').read_text()
  self.assertIn(':focus-visible',css);self.assertIn(':hover',css)
  self.assertNotIn('vehicle-history-status',css)
  self.assertNotIn('display:none',css)
