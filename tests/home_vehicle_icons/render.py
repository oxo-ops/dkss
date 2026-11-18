import os,json
from pathlib import Path
from jinja2 import Environment,FileSystemLoader
from PIL import Image,ImageChops,ImageStat
repo=Path(os.environ['PRODUCT_REPO']);out=Path(os.environ['HTML_OUT']);out.mkdir(parents=True,exist_ok=True)
env=Environment(loader=FileSystemLoader(repo/'templates'),autoescape=True)
env.globals['url_for']=lambda endpoint,filename,**kw:'/static/'+filename
macro=env.get_template('macros/vehicle_icon_sources.html').module.vehicle_icon_sources
names=['truck','trailer','tractor','crane','flatbed','car'];rows=[]
for name in names:
 rows.append('<div><span>'+name+'</span><img class="before" src="/static/icons/'+name+'.png"><img class="after" '+str(macro(name+'.png'))+'></div>')
html='<meta charset="utf-8"><meta name="viewport" content="width=device-width"><style>body{font:16px sans-serif;margin:16px;background:#f2f6ff}div{display:flex;align-items:center;gap:24px;padding:12px;border-bottom:1px solid #ccd}span{width:70px}img{width:43px;height:43px;object-fit:contain}</style><h2>Original / display</h2>'+''.join(rows)
(out/'icons.html').write_text(html,encoding='utf8')
measure=[]
for dpr,size in [(1,96),(2,192),(3,384),(4,384)]:
 original=Image.open(repo/'static/icons/truck.png').convert('RGBA')
 display=Image.open(repo/f'static/icons/truck-display-{size}.png').convert('RGBA')
 target=(43*dpr,43*dpr)
 def fit(im):
  im=im.copy();im.thumbnail(target,Image.Resampling.LANCZOS);canvas=Image.new('RGBA',target,'white');canvas.alpha_composite(im,((target[0]-im.width)//2,(target[1]-im.height)//2));return canvas.convert('RGB')
 a,b=fit(original),fit(display)
 diff=ImageChops.difference(a,b);stats=ImageStat.Stat(diff)
 measure.append({'dpr':dpr,'source_bytes':(repo/'static/icons/truck.png').stat().st_size,'display_bytes':(repo/f'static/icons/truck-display-{size}.png').stat().st_size,'rgb_mean_abs_error':stats.mean})
 a.save(out/f'original-{dpr}.png');b.save(out/f'display-{dpr}.png')
(out/'pixel-report.json').write_text(json.dumps(measure,indent=2))
