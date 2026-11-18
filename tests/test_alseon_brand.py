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
        desktop, mobile = css.split('@media (max-width: 900px)', 1)
        self.assertNotIn('.sidebar {', desktop)
        self.assertIn('width: var(--app-drawer-width);', mobile)
        self.assertIn('min-width: var(--app-drawer-width);', mobile)
        self.assertIn('padding-right: 68px;', mobile)

    def test_transparent_tile_and_original_toggle_hover(self):
        css = (ROOT / 'static/css/alseon_brand.css').read_text()
        self.assertIn('background: transparent;', css)
        self.assertNotIn('background: #fff;', css)
        self.assertIn('.sidebar-head .sidebar-toggle:hover,', css)
        self.assertIn('background: rgba(15, 23, 42, 0.18);', css)

    def test_dark_display_maps_color_without_changing_alpha(self):
        import re
        html = (ROOT / 'templates/base.html').read_text()
        fragment = (ROOT / 'templates/_alseon_brand_filter.html').read_text()
        css = (ROOT / 'static/css/alseon_brand.css').read_text()
        self.assertIn('{% include "_alseon_brand_filter.html" %}', html)
        self.assertIn('filter: url(#alseon-dark-logo);', css)
        self.assertIn('color-interpolation-filters="sRGB"', fragment)
        self.assertNotIn('drop-shadow(', css)
        matrix = [float(v) for v in re.search(r'values="([^"]+)"', fragment).group(1).split()]
        def apply(rgb):
            vec = [v / 255 for v in rgb] + [1]
            return [round(max(0, min(1, sum(matrix[i*5+j]*vec[j] for j in range(5))))*255) for i in range(4)]
        self.assertEqual(apply([1,33,74,255]), [255,255,255,255])
        self.assertEqual(apply([0,81,252,255]), [0,81,252,255])
        for alpha in [0,1,64,128,254,255]:
            self.assertEqual(apply([1,33,74,alpha])[3], alpha)

    def test_source_png_bytes_preserved(self):
        import hashlib
        expected = {
            'symbol': '38f6e455953f0f1ef076b860cb463b0b9bf75e86853f8b11d943f46c4759e213',
            'wordmark': '16794865f763e7c7752ed1ebcd9da6d775381609146379a08cc667b509f8e24e',
        }
        for name, digest in expected.items():
            self.assertEqual(hashlib.sha256((ROOT / f'static/images/alseon/{name}.png').read_bytes()).hexdigest(), digest)

    def test_brand_shrinks_without_clipping_toggle(self):
        css = (ROOT / 'static/css/alseon_brand.css').read_text()
        self.assertIn('flex: 0 1 164px;', css)
        self.assertIn('min-width: 0;', css)
        self.assertIn('max-width: 100%;', css)
        self.assertIn('width: 106.756757%;', css)

if __name__ == '__main__':
    unittest.main()
