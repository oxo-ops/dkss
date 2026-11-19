import re,sys
from pathlib import Path
from jinja2 import Environment,FileSystemLoader
repo=Path.cwd();out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
env=Environment(loader=FileSystemLoader(repo/'templates'),autoescape=True)
env.globals['url_for']=lambda endpoint,filename,**kw: '/static/'+filename
css=''.join((repo/p).read_text() for p in ['static/css/style.css','static/css/dashboard_safety_attention.css','static/css/dashboard_mobile_refinement.css','static/css/video_proposal_lists.css','static/css/dashboard_mobile_priority.css','static/css/dashboard_office_trends.css','static/css/dashboard_quiet_affordances.css'])
rows=[dict(content='雨天の構内で路面が滑りやすいことを確認し、停止位置を手前に見直す',state=s,action='写真と対策内容を確認',due_date='2026-11-19',location='試験営業所',url='/fixture/safety/'+str(i)) for i,s in enumerate(['対策確認待ち','差し戻し','対策未確認','対策確認待ち'])]
safety=env.get_template('partials/dashboard_safety_attention.html').render(dashboard_safety_attention=dict(available=True,items=rows))
source=(repo/'templates/index.html').read_text()
macro=re.search(r'{% macro attention_table[\s\S]*?{% endmacro %}',source).group()
proposals=[dict(priority='中',target='前照灯、方向指示器、車幅灯、非常点滅灯',action='光源・接点・通電状態を確認する。',timing='夜間・薄暮時の使用前',feedback_status='open',url='/fixture/vehicle/1',vehicle_number='品川 100 か 101',proposal_id=i) for i in range(2)]
ai=env.from_string(macro+'{{ attention_table(items) }}').render(items=proposals)
office=env.get_template('partials/dashboard_office_trends.html').render(dashboard_office_actions=[dict(kind='安全',state='対策確認待ち',title='安全の確認',url='/fixture/office',priority='')],dashboard_office_check_trend=dict(issues=[]))
office=re.sub(r'<script src="/static/js/dashboard_office_actions\.js"[^>]*></script>',lambda _m:'<script>'+(repo/'static/js/dashboard_office_actions.js').read_text()+'</script>',office)
html='<html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><style>'+css+'body{margin:0;padding:12px;box-sizing:border-box}.dashboard-page{width:auto!important;margin:0!important;padding:0!important}</style><body><main class="dashboard-page dashboard-design-v2">'+safety+ai+office+'</main>'
(out/'page.html').write_text(html)
