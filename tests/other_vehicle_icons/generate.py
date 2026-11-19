"""Offline-only static icon derivatives. Originals remain byte-identical."""
import os,json,hashlib
from pathlib import Path
from PIL import Image,ImageChops,ImageStat,ImageDraw,PngImagePlugin
repo=Path(os.environ['PRODUCT_REPO']);out=Path(os.environ['OUTPUT']);out.mkdir(parents=True,exist_ok=True)
assets=out/'assets';assets.mkdir(exist_ok=True)
names=['trailer','tractor','crane','flatbed','car'];report=[]
sheet=Image.new('RGB',(600,140*len(names)),(242,246,255));draw=ImageDraw.Draw(sheet)
for row,name in enumerate(names):
 source=repo/f'static/icons/{name}.png';raw=source.read_bytes();sha=hashlib.sha256(raw).hexdigest()
 original=Image.open(source).convert('RGBA');variants={}
 for size in (96,192,384):
  im=original.copy();im.thumbnail((size,size),Image.Resampling.LANCZOS)
  meta=PngImagePlugin.PngInfo();meta.add_text('SourceSHA256',sha)
  target=assets/f'{name}-display-{size}.png';im.save(target,format='PNG',optimize=True,pnginfo=meta)
  assert target.stat().st_size<len(raw)
  assert (repo/'static/icons'/target.name).read_bytes()==target.read_bytes(), 'committed derivative differs from reproducible output'
  variants[size]={'bytes':target.stat().st_size,'dimensions':im.size}
 errors=[]
 def fit(im,n):
  im=im.copy();im.thumbnail((n,n),Image.Resampling.LANCZOS)
  canvas=Image.new('RGBA',(n,n),(242,246,255,255));canvas.alpha_composite(im,((n-im.width)//2,(n-im.height)//2));return canvas.convert('RGB')
 for dpr,size in [(1,96),(2,192),(3,384),(4,384)]:
  a=fit(original,43*dpr);b=fit(Image.open(assets/f'{name}-display-{size}.png'),43*dpr)
  mae=ImageStat.Stat(ImageChops.difference(a,b)).mean
  assert max(mae)<3, (name,dpr,mae)
  errors.append({'dpr':dpr,'rgb_mae':mae})
 draw.text((10,row*140+10),name,fill=(20,40,70))
 sheet.paste(fit(original,86),(170,row*140+20));sheet.paste(fit(Image.open(assets/f'{name}-display-192.png'),86),(340,row*140+20))
 assert source.read_bytes()==raw
 report.append({'name':name,'source_sha256':sha,'source_bytes':len(raw),'source_dimensions':original.size,'variants':variants,'rendered_errors':errors})
sheet.save(out/'original-vs-display.png');(out/'report.json').write_text(json.dumps(report,indent=2))
