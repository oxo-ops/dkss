"""Presentation contracts: preserve existing shared styling and upload behavior."""
from pathlib import Path
import unittest
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]

class Tags(HTMLParser):
    def __init__(self):
        super().__init__(); self.tags = []
    def handle_starttag(self, name, attrs):
        self.tags.append((name, dict(attrs)))

class InspectionDetailButtonLayoutTests(unittest.TestCase):
    def setUp(self):
        self.css = (ROOT / 'static/css/vehicle_checklist_compact.css').read_text()
        html = (ROOT / 'templates/vehicle_checklist_results.html').read_text()
        self.modal = html.split('<div id="detailModal"', 1)[1].split('<div id="vehicleRejectModal"', 1)[0]
        parser = Tags(); parser.feed(self.modal); self.tags = parser.tags

    def test_both_attachment_controls_keep_native_input_contract(self):
        inputs = [a for t,a in self.tags if t == 'input' and a.get('type') == 'file']
        self.assertEqual(len(inputs), 2)
        self.assertEqual(inputs[0]['capture'], 'environment')
        self.assertEqual(inputs[0]['accept'], 'image/*')
        self.assertEqual(inputs[1]['accept'], 'image/*,video/*,.pdf')
        self.assertIn('multiple', inputs[1])
        for attrs in inputs:
            self.assertEqual(attrs['name'], 'files')
            self.assertIn('js-detail-file-input', attrs['class'])
        icons = [a for t,a in self.tags if t == 'svg']
        self.assertEqual(len(icons), 2)
        for attrs in icons:
            self.assertEqual(attrs['aria-hidden'], 'true')
            self.assertEqual(attrs['focusable'], 'false')
            self.assertEqual(attrs['stroke'], 'currentColor')

    def test_save_close_and_permissions_are_preserved(self):
        buttons = [a for t,a in self.tags if t == 'button']
        self.assertEqual([b['type'] for b in buttons], ['submit', 'button'])
        self.assertIn('js-close-detail-modal', buttons[1]['class'])
        self.assertIn('multipart/form-data', self.modal)
        self.assertIn('/save-detail', self.modal)
        self.assertIn('name="csrf_token"', self.modal)
        self.assertIn('.file-upload-button[hidden] { display: none; }', self.css)
        self.assertIn('.btn[hidden] + .js-close-detail-modal { grid-column: 1 / -1; }', self.css)

    def test_compact_consistent_touch_geometry_without_new_color_scheme(self):
        self.assertIn('min-height: 48px;', self.css)
        self.assertIn('height: 48px;', self.css)
        self.assertIn('grid-template-columns: repeat(2, minmax(0, 1fr));', self.css)
        self.assertNotIn('width: 96px', self.css)
        self.assertIn('grid-column: 1 / -1;', self.css)
        self.assertIn('#detailModal #detailCommentEditor { min-height: 110px; }', self.css)
        shared = (ROOT / 'static/css/style.css').read_text()
        for color in ('#d4dcf3', '#f5f5ff', '#405589', '#bdb4f3', '#eeebff'):
            self.assertIn(color, self.css)
            self.assertIn(color, shared)
        self.assertNotIn('background: var(--dkss-action-blue)', self.css)

if __name__ == '__main__':
    unittest.main()
