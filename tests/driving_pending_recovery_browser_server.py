"""Loopback-only synthetic browser fixture; no production DATABASE_URL fallback."""
import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import threading

os.environ.update(DOCUMENT_IMPORT_WORKER_ENABLED='0', AWS_EC2_METADATA_DISABLED='true')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flask import jsonify, redirect, request, session
from werkzeug.serving import make_server
from test_driving_pending_identity_recovery import PendingRecoveryTests, PostgresPendingRecoveryTests
from dkss_app import driving_access, driving_pending_identity as recovery

parser=argparse.ArgumentParser()
parser.add_argument('--kind',choices=['sqlite','postgres'],required=True)
parser.add_argument('--port',type=int,required=True)
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args()
cls=PendingRecoveryTests if args.kind=='sqlite' else PostgresPendingRecoveryTests
cls.setUpClass()
m=cls.m; app=m.app; key=secrets.token_urlsafe(24); fixture={}; server=None


def reset(normal=False, count=1):
    with app.app_context():
        if m.db.engine.dialect.name=='sqlite':m.db.engine._driving_fixture_fk=False
    case=cls('test_R01_existing_readback_and_optional_reference_confirm_without_reupload')
    case.setUp()
    try:
        other=case.person(username='second-manager',name='反映担当'); other.role='admin'
        viewer=case.person(username='unrelated-person',name='無関係の利用者')
        if normal:
            p=json.loads(case.item.payload_json)
            p.update(_driving_account_choice=case.person_to_confirm.username,
                     _driving_account_identity=case.person_to_confirm.account_identity)
            case.item.payload_json=json.dumps(p); case.draft.preview_json=json.dumps({'records':[p]})
        m.db.session.commit()
        for index in range(2,count+1):case.seed(index)
        fixture.update(pending=case.pending.id,item=case.item.id,draft=case.draft.id,vehicle=case.vehicle.id,
            person_uuid=case.person_to_confirm.account_identity,admin_uuid=case.admin.account_identity,
            applier_uuid=other.account_identity,raw=case.raw())
        return dict(pending=fixture['pending'],item=fixture['item'],vehicle=str(fixture['vehicle']),
            review='/master/vehicles/pending/'+fixture['pending']+'/driving-reports/'+fixture['item']+'/identity?q=1234',
            queue='/master/vehicles/pending/'+fixture['pending']+'?q=1234',
            source='/master/vehicles/pending/'+fixture['pending']+'/document-sources/'+fixture['draft'],
            sha256=case.draft.source_sha256,person_uuid=fixture['person_uuid'],admin_uuid=fixture['admin_uuid'],applier_uuid=fixture['applier_uuid'])
    finally:
        m.db.session.remove()
        case.ctx.pop()


def control():
    if not request.path.startswith('/_recovery_fixture/'):return None
    if request.headers.get('X-Recovery-Fixture')!=key:return '',404
    action=request.path.rsplit('/',1)[-1]
    if action=='reset':return jsonify(reset(request.args.get('normal')=='1',request.args.get('count',1,type=int)))
    if action=='login':
        username={'admin':'admin','applier':'second-manager','viewer':'unrelated-person'}[request.args.get('as','admin')]
        user=m.User.query.filter_by(company_code='TEST',username=username).one()
        session.clear();session.update(company_code=user.company_code,username=user.username,role=user.role,
            account_identity=user.account_identity,password_changed_at=user.password_changed_at)
        return redirect('/master/vehicles/pending/'+fixture['pending']) if user.role=='admin' else redirect('/')
    if action=='state':
        item=m.db.session.get(m.VehicleImportPendingRecord,fixture['item'])
        draft=m.db.session.get(m.VehicleDocumentImportDraft,fixture['draft'])
        record=m.VehicleDrivingReportRecord.query.first()
        evidence=driving_access.DrivingReaderAccount.query.first()
        return jsonify(events=json.loads(item.result_json).get(recovery.KEY,[]),report_count=m.VehicleDrivingReportRecord.query.count(),
            record_id=record.id if record else None,grant_uuid=evidence.account_identity if evidence else None,
            applied_by=evidence.actor_identity if evidence else None,raw_unchanged=(draft.source_file,draft.source_sha256,draft.preview_json,item.payload_json)==fixture['raw'],
            pending_status=m.db.session.get(m.VehicleImportPending,fixture['pending']).status,
            result=json.loads(item.result_json))
    if action=='stop':
        threading.Thread(target=server.shutdown,daemon=True).start()
        return jsonify(stopping=True)
    return '',404


app.before_request_funcs.setdefault(None,[]).insert(0,control)
args.out.parent.mkdir(parents=True,exist_ok=True)
args.out.write_text(json.dumps({'base':'http://127.0.0.1:'+str(args.port),'key':key,'kind':args.kind}),encoding='utf8')
# Reset recreates this fixture's tables. Serialize HTTP fixture requests so
# background dashboard reads cannot race its test-only DDL; product concurrency
# is exercised independently against real connections in the acceptance suite.
server=make_server('127.0.0.1',args.port,app,threaded=False)
try:server.serve_forever()
finally:cls.tearDownClass()
