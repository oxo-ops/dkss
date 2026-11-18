"""After successful synthetic capture, prepare the image-bearing guide in CI only.
Never publishes files. The original source checkout is untouched unless explicitly supplied.
"""
import os,shutil
from pathlib import Path
repo=Path(os.environ['PRODUCT_REPO']);art=Path(os.environ['ARTIFACTS'])
source=art/'390-ai-evidence-open.png'
if not source.is_file():raise SystemExit('successful actual-renderer capture is required')
if source.read_bytes()[:8] != b'\x89PNG\r\n\x1a\n':raise SystemExit('capture is not PNG')
if 'data-guide-ai-picture' in (repo/'templates/partials/first_use_guide.html').read_text():
 assert (repo/'static/guide/ai-evidence-open.png').read_bytes()==source.read_bytes(), 'committed AI image differs from exact-HEAD capture'
 assert 'aiPicture.hidden' in (repo/'static/js/first_use_guide.js').read_text()
 raise SystemExit(0)
dest=repo/'static/guide/ai-evidence-open.png';dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
p=repo/'templates/partials/first_use_guide.html';s=p.read_text();anchor='<p data-guide-text></p>'
assert s.count(anchor)==1
figure='''{% if request.endpoint == 'vehicle_karte_analysis' %}<figure class="first-guide-picture" data-guide-ai-picture hidden><img src="{{ url_for('static', filename='guide/ai-evidence-open.png') }}" width="390" height="844" alt="提案の詳細を開き、根拠と対応記録を確認する画面。" loading="lazy"></figure>{% endif %}'''
p.write_text(s.replace(anchor,figure+anchor).replace('20261118-detail-after-preview-1','20261118-ai-detail-guide-1'))
p=repo/'static/js/first_use_guide.js';s=p.read_text();s=s.replace("const picture=root.querySelector('[data-guide-picture]');","const picture=root.querySelector('[data-guide-picture]');\n  const aiPicture=root.querySelector('[data-guide-ai-picture]');")
s=s.replace("if(picture) picture.hidden=s.selector!=='.inspection-item-detail';","if(picture) picture.hidden=s.selector!=='.inspection-item-detail';\n    if(aiPicture) aiPicture.hidden=s.selector!=='.ka7-proposals .ka-reference-detail-button';")
p.write_text(s)
p=repo/'static/css/first_use_guide.css';p.write_text(p.read_text()+'\n[data-guide-ai-picture] img{width:100%;max-height:180px;object-fit:contain}\n')
