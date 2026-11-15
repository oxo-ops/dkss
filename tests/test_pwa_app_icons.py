"""PWA asset regression checks. Not a browser installability certification."""
import hashlib
import json
from pathlib import Path
import unittest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]

class PwaAppIconTests(unittest.TestCase):
    def test_manifest_uses_dedicated_correctly_sized_assets(self):
        manifest = json.loads((ROOT / 'static/manifest.webmanifest').read_text())
        for size in (192, 512):
            with self.subTest(size=size):
                entries = [i for i in manifest['icons'] if i.get('sizes') == f'{size}x{size}']
                self.assertEqual(len(entries), 1)
                icon = entries[0]
                self.assertEqual(icon['src'], f'/static/icons/app-{size}.png')
                self.assertEqual(icon['type'], 'image/png')
                self.assertEqual(icon.get('purpose', 'any'), 'any')
                with Image.open(ROOT / icon['src'].lstrip('/')) as image:
                    image.load()
                    self.assertEqual(image.format, 'PNG')
                    self.assertEqual(image.size, (size, size))
                    self.assertEqual(image.mode, 'RGBA')
    def test_original_notification_asset_preserved(self):
        raw = (ROOT / 'static/icons/notification.png').read_bytes()
        self.assertEqual(hashlib.sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest(),
                         'e5927ed9d851d7fa9d4d0c8626a9b4dd116dcf34')
    def test_app_launch_configuration_preserved(self):
        manifest = json.loads((ROOT / 'static/manifest.webmanifest').read_text())
        self.assertEqual(manifest['start_url'], '/')
        self.assertEqual(manifest['display'], 'standalone')
        self.assertEqual(manifest['name'], 'DKSS')
    def test_transparency_and_visible_content_not_clipped(self):
        for size in (192, 512):
            with self.subTest(size=size), Image.open(ROOT / f'static/icons/app-{size}.png') as image:
                alpha = image.getchannel('A')
                self.assertEqual(alpha.getextrema(), (0, 255))
                # Ignore near-transparent resampling fringes; NOT a maskable claim.
                visible = alpha.point(lambda value: 255 if value >= 16 else 0)
                box = visible.getbbox()
                self.assertIsNotNone(box)
                self.assertGreater(box[0], 0); self.assertGreater(box[1], 0)
                self.assertLess(box[2], size); self.assertLess(box[3], size)

if __name__ == '__main__':
    unittest.main()
