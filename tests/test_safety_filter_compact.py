from pathlib import Path
from jinja2 import Environment
from urllib.parse import urlencode,parse_qs,urlsplit
import re
s=(Path(__file__).resolve().parents[1]/'templates/pointouts.html').read_text();s=s[s.index('<section class="safety-summary-grid'):];s=s[:s.index('</section>')+10]
for state in ['', 'waiting','not_started','rejected','approved','none']:
 html=Environment(autoescape=True).from_string(s).render(status_filter=state,patrol_stats=dict(waiting=1,not_started=2,rejected=3),view_type='user',office_filter='本社',category_filter='安全',date_from='2026-11-01',date_to='2026-11-18',page_size=30,url_for=lambda endpoint,**kw:'/pointouts?'+urlencode(kw))
 assert html.count('class="safety-summary-card')==3
 assert '全件数' not in html and '対象外' not in html and '承認済み' not in html
 for key,href in zip(['waiting','not_started','rejected'],re.findall(r'href="([^"]+)"',html)):
  import html as h
  q=parse_qs(urlsplit(h.unescape(href)).query,keep_blank_values=True)
  assert q['status']==['' if state==key else key]
  assert q['office']==['本社'] and q['category']==['安全'] and q['date_from']==['2026-11-01']
print('6 filter states PASS: 3 cards, toggle off, other conditions preserved')
