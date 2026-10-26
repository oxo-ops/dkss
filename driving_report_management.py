"""Company-scoped report review, reconciliation and exports. No AI calls on GET."""
import csv
import hashlib
import io
import json
from urllib.parse import urlsplit
from datetime import date, datetime
from zoneinfo import ZoneInfo
from flask import abort, flash, redirect, render_template, request, send_file, session, url_for
from driving_report_pdf import export_pdf
from driving_report_insights import periods, driver_keys, collect, dashboard as insights_dashboard, number, review_notes
from driving_report_data import payload, version, identity, decimal, match_report, canonical_operations, metrics_summary, eligible_reports

STATES={'unreviewed':'未確認','reviewed':'確認済み','coaching':'指導・対応中','followup':'次回振り返り','completed':'対応完了'}
MATCH={'standalone':'日報のみ','distinct':'別運行として確認済み','matched':'CSVと照合済み','resolved':'採用値を確認済み','conflict':'CSVとの値が不一致','ambiguous':'CSVとの対応を確認'}
LABELS={'distance':'走行距離','departure_meter':'開始積算距離','arrival_meter':'終了積算距離'}


def register_driving_reports(app, db, g):
    Record=g['VehicleDrivingReportRecord'];Operation=g['VehicleOperationRecord'];Vehicle=g['Vehicle'];Draft=g['VehicleDocumentImportDraft']
    def access():
        if not g['require_master_admin']():abort(403)
    def report_return():
        value=request.args.get('return_to') or request.form.get('return_to') or ''
        try:parts=urlsplit(value)
        except ValueError:return url_for('driving_reports')
        return value if not parts.scheme and not parts.netloc and parts.path=='/safety/driving-reports' else url_for('driving_reports')
    def target(record_id,lock=False):
        access();q=Record.query.filter_by(company_code=session['company_code'],id=record_id)
        return (q.with_for_update() if lock else q).first_or_404()
    def operations(company,vehicle):
        return Operation.query.filter_by(company_code=company,vehicle_record_id=vehicle).all()
    def reports(company,vehicle):
        return Record.query.filter_by(company_code=company,vehicle_record_id=vehicle).all()
    def canonical(company,vehicle,rows=None):
        return canonical_operations(operations(company,vehicle) if rows is None else rows,reports(company,vehicle))
    def selected(args=None):
        args=request.args if args is None else args
        access();q=Record.query.filter_by(company_code=session['company_code'])
        for name,op in [('start','ge'),('end','le')]:
            value=args.get(name,'').strip()
            if value:
                try:date.fromisoformat(value)
                except ValueError:abort(400)
                q=q.filter(Record.operation_date>=value) if op=='ge' else q.filter(Record.operation_date<=value)
        if args.get('start') and args.get('end') and args['start']>args['end']:abort(400)
        if args.get('vehicle'):
            try:vid=int(args['vehicle'])
            except ValueError:abort(400)
            q=q.filter_by(vehicle_record_id=vid)
        rows=q.order_by(Record.operation_date.desc(),Record.id.desc()).all()
        # Text filters are applied to original report fields, never a driver's current assignment.
        for name,fields in [('driver',('driver_name','driver_code')),('office',('office_name','driver_office','vehicle_office'))]:
            value=args.get(name,'').strip()
            if len(value)>200:abort(400)
            if value:rows=[r for r in rows if any(value in str(payload(r).get(f) or '') for f in fields)]
        state=args.get('state','')
        if state:
            if state not in STATES and state!='cancelled':abort(400)
            rows=[r for r in rows if (payload(r).get('lifecycle')=='cancelled' if state=='cancelled' else (payload(r).get('review') or {}).get('state','unreviewed')==state and payload(r).get('lifecycle') not in {'cancelled','superseded'})]
        return rows
    def view(row,ops=None,vehicle_label=None):
        p=payload(row);v=Vehicle.query.filter_by(company_code=row.company_code,id=row.vehicle_record_id).first() if vehicle_label is None else None
        match=match_report(row,operations(row.company_code,row.vehicle_record_id) if ops is None else ops)
        plate=vehicle_label if vehicle_label is not None else g['vehicle_number']({f:getattr(v,f) or '' for f in ['plate_area','plate_class','plate_kana','plate_number']}) if v else '車両なし'
        return {'row':row,'data':p,'plate':plate,'match':match,'review':p.get('review') or {},'lifecycle':p.get('lifecycle','active'),'version':version(row)}
    def dimensions(rows):
        grouped={}
        for row in rows:
            p=payload(row)
            if p.get('lifecycle') in {'cancelled','superseded'}:continue
            driver=(str(p.get('source_system'))+' / '+str(p.get('driver_code'))) if p.get('driver_code') and p.get('source_system') else (p.get('driver_name') or '乗務員不明')+'（未照合・日報 '+str(row.id)+'）'
            key=(driver,p.get('driver_office') or p.get('office_name') or '所属不明')
            grouped.setdefault(key,[]).append(row)
        return [{'driver':key[0],'office':key[1],**metrics_summary(values)} for key,values in grouped.items()]
    @app.context_processor
    def driving_context():
        return {'driving_review_states':STATES,'driving_match_labels':MATCH,'driving_conflict_labels':LABELS,'driving_scope_labels':{'trip':'1運行','daily':'日別','monthly':'月次集計','unknown':'不明'},'driving_item_status':{'candidate':'読取候補','confirmed':'確認済み','illegible':'判読不能','not_recorded':'記載なし','not_applicable':'対象外','unknown':'不明'},'driving_speaker_labels':{'auto':'自動コメント','driver':'乗務員','manager':'管理者','unknown':'話者不明'}}
    def persist(row, old_json):
        values={"details_json":row.details_json,"operation_date":row.operation_date,"mileage":row.mileage,"content":row.content,"report_number":row.report_number,"operation_record_id":row.operation_record_id}
        with db.session.no_autoflush:
            count=Record.query.filter_by(id=row.id,company_code=row.company_code,details_json=old_json).update(values,synchronize_session=False)
        if count!=1:
            db.session.rollback();abort(409,'記録が更新されました。再表示してください。')
        # The explicit conditional update is authoritative; do not flush a stale ORM update later.
        from sqlalchemy.orm.attributes import set_committed_value
        for key,value in values.items():set_committed_value(row,key,value)
        db.session.commit()
    def prepare_insights(args,scope_override=None):
        access()
        allowed={'period','start','end','driver','office','vehicle','state','metric','focus','page'}
        args={key:args[key] for key in allowed if key in args}
        for key in ('metric','focus'):
            if args.get(key) and (len(args[key])!=24 or any(c not in '0123456789abcdef' for c in args[key])):abort(400)
        today=datetime.now(ZoneInfo('Asia/Tokyo')).date()
        try:period=scope_override or periods(args,today)
        except (ValueError,OverflowError) as exc:abort(400,str(exc))
        resolved=dict(args);resolved.update(period=period['mode'],start=period['start'],end=period['end'])
        rows=selected(resolved)
        previous=selected(dict(resolved,start=period['previous_start'],end=period['previous_end'])) if period['previous_start'] else []
        q=Record.query.filter_by(company_code=session['company_code'])
        if period['start']:q=q.filter(Record.operation_date>=(period['previous_start'] or period['start']))
        if period['end']:q=q.filter(Record.operation_date<=period['end'])
        context=q.all()
        vehicles=Vehicle.query.filter_by(company_code=session['company_code']).all()
        labels={v.id:g['vehicle_number']({f:getattr(v,f) or '' for f in ['plate_area','plate_class','plate_kana','plate_number']}) or v.chassis_number or '車両 '+str(v.id) for v in vehicles}
        ids={r.vehicle_record_id for r in context};ops={}
        if ids:
            query=Operation.query.filter(Operation.company_code==session['company_code'],Operation.vehicle_record_id.in_(ids))
            if period['start']:query=query.filter(Operation.operation_date>=(period['previous_start'] or period['start']))
            if period['end']:query=query.filter(Operation.operation_date<=period['end'])
            for row in query.all():ops.setdefault((row.company_code,row.vehicle_record_id),[]).append(row)
        keys,conflicting=driver_keys(context)
        warning_keys={keys[r.id] for r in context if driver_keys([r])[0][r.id] in conflicting}
        current_context=[r for r in context if (not period['start'] or r.operation_date>=period['start']) and (not period['end'] or r.operation_date<=period['end'])]
        previous_context=[r for r in context if period['previous_start'] and period['previous_start']<=r.operation_date<=period['previous_end']]
        facts,issues=collect(rows,ops,keys,current_context)
        before,old_issues=collect(previous,ops,keys,previous_context)
        board=insights_dashboard(facts,before,labels,args.get('metric',''),args.get('focus',''))
        for driver in board['drivers']:
            driver['identity_warning']=not driver['identified'] or driver['key'] in warning_keys
        board.update(period=period,issues=issues,previous_issues=old_issues,labels=labels,
            review_notes=review_notes(rows,facts,issues,conflicting),
            pending_count=sum((payload(r).get('review') or {}).get('state') in {'coaching','followup'} and payload(r).get('lifecycle') not in {'cancelled','superseded'} for r in rows))
        return rows,previous,ops,vehicles,resolved,board,facts

    def history_context(board,facts):
        focus=board['selected_driver']
        ids={f['vehicle_id'] for f in facts if focus and f['driver_key']==focus['key']}
        if not ids:return []
        cutoff=board['period']['end'] or datetime.now(ZoneInfo('Asia/Tokyo')).date().isoformat()
        M=g['VehicleMaintenanceRecord']
        records=M.query.filter(M.company_code==session['company_code'],M.vehicle_record_id.in_(ids),
            M.completion_date.isnot(None),M.completion_date!='',M.completion_date<=cutoff,
            M.status.in_(['完了','completed','']) | M.status.is_(None)).order_by(M.completion_date.desc(),M.id.desc()).all()
        grouped={vid:[] for vid in ids}
        for row in records:
            if len(grouped[row.vehicle_record_id])<5:grouped[row.vehicle_record_id].append(row)
        return [{'id':vid,'label':board['labels'].get(vid,'車両 '+str(vid)),
            'summary':insights_dashboard([f for f in facts if f['vehicle_id']==vid and f['driver_key']==focus['key']],[],board['labels'],board['metric_id'])['summary'],
            'records':grouped[vid]} for vid in sorted(ids)]

    @app.route('/safety/driving-reports')
    def driving_reports():
        rows,previous,ops,vehicles,filters,board,facts=prepare_insights(request.args)
        try:page=max(1,int(request.args.get('page','1')))
        except ValueError:abort(400)
        summary=metrics_summary(rows)
        summary.update(distance=str(board['summary']['distance']) if board['summary']['distance'] is not None else None,
            operation_count=board['summary']['count'],distance_count=board['summary']['distance_count'])
        return render_template('driving_reports.html',reports=[view(r,ops.get((r.company_code,r.vehicle_record_id),[]),board['labels'].get(r.vehicle_record_id)) for r in rows[(page-1)*100:page*100]],
            summary=summary,insights=board,vehicle_history=history_context(board,facts),page=page,total=len(rows),filters=filters,filter_query=filters,vehicles=vehicles,
            insight_number=number)
    @app.route('/safety/driving-reports/<int:record_id>')
    def driving_report_detail(record_id):
        row=target(record_id)
        return render_template('driving_report_detail.html',report=view(row),report_return_url=report_return(),assignees=g['User'].query.filter_by(company_code=row.company_code,role='admin').all())
    def change(row,kind,detail):
        p=payload(row);events=p.setdefault('audit',[])
        if len(events)>=1000:abort(409,'変更履歴の保存上限です。管理者へ確認してください。')
        events.append({'kind':kind,'by':session['username'],'at':datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),'detail':detail})
        return p
    @app.route('/safety/driving-reports/<int:record_id>/review',methods=['POST'])
    def driving_report_review(record_id):
        row=target(record_id,True);old_json=row.details_json
        if request.form.get('version')!=version(row):abort(409,'記録が更新されました。再表示してください。')
        state=request.form.get('state','');note=request.form.get('note','').strip();next_date=request.form.get('next_date','');assignee=request.form.get('assignee','')
        review=payload(row).get('review') or {}
        action=request.form.get('action',review.get('action','')).strip()
        explanation=request.form.get('driver_explanation',review.get('driver_explanation','')).strip()
        if state not in STATES or max(len(note),len(action),len(explanation))>5000:abort(400)
        if next_date:
            try:date.fromisoformat(next_date)
            except ValueError:abort(400)
        if assignee and not g['User'].query.filter_by(company_code=row.company_code,username=assignee,role='admin').first():abort(400)
        p=change(row,'review',{'before':payload(row).get('review'), 'state':state,'note':note,'next_date':next_date,'assignee':assignee,'action':action,'driver_explanation':explanation})
        previous=p.get('review') or {};p['review']={'state':state,'note':note,'next_date':next_date,'assignee':assignee,'action':action,'driver_explanation':explanation,'by':session['username'],'at':p['audit'][-1]['at']}
        # A deliberate assignment requests review of a past report; repeated saves do not re-notify.
        if assignee and assignee!=previous.get('assignee'):
            user=g['User'].query.filter_by(company_code=row.company_code,username=assignee).one()
            db.session.add(g['Notification'](company_code=row.company_code,target_user=(str(user.last_name or '')+str(user.first_name or '')) or assignee,target_username=assignee,title='取り込んだ運転日報の確認依頼',message=(row.operation_date or '日付不明')+'の過去日報を確認してください。',link=url_for('driving_report_detail',record_id=row.id),created_at=datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y-%m-%d %H:%M:%S')))
        row.details_json=json.dumps(p,ensure_ascii=False)
        persist(row,old_json);return redirect(url_for('driving_report_detail',record_id=row.id,return_to=report_return()))
    @app.route('/safety/driving-reports/<int:record_id>/reconcile',methods=['POST'])
    def driving_report_reconcile(record_id):
        row=target(record_id,True);old_json=row.details_json
        if request.form.get('version')!=version(row):abort(409)
        mode=request.form.get('mode');use=request.form.get('use')
        if mode not in {'linked','distinct','cancelled'}:abort(400)
        p=change(row,'reconciliation',{'mode':mode,'operation_id':request.form.get('operation_id'),'use':use})
        if mode=='cancelled':p['lifecycle']='cancelled'
        elif mode=='distinct':p['reconciliation']={'mode':'distinct'};row.operation_record_id=None
        else:
            if use not in {'pdf','csv'}:abort(400)
            try:oid=int(request.form.get('operation_id',''))
            except ValueError:abort(400)
            candidate=Operation.query.filter_by(id=oid,company_code=row.company_code,vehicle_record_id=row.vehicle_record_id,operation_date=row.operation_date).first_or_404()
            original=row.details_json
            p['reconciliation']={'mode':'linked','operation_id':candidate.id}
            row.details_json=json.dumps(p,ensure_ascii=False);matched=match_report(row,[candidate])
            p['reconciliation'].update({'use':use,'fingerprint':matched['fingerprint']});row.operation_record_id=candidate.id
            row.details_json=original
        row.details_json=json.dumps(p,ensure_ascii=False);persist(row,old_json)
        return redirect(url_for('driving_report_detail',record_id=row.id))
    @app.route('/safety/driving-reports/<int:record_id>/edit',methods=['GET','POST'])
    def driving_report_edit(record_id):
        row=target(record_id,request.method=='POST');old_json=row.details_json;draft=Draft.query.filter_by(id=row.source_draft_id,company_code=row.company_code,status='completed').first_or_404();p=payload(row)
        choices=[{'id':v.id,'number':g['vehicle_number']({f:getattr(v,f) or '' for f in ['plate_area','plate_class','plate_kana','plate_number']}),'chassis_number':v.chassis_number or '','deleted':v.deleted} for v in Vehicle.query.filter_by(company_code=row.company_code).all()]
        if request.method=='POST':
            if request.form.get('record_version')!=version(row):abort(409)
            values,errors=g['validate_vehicle_document_record'](draft,row.source_record_index,p,request.form,allow_pending_vehicle=False)
            if errors:return g['return_form_errors'](errors)
            if values['vehicle_record_id']!=row.vehicle_record_id:abort(400,'訂正では対象車両を変更できません。')
            updated=change(row,'correction',{'before':p,'record_date':values['record_date']})
            # Store only the changed snapshot in the audit, without recursively copying audit history.
            updated['audit'][-1]['detail']['before']={k:v for k,v in p.items() if k!='audit'}
            for key in ('audit','review','lifecycle'):values[key]=updated.get(key,p.get(key))
            values.pop('reconciliation',None);row.operation_record_id=None
            row.operation_date=values['record_date'];row.mileage=decimal(values.get('mileage'));row.content=values['content'];row.report_number=values.get('report_number');row.details_json=json.dumps(values,ensure_ascii=False)
            persist(row,old_json);return redirect(url_for('driving_report_detail',record_id=row.id,return_to=report_return()))
        originals=g['safe_json_dict'](draft.preview_json).get('original_records') or []
        original=originals[row.source_record_index] if row.source_record_index<len(originals) else p
        doc={'id':draft.id,'filename':draft.source_filename,'document_type':'driving_report','preview':{'records':[p],'original_records':[None]*row.source_record_index+[original]}}
        # Preserve the immutable original record index used by form names and source navigation.
        doc['record_index_offset']=row.source_record_index
        doc['source_url']=url_for('vehicle_driving_report_source',record_id=row.id)
        return render_template('vehicle_document_import_preview.html',documents=[doc],batch_id=draft.batch_id,vehicle_choices=choices,save_action=url_for('driving_report_edit',record_id=row.id),record_version=version(row),edit_record=True)
    @app.route('/safety/driving-reports/export.<format>')
    def driving_report_export(format):
        export_args=dict(request.args)
        if 'period' in export_args:
            try:period=periods(export_args,datetime.now(ZoneInfo('Asia/Tokyo')).date())
            except (ValueError,OverflowError) as exc:abort(400,str(exc))
            export_args.update(start=period['start'],end=period['end'])
        rows=selected(export_args)
        if format not in {'csv','pdf'}:abort(404)
        heading=['日報ID','運行日','対象期間終了','車両','乗務員','営業所','メーカー','帳票','粒度','状態','取込確認','開始時刻','終了時刻','開始積算距離km','終了積算距離km','走行距離km','走行時間','アイドリング時間','消費燃料','燃料単位','燃費','燃費単位','確認指導内容','次回確認日','確認担当','CSV照合状態','採用元','CSV記録ID','抽出条件','出力日時','区分','項目','原文値','数値','単位','分子','分母','分母単位','点数','評価','定義','閾値','道路','開始','終了','場所','話者','備考','原本ページ','原本ID']
        output=[]
        for r in rows:
            p=payload(r);base=[r.id,r.operation_date,p.get('operation_end_date'),p.get('registration_number'),p.get('driver_name'),p.get('driver_office') or p.get('office_name'),p.get('source_system'),p.get('report_title'),p.get('report_scope'),p.get('lifecycle','active'),STATES.get((p.get('review') or {}).get('state','unreviewed'))]
            review=p.get('review') or {}
            base += [p.get(k) for k in ('operation_start_time','operation_end_time','start_mileage','mileage','distance','driving_time','idle_time','fuel_consumption','fuel_unit','fuel_economy','fuel_economy_unit')]
            match=match_report(r,operations(r.company_code,r.vehicle_record_id))
            base += [review.get('note'),review.get('next_date'),review.get('assignee'),MATCH[match['status']],match.get('use'),match['operation'].id if match['operation'] else None,json.dumps(request.args.to_dict(),ensure_ascii=False),datetime.now(ZoneInfo('Asia/Tokyo')).isoformat()]
            collections=['report_items','events','duties','extra_items']
            for collection in collections:
                for item in p.get(collection,[]):
                    output.append(base+[collection,item.get('item_name'),item.get('raw_result'),item.get('value'),item.get('unit'),item.get('numerator'),item.get('denominator'),item.get('denominator_unit'),item.get('score'),item.get('result_text'),item.get('definition'),item.get('threshold'),item.get('road_type'),item.get('start_at'),item.get('end_at'),item.get('place'),item.get('speaker'),((item.get('notes') or '')+' 読取状態:'+str(item.get('status') or '不明')),item.get('source_page'),r.source_draft_id])
            if not any(p.get(c) for c in collections):output.append(base+['']*(len(heading)-len(base)-1)+[r.source_draft_id])
            for e in p.get('audit',[]):output.append(base+['確認履歴',e.get('kind'),json.dumps(e,ensure_ascii=False)]+['']*(len(heading)-len(base)-4)+[r.source_draft_id])
        reviews={r.id:payload(r).get('review') or {} for r in rows}
        heading += ['改善する行動','乗務員の説明']
        output=[values+[reviews[values[0]].get('action'),reviews[values[0]].get('driver_explanation')] for values in output]
        board=None
        if request.args.get('view')=='comparison' or format=='pdf':
            partial=None
            if 'period' not in export_args and bool(export_args.get('start'))!=bool(export_args.get('end')):
                partial={'mode':'custom','start':export_args.get('start',''),'end':export_args.get('end',''),'previous_start':'','previous_end':''}
            _,_,_,_,_,board,_=prepare_insights(dict(export_args,period=export_args.get('period','custom' if export_args.get('start') and export_args.get('end') else 'all')),partial)
        if format=='csv' and request.args.get('view')=='comparison':
            heading=['開始日','終了日','前期間開始','前期間終了','乗務員','コード','営業所','使用車両','運行数','走行距離km','指標','単位','表示値','前期間値','差','対象運行数','計算分子','計算分母','原本日付','提供元','設定版','定義','閾値','道路区分','日報ID','本人照合']
            output=[]
            m=board['metric'] or {}
            for driver in board['drivers']:
                now=driver['current'];before=driver['previous'];period=board['period']
                output.append([period['start'],period['end'],period['previous_start'],period['previous_end'],driver['name'],driver['code'],' / '.join(driver['offices']),
                    ' / '.join(v['label'] for v in driver['vehicles']),now['count'],number(now['distance']),m.get('name'),m.get('unit'),now['display'],before['display'],driver['change'],
                    now['metric_count'],number(now['numerator']),number(now['denominator']),now.get('latest_date'),m.get('source'),m.get('version'),m.get('definition'),m.get('threshold'),m.get('road'),
                    ' / '.join(str(i) for i in now['sources']),'未照合' if driver['identity_warning'] else 'コードで照合'])
        if format=='csv':
            out=io.StringIO();writer=csv.writer(out);writer.writerow(heading)
            def safe(value):
                text=str(value) if value is not None else ''
                return "'"+text if text.lstrip().startswith(('=','+','-','@')) or text.startswith(('\t','\r','\n')) else text
            for values in output:writer.writerow([safe(v) for v in values])
            content=('\ufeff'+out.getvalue()).encode('utf-8');mime='text/csv; charset=utf-8'
        else:
            summary=metrics_summary(rows)
            lines=['運転実績と確認記録','出力日時 '+datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),'抽出条件 '+json.dumps(request.args.to_dict(),ensure_ascii=False),'会社 '+session['company_code'],f'日報 {len(rows)}件 比較条件不足 {len(summary["not_comparable"])}項目','原本の点数は方式別に保持。異なる方式の平均・順位は算出しません。','']
            if board:
                p=board['period'];m=board['metric'] or {}
                lines += ['乗務員ごとの運転傾向',f'対象 {p["start"] or "全期間"} ～ {p["end"] or ""}',
                    f'前期間 {p["previous_start"] or "なし"} ～ {p["previous_end"] or ""}',f'指標 {m.get("name", "なし")} {m.get("unit", "")}',
                    f'出典・条件 {m.get("source", "")} {m.get("version", "")} {m.get("definition", "")} {m.get("threshold", "")} {m.get("road", "")}' ]
                for person in board['drivers']:
                    now=person['current']
                    lines += [f'{person["name"]} {person["code"]} {" / ".join(person["offices"])}',
                        f'運行 {now["count"]}件 距離 {number(now["distance"])}km 指標 {now["display"]} {m.get("unit", "")} 対象 {now["metric_count"]}件',
                        f'前期間 {person["previous"]["display"]} 差 {person["change"] or "比較値なし"}',
                        '出典日報 '+', '.join(str(v) for v in now['sources'])]
            for group in summary['groups']:
                lines += [f'比較可能指標 {group["source_system"]} {group["version"]} {group["name"]} 単位 {group["unit"]} {group["count"]}件',f'定義 {group["definition"]} 条件 {group["threshold"] or "不明"} 分子合計/分母合計 {group["ratio"] or "算出対象外"}']
            for r in rows:
                p=payload(r);review=p.get('review') or {};match=match_report(r,operations(r.company_code,r.vehicle_record_id))
                lines += [f'CSV照合 {MATCH[match["status"]]} 採用 {match.get("use") or "日報のみ"} 取込状態 {"取消" if p.get("lifecycle") == "cancelled" else "有効"}']
                lines += [f'日報 {r.id} 運行 {r.operation_date or "不明"} {p.get("registration_number") or ""}',f'乗務員 {p.get("driver_name") or "不明"} 所属 {p.get("driver_office") or p.get("office_name") or "不明"}',f'帳票 {p.get("source_system") or "不明"} {p.get("report_title") or ""} 粒度 {p.get("report_scope") or "trip"}',f'積算 {p.get("mileage") or "未取得"} km 距離 {p.get("distance") or "未取得"} km',f'確認 {STATES.get(review.get("state","unreviewed"))} 担当 {review.get("assignee") or "未設定"} 次回 {review.get("next_date") or "未設定"}',f'所見 {review.get("note") or "記載なし"}',f'改善する行動 {review.get("action") or "未設定"}',f'乗務員の説明 {review.get("driver_explanation") or "記載なし"}']
                labels={'operation_start_time':'開始時刻','operation_end_time':'終了時刻','driving_time':'走行時間','handling_time':'ハンドル時間','idle_time':'アイドリング時間','rest_time':'休憩休息','work_time':'作業時間','fuel_consumption':'消費燃料','fuel_unit':'燃料単位','fuel_economy':'燃費','fuel_economy_unit':'燃費単位','driver_comment':'乗務員コメント','manager_comment':'管理者所見','notes':'手書き特記事項','definition_version':'評価設定版','issued_at':'出力日時','timezone':'タイムゾーン'}
                for key,label in labels.items():
                    if p.get(key) is not None:lines.append(label+' '+str(p[key]))
                for collection in ['report_items','events','duties','extra_items']:
                    for item in p.get(collection,[]):lines += [f'{item.get("category") or collection} {item.get("item_name")} {item.get("raw_result") or "未取得"} 点数 {item.get("score") or "未取得"} 評価 {item.get("result_text") or "未取得"}',f'定義 {item.get("definition") or "不明"} 単位 {item.get("unit") or "不明"} 条件 {item.get("threshold") or "不明"} 原本 {item.get("source_page")}頁',f'数値 {item.get("value") or "未取得"} 分子 {item.get("numerator") or "未取得"} 分母 {item.get("denominator") or "未取得"} {item.get("denominator_unit") or ""}',f'日時 {item.get("start_at") or "不明"} ～ {item.get("end_at") or "不明"} 場所 {item.get("place") or "不明"}',str(item.get('notes') or '')]
                for e in p.get('audit',[]):lines += ['確認履歴 '+json.dumps(e,ensure_ascii=False)]
                lines += [f'出典 日報:{r.id} 原本:{r.source_draft_id}','']
            content=export_pdf(lines);mime='application/pdf'
        response=send_file(io.BytesIO(content),mimetype=mime,as_attachment=True,download_name='driving-reports.'+format,max_age=0);response.headers['Cache-Control']='private, no-store';return response
    return {'canonical':canonical,'reports':reports,'view':view,'summary':metrics_summary}
