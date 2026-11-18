import sys
from pathlib import Path
from jinja2 import Environment
from markupsafe import Markup
repo=Path.cwd();out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
env=Environment(autoescape=True)
source=(repo/'templates/vehicle_checklist_results.html').read_text()
source=source[source.index('{% set vehicle_compact_ready'):source.index('{% if not vehicle_record_id %}')]
css=''.join((repo/p).read_text() for p in ['static/css/style.css','static/css/vehicle_checklist_compact.css','static/css/vehicle_checklist_toolbar.css'])
js=(repo/'static/js/vehicle_checklist_toolbar.js').read_text()
for count in [0,8]:
 html=env.from_string(source).render(selected_vehicle=dict(number='品川 100 か 101'),checklist=dict(fixed_template_code='daily_inspection_truck_trailer'),active_result=None,request=dict(args={},path='/fixture/checklist'),year='2026',month='11',active_day='19',results=[dict(index=7)],vehicle_record_id='vehicle-1',usage_vehicles=[],vehicle_today=dict(is_selected=True),other_vehicle_inspection_defects=[{}]*count,checklist_result_heading=lambda *a:Markup('<h2>日常点検表</h2>'))
 html='<html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><style>'+css+'body{margin:0;padding:12px;box-sizing:border-box} </style><body>'+html+'<h3>2026年11月 点検状況</h3><div id="vehicle-other-day-defects">元の点検日の不具合</div><script>'+js+'</script></body></html>'
 (out/('page-'+str(count)+'.html')).write_text(html)
