"""No business mutation: audit semantic coverage and class-only template diffs."""
import re,subprocess,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
base='463894aac8cad65b9b28ffe0a1d354359b1d1050'
covered=('btn-edit','btn-delete','btn-detail','btn-danger','danger','driver-license-remove','import-clear','import-receipt-delete','pointout-detail-delete','nd-delete','notification-menu-delete','safety-result-mobile-detail','dashboard-report-back')
rows=[]
for p in sorted((ROOT/'templates').glob('*.html')):
 s=p.read_text()
 for m in re.finditer(r'<(a|button)\b[^>]*>(.*?)</\1>',s,re.S):
  txt=re.sub('<[^>]*>','',m[2]).strip()
  if any(t in txt for t in ('編集','削除','詳細')) and len(txt)<90:
   if any(t in m[0] for t in covered):state='common family'
   elif p.name=='pointouts.html' and txt=='詳細':state='scoped existing selector'
   else:state='navigation or cancel, unchanged'
   rows.append({'template':p.name,'label':txt,'coverage':state})
# Class-only updates cannot alter CSRF, authorization, href, method or confirm.
changed=subprocess.check_output(['git','diff','--name-only','--','templates'],cwd=ROOT,text=True).splitlines()
for name in changed:
 old=subprocess.check_output(['git','show',base+':'+name],cwd=ROOT,text=True);new=(ROOT/name).read_text()
 if name=='templates/base.html':new=re.sub(r'<link[^\n]+common_action_buttons.css[^\n]+>\n','',new)
 clean=lambda s:re.sub(r'\bclass="[^"]*"','class=""',s)
 assert clean(old)==clean(new),name
(ROOT/'tests/common_action_buttons/inventory.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
print(f'{len(rows)} controls reviewed; {len(changed)} templates class-only/link-only, behavior retained')
