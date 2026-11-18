import sys,time,json
from io import BytesIO
from PIL import Image,ImageDraw
from unittest.mock import patch
import test_preview_unit as unit
from flask import session
p,a=unit.p,unit.a
rows=[]
for dims in [(1600,1200),(4000,3000)]:
 im=Image.new('RGB',dims,'#b8c2cb');d=ImageDraw.Draw(im)
 for x in range(0,dims[0],50):
  for y in range(0,dims[1],50):d.rectangle((x,y,x+35,y+35),fill=((x*7+y)%256,(x+y*3)%256,(x+y)%256))
 out=BytesIO();im.save(out,'JPEG',quality=94);raw=out.getvalue()
 for width in (480,960):
  t=unit.Tests();t.setUp();t.raw=raw
  start=time.perf_counter();r=t.get(str(width));cold=time.perf_counter()-start
  start=time.perf_counter();t.get(str(width));warm=time.perf_counter()-start
  rows.append(dict(original=dims,width=width,source_bytes=len(raw),preview_bytes=len(r[0]) if r else None,cold_seconds=cold,warm_seconds=warm,reads=t.reads))
print(json.dumps(rows,indent=2))
