import argparse,json,sys,threading
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
p=argparse.ArgumentParser();p.add_argument('--repo',required=True);p.add_argument('--out',required=True);p.add_argument('--preflight',action='store_true');args=p.parse_args()
repo=Path(args.repo).resolve();out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True)
sys.path[:0]=[str(repo),str(repo/'tests'),str(Path(__file__).parent)]
from test_office_summary_restricted import OfficeSummaryTests
from identity_fixture import identity_for
from werkzeug.serving import make_server
F=OfficeSummaryTests;F.setUpClass();case=F();case.setUp();app=case.m.app
for row in [case.own,case.theirs,case.support]:row.operation_date=datetime.now(ZoneInfo('Asia/Tokyo')).date().isoformat()
case.m.db.session.commit();app.config['WTF_CSRF_ENABLED']=True

def snapshot():
 return [(t.name,[dict(row) for row in case.m.db.session.execute(t.select()).mappings().all()]) for t in case.m.db.metadata.sorted_tables]
before=json.dumps(snapshot(),sort_keys=True,default=str)
@app.get('/__test_unchanged')
def unchanged():
 return {'unchanged':json.dumps(snapshot(),sort_keys=True,default=str)==before}
cookies={}
for role,name in [('user','two'),('admin','admin')]:
 client=app.test_client();user=case.m.User.query.filter_by(company_code='TEST',username=name).one()
 with client.session_transaction() as s:s.update(account_identity=identity_for('TEST',name,app=app),company_code='TEST',username=name,role=role,password_changed_at=user.password_changed_at)
 cookies[role]=client.get_cookie(app.config.get('SESSION_COOKIE_NAME','session')).value
(out/'cookies.json').write_text(json.dumps(cookies))
if args.preflight:
 for route in ['/safety/driving-reports?scope=self','/safety/driving-reports/office-summary']:
  response=case.client.get(route);assert response.status_code==200
 assert json.dumps(snapshot(),sort_keys=True,default=str)==before
 case.tearDown();F.tearDownClass();print('PREFLIGHT_OK');raise SystemExit(0)
server=make_server('127.0.0.1',51238,app,threaded=True)
try:
 (out/'ready').write_text('ready');server.serve_forever()
finally:
 server.server_close();case.tearDown();F.tearDownClass()
