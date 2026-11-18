"""Template fragments only; no app import, storage, network, or actual data."""
from pathlib import Path
from jinja2 import Environment
import argparse,json
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
root=Path(__file__).parent;overlay=root/'product'
def read(n):
 x=overlay/n
 return (x if x.exists() else a.repo/n).read_text()
t=read('templates/index.html');i=t.index('{% macro attention_table');j=t.index('{% endmacro %}',i)+len('{% endmacro %}');fn=Environment(autoescape=True).from_string(t[i:j]).module.attention_table
s=read('templates/partials/dashboard_safety_attention.html');i=s.index('{% macro safety_rows');j=s.index('{% endmacro %}',i)+len('{% endmacro %}');sf=Environment(autoescape=True).from_string(s[i:j]).module.safety_rows
css='\n'.join(read('static/css/'+x) for x in ['style.css','dashboard_attention.css','dashboard_safety_attention.css','dashboard_mobile_refinement.css','dashboard_office_trends.css','video_proposal_lists.css','dashboard_summary_mobile.css'])
css+='\n'+read('static/css/dashboard_mobile_priority.css')
a.out.mkdir(parents=True,exist_ok=True)
for case in ['same','mixed','long','empty']:
 rows=[]
 for n,state in enumerate(['open','accepted','in_progress','completed','dismissed'] if case!='empty' else []):
  v=n if case=='mixed' else 1
  rows.append(dict(url=f'/vehicle/karte/{v}/analysis',vehicle_number=f'品川100か10{v}',proposal_id=f'p{n}',target='タイヤ空気圧の確認'+('と長い確認項目'*5 if case=='long' else ''),action='点検結果を確認して適切な対応を判断する。'+('安全な運行条件を確認する。'*8 if case=='long' else ''),timing='次回運行前'+('車両状態と運行計画を確認する。'*5 if case=='long' else ''),feedback_status=state,priority='中'))
 safety=[dict(content='雨天時の構内における周辺確認'+('と歩行者の安全確保'*6 if case=='long' else ''),state='対策確認待ち',url='/pointouts/1',action='現場の対応状況を確認する。',due_date='2026-11-23',location='中央営業所')] if rows else []
 requests='<div class="dashboard-reference-bottom-grid"><section class="dashboard-reference-bottom-panel" data-fixture-trend><h3>営業所の傾向</h3></section><section class="dashboard-reference-bottom-panel dashboard-personal-requests" data-personal-requests><h3>自分への依頼</h3><div class="dashboard-reference-action-links"><a href="/notifications?view=action&amp;category=vehicle&amp;type=vehicle_response">運行判断・不具合対応 <b>1件</b></a></div></section></div>'
 html='<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><style>'+css+'</style><style>body{margin:0;padding:12px;box-sizing:border-box}.dashboard-page{max-width:1200px;margin:auto}body.enlarge{font-size:200%}body.enlarge .dashboard-page :is(strong,p,small,a,span){font-size:20px}</style><main class="dashboard-page dashboard-design-v2"><section class="dashboard-attention dashboard-attention-list"><h3>安全・車両の確認・対応</h3><section class="dashboard-safety-attention"><h4>安全管理：次の対応</h4>'+str(sf(safety))+'</section><h4 class="dashboard-vehicle-attention-heading">車両管理：AIの整備提案</h4><div class="dashboard-attention-panel"><h3>自分の使用車両</h3>'+str(fn(rows,True))+'</div></section>'+requests+'</main><script>'+read('static/js/dashboard_mobile_priority.js')+'</script>'
 (a.out/(case+'.html')).write_text(html)
print(json.dumps({'pages':4,'source':'production Jinja fragments','real_data':False}))
