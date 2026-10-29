"""Change processing type without resending sources, including reviewed corrections."""
import hashlib
import json
from uuid import UUID, uuid5, uuid4
from flask import abort, current_app, flash, redirect, render_template, request, session, url_for
from itsdangerous import URLSafeTimedSerializer, BadSignature
from sqlalchemy.orm import defer
from .extensions import db
from .models import VehicleDocumentImportDraft as Draft, Vehicle
from .access import require_master_admin
from . import document_import_queue as queue
from . import import_owner
from document_type_detection import KINDS


def revision(row):
    return {'id':row.id, 'company':row.company_code, 'user':session.get('username'),
            'actor_identity':import_owner.current_identity(),
            'kind':row.document_type, 'registered':row.status=='completed',
            'generation':queue.metadata(row.result_json).get('generation',0), 'sha':row.source_sha256}


def correction_impact(row, lock=False):
    info=json.loads(row.result_json or '{}')
    ids={r.get('vehicle_record_id') for r in info.get('records',[]) if isinstance(r,dict)}
    if len(ids)!=1:
        vehicle=Vehicle.query.filter(Vehicle.company_code==row.company_code,Vehicle.id.in_([v for v in ids if v is not None])).first()
        return vehicle, {'problems':['複数車両の登録内容が含まれています。元の記録を確認してから訂正してください。'], 'counts':{}}
    vehicle=Vehicle.query.filter_by(company_code=row.company_code,id=next(iter(ids)),deleted=False).first()
    if vehicle is None:
        return None, {'problems':['元の車両を確認できません。車両一覧から登録内容を確認してください。'], 'counts':{}}
    return vehicle, current_app.extensions['dkss']['document_deletion']['plan'](vehicle,row,lock=lock)


