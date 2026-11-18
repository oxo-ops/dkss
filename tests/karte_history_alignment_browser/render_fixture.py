import json,sys
from pathlib import Path
from jinja2 import Environment,FileSystemLoader
repo=Path(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
e=Environment(loader=FileSystemLoader(repo/'templates'),autoescape=True)
s=(repo/'templates/vehicle_karte.html').read_text();a=s.index('<ol class="ko-timeline">');b=s.index('</ol>',a)+5
kinds=['日常点検','異常・指摘','整備','担当者変更','営業所変更','車検']
rows=[dict(kind=k,date='2026-11-18',content='内容を保持した確認記録 '+k,status='確認待ち',mileage=None,link='/unchanged/'+str(i)) for i,k in enumerate(kinds)]
e.filters['distance_km']=str
snippet=e.from_string("{% from 'vehicle_history_symbol.html' import history_symbol %}"+s[a:b]).render(karte_recent_entries=rows,vehicle={'id':1},url_for=lambda *a,**k:'/fallback')
macro=e.get_template('vehicle_history_symbol.html').module.history_symbol
ref=''.join('<div>'+str(macro(k))+'</div>' for k in kinds)
html='<html lang="ja"><meta charset="utf-8"><style>'+ (repo/'static/css/style.css').read_text()+'\n'+(repo/'static/css/vehicle_karte_overview.css').read_text()+'</style><body><main style="padding:12px"><div id="vehicle-karte-overview"><section class="card"><h3>直近の履歴</h3>'+snippet+'</section></div><section id="reference">'+ref+'</section></main></body></html>'
(out/'fixture.html').write_text(html)
s=(repo/'templates/vehicle_karte_history.html').read_text();a=s.index('<table class="checklist-table');b=s.index('</table>',a)+8
for i,row in enumerate(rows):row.update(cost=None if i%2==0 else 1200,mileage=None if i%2==0 else 1000,actor='担当者'+str(i),files=[])
fragment=e.from_string("{% from 'vehicle_history_symbol.html' import history_symbol %}"+s[a:b]).render(history_current_year=2026,history_page=__import__('types').SimpleNamespace(items=rows),url_for=lambda *a,**k:'/file')
html='<html lang="ja"><meta charset="utf-8"><style>'+(repo/'static/css/style.css').read_text()+'\n'+(repo/'static/css/vehicle_karte_history.css').read_text()+'</style><body class="vehicle-list-ppt"><main style="padding:10px"><section class="vehicle-karte-history-panel">'+fragment+'</section></main></body></html>'
(out/'table.html').write_text(html)
