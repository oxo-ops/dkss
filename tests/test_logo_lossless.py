"""Pixel-preserving encoding only. No source artwork, layout or auth changes."""
from pathlib import Path
import unittest
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
class LosslessLogoTests(unittest.TestCase):
 def test_original_pixels_alpha_dimensions_and_profile_preserved(self):
  for name in ('wordmark','symbol'):
   with self.subTest(asset=name):
    a=Image.open(ROOT/f'static/images/alseon/{name}.png')
    b=Image.open(ROOT/f'static/images/alseon/{name}.webp')
    self.assertEqual(a.size,b.size)
    self.assertEqual(a.info.get('icc_profile',b''),b.info.get('icc_profile',b''))
    self.assertEqual(a.convert('RGBA').tobytes(),b.convert('RGBA').tobytes())
    self.assertLess((ROOT/f'static/images/alseon/{name}.webp').stat().st_size,(ROOT/f'static/images/alseon/{name}.png').stat().st_size)
 def test_small_and_high_dpr_render_inputs_match(self):
  for name,widths in [('wordmark',(148,296,444,2172)),('symbol',(48,96,144,1536))]:
   a=Image.open(ROOT/f'static/images/alseon/{name}.png').convert('RGBA')
   b=Image.open(ROOT/f'static/images/alseon/{name}.webp').convert('RGBA')
   for width in widths:
    size=(width,round(a.height*width/a.width))
    self.assertEqual(a.resize(size,Image.Resampling.LANCZOS).tobytes(),b.resize(size,Image.Resampling.LANCZOS).tobytes())
 def test_picture_keeps_png_fallback_and_dimensions(self):
  text=(ROOT/'templates/base.html').read_text()
  for name in ('wordmark','symbol'):
   self.assertIn(f"filename='images/alseon/{name}.webp'",text)
   self.assertIn(f"filename='images/alseon/{name}.png'",text)
  self.assertIn('width="2172" height="724"',text)
  self.assertIn('width="1536" height="1024"',text)
if __name__=='__main__':unittest.main()
