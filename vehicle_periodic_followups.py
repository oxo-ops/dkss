"""Read-only AI proposals from periodic evidence; existing actual facts are preserved."""
import hashlib
import json
from datetime import date, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from flask import abort, jsonify, render_template, request, session, url_for
from sqlalchemy.exc import SQLAlchemyError


def generate_periodic_proposals(payload):
    from vehicle_karte_analysis_ai import analyze_vehicle_karte
    result = analyze_vehicle_karte(payload)
    allowed = {row['source_id'] for row in payload['records']}
    for fact in payload.get('preventive_facts', {}).get('part_replacements', []):
        allowed.update(fact.get('source_ids', []))
    allowed.update(row['source_id'] for row in payload.get('maintenance_knowledge', []))
    if payload.get('vehicle_source'):
        allowed.add(payload['vehicle_source']['source_id'])
    items = []
    for item in result.get('recommendations', []):
        refs = item.get('source_ids') or []
        if not refs or not set(refs) <= allowed or item.get('priority') not in {'高', '中', '低'}:
            raise ValueError('INVALID_PROPOSAL_EVIDENCE')
        items.append(item)
    items.sort(key=lambda item: {'高': 0, '中': 1, '低': 2}[item['priority']])
    return {**result, 'recommendations': items}


def register_periodic_followups(app, db, Record, Vehicle, Company, User, Maintenance, Notification, maintenance_event, analysis_context):
    from dkss_app.vehicle_periodic_followups_models import get_models
    PeriodicInspectionProposal, PeriodicInspectionIssue, PeriodicInspectionIssueEvent, = get_models(db)

    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='periodic-proposal')
    app.extensions['periodic_proposal_executor'] = executor


    def now():
        return datetime.now(ZoneInfo('Asia/Tokyo'))

    def json_dict(value):
        try:
            data = json.loads(value or '{}')
        except (ValueError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    def snapshot(record):
        details = json_dict(record.details_json)
        items = details.get('inspection_items')
        items = items if isinstance(items, list) else []
        rows = [{'key': str(index), 'item': item} for index, item in enumerate(items) if isinstance(item, dict)]
        rows.append({'key': 'manual', 'item': {'item_name': '原本・備考から追加', 'notes': details.get('notes') or record.content or ''}})
        token = hashlib.sha256(json.dumps([record.id, record.inspection_date, record.details_json, record.content], ensure_ascii=False).encode()).hexdigest()
        return rows, token

    def lock(company):
        if Company.query.filter_by(company_code=company, active=True).update({Company.company_code: Company.company_code}, synchronize_session=False) != 1:
            abort(403)
        db.session.expire_all()

    def actor():
        user = User.query.filter_by(company_code=session.get('company_code'), username=session.get('username'), login_locked=False).first()
        if not user or user.role not in {'admin', 'itc'}:
            abort(403)
        return user

    def add_event(issue, action, user, note, performed=None):
        ids = []
        previous_events = PeriodicInspectionIssueEvent.query.filter_by(company_code=issue.company_code, issue_id=issue.id).all()
        old_ids = [number for event in previous_events for number in json.loads(event.notification_ids_json or '[]')]
        if old_ids:
            Notification.query.filter(Notification.company_code == issue.company_code, Notification.id.in_(old_ids)).update({'read': True}, synchronize_session='fetch')
        vehicle = Vehicle.query.filter_by(company_code=issue.company_code, id=issue.vehicle_record_id, deleted=False).first()
        if vehicle and vehicle.office and issue.status in {'対応待ち', '整備中', '再確認待ち'}:
            for recipient in User.query.filter_by(company_code=issue.company_code, office=vehicle.office, role='admin', login_locked=False).all():
                notification = Notification(company_code=issue.company_code, target_username=recipient.username,
                    target_user=(recipient.last_name or '') + (recipient.first_name or ''),
                    title='点検簿の対応確認：' + issue.status,
                    message=issue.description + '\n対応状況：' + issue.status + '\n原本・整備内容を確認して対応を登録してください。',
                    link=link(issue), read=False,
                    workflow_context_json=json.dumps({'action': 'periodic_issue', 'issue_id': issue.id, 'version': issue.version, 'office': vehicle.office}, ensure_ascii=False))
                db.session.add(notification)
                db.session.flush()
                ids.append(notification.id)
        db.session.add(PeriodicInspectionIssueEvent(company_code=issue.company_code, issue_id=issue.id,
            action=action, actor=user.username, performed_date=performed, note=note,
            maintenance_record_id=issue.maintenance_record_id, created_at=now().isoformat(timespec='seconds'), notification_ids_json=json.dumps(ids)))

    def workflow(notification):
        context = json_dict(notification.workflow_context_json)
        issue = PeriodicInspectionIssue.query.filter_by(company_code=notification.company_code, id=context.get('issue_id')).first()
        vehicle = Vehicle.query.filter_by(company_code=notification.company_code, id=issue.vehicle_record_id, deleted=False).first() if issue else None
        user = User.query.filter_by(company_code=notification.company_code, username=notification.target_username, role='admin', login_locked=False).first()
        if issue and issue.status == '解消':
            return {'workflow_status': 'completed', 'workflow_label': '再確認済み・解消', 'requires_action': False}
        pending = bool(issue and vehicle and user and vehicle.office and vehicle.office == context.get('office') == user.office
            and issue.version == context.get('version') and issue.status in {'対応待ち', '整備中', '再確認待ち'})
        return {'workflow_status': 'pending' if pending else 'closed', 'workflow_label': issue.status if pending else '対応状況・対象変更により終了', 'requires_action': pending}

    def history(company, vehicle_id):
        rows = db.session.query(PeriodicInspectionIssueEvent, PeriodicInspectionIssue).join(PeriodicInspectionIssue,
            PeriodicInspectionIssue.id == PeriodicInspectionIssueEvent.issue_id).filter(
            PeriodicInspectionIssueEvent.company_code == company, PeriodicInspectionIssue.company_code == company,
            PeriodicInspectionIssue.vehicle_record_id == vehicle_id).all()
        return [{'key': 'periodic-issue-event:' + str(event.id), 'date': event.performed_date or event.created_at[:10],
            'kind': '点検簿の対応', 'content': event.action + ' / ' + issue.description + ' / ' + event.note,
            'files': [], 'mileage': None, 'cost': None, 'status': event.action, 'actor': event.actor, 'link': link(issue)} for event, issue in rows]

    def bounded_text(value, label):
        value = str(value or '').strip()
        if not value or len(value) > 5000:
            raise ValueError(label + 'を1～5000文字で入力してください。')
        return value

    def actual_day(value, earliest):
        try:
            day = date.fromisoformat(value or '')
            lower = date.fromisoformat(earliest)
        except (TypeError, ValueError):
            raise ValueError('実施日を正しい日付で入力してください。')
        if day.isoformat() != value or day < lower or day > now().date():
            raise ValueError('実施日は対象の点検・整備完了日以降、今日以前にしてください。')
        return day.isoformat()

    def for_maintenance(company, record_id):
        if not record_id:
            return []
        historic_ids = db.session.query(PeriodicInspectionIssueEvent.issue_id).filter_by(company_code=company, maintenance_record_id=record_id)
        return PeriodicInspectionIssue.query.filter(PeriodicInspectionIssue.company_code == company,
            db.or_(PeriodicInspectionIssue.maintenance_record_id == record_id, PeriodicInspectionIssue.id.in_(historic_ids))).all()

    def sync_maintenance(record, intent, user):
        """Called in the existing maintenance form transaction, never commits."""
        for issue in for_maintenance(record.company_code, record.id):
            if issue.vehicle_record_id != record.vehicle_record_id:
                raise ValueError('定期点検の紐付け先を確認してください。')
            completed = PeriodicInspectionIssueEvent.query.filter_by(company_code=record.company_code, issue_id=issue.id,
                maintenance_record_id=record.id, action='整備完了').order_by(PeriodicInspectionIssueEvent.id.desc()).first()
            if completed and record.completion_date != completed.performed_date:
                raise ValueError('再確認に紐付く整備完了日は変更できません。元の点検簿の対応履歴を確認してください。')
            if issue.maintenance_record_id != record.id:
                continue
            if intent != 'complete' or issue.status != '整備中':
                continue
            original = Record.query.filter_by(id=issue.inspection_record_id, company_code=issue.company_code, vehicle_record_id=issue.vehicle_record_id).first()
            if original is None:
                raise ValueError('元の点検簿を確認できません。')
            performed = actual_day(record.completion_date, original.inspection_date)
            note = bounded_text(record.repair_content or record.content, '整備内容')
            issue.status = '再確認待ち'
            issue.version += 1
            add_event(issue, '整備完了', user, note, performed)

    def summary(company, vehicle_id):
        issues = PeriodicInspectionIssue.query.filter_by(company_code=company, vehicle_record_id=vehicle_id).order_by(PeriodicInspectionIssue.id.desc()).all()
        return {'issues': issues, 'open_count': sum(issue.status not in {'解消', '取消'} for issue in issues)}

    def link(issue):
        return url_for('vehicle_periodic_followup', vehicle_record_id=issue.vehicle_record_id, record_id=issue.inspection_record_id) + '#periodic-issue-' + str(issue.id)

    app.jinja_env.globals['periodic_issue_url'] = link

    def target(vehicle_record_id, record_id):
        company = session.get('company_code')
        vehicle = Vehicle.query.filter_by(company_code=company, id=vehicle_record_id, deleted=False).first_or_404()
        record = Record.query.filter_by(company_code=company, vehicle_record_id=vehicle.id, id=record_id).first_or_404()
        return vehicle, record

    def proposal_input(vehicle, selected):
        payload, evidence = analysis_context(vehicle)
        rows = payload["records"]
        by_source = {row["source_id"]: row for row in rows}
        focus = []
        records = Record.query.filter_by(company_code=vehicle.company_code, vehicle_record_id=vehicle.id).order_by(Record.inspection_date, Record.id).all()
        for record in records:
            details = json_dict(record.details_json)
            source = 'periodic:' + str(record.id)
            item_rows = details.get('inspection_items') or []
            items = [item for item in item_rows if isinstance(item, dict)] if isinstance(item_rows, list) else []
            values = {'source_id': source, 'date': record.inspection_date, 'type': '定期点検',
                'content': record.content, 'notes': details.get('notes'), 'inspection_type': record.inspection_type,
                'symbol_legend': details.get('symbol_legend'), 'inspection_items': items,
                'mileage': str(record.mileage) if record.mileage is not None else None}
            if source in by_source:
                by_source[source].update(values)
            else:
                rows.append(values)
            evidence[source] = {'label': record.inspection_date + ' 点検簿', 'url': url_for('vehicle_periodic_inspection_source', record_id=record.id)}
            if record.id == selected.id:
                focus.append(source)
        for issue in PeriodicInspectionIssue.query.filter_by(company_code=vehicle.company_code, vehicle_record_id=vehicle.id).order_by(PeriodicInspectionIssue.id).all():
            source = 'periodic_issue:' + str(issue.id)
            rows.append({'source_id': source, 'date': issue.created_at[:10], 'type': '登録済みの点検指摘',
                'content': issue.description, 'status': issue.status, 'maintenance_record_id': issue.maintenance_record_id,
                'inspection_record_id': issue.inspection_record_id})
            evidence[source] = {'label': '登録済みの対応状況', 'url': link(issue)}
        payload.update({
            'proposal_context_version': 'vehicle-wide-20261022-1',
            'focus_source_ids': focus, 'as_of': now().date().isoformat(),
            'analysis_focus': 'この車両の日常点検・定期点検・整備修理・部品交換・走行距離と適用可能な知識を照合し、今後の確認・整備候補を優先順に提案する。指定した点検簿だけに候補を限定しない。日常点検は修理と再確認の結果まで確認する。修理済みと再確認済みを混同しない。後日の整備・点検と照合する。原本の凡例を優先し、×を故障と決めつけない。交換・修理・調整済みの記号だけで追加整備を要求しない。空欄は未実施・不良ではない。必要な候補がなければ空配列。入力を要求せず、根拠・確認方法・時期を提案する。overviewに内部向けの記号解釈や処理方針を書かない。優先度は安全への影響、記録された未解消症状や繰り返し、適用条件を満たす整備時期を根拠とする。資料がないことだけで高優先度にしない。PPTの画面例の数値を整備基準として採用しない。',
        })
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
        return payload, evidence, digest

    def proposal_worker(company, record_id, run_token, payload):
        with app.app_context():
            try:
                result = generate_periodic_proposals(payload)
                updates = {'status': 'completed', 'result_json': json.dumps(result, ensure_ascii=False), 'error': None}
            except Exception as exc:
                app.logger.warning('Periodic inspection proposal generation failed (%s)', type(exc).__name__)
                updates = {'status': 'error', 'result_json': '{}', 'error': 'not_configured' if str(exc) == 'API_KEY_NOT_SET' else 'generation_failed'}
            try:
                updates['updated_at'] = now().isoformat(timespec='seconds')
                PeriodicInspectionProposal.query.filter_by(company_code=company, inspection_record_id=record_id, run_token=run_token).update(updates, synchronize_session=False)
                db.session.commit()
            finally:
                db.session.remove()

    @app.route('/vehicle/karte/<int:vehicle_record_id>/periodic/<int:record_id>/suggestions', methods=['GET', 'POST'])
    def vehicle_periodic_suggestions(vehicle_record_id, record_id):
        if request.method == 'POST':
            actor()
            lock(session.get('company_code'))
        vehicle, record = target(vehicle_record_id, record_id)
        payload, evidence, digest = proposal_input(vehicle, record)
        job = PeriodicInspectionProposal.query.filter_by(company_code=vehicle.company_code, inspection_record_id=record.id).first()
        if request.method == 'POST':
            if job and job.status == 'running':
                if datetime.fromisoformat(job.updated_at) > now() - timedelta(minutes=15):
                    db.session.rollback()
                    return jsonify(status='running')
            if not job or job.input_hash != digest or job.status != 'completed':
                if job and job.status == 'error' and job.input_hash == digest and datetime.fromisoformat(job.updated_at) > now() - timedelta(minutes=5) and not (request.get_json(silent=True) or {}).get('retry'):
                    db.session.rollback()
                    return jsonify(status='error', error=job.error)
                active_count = PeriodicInspectionProposal.query.filter(PeriodicInspectionProposal.company_code == vehicle.company_code,
                    PeriodicInspectionProposal.status == 'running', PeriodicInspectionProposal.updated_at > (now() - timedelta(minutes=15)).isoformat(timespec='seconds')).count()
                if active_count >= 2:
                    db.session.rollback()
                    return jsonify(status='error', error='busy'), 429
                if job is None:
                    job = PeriodicInspectionProposal(company_code=vehicle.company_code, inspection_record_id=record.id)
                    db.session.add(job)
                token = str(uuid4())
                job.input_hash, job.run_token, job.status = digest, token, 'running'
                job.result_json, job.error, job.updated_at = '{}', None, now().isoformat(timespec='seconds')
                db.session.commit()
                try:
                    executor.submit(proposal_worker, vehicle.company_code, record.id, token, payload)
                except RuntimeError:
                    job.status, job.error = 'error', 'generation_failed'
                    db.session.commit()
                    return jsonify(status='error', error=job.error)
                return jsonify(status='running'), 202
            db.session.rollback()
        if not job or job.input_hash != digest:
            return jsonify(status='missing')
        return jsonify(status=job.status, result=json_dict(job.result_json) if job.status == 'completed' else None,
            evidence=evidence, error=job.error, updated_at=job.updated_at)

    @app.route('/vehicle/karte/<int:vehicle_record_id>/periodic/<int:record_id>/followup', methods=['GET', 'POST'])
    def vehicle_periodic_followup(vehicle_record_id, record_id):
        if request.method == 'POST':
            actor()
            return '手入力での指摘登録は終了しました。点検簿のAI提案を確認してください。', 410
        vehicle, record = target(vehicle_record_id, record_id)
        issues = PeriodicInspectionIssue.query.filter_by(company_code=vehicle.company_code, inspection_record_id=record.id, vehicle_record_id=vehicle.id).order_by(PeriodicInspectionIssue.id).all()
        events = PeriodicInspectionIssueEvent.query.filter(PeriodicInspectionIssueEvent.company_code == vehicle.company_code, PeriodicInspectionIssueEvent.issue_id.in_([i.id for i in issues])).order_by(PeriodicInspectionIssueEvent.id).all() if issues else []
        number = ' '.join(str(getattr(vehicle, field) or '') for field in ['plate_area', 'plate_class', 'plate_kana', 'plate_number']).strip()
        from vehicle_inspection_plans import READ_KINDS
        return render_template('vehicle_periodic_followup.html', vehicle=vehicle, vehicle_number=number,
            inspection_kind_label=READ_KINDS.get(app.extensions['inspection_plan_sync'].record_kind(record), 'その他の点検'),
            record=record, issues=issues, events=events, evidence={i.id: json_dict(i.evidence_json) for i in issues},
            can_generate=session.get('role') in {'admin', 'itc'})

    return SimpleNamespace(Issue=PeriodicInspectionIssue, Event=PeriodicInspectionIssueEvent, summary=summary,
        for_maintenance=for_maintenance, sync_maintenance=sync_maintenance, lock=lock, workflow=workflow, history=history,
        Proposal=PeriodicInspectionProposal, proposal_input=proposal_input, worker=proposal_worker)
