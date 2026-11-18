"""Candidate: shared AONAGI standard-inspection optimistic baseline."""
import hashlib,json
from flask import current_app,session,request,jsonify,url_for,redirect,flash,g
from itsdangerous import URLSafeTimedSerializer,BadSignature
from . import models

def enabled(checklist,company):
    return (session.get('aonagi_readonly_demo') is True
        and current_app.config.get('PUBLIC_DEMO_SHARED_COMPANY') is True
        and company == session.get('company_code') == current_app.config.get('PUBLIC_DEMO_COMPANY') == 'AONAGI'
        and checklist.get('fixed_template_code') == 'daily_inspection_truck_trailer')

def scope(company,index,vehicle,year,month,day):
    return [company,int(index),int(vehicle),str(int(year)),str(int(month)).zfill(2),str(int(day)).zfill(2)]

def digest(record):
    if record is None:value=None
    else:value={c.name:getattr(record,c.name) for c in record.__table__.columns}
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()

def serializer():return URLSafeTimedSerializer(current_app.secret_key,salt='demo-standard-inspection-v1')
def issue(record,key):return serializer().dumps({'scope':key,'digest':digest(record)})
def url(key):return url_for('vehicle_checklist_results',index=key[1],vehicle_record_id=key[2],year=key[3],month=key[4],active_day=key[5])

def page_token(checklist,company,index,vehicle,year,month,day):
    if not vehicle or not enabled(checklist,company):return ''
    key=scope(company,index,vehicle,year,month,day)
    row=models.VehicleChecklistResult.query.filter_by(company_code=company,checklist_id=key[1],vehicle_record_id=key[2],year=key[3],month=key[4],day=key[5]).first()
    return issue(row,key)

def conflict(checklist,company,index,vehicle,year,month,day,record):
    if not enabled(checklist,company):return None
    key=scope(company,index,vehicle,year,month,day)
    token=request.headers.get('X-DKSS-Demo-Snapshot') or request.form.get('demo_snapshot','')
    try:data=serializer().loads(token,max_age=3600)
    except BadSignature:data={}
    if (isinstance(data,dict) and data.get('scope')==key and data.get('digest')==digest(record)
        and (record is None or record.status not in {'承認待ち','承認済み','点検完了'})):return None
    # Do not publish a normal-save receipt, mutate, upload or notify.
    target=url(key)
    flash('先に保存された点検結果を表示しています。今回の入力は上書きしていません。','info')
    if request.headers.get('X-DKSS-Validation-Only')=='1' or request.headers.get('X-DKSS-Final-Submit')=='1':
        response=jsonify(saved=False,preserved=True,redirect_url=target)
        response.headers['X-DKSS-Demo-Preserved']='1'
        return response
    return redirect(target)

def prepare_ack(checklist,record):
    if not enabled(checklist,record.company_code):return
    from .extensions import db
    db.session.flush()
    key=scope(record.company_code,record.checklist_id,record.vehicle_record_id,record.year,record.month,record.day)
    g.demo_inspection_own_ack=(key,issue(record,key))

def acknowledged(checklist,record,target=None):
    if not enabled(checklist,record.company_code):return None
    key=scope(record.company_code,record.checklist_id,record.vehicle_record_id,record.year,record.month,record.day)
    final=request.headers.get('X-DKSS-Final-Submit')=='1'
    if request.headers.get('X-DKSS-Validation-Only')!='1' and not final:return None
    response=jsonify(success=True,saved=True,redirect_url=target or url(key)) if final else jsonify(saved=True)
    prepared=getattr(g,'demo_inspection_own_ack',None)
    if not prepared or prepared[0]!=key:raise RuntimeError('MISSING_OWN_COMMIT_BASELINE')
    response.headers['X-DKSS-Demo-Snapshot']=prepared[1]
    return response
