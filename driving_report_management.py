"""Company-scoped report review, reconciliation and exports. No AI calls on GET."""
import csv
import hashlib
import io
import json
from urllib.parse import urlsplit
from datetime import date, datetime
from zoneinfo import ZoneInfo
from sqlalchemy import and_, or_
from flask import abort, flash, redirect, render_template, request, send_file, session, url_for
from driving_report_pdf import export_pdf
import driving_report_workspace as workspace
import driving_report_comparisons as comparisons
import driving_report_maintenance as maintenance_context
import driving_report_conditions as vehicle_conditions
import driving_report_presentation as presentation
from driving_report_reflection import register_reflections
from dkss_app import driving_access as readership
from driving_report_insights import periods, driver_keys, collect, dashboard as insights_dashboard, number, review_notes
from driving_report_data import payload, version, identity, decimal, match_report, canonical_operations, metrics_summary, eligible_reports

def shown(value):
    return str(value) if value is not None and value!='' else '未取得'


STATES={'unreviewed':'未確認','reviewed':'確認済み','coaching':'指導・対応中','followup':'次回振り返り','completed':'対応完了'}
OUTCOMES={'':'未確認','improved':'改善を確認','continue':'継続確認','incomparable':'比較困難'}
MATCH={'standalone':'日報のみ','distinct':'別運行として確認済み','matched':'CSVと照合済み','resolved':'採用値を確認済み','conflict':'CSVとの値が不一致','ambiguous':'CSVとの対応を確認'}
LABELS={'distance':'走行距離','departure_meter':'開始積算距離','arrival_meter':'終了積算距離'}


