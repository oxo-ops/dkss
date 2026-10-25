"""Delete an attributable imported document and its exclusively owned records.
No AI request is performed by this module. Ambiguous/shared ownership fails closed.
"""
import hashlib,json
from datetime import datetime,timezone
from flask import abort,flash,redirect,render_template,request,session,url_for
from itsdangerous import URLSafeTimedSerializer,BadSignature,SignatureExpired
from sqlalchemy import select


def register_document_deletion(app,db,g):
    if app.extensions.get('vehicle_document_deletion_v1'):return
    app.extensions['vehicle_document_deletion_v1']=True
    def snapshot(row):
        values={column.key:getattr(row,column.key) for column in row.__table__.columns}
        return {key:({'sha256':hashlib.sha256(value).hexdigest(),'size':len(value)} if isinstance(value,bytes) else value) for key,value in values.items()}
    def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
    def parse(text):
        try:
            value=json.loads(text or '{}');return value if isinstance(value,dict) else {}
        except (ValueError,TypeError):return {}
    def require_access(vehicle_id,draft_id,lock=False):
        if not session.get('username') or not session.get('company_code') or session.get('role') not in ('admin','itc'):abort(403)
        vehicle=g['Vehicle'].query.filter_by(id=vehicle_id,company_code=session['company_code'],deleted=False).first_or_404()
        query=g['VehicleDocumentImportDraft'].query.filter_by(id=draft_id,company_code=vehicle.company_code,status='completed')
        if lock:query=query.with_for_update()
        draft=query.first_or_404()
        links=parse(draft.result_json).get('records',[])
        if not isinstance(links,list) or not any(isinstance(x,dict) and x.get('vehicle_record_id')==vehicle.id for x in links):abort(404)
        return vehicle,draft
    def plan(vehicle,draft,lock=False):
        company=vehicle.company_code;owned=[];problems=[];detach=[]
        def rows(model,**filters):
            q=model.query.filter_by(company_code=company,**filters)
            return (q.with_for_update() if lock else q).all()
        def own(row):
            if not any(x.__table__.name==row.__table__.name and x.id==row.id for x in owned):owned.append(row)
        records=parse(draft.result_json).get('records',[])
        if parse(draft.result_json).get('pending_records'):problems.append('この資料には登録待ちの明細が残っています。先に登録待ちの対応を確認してください。')
        if any(not isinstance(x,dict) or x.get('vehicle_record_id')!=vehicle.id for x in records):
            problems.append('この原本は複数車両で共有されています。車両ごとの取込取消が必要です。')
        for link in records:
            if not isinstance(link,dict) or link.get('vehicle_record_id')!=vehicle.id:continue
            if link.get('maintenance_document_id'):
                docs=rows(g['VehicleMaintenanceDocument'],id=link['maintenance_document_id'])
                if len(docs)!=1 or docs[0].source_draft_id!=draft.id:problems.append('添付資料の関連が変更されています。');continue
                doc=docs[0]
                if doc.financial_status not in ('pending','duplicate','excluded') or doc.parts_status not in ('pending','not_applicable'):
                    problems.append('この資料の費用・部品は既存記録へ反映済みです。既存記録を残すため差分の取消が必要です。');continue
                own(doc);detach.append(doc);continue
            kind=link.get('document_type') or draft.document_type
            if kind=='maintenance':
                record=g['VehicleMaintenanceRecord'].query.filter_by(company_code=company,vehicle_record_id=vehicle.id,id=link.get('record_id')).with_for_update().first() if lock else g['VehicleMaintenanceRecord'].query.filter_by(company_code=company,vehicle_record_id=vehicle.id,id=link.get('record_id')).first()
                if record is None:problems.append('整備記録の関連を確認できません。');continue
                details=parse(record.invoice_details_json);source=details.get('source') or {}
                if not isinstance(source,dict) or source.get('draft_id')!=draft.id or source.get('sha256')!=draft.source_sha256 or details.get('before_invoice_attachment_json') is not None:
                    problems.append('既存整備への追加資料、又は出典が一致しない記録です。既存情報を保護するため削除できません。');continue
                events=rows(g['VehicleMaintenanceRecordEvent'],maintenance_record_id=record.id)
                if any(e.action!='imported' for e in events):problems.append('取込後に編集・作業履歴が追加された整備です。関連の確認が必要です。');continue
                parts=rows(g['VehiclePartReplacement'],maintenance_record_id=record.id)
                if any(p.updated_by_username for p in parts):problems.append('部品記録が手動編集されています。関連の確認が必要です。');continue
                for part in parts:
                    for src in rows(g['VehiclePartReplacementSource'],replacement_id=part.id):own(src)
                    own(part)
                for event in events:own(event)
                own(record)
            elif kind in ('inspection','driving_report'):
                model=g['VehiclePeriodicInspectionRecord' if kind=='inspection' else 'VehicleDrivingReportRecord']
                records2=rows(model,vehicle_record_id=vehicle.id,id=link.get('record_id'),source_draft_id=draft.id)
                if len(records2)!=1:problems.append('取込記録の出典が一致しません。');continue
                if kind=='driving_report' and records2[0].operation_record_id is not None:problems.append('運行記録と共有されています。関連の取消が必要です。');continue
                own(records2[0])
            else:problems.append('この資料種別は取込取消に未対応です。')
        # Find every foreign-key child. Never silently cascade an unrelated record.
        owned_keys={(x.__table__.name,x.id) for x in owned}
        for parent in owned:
            for table in db.metadata.tables.values():
                for column in table.columns:
                    for fk in column.foreign_keys:
                        if fk.column.table.name!=parent.__table__.name or fk.column.name!='id':continue
                        selected=db.session.execute(select(table).where(column==parent.id)).mappings().all()
                        for row in selected:
                            if (table.name,row.get('id')) not in owned_keys:
                                problems.append('別の資料・点検計画・不具合対応等と共有されている記録があります。関連を確認してから取り消してください。')
        # Check draft references too: unlisted sources or pending records must not remain active.
        for name in ('VehicleMaintenanceDocument','VehiclePeriodicInspectionRecord','VehicleDrivingReportRecord'):
            for row in rows(g[name],source_draft_id=draft.id):
                if (row.__table__.name,row.id) not in owned_keys:problems.append('この原本には一覧以外の関連記録があります。関連の確認が必要です。')
        for row in rows(g['VehicleMaintenanceRecord']):
            src=parse(row.invoice_details_json).get('source') or {}
            if isinstance(src,dict) and src.get('draft_id')==draft.id and (row.__table__.name,row.id) not in owned_keys:
                problems.append('この資料由来の整備記録に未確認の関連があります。')
        for row in rows(g['VehicleImportPendingRecord'],document_draft_id=draft.id):
            if row.status=='pending':problems.append('原本に登録待ちの明細があります。')
            else:own(row)
        ordered=[];remaining=list(owned)
        while remaining:
            leaves=[]
            for candidate in remaining:
                has_child=False
                for child in remaining:
                    if child is candidate:continue
                    for column in child.__table__.columns:
                        for fk in column.foreign_keys:
                            if fk.column.table.name==candidate.__table__.name and fk.column.name=='id' and getattr(child,column.key)==candidate.id:has_child=True
                if not has_child:leaves.append(candidate)
            if not leaves:
                problems.append('関連記録が循環しています。関連の確認が必要です。');break
            for row in leaves:ordered.append(row);remaining.remove(row)
        owned=ordered if not remaining else owned
        ids=[]
        for row in owned:
            prefix={'vehicle_maintenance_record':'maintenance','vehicle_part_replacement':'part','vehicle_periodic_inspection_record':'periodic','vehicle_driving_report_record':'driving_report'}.get(row.__table__.name)
            if prefix:ids.append(f'{prefix}:{row.id}')
        feedback=[]
        for row in rows(g['VehicleAnalysisFeedback'],vehicle_record_id=vehicle.id):
            snap=parse(row.snapshot_json);refs=(snap.get('proposal') or {}).get('source_ids',[])
            if isinstance(refs,list) and set(ids).intersection(x for x in refs if isinstance(x,str)):feedback.append(row)
        state=g['VehicleKarteAnalysis'].query.filter_by(company_code=company,vehicle_record_id=vehicle.id).first()
        value={'draft':snapshot(draft),'owned':[snapshot(x) for x in owned],'feedback':[snapshot(x) for x in feedback],
               'state':snapshot(state) if state else None,'problems':sorted(set(problems))}
        return {'digest':digest(value),'owned':owned,'feedback':feedback,'state':state,'ids':ids,
                'problems':sorted(set(problems)),'records':[{'kind':x.__table__.name,'id':x.id,'date':getattr(x,'entry_date',None) or getattr(x,'inspection_date',None) or getattr(x,'replacement_date',None) or '', 'content':getattr(x,'content',None) or getattr(x,'part_name',None) or '', 'cost':getattr(x,'total_cost',None)} for x in owned if x.__table__.name in ('vehicle_maintenance_record','vehicle_periodic_inspection_record','vehicle_part_replacement')],'counts':{
                    '整備記録':sum(type(x) is g['VehicleMaintenanceRecord'] for x in owned),
                    '部品交換':sum(type(x) is g['VehiclePartReplacement'] for x in owned),
                    '点検記録':sum(type(x) is g['VehiclePeriodicInspectionRecord'] for x in owned),
                    '添付のみの関連':len(detach)}}

    @app.before_request
    def reject_deleted_source():
        if request.endpoint!='vehicle_document_import_source':return None
        draft_id=(request.view_args or {}).get('draft_id')
        row=g['VehicleDocumentImportDraft'].query.filter_by(id=draft_id,company_code=session.get('company_code')).first()
        if row is not None and row.status=='deleted':abort(404)

    @app.route('/vehicle/karte/<int:vehicle_record_id>/documents/<draft_id>/delete',methods=['GET','POST'],endpoint='vehicle_document_delete')
    def delete_document(vehicle_record_id,draft_id):
        vehicle,draft=require_access(vehicle_record_id,draft_id,request.method=='POST')
        p=plan(vehicle,draft,request.method=='POST')
        serializer=URLSafeTimedSerializer(app.secret_key,salt='vehicle-document-delete-v1')
        token=serializer.dumps({'company':vehicle.company_code,'vehicle':vehicle.id,'draft':draft.id,'digest':p['digest'],'user':session['username']})
        if request.method=='GET':return render_template('vehicle_document_delete_confirm.html',vehicle=vehicle,draft=draft,impact=p,delete_token=token)
        if p['problems']:abort(409,description='関連記録を保護するため削除を停止しました。削除確認画面を開き直してください。')
        try:data=serializer.loads(request.form.get('delete_token',''),max_age=900)
        except (BadSignature,SignatureExpired):abort(409,description='削除確認の有効期限が切れました。開き直してください。')
        if data!={'company':vehicle.company_code,'vehicle':vehicle.id,'draft':draft.id,'digest':p['digest'],'user':session['username']} or request.form.get('confirm_delete')!='yes':abort(409,description='記録が変更されています。削除確認をやり直してください。')
        try:
            # Retain responses as withdrawn history, and exclude them from future AI input.
            for feedback in p['feedback']:
                snap=parse(feedback.snapshot_json);snap['source_withdrawn']={'draft_id':draft.id,'at':datetime.now(timezone.utc).isoformat()}
                feedback.snapshot_json=json.dumps(snap,ensure_ascii=False)
            # Topological child-first order; foreign-key links to surviving data were blocked above.
            for row in p['owned']:
                db.session.delete(row);db.session.flush()
            metadata={'filename':draft.source_filename,'sha256':draft.source_sha256,'removed_sources':p['ids'],'counts':p['counts']}
            draft.status='deleted';draft.source_file=b'';draft.preview_json='{}';draft.result_json=json.dumps({'deleted':True,'at':datetime.now(timezone.utc).isoformat(),'by':session['username']},ensure_ascii=False)
            state=p['state']
            if state:
                state.result_json='{}';state.status='pending';state.input_hash=None;state.lease_token=None;state.lease_expires_at=None;state.last_error=None
            db.session.flush()
            payload,_=g['get_vehicle_karte_analysis_job_data'](vehicle)
            state=g['queue_vehicle_karte_analysis'](vehicle,payload)
            state.next_analysis_at=datetime.now(timezone.utc);state.request_reason='誤登録資料の削除・由来記録の取消'
            g['add_audit_log']('delete_imported_document','VehicleDocumentImportDraft',draft.id,json.dumps(metadata,ensure_ascii=False))
            db.session.commit()
        except BaseException:
            db.session.rollback();raise
        flash('資料と、その資料だけが根拠の登録データを削除しました。AI分析を更新待ちにしました。','success')
        return redirect(url_for('vehicle_karte_documents',vehicle_record_id=vehicle.id))
    return {'plan':plan}
