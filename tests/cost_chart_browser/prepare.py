"""Synthetic only: actual cost template/product JS, minimal outer shell, no app/DB."""
from pathlib import Path
from decimal import Decimal
import json,hashlib
from jinja2 import Environment,ChoiceLoader,DictLoader,FileSystemLoader
R=Path(__file__).resolve().parent;ROOT=R.parents[1];VERSION='20261117-cost-decimals-axis-2'
SCENARIOS={'tiny':['0.01','0.50','0'],'tiny_only':['0.01','0','0'],'tiny_negative':['-0.01','0','0'],'zero':['0','0','0'],'ordinary':['500.01','1000.10','0'],'negative':['-50.01','100','0'],'unknown':[None,None,None],'missing':[None,None,None],'mixed':['0',None,'0.01'],'large':['999999999999.99','1000000.01','0']}
shell='''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/static/css/style.css"><link rel="stylesheet" href="/static/css/responsive_layout.css"><body><main>{% block content %}{% endblock %}</main></body></html>'''
env=Environment(loader=ChoiceLoader([DictLoader({'base.html':shell,'vehicle_karte_header.html':'','vehicle_karte_tabs.html':''}),FileSystemLoader(str(ROOT/'templates'))]),autoescape=True)
env.filters['distance_km']=lambda v:str(v) if v is not None else '—'
def money(v):return format(Decimal(str(v)),',.2f').rstrip('0').rstrip('.') if v is not None else '—'
def url_for(endpoint,**kw):return '/static/'+kw['filename']+'?v='+kw.get('v','') if endpoint=='static' else '/synthetic-no-navigation'
for name,values in SCENARIOS.items():
 known=[Decimal(v) for v in values if v is not None];total=str(sum(known)*4) if known else None
 missing=12 if name=='missing' else 4 if name=='mixed' else 0
 summary={'total_cost':total,'category_costs':[],'show_cost_ring':False}
 if total is not None and Decimal(total)>0:summary.update(category_costs=[dict(label='架空整備',amount=total,color='#397dea',percentage=100)],show_cost_ring=True)
 def item(v):return dict(amount=v,record_count=int(v is not None or name in ('missing','mixed')),missing_amount_count=int(v is None and name in ('missing','mixed')))
 details=dict(selected_year=2026,selected_summary=summary,all_time_summary=summary,available_years=[2026],undated_record_count=0,missing_amount_count=missing,all_time_missing_amount_count=missing,previous_missing_amount_count=0,change_percentage=None,previous_total=None,rolling_average=None,rolling_missing_amount_count=0,average_start='2025-11-01',average_last_month='2026/10',monthly_costs=[dict(month=i+1,**item(values[i%3])) for i in range(12)],yearly_costs=[dict(year=2024+i,**item(v)) for i,v in enumerate(values)],high_cost_records=[],recent_records=[])
 page=env.get_template('vehicle_karte_costs.html').render(cost_details=details,import_context=None,vehicle={'id':1},cost_current_year=2026,url_for=url_for,format_cost_number=money)
 assert VERSION in page
 (R/f'{name}.html').write_text(page)
files=['static/js/vehicle_karte_costs.js','templates/vehicle_karte_costs.html','static/css/style.css','static/css/responsive_layout.css']
(R/'manifest.json').write_text(json.dumps(dict(version=VERSION,sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files},scenarios=SCENARIOS,full_shell=False,live_access=False),ensure_ascii=False,indent=2))
print('Prepared 10 synthetic real-template cases; browser not run')
