from pathlib import Path
from jinja2 import Environment,DictLoader
import json,hashlib
from urllib.parse import urlencode
root=Path(__file__).resolve().parent;repo=root.parents[1]
src=repo/'templates/document_import_job.html';jobs=json.loads((root/'synthetic-jobs.json').read_text())
base='<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/static/css/style.css"><link rel="stylesheet" href="/static/css/responsive_layout.css"><body data-responsive-shell><main class="main-content">{% block content %}{% endblock %}</main></body></html>'
env=Environment(loader=DictLoader({'base.html':base,'page.html':src.read_text()}),autoescape=True)
def url_for(endpoint,**kw):
 if endpoint=='static':return '/static/'+kw['filename']+('?' + urlencode({'v':kw['v']}) if 'v' in kw else '')
 if endpoint=='retry_document_import':return '/vehicle/data-import/jobs/'+kw['batch_id']+'/retry'
 if endpoint=='vehicle_data_import':return '/vehicle/data-import'
 raise AssertionError(endpoint)
job=json.loads(json.dumps(jobs[0]['job']));job['files'][0]['filename']='架空の長いファイル名_'+('x'*100)+'.pdf'
html=env.get_template('page.html').render(job=job,request={'args':{'open':'1'}},url_for=url_for,csrf_token=lambda:'synthetic-only')
(root/'page.html').write_text(html);(root/'jobs.json').write_text(json.dumps(jobs,ensure_ascii=False))
(root/'manifest.json').write_text(json.dumps({'template_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'candidate_sha256':hashlib.sha256((repo/'static/js/document_import_queue.js').read_bytes()).hexdigest(),'js_source':'static/js/document_import_queue.js','expected_head':__import__('os').environ['EXPECTED_HEAD'],'real_base_template':False,'production_access':False,'cache_tested':False},indent=2))
assert 'この受付の状況を再確認' not in html # Added by actual candidate JS, not invented in template.
assert 'documentImportJob' in html and 'synthetic-only' in html
print('Real receipt template rendered with synthetic JSON; minimal base shell, not full application.')

assert 'document_import_queue.js?v=20261117-receipt-status-guard-1' in html