def register_driving_reports(app, db, g):
    Record=g['VehicleDrivingReportRecord'];Operation=g['VehicleOperationRecord'];Vehicle=g['Vehicle'];Draft=g['VehicleDocumentImportDraft']
    def access(write=False):
        if session.get('role') not in {'user','admin','itc'} or (write and not readership.administrator()):abort(403)
    def report_return():
        value=request.args.get('return_to') or request.form.get('return_to') or ''
        try:parts=urlsplit(value)
        except ValueError:return url_for('driving_reports')
        return value if not parts.scheme and not parts.netloc and parts.path=='/safety/driving-reports' else url_for('driving_reports')
    def target(record_id,lock=False):
        access(write=lock);q=Record.query.filter_by(company_code=session['company_code'],id=record_id)
        return readership.require_report((q.with_for_update() if lock else q).first_or_404())
    def operations(company,vehicle):
        return Operation.query.filter_by(company_code=company,vehicle_record_id=vehicle).all()
    def reports(company,vehicle):
        return Record.query.filter_by(company_code=company,vehicle_record_id=vehicle).all()
    def canonical(company,vehicle,rows=None):
        return canonical_operations(operations(company,vehicle) if rows is None else rows,reports(company,vehicle))
    def workspace_scope(args):
        admin=readership.administrator()
        if not admin:return workspace.scope_filter(args,[],None,False),[],[],[]
        users=g['User'].query.filter_by(company_code=session['company_code']).all()
        from dkss_app.models import Office, Driver
        masters=Driver.query.filter_by(company_code=session['company_code']).all()
        registered=Office.query.filter_by(company_code=session['company_code']).all()
        company_rows=Record.query.filter_by(company_code=session['company_code']).all()
        choices=workspace.office_choices(registered,masters,company_rows)
        user=next((u for u in users if u.username==session.get('username')),None)
        try:resolved=workspace.scope_filter(args,choices,user.office if user else None,True)
        except ValueError as exc:abort(400,str(exc))
        return resolved,choices,masters,users
    def condition_vehicles():
        query=Vehicle.query.filter_by(company_code=session['company_code'])
        if not readership.administrator():
            visible=readership.visible(Record.query.filter_by(company_code=session['company_code']).all())
            query=query.filter(Vehicle.id.in_({r.vehicle_record_id for r in visible}))
        return query.all()
    def selected(args=None):
        args=request.args if args is None else args
        access();args,choices,_,_=workspace_scope(args);q=Record.query.filter_by(company_code=session['company_code'])
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
        rows=readership.visible(q.order_by(Record.operation_date.desc(),Record.id.desc()).all())
        office=workspace.scope_name(args,choices,readership.administrator())
        if readership.administrator() and args['scope']=='office':
            rows=[r for r in rows if office and workspace.report_office(r)==office]
        # Text filters are applied to original report fields, never a driver's current assignment.
        for name,fields in [('driver',('driver_name','driver_code'))]:
            value=args.get(name,'').strip()
            if len(value)>200:abort(400)
            if value:rows=[r for r in rows if any(value in str(payload(r).get(f) or '') for f in fields)]
        state=args.get('state','')
        if state:
            if state not in STATES and state!='cancelled':abort(400)
            rows=[r for r in rows if (payload(r).get('lifecycle')=='cancelled' if state=='cancelled' else (payload(r).get('review') or {}).get('state','unreviewed')==state and payload(r).get('lifecycle') not in {'cancelled','superseded'})]
        due=args.get('followup_due','')
        if due not in {'','due','upcoming'}:abort(400)
        if due:
            today=datetime.now(ZoneInfo('Asia/Tokyo')).date()
            rows=[r for r in rows if comparisons.followup_status(r,today)==due]
        if any(args.get(field) for field in vehicle_conditions.FIELDS):
            try:rows=vehicle_conditions.apply(rows,condition_vehicles(),args)
            except ValueError as exc:abort(400,str(exc))
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
        return {'driving_is_admin':readership.administrator(),'driving_review_states':STATES,'driving_outcomes':OUTCOMES,'driving_match_labels':MATCH,'driving_conflict_labels':LABELS,'driving_scope_labels':{'trip':'1運行','daily':'日別','monthly':'月次集計','unknown':'不明'},'driving_item_status':{'candidate':'読取候補','confirmed':'確認済み','illegible':'判読不能','not_recorded':'記載なし','not_applicable':'対象外','unknown':'不明'},'driving_speaker_labels':{'auto':'自動コメント','driver':'乗務員','manager':'管理者','unknown':'話者不明'}}
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
        allowed={'category','period','start','end','driver','office','vehicle','state','metric','focus','page','compare','scope','listing','breakdown','compare_start','compare_end','followup_due','vehicle_make','vehicle_model','vehicle_body','vehicle_year'}
        args={key:args[key] for key in allowed if key in args}
        for key in ('metric','focus'):
            if args.get(key) and (len(args[key])!=24 or any(c not in '0123456789abcdef' for c in args[key])):abort(400)
        if args.get('category','safety') not in {'safety','economy','other'}:abort(400)
        args,office_options,master_drivers,company_users=workspace_scope(args)
        if args.get('listing','offices') not in {'offices','people'}:abort(400)
        if args.get('breakdown','people') not in {'offices','people','vehicle','vehicles'}:abort(400)
        if not readership.administrator():
            args['breakdown']='vehicles'
            args.pop('driver',None)
        today=datetime.now(ZoneInfo('Asia/Tokyo')).date()
        try:period=scope_override or periods(args,today)
        except (ValueError,OverflowError) as exc:abort(400,str(exc))
        resolved=dict(args);resolved.update(period=period['mode'],start=period['start'],end=period['end'])
        rows=selected(resolved)
        previous=selected(dict(resolved,start=period['previous_start'],end=period['previous_end'])) if period['previous_start'] else []
        q=Record.query.filter_by(company_code=session['company_code'])
        def date_windows(column):
            current=[]
            if period['start']:current.append(column>=period['start'])
            if period['end']:current.append(column<=period['end'])
            windows=[and_(*current)]
            if period['previous_start']:windows.append(and_(column>=period['previous_start'],column<=period['previous_end']))
            return or_(*windows)
        if period['start'] or period['end']:q=q.filter(date_windows(Record.operation_date))
        context=readership.visible(q.all())
        vehicle_query=Vehicle.query.filter_by(company_code=session['company_code'])
        if not readership.administrator():vehicle_query=vehicle_query.filter(Vehicle.id.in_({r.vehicle_record_id for r in context}))
        vehicles=vehicle_query.all()
        labels={v.id:g['vehicle_number']({f:getattr(v,f) or '' for f in ['plate_area','plate_class','plate_kana','plate_number']}) or v.chassis_number or '車両 '+str(v.id) for v in vehicles}
        ids={r.vehicle_record_id for r in context};ops={}
        if ids:
            query=Operation.query.filter(Operation.company_code==session['company_code'],Operation.vehicle_record_id.in_(ids))
            if period['start'] or period['end']:query=query.filter(date_windows(Operation.operation_date))
            for row in query.all():ops.setdefault((row.company_code,row.vehicle_record_id),[]).append(row)
        keys,conflicting=driver_keys(context)
        warning_keys={keys[r.id] for r in context if driver_keys([r])[0][r.id] in conflicting}
        confirmed=readership.bindings(context)
        for record_id,grant in confirmed.items():keys[record_id]=readership.account_key(grant)
        unfocused_rows=list(rows)
        if args.get('focus'):
            rows=[r for r in rows if keys.get(r.id)==args['focus']]
            previous=[r for r in previous if keys.get(r.id)==args['focus']]
        current_context=[r for r in context if (not period['start'] or r.operation_date>=period['start']) and (not period['end'] or r.operation_date<=period['end'])]
        previous_context=[r for r in context if period['previous_start'] and period['previous_start']<=r.operation_date<=period['previous_end']]
        # Deduplication may consult copies, but never select an out-of-scope
        # office/person as the representative or as a source of metric values.
        office=workspace.scope_name(resolved,office_options,readership.administrator())
        def in_scope(row):
            return (not readership.administrator() or resolved['scope']=='company' or
                    bool(office) and workspace.report_office(row)==office) and (
                    not args.get('focus') or keys.get(row.id)==args['focus'])
        usage_context=[r for r in current_context if (not readership.administrator() or resolved['scope']=='company' or bool(office) and workspace.report_office(r)==office)]
        shared_facts=[]
        if readership.administrator() and args.get('focus'):
            shared_facts,_=collect(unfocused_rows,ops,keys,usage_context)
            for fact in shared_facts:
                fact['identified']=fact['row'].id in confirmed or fact['identified'] and fact['driver_key'] not in warning_keys
        current_context=[r for r in current_context if in_scope(r)]
        previous_context=[r for r in previous_context if in_scope(r)]
        facts,issues=collect(rows,ops,keys,current_context)
        before,old_issues=collect(previous,ops,keys,previous_context)
        for fact in facts+before:
            if fact['row'].id in confirmed:
                fact['identified']=True;fact['identity_confirmed']=True
        registered={v.id:vehicle_conditions.metadata(v) for v in vehicles}
        for fact in facts+before:
            fact['vehicle_conditions']=registered.get(fact['vehicle_id'],{})
        board=insights_dashboard(facts,before,labels,presentation.initial_metric(facts,before,args.get('metric',''),args.get('category','safety')),args.get('focus',''))
        if not readership.administrator() and not args.get('focus') and len(board['drivers'])==1:
            resolved['focus']=board['drivers'][0]['key']
            board=insights_dashboard(facts,before,labels,presentation.initial_metric(facts,before,args.get('metric',''),args.get('category','safety')),resolved['focus'])
        for driver in board['drivers']:
            driver['identity_warning']=not driver['identified'] or driver['key'] in warning_keys
        board['condition_choices']=vehicle_conditions.choices(condition_vehicles())
        board['condition_labels']={field:label for field,(_,label) in vehicle_conditions.FIELDS.items()}
        board['condition_caption']=' ／ '.join(label+'：'+next((item['name'] for item in board['condition_choices'][field] if item['key']==resolved.get(field)), '未登録・不明') for field,label in board['condition_labels'].items() if resolved.get(field)) or '指定なし'
        board['registered_vehicle_conditions']=[registered[vid] for vid in sorted({f['vehicle_id'] for f in facts+before}) if vid in registered]
        board['shared_vehicle_usage']=vehicle_conditions.usage(shared_facts)
        board.update(period=period,issues=issues,previous_issues=old_issues,labels=labels,
            review_notes=review_notes(rows,facts,issues,conflicting),
            pending_count=sum((payload(r).get('review') or {}).get('state') in {'coaching','followup'} and payload(r).get('lifecycle') not in {'cancelled','superseded'} for r in rows))
        focus=board['selected_driver']
        scope_ids={rid for fact in facts if focus and fact['driver_key']==focus['key'] for rid in fact['copies']}
        scope=[r for r in rows if r.id in scope_ids]
        board['reader_count']=len(scope)
        board['reader_version']=hashlib.sha256(json.dumps([(r.id,version(r)) for r in scope]).encode()).hexdigest()
        board['reader_rows']=scope
        workspace.enrich(board,facts,before,master_drivers,company_users,confirmed,office_options,resolved,readership.administrator())
        board['scope']=resolved['scope']
        mode=resolved.get('breakdown') or ('vehicles' if focus else 'offices' if resolved['scope']=='company' else 'people')
        comparison_ready=not ((mode=='vehicle' and not resolved.get('vehicle')) or (mode=='vehicles' and not focus))
        board['comparison']=comparisons.build(board,facts if comparison_ready else [],before if comparison_ready else [],mode,readership.administrator())
        board['comparison']['ready']=comparison_ready
        review_items=comparisons.followups(rows)
        board['followups']=review_items
        due_ids={r.id for r in rows if comparisons.followup_status(r,today)=='due'}
        board['due_followups']=sorted([dict(item,driver_key=keys.get(item['id'],'')) for item in review_items if item['id'] in due_ids],key=lambda item:(item['review']['next_date'],item['id']))
        board['period_days']=(date.fromisoformat(period['end'])-date.fromisoformat(period['start'])).days+1 if period['start'] and period['end'] else None
        board['comparison_days']=(date.fromisoformat(period['previous_end'])-date.fromisoformat(period['previous_start'])).days+1 if period['previous_start'] else None
        summaries={rid:fact for fact in facts for rid in fact['copies']}
        board['report_metrics']={rid:[m for m in fact['metrics'] if m['id']==board['metric_id']] for rid,fact in summaries.items()}
        resolved['category']=presentation.category(board['metric']) if args.get('metric') and board.get('metric') and board['metric_id']==args['metric'] else resolved.get('category','safety')
        presentation.enrich(board,facts,before,resolved['category'])
        return rows,previous,ops,vehicles,resolved,board,facts

    reflection_service=register_reflections(app,db,prepare_insights,history=lambda board,facts:history_context(board,facts))

    def history_context(board,facts):
        focus=board['selected_driver']
        ids={f['vehicle_id'] for f in facts if focus and f['driver_key']==focus['key']}
        if not ids or not readership.administrator():return []
        cutoff=board['period']['end'] or datetime.now(ZoneInfo('Asia/Tokyo')).date().isoformat()
        M=g['VehicleMaintenanceRecord']
        records=M.query.filter(M.company_code==session['company_code'],M.vehicle_record_id.in_(ids),
            M.completion_date.isnot(None),M.completion_date!='',M.completion_date<=cutoff,
            M.status.in_(['完了','completed','']) | M.status.is_(None)).order_by(M.completion_date.desc(),M.id.desc()).all()
        grouped={vid:[] for vid in ids}
        for row in records:
            if len(grouped[row.vehicle_record_id])<5:grouped[row.vehicle_record_id].append(row)
        from dkss_app.models import VehiclePartReplacement, VehiclePeriodicInspectionRecord
        all_maintenance=M.query.filter(M.company_code==session['company_code'],M.vehicle_record_id.in_(ids)).all()
        parts=VehiclePartReplacement.query.filter(VehiclePartReplacement.company_code==session['company_code'],VehiclePartReplacement.vehicle_record_id.in_(ids)).all()
        periodic=VehiclePeriodicInspectionRecord.query.filter(VehiclePeriodicInspectionRecord.company_code==session['company_code'],VehiclePeriodicInspectionRecord.vehicle_record_id.in_(ids)).all()
        all_ops=Operation.query.filter(Operation.company_code==session['company_code'],Operation.vehicle_record_id.in_(ids)).all()
        all_reports=Record.query.filter(Record.company_code==session['company_code'],Record.vehicle_record_id.in_(ids),Record.operation_date<=cutoff).all()
        vehicles=Vehicle.query.filter(Vehicle.company_code==session['company_code'],Vehicle.id.in_(ids)).all()
        result=[]
        for vehicle in sorted(vehicles,key=lambda v:v.id):
            vid=vehicle.id
            own=lambda rows:[r for r in rows if r.vehicle_record_id==vid]
            context=maintenance_context.build(vehicle,own(all_maintenance),own(parts),
                canonical_operations(own(all_ops),own(all_reports)),own(periodic),board['period']['start'],cutoff)
            factual,_,_=maintenance_context.filter_vehicle_maintenance_factual_history(grouped[vid])
            result.append({'id':vid,'label':board['labels'].get(vid,'車両 '+str(vid)),
                'summary':insights_dashboard([f for f in facts if f['vehicle_id']==vid and f['driver_key']==focus['key']],[],board['labels'],board['metric_id'])['summary'],
                'records':factual,'context':context,'usage':board.get('shared_vehicle_usage',{}).get(vid,[])})
        return result

    @app.route('/safety/driving-reports')
    def driving_reports():
        rows,previous,ops,vehicles,filters,board,facts=prepare_insights(request.args)
        try:page=max(1,int(request.args.get('page','1')))
        except ValueError:abort(400)
        summary=metrics_summary(rows)
        reflection=reflection_service['view'](rows,previous,filters,board,facts)
        summary.update(distance=str(board['summary']['distance']) if board['summary']['distance'] is not None else None,
            operation_count=board['summary']['count'],distance_count=board['summary']['distance_count'])
        return render_template('driving_reports.html',reports=[view(r,ops.get((r.company_code,r.vehicle_record_id),[]),board['labels'].get(r.vehicle_record_id)) for r in rows[(page-1)*100:page*100]],
            summary=summary,insights=board,reflection=reflection,driving_user_office=(getattr(g['User'].query.filter_by(company_code=session['company_code'],username=session['username']).first(),'office','') or ''),vehicle_history=history_context(board,facts),page=page,total=len(rows),filters=filters,filter_query=filters,vehicles=vehicles,
            insight_number=number,reader_users=g['User'].query.filter_by(company_code=session['company_code'],role='user').order_by(g['User'].username).all() if readership.administrator() else [])
    @app.route('/safety/driving-reports/<int:record_id>')
    def driving_report_detail(record_id):
        row=target(record_id)
        return render_template('driving_report_detail.html',report=view(row),report_return_url=report_return(),assignees=g['User'].query.filter_by(company_code=row.company_code,role='admin').all() if readership.administrator() else [],
            reader=readership.reader(row) if readership.administrator() else None,
            reader_current=bool(readership.reader(row) and readership.reader(row).identity_hash==readership.fingerprint(row)) if readership.administrator() else False,
            reader_users=g['User'].query.filter_by(company_code=row.company_code,role='user').order_by(g['User'].username).all() if readership.administrator() else [])
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
        outcome=request.form.get('outcome',review.get('outcome','')).strip()
        comparison_note=request.form.get('comparison_note',review.get('comparison_note','')).strip()
        if state not in STATES or outcome not in OUTCOMES or max(len(note),len(action),len(explanation),len(comparison_note))>5000:abort(400)
        if outcome=='improved' and not comparison_note:abort(400,'改善を確認した比較条件と根拠を入力してください。')
        if next_date:
            try:date.fromisoformat(next_date)
            except ValueError:abort(400)
        if assignee and not g['User'].query.filter_by(company_code=row.company_code,username=assignee,role='admin').first():abort(400)
        p=change(row,'review',{'before':payload(row).get('review'), 'state':state,'note':note,'next_date':next_date,'assignee':assignee,'action':action,'driver_explanation':explanation,'outcome':outcome,'comparison_note':comparison_note})
        previous=p.get('review') or {};p['review']={'state':state,'note':note,'next_date':next_date,'assignee':assignee,'action':action,'driver_explanation':explanation,'outcome':outcome,'comparison_note':comparison_note,'by':session['username'],'at':p['audit'][-1]['at']}
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
        return redirect(url_for('driving_report_detail',record_id=row.id,return_to=report_return()))
    @app.route('/safety/driving-reports/<int:record_id>/edit',methods=['GET','POST'])
    def driving_report_edit(record_id):
        access(write=True)
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
        if 'period' not in export_args and bool(export_args.get('start'))!=bool(export_args.get('end')):
            partial={'mode':'custom','start':export_args.get('start',''),'end':export_args.get('end',''),'previous_start':'','previous_end':''}
        else:partial=None
        rows,_,_,_,export_args,export_board,export_facts=prepare_insights(export_args,partial)
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
            for e in (p.get('audit',[]) if readership.administrator() else []):output.append(base+['確認履歴',e.get('kind'),json.dumps(e,ensure_ascii=False)]+['']*(len(heading)-len(base)-4)+[r.source_draft_id])
        reviews={r.id:payload(r).get('review') or {} for r in rows}
        heading += ['改善する行動','乗務員の説明','前後比較の確認結果','比較条件と根拠']
        output=[values+[reviews[values[0]].get('action'),reviews[values[0]].get('driver_explanation'),OUTCOMES.get(reviews[values[0]].get('outcome','')),reviews[values[0]].get('comparison_note')] for values in output]
        board=export_board
        if format=='csv' and request.args.get('view')=='comparison':
            heading=['開始日','終了日','前期間開始','前期間終了','乗務員','コード','営業所','使用車両','運行数','走行距離km','指標','単位','表示値','前期間値','差','対象運行数','計算分子','計算分母','原本日付','提供元','設定版','定義','閾値','道路区分','日報ID','本人照合','現在所属（確認済み乗務員台帳）','所属区分','距離取得運行数','距離取得状態','前期間走行距離km','前期間距離取得運行数','前期間距離取得状態','分子単位','分母単位','算出の元値']
            output=[]
            m=board['metric'] or {}
            for driver in board['drivers']:
                now=driver['current'];before=driver['previous'];period=board['period']
                output.append([period['start'],period['end'],period['previous_start'],period['previous_end'],driver['name'],driver['code'],' / '.join(driver['offices']),
                    ' / '.join(v['label'] for v in driver['vehicles']),now['count'],number(now['distance']) if now['distance'] is not None else None,m.get('name'),m.get('unit'),now['display'],before['display'],driver['change'],
                    now['metric_count'],number(now['numerator']),number(now['denominator']),now.get('latest_date'),m.get('source'),m.get('version'),m.get('definition'),m.get('threshold'),m.get('road'),
                    ' / '.join(str(i) for i in now['sources']),'未照合' if driver['identity_warning'] else 'コードで照合',driver.get('current_office',''),driver.get('affiliation_label',''),now['distance_count'],now['distance_state'],number(before['distance']) if before['distance'] is not None else None,before['distance_count'],before['distance_state'],now['numerator_unit'],now['denominator_unit'],now['basis_display']])
        if format=='csv' and request.args.get('view')=='breakdown':
            heading=['表示範囲','開始日','終了日','前期間開始','前期間終了','比較','対象','指標','単位','表示値','前期間値','差','運行数','走行距離km','指標取得運行数','取得率%','計算分子','計算分母','対応距離km','使用車両','前期間使用車両','条件変化','提供元','設定版','定義','閾値','道路区分','日報ID','距離取得運行数','距離取得状態','前期間走行距離km','前期間距離取得運行数','前期間距離取得状態','識別できた乗務員数','乗務員未確認の運行数','分子単位','分母単位','算出の元値']
            output=[];comparison=board['comparison'];m=board['metric'] or {};period=board['period']
            for item in comparison['rows']:
                now=item['current'];before=item['previous']
                output.append([board['scope_name'],period['start'],period['end'],period['previous_start'],period['previous_end'],comparison['title'],item['label'],m.get('name'),m.get('unit'),now['display'],before['display'],item['change'],now['count'],number(now['distance']) if now['distance'] is not None else None,now['metric_count'],item['coverage'],number(now['numerator']),number(now['denominator']),number(now['paired_distance']) if now['paired_distance'] is not None else None,' / '.join(item['conditions']['vehicles']),' / '.join(item['previous_conditions']['vehicles']),'あり' if item['conditions_changed'] else '未確認',m.get('source'),m.get('version'),m.get('definition'),m.get('threshold'),m.get('road'),' / '.join(str(i) for i in now['sources']),now['distance_count'],now['distance_state'],number(before['distance']) if before['distance'] is not None else None,before['distance_count'],before['distance_state'],item['identity_counts']['driver_count'],item['identity_counts']['unidentified_count'],now['numerator_unit'],now['denominator_unit'],now['basis_display']])
        if format=='csv' and request.args.get('view')=='maintenance':
            heading=['車両ID','車両','基準日','区分','項目','金額円','交換日','交換時積算距離km','交換後距離km','経過日数','整備記録ID','集計開始','集計終了']
            output=[]
            for vehicle in history_context(board,export_facts):
                context=vehicle['context'];cost=context['cost']
                output.append([vehicle['id'],vehicle['label'],context['as_of'],'車両全体の実費','整備実費',cost['total'],'','','','',' / '.join(map(str,cost['source_ids'])),cost['start'],cost['end']])
                for part in context['parts']:
                    output.append([vehicle['id'],vehicle['label'],context['as_of'],'交換記録',part['name'],'',part['date'],part['mileage'],part['distance_since'],part['days_since'],part['maintenance_id'],cost['start'],cost['end']])
        if format=='csv':
            heading += ['車両条件（現在の台帳）']
            output=[values+[board['condition_caption']] for values in output]
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
                        ('現在所属 '+(person.get('current_office') or '未確認')+' ／ '+person.get('affiliation_label','') if readership.administrator() else ''),
                        f'運行 {now["count"]}件 距離 {now["distance_display"]} 指標 {now["display"]} {m.get("unit", "")} 対象 {now["metric_count"]}件',
                        now['basis_display'],f'前期間 {person["previous"]["display"]} 差 {person["change"] or "比較値なし"}',
                        '出典日報 '+', '.join(str(v) for v in now['sources'])]
            if request.args.get('breakdown'):
                comparison=board['comparison']
                lines += [comparison['title']]
                for item in comparison['rows']:
                    now=item['current']
                    lines += [item['identity_counts']['identity_display'],'走行距離 '+now['distance_display']+' ／ 前期間 '+item['previous']['distance_display'],f'{item["label"]}：{now["display"]} {m.get("unit", "")} 前期間 {item["previous"]["display"]} 差 {item["change"] if item["change"] is not None else "比較値なし"}',
                              f'指標取得 {now["metric_count"]}/{now["count"]}運行（{item["coverage"]}%）',now['basis_display'],'前期間の元値 '+item['previous']['basis_display'],
                              '使用車両 '+ ' / '.join(item['conditions']['vehicles']),
                              '前期間の車両 '+ ' / '.join(item['previous_conditions']['vehicles']),
                              '出典日報 '+ ', '.join(str(rid) for rid in now['sources'])]
            for vehicle in history_context(board,export_facts):
                context=vehicle['context'];cost=context['cost']
                lines += [vehicle['label']+' 使用車両の整備情報',f'車両全体の実費 {number(cost["total"])}円 ({cost["start"] or "登録開始"} ～ {cost["end"]})', '他の乗務員の使用分を含む車両全体の実費。最後の乗務員へ帰属させない。']
                for part in context['parts']:
                    lines += [f'{part["name"]} {part["date"]}交換 経過 {part["days_since"] if part["days_since"] is not None else "未算出"}日 交換後 {number(part["distance_since"])}km 整備記録 {part["maintenance_id"]}']
            lines += ['車両条件（現在の台帳） '+board['condition_caption']]
            for group in summary['groups']:
                lines += [f'比較可能指標 {group["source_system"]} {group["version"]} {group["name"]} 単位 {group["unit"]} {group["count"]}件',f'定義 {group["definition"]} 条件 {group["threshold"] or "不明"} 分子合計/分母合計 {group["ratio"] or "算出対象外"}']
            for r in rows:
                p=payload(r);review=p.get('review') or {};match=match_report(r,operations(r.company_code,r.vehicle_record_id))
                lines += [f'CSV照合 {MATCH[match["status"]]} 採用 {match.get("use") or "日報のみ"} 取込状態 {"取消" if p.get("lifecycle") == "cancelled" else "有効"}']
                lines += [f'日報 {r.id} 運行 {r.operation_date or "不明"} {p.get("registration_number") or ""}',f'乗務員 {p.get("driver_name") or "不明"} 所属 {p.get("driver_office") or p.get("office_name") or "不明"}',f'帳票 {p.get("source_system") or "不明"} {p.get("report_title") or ""} 粒度 {p.get("report_scope") or "trip"}',f'積算 {shown(p.get("mileage"))} km 距離 {shown(p.get("distance"))} km',f'確認 {STATES.get(review.get("state","unreviewed"))} 担当 {review.get("assignee") or "未設定"} 次回 {review.get("next_date") or "未設定"}',f'所見 {review.get("note") or "記載なし"}',f'改善する行動 {review.get("action") or "未設定"}',f'乗務員の説明 {review.get("driver_explanation") or "記載なし"}']
                lines += ['前後比較 '+OUTCOMES.get(review.get('outcome',''),'未確認'), '比較条件と根拠 '+(review.get('comparison_note') or '未記録')]
                labels={'operation_start_time':'開始時刻','operation_end_time':'終了時刻','driving_time':'走行時間','handling_time':'ハンドル時間','idle_time':'アイドリング時間','rest_time':'休憩休息','work_time':'作業時間','fuel_consumption':'消費燃料','fuel_unit':'燃料単位','fuel_economy':'燃費','fuel_economy_unit':'燃費単位','driver_comment':'乗務員コメント','manager_comment':'管理者所見','notes':'手書き特記事項','definition_version':'評価設定版','issued_at':'出力日時','timezone':'タイムゾーン'}
                for key,label in labels.items():
                    if p.get(key) is not None:lines.append(label+' '+str(p[key]))
                for collection in ['report_items','events','duties','extra_items']:
                    for item in p.get(collection,[]):lines += [f'{item.get("category") or collection} {item.get("item_name")} {item.get("raw_result") or "未取得"} 点数 {shown(item.get("score"))} 評価 {item.get("result_text") or "未取得"}',f'定義 {item.get("definition") or "不明"} 単位 {item.get("unit") or "不明"} 条件 {item.get("threshold") or "不明"} 原本 {item.get("source_page")}頁',f'数値 {shown(item.get("value"))} 分子 {shown(item.get("numerator"))} 分母 {shown(item.get("denominator"))} {item.get("denominator_unit") or ""}',f'日時 {item.get("start_at") or "不明"} ～ {item.get("end_at") or "不明"} 場所 {item.get("place") or "不明"}',str(item.get('notes') or '')]
                for e in (p.get('audit',[]) if readership.administrator() else []):lines += ['確認履歴 '+json.dumps(e,ensure_ascii=False)]
                lines += [f'出典 日報:{r.id} 原本:{r.source_draft_id}','']
            content=export_pdf(lines);mime='application/pdf'
        response=send_file(io.BytesIO(content),mimetype=mime,as_attachment=True,download_name='driving-reports.'+format,max_age=0);response.headers['Cache-Control']='private, no-store';return response
    @app.route('/safety/driving-reports/readers',methods=['POST'])
    def driving_report_readers():
        access(write=True)
        _,_,_,_,filters,board,_=prepare_insights(request.form)
        if not board['reader_rows'] or request.form.get('reader_version')!=board['reader_version']:abort(409,'対象の日報が変わりました。再表示してください。')
        if 'reader_username' not in request.form:abort(400)
        username=request.form['reader_username'].strip()
        if username=='__revoke__':username=''
        for row in board['reader_rows']:
            old=row.details_json
            p=change(row,'reader',{'username':username})
            updated=json.dumps(p,ensure_ascii=False)
            with db.session.no_autoflush:
                count=Record.query.filter_by(id=row.id,company_code=row.company_code,details_json=old).update({'details_json':updated},synchronize_session=False)
            if count!=1:db.session.rollback();abort(409)
        readership.assign(board['reader_rows'],username,session['username'])
        db.session.commit()
        flash('本人の閲覧設定を保存しました。','success')
        grant=readership.reader(board['reader_rows'][0])
        focus=readership.account_key(grant) if grant else ''
        return redirect(url_for('driving_reports',**dict(filters,focus=focus,_anchor='driver-trend' if focus else 'driver-comparison')))

    @app.after_request
    def private_driving_response(response):
        if request.path.startswith('/safety/driving-reports'):
            response.headers['Cache-Control']='private, no-store'
        return response

    @app.cli.command('init-driving-access')
    def init_driving_access():
        readership.initialize_driving_access(app)
        print('DRIVING_ACCESS_INITIALIZED')

    @app.route('/safety/driving-reports/<int:record_id>/reader',methods=['POST'])
    def driving_report_reader(record_id):
        access(write=True)
        row=target(record_id,True)
        if request.form.get('version')!=version(row):abort(409)
        old_json=row.details_json
        username=request.form.get('reader_username','').strip()
        p=change(row,'reader',{'username':username})
        readership.assign([row],username,session['username'])
        row.details_json=json.dumps(p,ensure_ascii=False)
        persist(row,old_json)
        return redirect(url_for('driving_report_detail',record_id=row.id,return_to=report_return()))

    return {'canonical':canonical,'reports':reports,'view':view,'summary':metrics_summary}
