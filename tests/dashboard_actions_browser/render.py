import json,sys
from pathlib import Path
from jinja2 import Environment,FileSystemLoader
repo=Path.cwd();out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
env=Environment(loader=FileSystemLoader(repo/'templates'),autoescape=True)
env.globals['url_for']=lambda endpoint,filename,**kw:'/static/'+filename
cases=[(0,0),(1,0),(0,1),(5,5),(6,11),(60,60)]
css=''.join((repo/p).read_text() for p in ['static/css/style.css','static/css/dashboard_safety_attention.css','static/css/dashboard_mobile_refinement.css','static/css/dashboard_office_trends.css'])
js=(repo/'static/js/dashboard_office_actions.js').read_text()
for safety,vehicle in cases:
 rows=[]
 for kind,count in [('安全',safety),('車両',vehicle)]:
  for i in range(count):
   rows.append(dict(kind=kind,title=kind+' '+str(i+1)+' 長い内容の確認。'*12,url='/fixture/'+('safety' if kind=='安全' else 'vehicle')+'/'+str(i),state='対策確認待ち',priority='高' if i==0 else '中'))
 issues=[dict(content='点検項目'+str(i),count=10-i,category='点検',records=[]) for i in range(5)]
 content=env.get_template('partials/dashboard_office_trends.html').render(dashboard_office_actions=rows,dashboard_scope_office='テスト営業所',dashboard_office_check_trend=dict(issues=issues))
 content=content.replace('<script src="/static/js/dashboard_office_actions.js" defer></script>','')
 # Remove URL query is handled by stripping only the one known generated script.
 import re
 content=re.sub(r'<script src="/static/js/dashboard_office_actions.js[^\"]*" defer></script>','',content)
 html='<html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><style>'+css+'body{margin:0;padding:12px;box-sizing:border-box}.dashboard-page{width:auto!important;margin:0!important;padding:0!important}</style><body><main class="dashboard-page dashboard-design-v2">'+content+'</main><script>'+js+'</script>'
 (out/(str(safety)+'-'+str(vehicle)+'.html')).write_text(html)

