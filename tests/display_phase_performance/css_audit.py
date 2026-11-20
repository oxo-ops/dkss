import sys,json,gzip,collections,hashlib
from pathlib import Path

import tinycss2
root=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve()
src=(root/'static/css/style.css').read_text();tokens=tinycss2.parse_component_value_list(src)
counts=collections.Counter()
def normalize(ts):
 result=[]
 for t in ts:
  if t.type=='comment':counts['comment_bytes']+=len(t.serialize().encode());continue
  if t.type=='whitespace':counts['whitespace_bytes']+=len(t.value.encode());t.value=' '
  for attr in ('content','arguments'):
   if hasattr(t,attr):setattr(t,attr,normalize(getattr(t,attr)))
  if t.type=='whitespace' and result and result[-1].type=='whitespace':continue
  result.append(t)
 return result
normalized=normalize(tokens);mini=tinycss2.serialize(normalized)
(out/'style.compact.css').write_text(mini)
# Reparse round-trip: same token types/values and positions of whitespace.
def signature(ts):
 return [(t.type, ' ' if t.type=='whitespace' else t.value if hasattr(t,'value') else t.name if hasattr(t,'name') else None, signature(t.content) if hasattr(t,'content') else signature(t.arguments) if hasattr(t,'arguments') else None) for t in ts if t.type!='comment']
assert signature(normalized)==signature(tinycss2.parse_component_value_list(mini))
css=tinycss2.parse_stylesheet(src,skip_comments=True,skip_whitespace=True);blocks=[];families=collections.Counter()
def walk(rs,context='root'):
 for r in rs:
  if r.type=='qualified-rule':
   sel=tinycss2.serialize(r.prelude).strip();size=len(r.serialize().encode());blocks.append((context,sel,size))
   for name in ('karte','dashboard','patrol','notification','inspection','driving','master','login','report'):
    if name in sel:families[name]+=size
  elif r.type=='at-rule' and r.content is not None:walk(tinycss2.parse_rule_list(r.content,skip_comments=True,skip_whitespace=True),context+'/'+r.at_keyword+' '+tinycss2.serialize(r.prelude).strip())
walk(css)
repeated=collections.Counter((c,s)for c,s,b in blocks)
res={'original_bytes':len(src.encode()),'compact_bytes':len(mini.encode()),'original_gzip':len(gzip.compress(src.encode())),'compact_gzip':len(gzip.compress(mini.encode())),'token_roundtrip_equal':True,'normalization_counts':dict(counts),'qualified_blocks':len(blocks),'repeated_selector_contexts':sum(n>1 for n in repeated.values()),'top_repeated':[dict(context=c,selector=s,count=n)for(c,s),n in repeated.most_common(15)],'selector_family_bytes_overlapping':dict(families),'largest_blocks':[dict(context=c,selector=s,bytes=b)for c,s,b in sorted(blocks,key=lambda t:-t[2])[:10]]}
(out/'audit.json').write_text(json.dumps(res,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in res.items() if k not in ('top_repeated','largest_blocks')},ensure_ascii=False,indent=2))