def document_import_kind(draft_id):
    if not require_master_admin():
        abort(403)
    query=Draft.query.options(defer(Draft.source_file)).filter_by(id=draft_id,
        company_code=session.get('company_code'))
    row=(query.with_for_update() if request.method=='POST' else query).first_or_404()
    if row.status!='completed' and not import_owner.owns(row):
        abort(404)
    if row.document_type not in KINDS or row.status not in {'queued','reading','type_review','preview','read_error','completed'}:
        abort(409,description='この資料は確認済み、または取り消されています。取込状況を確認してください。')
    serializer=URLSafeTimedSerializer(current_app.secret_key,salt='document-kind-v1')
    token=serializer.dumps(revision(row))
    vehicle,impact=correction_impact(row) if row.status=='completed' else (None,None)
    back=url_for('vehicle_karte_documents',vehicle_record_id=vehicle.id) if vehicle else url_for('vehicle_data_import')
    if request.method=='GET':
        source_url=(url_for('vehicle_karte_document_source',vehicle_record_id=vehicle.id,draft_id=row.id)
                    if vehicle else url_for('vehicle_document_import_source',draft_id=row.id))
        return render_template('document_import_kind.html',draft=row,kinds=KINDS,kind_token=token,
            job=queue.metadata(row.result_json),impact=impact,back_url=back,source_url=source_url)
    actor_identity=import_owner.identity_for_actor(session.get('company_code'),session.get('username'),lock=True)
    if not actor_identity:
        abort(403)
    if request.form.get('action')=='cancel':
        if row.status!='completed':
            job=queue.metadata(row.result_json)
            job.update(phase='cancelled',message='この資料の読み取りをキャンセルしました。')
            job.pop('token',None);job.pop('lease_until',None)
            row.status='deleted';row.source_file=b'';row.preview_json='{}';row.result_json=queue.result(job)
            from .document_sources import purge_unreferenced
            purge_unreferenced(row.company_code,row.source_sha256)
            db.session.commit()
        return redirect(back,code=303)
    kind=request.form.get('document_type')
    if kind not in KINDS:
        abort(400,description='資料の種類を選択してください。原本は保存されています。')
    submitted=request.form.get('kind_token','')
    request_key=hashlib.sha256((submitted+':'+kind).encode()).hexdigest()
    if queue.metadata(row.result_json).get('last_kind_request')==request_key:
        return redirect(url_for('document_import_job',batch_id=row.batch_id,open=1),code=303)
    try:
        signed=serializer.loads(submitted,max_age=1800)
    except BadSignature:
        abort(409,description='確認の有効期限が切れました。この画面を開き直してください。原本は保存されています。')
    if signed!=revision(row):
        abort(409,description='資料の処理状態が変わりました。この画面を開き直してください。')
    from .import_flow import completed_document
    if row.status=='completed' and kind==row.document_type:
        flash('すでにこの種類で登録されています。','info')
        return redirect(back,code=303)
    if completed_document(row.company_code,kind,row.source_sha256):
        if row.status!='completed':
            row.status='skipped'
            job=queue.metadata(row.result_json);job.update(phase='complete',message='この種類の資料は登録済みです。')
            row.result_json=queue.result(job);db.session.commit()
        flash('この資料は、選択した種類ですでに登録されています。再登録は不要です。','info')
        return redirect(back,code=303)
    if row.status=='completed':
        vehicle,impact=correction_impact(row,lock=True)
        if impact['problems']:
            abort(409,description='関連記録を保護するため自動訂正を停止しました。元の記録から登録内容を確認してください。')
        key=str(uuid5(UUID(row.id),actor_identity+':'+request_key))
        existing=db.session.get(Draft,key)
        if existing:
            return redirect(url_for('document_import_job',batch_id=existing.batch_id,open=1),code=303)
        correction={'source_id':row.id,'digest':impact['correction_digest'],'vehicle_id':vehicle.id,'counts':impact['counts']}
        new=Draft(id=key,batch_id=str(uuid4()),company_code=row.company_code,created_by_username=session['username'],owner_identity=actor_identity,
            document_type=kind,source_filename=row.source_filename,source_sha256=row.source_sha256,source_file=queue.store_source(row.company_code,row.source_sha256,row.source_file),
            status='queued',preview_json='{}',result_json=queue.result({'correction':correction}))
        db.session.add(new);row=new
    job=queue.metadata(row.result_json)
    job.update(phase='queued',attempts=0,forced_type=True,requested_type=kind,
        generation=job.get('generation',0)+1,last_kind_request=request_key,message='',
        routing_notice=KINDS[kind]+'として読み取りました。',updated_at=queue.now().isoformat())
    job.pop('token',None);job.pop('lease_until',None)
    row.status='queued';row.document_type=kind;row.preview_json='{}';row.result_json=queue.result(job)
    db.session.commit()
    from .document_import_worker import start_worker
    start_worker(current_app._get_current_object())
    return redirect(url_for('document_import_job',batch_id=row.batch_id,open=1),code=303)


def validate_corrections(drafts, submissions):
    validated=[]
    for row in drafts:
        correction=queue.metadata(row.result_json).get('correction')
        if not correction:
            continue
        if request.form.get('confirm_kind_correction')!='yes':
            raise ValueError('元の登録を置き換える内容を確認し、訂正の確認にチェックしてください。')
        selected=[values for draft,_,values in submissions if draft.id==row.id]
        if not selected or any(v.get('vehicle_record_id')!=correction['vehicle_id'] for v in selected):
            raise ValueError('訂正は元の車両への登録で行ってください。元の記録は変更していません。')
        original=Draft.query.filter_by(id=correction['source_id'],company_code=row.company_code,
            status='completed').with_for_update().first()
        if original is None:
            raise ValueError('元の資料は変更・訂正されています。取込状況を確認してください。')
        vehicle,impact=correction_impact(original,lock=True)
        if impact['problems'] or impact['correction_digest']!=correction['digest']:
            raise ValueError('元の登録内容が変更されています。資料の種類の修正を開き直してください。')
        validated.append((vehicle,original,row,correction['digest']))
    return validated
