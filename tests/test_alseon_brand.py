"""Static brand contract; real browser visual acceptance remains separate."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class AlseonBrandTests(unittest.TestCase):
    def test_brand_anchor_and_assets(self):
        html = (ROOT / 'templates/base.html').read_text()
        self.assertIn('aria-label="ALSEON ホーム"', html)
        self.assertNotIn('<span class="logo-mark">L</span>', html)
        self.assertNotIn('<span class="logo-text">LOGO</span>', html)
        for name in ('wordmark', 'symbol'):
            self.assertIn(f"images/alseon/{name}.png", html)
            self.assertTrue((ROOT / f'static/images/alseon/{name}.png').is_file())

    def test_exclusive_display_with_mobile_reset(self):
        css = (ROOT / 'static/css/alseon_brand.css').read_text()
        self.assertIn('@media (min-width: 901px)', css)
        self.assertIn('body.sidebar-collapsed .alseon-wordmark { display: none; }', css)
        self.assertIn('body.sidebar-collapsed .alseon-symbol { display: block; }', css)
        self.assertIn('@media (max-width: 900px)', css)
        self.assertIn('body.sidebar-collapsed .alseon-wordmark { display: block; }', css)
        self.assertIn('body.sidebar-collapsed .alseon-symbol { display: none; }', css)
        self.assertNotIn('.sidebar {', css)

if __name__ == '__main__':
    unittest.main()
