"""Company-scoped inspection planning; dates here are operational plans, not legal judgments."""
import calendar
import hashlib
import json
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from flask import current_app, has_app_context, abort, jsonify, render_template, request, session, has_request_context
from sqlalchemy import event
from sqlalchemy.orm import Session, load_only
from sqlalchemy.exc import IntegrityError, OperationalError
from inspection_kind_identity import PERIODIC_STORAGE_KIND, new_storage_kind, document_kind_identity

KINDS = {'3month': '3か月点検', '12month': '12か月点検', 'vehicle_inspection': '車検', 'ad_hoc': '突発修理'}
UNCONFIRMED = 'annual_unconfirmed'
READ_KINDS = {**KINDS, UNCONFIRMED: '車検／12か月点検・区分未確認'}


def normalize_kind(kind):
    return '12month' if kind == PERIODIC_STORAGE_KIND else kind


def kind_values(kind):
    return (PERIODIC_STORAGE_KIND, '12month') if normalize_kind(kind) == '12month' else ('vehicle_inspection', '12month') if kind == 'vehicle_inspection' else ('12month',) if kind == UNCONFIRMED else (kind,)



def iso_date(value):
    try:
        parsed = date.fromisoformat(str(value or ''))
        return parsed if parsed.isoformat() == value else None
    except ValueError:
        return None


def month(value):
    value = str(value or '')
    return value if len(value) == 7 and iso_date(value + '-01') else None


def add_months(value, count):
    offset = value.year * 12 + value.month - 1 + count
    year, mon = divmod(offset, 12)
    return date(year, mon + 1, min(value.day, calendar.monthrange(year, mon + 1)[1]))


def register_inspection_plans(app, db, Vehicle, Record, Company, User, Office, Draft, *, Maintenance=None, Document=None):
    from dkss_app.vehicle_inspection_plans_models import get_models
    VehicleInspectionPlan, VehicleInspectionPlanEvent, VehicleInspectionExecution, VehicleInspectionExecutionEvidence, = get_models(db)


    Plan = VehicleInspectionPlan
    Event = VehicleInspectionPlanEvent



    Evidence = VehicleInspectionExecutionEvidence
    Execution = VehicleInspectionExecution
    queue_key = 'inspection_plan_sync_' + str(id(Record))
    import_key = 'inspection_plan_imports_' + str(id(Record))

    def today():
        return datetime.now(ZoneInfo('Asia/Tokyo')).date()

    def number(v):
        return ' '.join(str(x) for x in (v.plate_area, v.plate_class, v.plate_kana, v.plate_number) if x) or v.chassis_number or 'ナンバー未登録'

    def details(record):
        try:
            result = json.loads(record.details_json or '{}')
            return result if isinstance(result, dict) else {}
        except (TypeError, ValueError):
            return {}

    def record_kind(record):
        if record.inspection_type != '12month':
            return normalize_kind(record.inspection_type)
        draft = Draft.query.filter_by(id=record.source_draft_id, company_code=record.company_code).options(
            load_only(Draft.id, Draft.company_code, Draft.document_type, Draft.status, Draft.preview_json, Draft.result_json)).first()
        identity = document_kind_identity(record, draft, company_code=record.company_code,
                                          vehicle_id=record.vehicle_record_id)
        return identity.kind or UNCONFIRMED

    def plan_kind(plan):
        if plan.kind != '12month':
            return normalize_kind(plan.kind)
        def from_record(ident, completed=False, snapshot=None):
            if type(ident) is not int:
                return None
            record = Record.query.filter_by(id=ident, company_code=plan.company_code,
                vehicle_record_id=plan.vehicle_record_id).first()
            if not record or record_kind(record) not in {'12month', 'vehicle_inspection'}:
                return None
            if completed:
                snapshot = snapshot or serialize_dates(plan)
                direct = (record.inspection_date == snapshot.get('reservation_date') or
                    (not snapshot.get('reservation_date') and record.inspection_date[:7] == snapshot.get('planned_month')))
                linked = Execution.query.filter_by(company_code=plan.company_code,
                    vehicle_record_id=plan.vehicle_record_id, plan_id=plan.id, source_record_id=record.id,
                    performed_date=record.inspection_date).first()
                if not direct and not linked:
                    return None
            return record_kind(record)
        kind = from_record(plan.source_record_id)
        if kind:
            return kind
        if plan.status == 'completed':
            kind = from_record(plan.completed_record_id, completed=True)
            if kind:
                return kind
        # A date edit may clear the current next-date provenance. Its original
        # company/vehicle/plan-bound audit snapshot still proves the kind.
        for audit in Event.query.filter_by(company_code=plan.company_code, plan_id=plan.id).order_by(Event.id).all():
            try:
                detail = json.loads(audit.detail_json or '{}')
            except (TypeError, ValueError):
                continue
            if not isinstance(detail, dict):
                continue
            for key in ('before', 'after'):
                snapshot = detail.get(key)
                if (not isinstance(snapshot, dict) or type(snapshot.get('id')) is not int
                        or snapshot.get('id') != plan.id or snapshot.get('vehicle_record_id') != plan.vehicle_record_id
                        or snapshot.get('kind') not in {'12month', PERIODIC_STORAGE_KIND, 'vehicle_inspection'}):
                    continue
                kind = from_record(snapshot.get('source_record_id'))
                if kind:
                    return kind
        # A legacy alias without established original/audit evidence is not
        # silently assigned to either fact. This never mutates its stored kind.
        return UNCONFIRMED

    def serialize_dates(plan):
        return {'reservation_date': plan.reservation_date, 'planned_month': plan.planned_month}

    def execution_kind(execution):
        if execution.kind != '12month':
            return normalize_kind(execution.kind)
        if execution.source_record_id:
            record = Record.query.filter_by(id=execution.source_record_id, company_code=execution.company_code,
                                           vehicle_record_id=execution.vehicle_record_id).first()
            if record and record.inspection_date == execution.performed_date and record_kind(record) in {'12month', 'vehicle_inspection'}:
                return record_kind(record)
        if execution.plan_id:
            plan = Plan.query.filter_by(id=execution.plan_id, company_code=execution.company_code,
                                       vehicle_record_id=execution.vehicle_record_id).first()
            if plan and plan_kind(plan) in {'12month', 'vehicle_inspection'}:
                return plan_kind(plan)
        return UNCONFIRMED

    def record_next(record):
        day = iso_date(record.next_inspection_date)
        return day.isoformat()[:7] if day else month(details(record).get('next_inspection_month'))

    def serialize(row):
        return {key: plan_kind(row) if key == 'kind' else getattr(row, key) for key in ('id', 'vehicle_record_id', 'kind', 'period_key', 'planned_month', 'reservation_date', 'document_date', 'factory', 'note', 'source', 'source_record_id', 'completed_record_id', 'status', 'version', 'updated_by', 'updated_at')}

    def record_event(row, action, before=None, kind_confirmation=None, duplicate_candidates=None):
        row.updated_at = datetime.now(ZoneInfo('UTC')).isoformat()
        row.updated_by = session.get('username', '') if has_request_context() else ''
        db.session.flush([row])
        db.session.add(Event(company_code=row.company_code, plan_id=row.id, action=action,
                             detail_json=json.dumps({'before': before, 'after': serialize(row),
                                'kind_confirmation': kind_confirmation, 'duplicate_candidates': duplicate_candidates}, ensure_ascii=False),
                             created_at=row.updated_at, created_by=row.updated_by))

    def records_for(code, ids):
        return Record.query.filter(Record.company_code == code, Record.vehicle_record_id.in_(ids)).order_by(Record.inspection_date, Record.id).all() if ids else []

    def manual_records(code, vid):
        return Execution.query.filter_by(company_code=code, vehicle_record_id=vid, source_record_id=None).order_by(Execution.performed_date.desc(), Execution.id.desc()).all()

    def facts_for(code, ids):
        rows = records_for(code, ids)
        if ids:
            for e in Execution.query.filter(Execution.company_code == code, Execution.vehicle_record_id.in_(ids), Execution.source_record_id.is_(None)).all():
                rows.append(SimpleNamespace(id=-e.id, execution_id=e.id, plan_id=e.plan_id, vehicle_record_id=e.vehicle_record_id,
                    inspection_type=execution_kind(e), inspection_date=e.performed_date, next_inspection_date=None, mileage=None,
                    inspection_company=e.factory, inspector_name=e.created_by,
                    details_json=json.dumps({'next_inspection_month': e.next_month})))
        rows = [SimpleNamespace(**{key: getattr(r, key, None) for key in
                ('id', 'execution_id', 'plan_id', 'vehicle_record_id', 'inspection_date',
                 'next_inspection_date', 'mileage', 'inspection_company', 'inspector_name', 'details_json')},
                inspection_type=record_kind(r) if r.id > 0 else r.inspection_type) for r in rows]
        return sorted(rows, key=lambda r: (r.inspection_date, r.id))

    def fact_data(r):
        manual = r.id < 0
        evidence = db.session.get(Evidence, -r.id) if manual else None
        case_id = None
        if evidence and evidence.document_id:
            execution = db.session.get(Execution, -r.id)
            vehicle = Vehicle.query.filter_by(id=r.vehicle_record_id, company_code=execution.company_code).first()
            originals = certificate_documents(vehicle, evidence.document_id) if vehicle else []
            case_id = originals[0]['maintenance_record_id'] if originals else None
        return {'previous_expiry': evidence.previous_expiry if evidence else None,
                'maintenance_record_id': case_id,
                'maintenance_url': f'/vehicle/karte/{r.vehicle_record_id}/maintenance?record_id={case_id}' if case_id else None,
                'new_expiry': evidence.new_expiry if evidence else None,
                'evidence_note': evidence.confirmation if evidence else None,
                'document_id': evidence.document_id if evidence else None,
                'record_id': None if manual else r.id, 'execution_id': -r.id if manual else None,
                'performed_date': r.inspection_date, 'factory': r.inspection_company or '',
                'mileage': str(r.mileage) if r.mileage is not None else None,
                'document_status': ('登録済み' if evidence and evidence.document_id else '未受領') if manual else '登録済み',
                'record_url': (f'/vehicle/inspection-plans/executions/{-r.id}/source' if evidence and evidence.document_id else None) if manual else f'/vehicle/periodic-inspections/{r.id}/source'}

    def invoice_actuals(code, ids, year):
        """Read existing invoice-backed facts; never create or complete a plan."""
        if Maintenance is None or not ids:
            return []
        attachments = Document.query.filter(
            Document.company_code == code, Document.vehicle_record_id.in_(ids),
            Document.maintenance_record_id.isnot(None), Document.financial_status == 'confirmed',
        ).options(load_only(
            Document.id, Document.maintenance_record_id, Document.vehicle_record_id, Document.source_draft_id,
        )).order_by(Document.id).all() if Document is not None else []
        by_record = {}
        for document in attachments:
            by_record.setdefault(document.maintenance_record_id, []).append(document)
        records = Maintenance.query.filter(
            Maintenance.company_code == code, Maintenance.vehicle_record_id.in_(ids),
            (Maintenance.invoice_details_json.isnot(None) | Maintenance.id.in_(list(by_record))),
        ).options(load_only(
            Maintenance.id, Maintenance.vehicle_record_id, Maintenance.invoice_details_json,
            Maintenance.status, Maintenance.completion_date, Maintenance.content, Maintenance.repair_content,
        )).order_by(Maintenance.id).all()
        sources = {}
        for record in records:
            if record.is_invoice_actual:
                info = json.loads(record.invoice_details_json)
                sources[record.id] = (record, info['source']['draft_id'])
            elif record.status in (None, '', '完了', 'completed') and by_record.get(record.id):
                source = next((doc for doc in by_record[record.id]
                               if doc.vehicle_record_id == record.vehicle_record_id), None)
                if source is not None:
                    sources[record.id] = (record, source.source_draft_id)
        source_refs = {
            record.id: list(dict.fromkeys([draft_id] + [
                doc.source_draft_id for doc in by_record.get(record.id, [])
                if doc.vehicle_record_id == record.vehicle_record_id
            ]))
            for record, draft_id in sources.values()
        }
        drafts = {d.id: d for d in Draft.query.filter(
            Draft.company_code == code, Draft.status == 'completed', Draft.document_type == 'maintenance',
            Draft.id.in_([key for refs in source_refs.values() for key in refs]),
        ).options(load_only(Draft.id, Draft.result_json, Draft.source_filename)).all()} if sources else {}
        result = []
        for record, _ in sources.values():
            originals = []
            for draft_id in source_refs[record.id]:
                draft = drafts.get(draft_id)
                if draft is None:
                    continue
                try:
                    registered = json.loads(draft.result_json or '{}').get('records', [])
                except (TypeError, ValueError, AttributeError):
                    continue
                if not isinstance(registered, list) or not any(
                    isinstance(row, dict) and str(row.get('vehicle_record_id')) == str(record.vehicle_record_id)
                    for row in registered
                ):
                    continue
                originals.append({
                    'url': f'/vehicle/karte/{record.vehicle_record_id}/documents/{draft.id}/source',
                    'filename': draft.source_filename,
                })
            if not originals:
                continue
            # Completion day is the source of the timeline; do not substitute invoice/entry days.
            performed = iso_date(record.completion_date)
            if performed and not f'{year}-04-01' <= performed.isoformat() <= f'{year+1}-03-31':
                continue
            content = ' '.join((record.repair_content or record.content or '整備').split())
            if len(content) > 70:
                content = content[:69] + '…'
            day = performed.isoformat() if performed else None
            result.append({
                'maintenance_record_id': record.id, 'vehicle_record_id': record.vehicle_record_id,
                'performed_date': day, 'summary': (day.replace('-', '/') if day else '実施日不明') + ' ' + content + ' 実施',
                'source_url': originals[0]['url'], 'sources': originals,
            })
        return result

    def repair_actuals(code, ids):
        """Project confirmed repair facts from their source, without copying records."""
        if Maintenance is None or not ids:
            return []
        records = Maintenance.query.filter(
            Maintenance.company_code == code, Maintenance.vehicle_record_id.in_(ids),
            Maintenance.category.in_(['突発修理', '修理', '故障', '応急処置']),
        ).order_by(Maintenance.completion_date, Maintenance.id).all()
        result = []
        for record in records:
            performed = iso_date(record.completion_date)
            # A booking, entry date or invoice date alone does not prove completion.
            if not performed or performed > today() or record.status not in (None, '', '完了', 'completed'):
                continue
            try:
                info = json.loads(record.invoice_details_json or '{}')
                files = json.loads(record.files_json or '[]')
                has_document = bool(files or (isinstance(info, dict) and
                                    isinstance(info.get('source'), dict) and info['source'].get('draft_id')))
            except (ValueError, TypeError):
                has_document = False
            result.append({'id': None, 'version': 0, 'vehicle_record_id': record.vehicle_record_id,
                'kind': 'ad_hoc', 'period_key': record.completion_date[:7],
                'planned_month': record.completion_date[:7], 'display_month': record.completion_date[:7],
                'reservation_date': None, 'document_date': None, 'status': 'completed', 'is_history': True,
                'source': 'maintenance', 'source_record_id': None, 'completed_record_id': None,
                'maintenance_record_id': record.id, 'performed_date': record.completion_date,
                'factory': record.maintenance_company or '', 'mileage': str(record.mileage) if record.mileage is not None else None,
                'note': record.repair_content or record.content or '',
                'document_status': '登録済み' if has_document else '未受領',
                'record_url': f'/vehicle/karte/{record.vehicle_record_id}/maintenance?record_id={record.id}#maintenance_detail_panel',
                'record_link_label': '整備・修理の記録を開く ↗'})
        return result

    def latest(code, vid):
        result = {}
        for r in reversed(facts_for(code, [vid])):
            if r.inspection_type in READ_KINDS and iso_date(r.inspection_date) and r.inspection_date <= today().isoformat():
                result.setdefault(r.inspection_type, fact_data(r))
        repairs = repair_actuals(code, [vid])
        if repairs and ('ad_hoc' not in result or repairs[-1]['performed_date'] >= result['ad_hoc']['performed_date']):
            result['ad_hoc'] = repairs[-1]
        return result

    def summary(code, vehicle_id):
        result = {}
        saved = Plan.query.filter_by(company_code=code, vehicle_record_id=vehicle_id).order_by(Plan.planned_month, Plan.id).all()
        for row in saved:
            if row.status == 'planned':
                result.setdefault(plan_kind(row), serialize(row))
        seen = set()
        for record in reversed(facts_for(code, [vehicle_id])):
            performed = iso_date(record.inspection_date)
            if record.inspection_type not in KINDS or record.inspection_type == 'ad_hoc' or not performed or performed > today():
                continue
            if record.inspection_type in seen:
                continue
            seen.add(record.inspection_type)
            blocked = any(plan_kind(p) == record.inspection_type and p.period_key == record_next(record) for p in saved)
            if not blocked and record.inspection_type not in result and record_next(record) and record_next(record) > performed.isoformat()[:7]:
                result[record.inspection_type] = {'id': None, 'version': 0, 'vehicle_record_id': vehicle_id,
                    'kind': record.inspection_type, 'period_key': record_next(record), 'planned_month': record_next(record),
                    'reservation_date': None, 'document_date': record.next_inspection_date or None, 'factory': '', 'note': '', 'source': 'document' if record.id > 0 else 'calculated', 'source_record_id': record.id if record.id > 0 else None,
                    'completed_record_id': None, 'status': 'planned'}
        if 'vehicle_inspection' not in result:
            vehicle = Vehicle.query.filter_by(company_code=code, id=vehicle_id, deleted=False).first()
            expiry = iso_date(vehicle.inspection_expiry) if vehicle else None
            if expiry and not any(plan_kind(p) == 'vehicle_inspection' and p.status == 'completed'
                    and expiry.isoformat()[:7] in (p.period_key, p.planned_month) for p in saved):
                mon = expiry.isoformat()[:7]
                result['vehicle_inspection'] = {'id': None, 'version': 0, 'vehicle_record_id': vehicle_id,
                    'kind': 'vehicle_inspection', 'period_key': mon, 'planned_month': mon,
                    'reservation_date': None, 'document_date': None, 'expiry_date': expiry.isoformat(),
                    'factory': '', 'note': '', 'source': 'expiry', 'source_record_id': None,
                    'completed_record_id': None, 'status': 'candidate', 'display_state': 'candidate'}
        return result

    def sync_record(record):
        """Called inside the import transaction; conservative matching, no financial writes."""
        performed = iso_date(record.inspection_date)
        kind = record_kind(record)
        if kind not in KINDS or not performed or performed > today():
            return
        code, vid = record.company_code, record.vehicle_record_id
        if not Vehicle.query.filter_by(company_code=code, id=vid).first():
            return
        execution = next((e for e in Execution.query.filter(Execution.kind.in_(kind_values(kind))).filter_by(company_code=code, vehicle_record_id=vid, performed_date=record.inspection_date).all() if execution_kind(e) == kind), None)
        if execution and execution.source_record_id is None:
            execution.source_record_id = record.id
            if execution.plan_id:
                original = Plan.query.filter_by(company_code=code, id=execution.plan_id, vehicle_record_id=vid).first()
                if original and original.status == 'completed' and not original.completed_record_id:
                    before = serialize(original)
                    original.completed_record_id, original.version = record.id, original.version + 1
                    record_event(original, 'document_attached', before)
        pending = [p for p in Plan.query.filter(Plan.kind.in_(kind_values(kind))).filter_by(company_code=code, vehicle_record_id=vid, status='planned').all() if plan_kind(p) == kind]
        # A different month is not sufficient evidence to complete somebody's reservation.
        matches = [p for p in pending if (p.reservation_date == record.inspection_date or
                   (not p.reservation_date and p.planned_month == record.inspection_date[:7]))]
        linked = Plan.query.filter_by(company_code=code, completed_record_id=record.id).first()
        if not linked and len(matches) == 1:
            p = matches[0]
            before = serialize(p)
            p.status, p.completed_record_id, p.version = 'completed', record.id, p.version + 1
            record_event(p, 'completed', before)
        nxt = record_next(record)
        if kind == 'ad_hoc':
            return
        if not nxt or nxt <= record.inspection_date[:7]:
            return
        # Older imports may fill history but never reintroduce a superseded next period.
        newer = [r for r in facts_for(code, [vid]) if r.inspection_type == kind and
                 iso_date(r.inspection_date) and r.inspection_date > record.inspection_date]
        if newer:
            return
        if execution:
            for candidate in pending:
                if (candidate.planned_month == execution.next_month and candidate.source == 'calculated'
                        and candidate.status == 'planned' and candidate.version == 1
                        and not candidate.reservation_date and not candidate.factory and not candidate.note):
                    before = serialize(candidate)
                    candidate.version += 1
                    if candidate.planned_month == nxt:
                        candidate.source, candidate.source_record_id = 'document', record.id
                        candidate.document_date = record.next_inspection_date or None
                        record_event(candidate, 'confirmed_from_document', before)
                    else:
                        candidate.status = 'cancelled'
                        record_event(candidate, 'superseded_from_document', before)
        if any(p.planned_month == nxt for p in pending):
            return
        existing = next((p for p in Plan.query.filter(Plan.kind.in_(kind_values(kind))).filter_by(company_code=code, vehicle_record_id=vid, period_key=nxt).all() if plan_kind(p) == kind), None)
        if existing:
            return
        p = Plan(company_code=code, vehicle_record_id=vid, kind=new_storage_kind(kind), period_key=nxt, planned_month=nxt,
                 document_date=record.next_inspection_date or None,
                 source='document', source_record_id=record.id, version=1, status='planned', factory='', note='')
        db.session.add(p)
        record_event(p, 'created_from_document')

    def sync_pending():
        pending = db.session.info.pop(queue_key, [])
        for record in pending:
            sync_record(record)

    # Register one dispatcher per model/extension, not one global listener per app.
    registered = getattr(db, "_dkss_inspection_sync_models", None)
    if registered is None:
        registered = db._dkss_inspection_sync_models = set()
    if Record not in registered:
        registered.add(Record)

        def owns_session(s):
            return (has_app_context()
                    and current_app.extensions.get("sqlalchemy") is db
                    and s is db.session())

        @event.listens_for(Session, 'before_flush')
        def remember_records(s, context, instances):
            if not owns_session(s):
                return
            new = [r for r in s.new if isinstance(r, Record)]
            if new:
                s.info.setdefault(import_key, []).extend(new)

        @event.listens_for(Session, 'after_flush_postexec')
        def imported_records(s, context):
            if not owns_session(s):
                return
            imported = s.info.pop(import_key, [])
            for record in imported:
                s.info.setdefault(queue_key, []).append(record)

        @event.listens_for(Session, 'before_commit')
        def synchronize_import_transaction(s):
            if not owns_session(s):
                return
            if any(isinstance(r, Record) for r in s.new):
                s.flush()
            if s.info.get(queue_key):
                current_app.extensions['inspection_plan_sync'].sync_pending()

        @event.listens_for(Session, 'after_rollback')
        def forget_rolled_back_records(s):
            s.info.pop(queue_key, None)
            s.info.pop(import_key, None)

    def scope_context(code, args):
        scope = args.get('scope') or 'office'
        if scope not in {'vehicle', 'office', 'company'}:
            abort(400, '対象範囲を確認してください。')
        offices = sorted({o.name for o in Office.query.filter_by(company_code=code).all()} |
                         {v.office for v in Vehicle.query.filter_by(company_code=code, deleted=False).all() if v.office})
        vehicle = None
        if args.get('vehicle_id'):
            try:
                vehicle = Vehicle.query.filter_by(company_code=code, id=int(args['vehicle_id']), deleted=False).first_or_404()
            except (ValueError, TypeError):
                abort(400, '車両を確認してください。')
        user = User.query.filter_by(company_code=code, username=session.get('username')).first()
        office = args.get('office') or (vehicle.office if vehicle else user.office if user else None)
        if scope == 'vehicle' and not vehicle:
            abort(400, '車両を選択してください。')
        if office and office not in offices:
            abort(400, '同じ会社の営業所を選択してください。')
        return scope, office, vehicle, offices

    def vehicles_in_scope(code, args):
        scope, office, vehicle, _ = scope_context(code, args)
        q = Vehicle.query.filter_by(company_code=code, deleted=False)
        if scope == 'vehicle':
            q = q.filter_by(id=vehicle.id)
        elif scope == 'office':
            if not office:
                return []
            q = q.filter_by(office=office)
        elif args.get('office'):
            q = q.filter_by(office=office)
        return q.order_by(Vehicle.id).all()

    def candidate_rows(code, vehicles, year):
        start, end = f'{year:04d}-04', f'{year+1:04d}-03'
        ids = [v.id for v in vehicles]
        saved = Plan.query.filter(Plan.company_code == code, Plan.vehicle_record_id.in_(ids)).all() if ids else []
        records = facts_for(code, ids)
        manual_by_plan = {e.plan_id: e for e in Execution.query.filter(Execution.company_code == code, Execution.vehicle_record_id.in_(ids)).all()} if ids else {}
        rows, missing = [], []
        for v in vehicles:
            for kind in READ_KINDS:
                own = [p for p in saved if p.vehicle_record_id == v.id and plan_kind(p) == kind]
                visible = []
                for p in own:
                    item = serialize(p)
                    actual = next((r for r in records if p.completed_record_id and r.id == p.completed_record_id), None)
                    execution = manual_by_plan.get(p.id)
                    if p.status == 'completed' and (actual or execution):
                        item['performed_date'] = actual.inspection_date if actual else execution.performed_date
                        item['display_month'] = item['performed_date'][:7]
                        item['document_status'] = '登録済み' if actual or execution.source_record_id else '未受領'
                        if execution and not actual:
                            fact = next((r for r in records if r.id == -execution.id), None)
                            if fact:
                                item.update(fact_data(fact))
                    if start <= p.planned_month <= end or start <= item.get('display_month', p.planned_month) <= end:
                        visible.append(item)
                rows.extend(visible)
                previous = [r for r in records if r.vehicle_record_id == v.id and r.inspection_type == kind and
                            iso_date(r.inspection_date) and r.inspection_date <= today().isoformat()]
                for r in previous:
                    if not start <= r.inspection_date[:7] <= end:
                        continue
                    if any(p.get('completed_record_id') == r.id or (r.id < 0 and getattr(r, 'plan_id', None) == p['id']) for p in visible):
                        continue
                    rows.append({'id': None, 'version': 0, 'vehicle_record_id': v.id, 'kind': kind,
                        'period_key': r.inspection_date[:7], 'planned_month': r.inspection_date[:7],
                        'display_month': r.inspection_date[:7], 'status': 'completed', 'is_history': True,
                        'reservation_date': None, 'factory': r.inspection_company or '', 'note': '',
                        'source': 'document' if r.id > 0 else 'manual', 'completed_record_id': r.id if r.id > 0 else None,
                        **fact_data(r)})
                if kind in {'ad_hoc', UNCONFIRMED}:
                    continue
                latest = previous[-1] if previous else None
                explicit = record_next(latest) if latest else None
                baseline = explicit or (latest.inspection_date[:7] if latest else None)
                expiry_baseline = kind == 'vehicle_inspection' and iso_date(v.inspection_expiry) is not None
                if expiry_baseline:
                    baseline = v.inspection_expiry[:7]
                    if baseline and baseline < start:
                        missing.append({'vehicle_record_id': v.id, 'kind': kind, 'reason': '車検証満了日が対象年度より前です。更新内容を確認してください。'})
                        continue
                if not baseline:
                    if not own:
                        missing.append({'vehicle_record_id': v.id, 'kind': kind, 'reason': '基準となる点検実績・次回記載なし' if not expiry_baseline else '車検証満了日未登録'})
                    continue
                if kind == 'vehicle_inspection' and not explicit and not expiry_baseline:
                    continue
                step = 3 if kind == '3month' else 12
                cursor = date.fromisoformat(baseline + '-01')
                if latest and not explicit and not expiry_baseline:
                    cursor = add_months(cursor, step)
                while not expiry_baseline and kind != 'vehicle_inspection' and cursor.isoformat()[:7] < start:
                    cursor = add_months(cursor, step)
                while start <= cursor.isoformat()[:7] <= end:
                    key = cursor.isoformat()[:7]
                    if key > (latest.inspection_date[:7] if latest else '') and not any((p.period_key == key or p.planned_month == key) and (not expiry_baseline or p.status != 'cancelled') for p in own):
                        reusable = next((p for p in own if expiry_baseline and p.status == 'cancelled' and p.period_key == key), None)
                        rows.append({'id': reusable.id if reusable else None, 'version': reusable.version if reusable else 0, 'vehicle_record_id': v.id, 'kind': kind,
                                     'period_key': key, 'planned_month': key, 'reservation_date': None,
                                     'factory': '', 'note': '', 'source': 'document' if explicit == key else 'calculated',
                                     'source_record_id': latest.id if latest and latest.id > 0 else None, 'status': 'candidate', 'completed_record_id': None})
                    if expiry_baseline or kind == 'vehicle_inspection':
                        break  # No assumption about the next certificate's validity period.
                    cursor = add_months(cursor, step)
        rows.extend(r for r in repair_actuals(code, ids) if start <= r['display_month'] <= end)
        return rows, missing

    def display_state(row):
        if row['status'] == 'candidate':
            return 'candidate'
        if row['status'] == 'completed':
            return 'completed'
        if row['status'] == 'cancelled':
            return 'cancelled'
        if (row.get('reservation_date') and row['reservation_date'] < today().isoformat()) or (not row.get('reservation_date') and row['planned_month'] < today().isoformat()[:7]):
            return 'awaiting'
        return 'reserved' if row.get('reservation_date') else 'unreserved'

    def data_for(code, args):
        scope, office, vehicle, offices = scope_context(code, args)
        vehicles = vehicles_in_scope(code, args)
        selected_month = args.get('month') or today().isoformat()[:7]
        if not month(selected_month) or not 2000 <= int(selected_month[:4]) <= 2098:
            abort(400, '表示する年月を確認してください。')
        try:
            year = int(args.get('year') or (int(selected_month[:4]) if int(selected_month[5:]) >= 4 else int(selected_month[:4])-1))
            if not 2000 <= year <= 2098:
                raise ValueError
        except (TypeError, ValueError):
            abort(400, '年度を確認してください。')
        rows, missing = candidate_rows(code, vehicles, year)
        by_id = {v.id: v for v in vehicles}
        invoice_rows = invoice_actuals(code, list(by_id), year)
        invoice_by_id = {r['maintenance_record_id']: r for r in invoice_rows}
        existing_repair_ids = set()
        for row in rows:
            invoice = invoice_by_id.get(row.get('maintenance_record_id'))
            if invoice:
                row['invoice_summary'] = invoice['summary']
                row['invoice_sources'] = invoice['sources']
                row['record_url'] = invoice['source_url']
                row['record_link_label'] = '請求書原本を開く ↗'
                existing_repair_ids.add(invoice['maintenance_record_id'])
        invoice_rows = [r for r in invoice_rows if r['maintenance_record_id'] not in existing_repair_ids]
        confirmed = {}
        for row in rows:
            if row['kind'] in {'12month', 'vehicle_inspection'} and (row.get('id') or row.get('record_id') or row.get('execution_id')):
                confirmed.setdefault(row['vehicle_record_id'], []).append(row)
        for row in rows:
            row['display_state'] = display_state(row)
            v = by_id[row['vehicle_record_id']]
            row['expiry_date'] = (row.get('previous_expiry') if row['status'] == 'completed' else v.inspection_expiry) if row['kind'] == 'vehicle_inspection' else None
            row['kind_confirmed'] = row['kind'] != UNCONFIRMED
            row['duplicate_candidates'] = []
            if row['kind'] == UNCONFIRMED:
                for other in confirmed.get(row['vehicle_record_id'], []):
                    day, other_day = row.get('performed_date'), other.get('performed_date')
                    overlap = day == other_day if day and other_day else row['planned_month'] == other['planned_month']
                    if overlap:
                        row['duplicate_candidates'].append({key: other.get(key) for key in
                            ('id', 'record_id', 'execution_id', 'kind', 'planned_month', 'performed_date')})
            row['duplicate_note'] = '重複候補：区分未確認の旧記録は変更していません。' if row['duplicate_candidates'] else ''
        return {'year': year, 'month': selected_month, 'today': today().isoformat(),
                'scope': scope, 'office': office or '', 'offices': offices,
                'needs_office': scope == 'office' and not office,
                'focus_vehicle_id': vehicle.id if vehicle else None,
                'vehicles': [{'id': v.id, 'number': number(v), 'chassis_number': v.chassis_number or '', 'office': v.office or '営業所未設定', 'expiry_date': v.inspection_expiry} for v in vehicles],
                'plans': rows, 'invoice_actuals': invoice_rows, 'missing': missing, 'can_edit': session.get('role') in {'admin', 'itc'}}

    def require_editor():
        if session.get('role') not in {'admin', 'itc'}:
            abort(403)

    @app.get('/vehicle/inspection-plans')
    def vehicle_inspection_plans():
        return render_template('vehicle_inspection_plans.html', plan_args={k: request.args.get(k, '') for k in ('scope', 'vehicle_id', 'office', 'year', 'month', 'view', 'kind', 'state')})

    @app.get('/vehicle/inspection-plans/export.xlsx')
    def vehicle_inspection_plans_excel():
        from flask import send_file
        from inspection_plan_excel import build_annual_workbook, annual_filename, KINDS, STATES
        if request.args.get('kind') and request.args['kind'] not in KINDS:
            abort(400, '点検種別を確認してください。')
        if request.args.get('state') and request.args['state'] not in STATES:
            abort(400, '状態を確認してください。')
        data = data_for(session['company_code'], request.args)
        response = send_file(build_annual_workbook(data, request.args),
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True, download_name=annual_filename(data, request.args), max_age=0)
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @app.get('/api/vehicle/inspection-plans')
    def vehicle_inspection_plans_data():
        code = session['company_code']
        if request.args.get('detail'):
            try:
                v = Vehicle.query.filter_by(company_code=code, id=int(request.args['vehicle_id'])).first_or_404()
            except (KeyError, ValueError):
                abort(400)
            data = {'vehicle': {'id': v.id, 'number': number(v), 'office': v.office or ''}, 'plans': summary(code, v.id),
                    'latest': latest(code, v.id), 'documents': certificate_documents(v),
                    'can_edit': session.get('role') in {'admin', 'itc'}}
        else:
            data = data_for(code, request.args)
        response = jsonify(data)
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    def validated_rows(payload, code):
        changes = payload.get('changes')
        if not isinstance(changes, list) or not 1 <= len(changes) <= 1000:
            abort(400, '1〜1000件の変更を選択してください。')
        normalized, keys, month_keys = [], set(), set()
        for raw in changes:
            if not isinstance(raw, dict):
                abort(400)
            try:
                vid, ident, version = int(raw['vehicle_record_id']), int(raw.get('id') or 0), int(raw.get('version') or 0)
            except (KeyError, TypeError, ValueError):
                abort(400)
            v = Vehicle.query.filter_by(company_code=code, id=vid, deleted=False).first_or_404()
            row = Plan.query.filter_by(company_code=code, id=ident, vehicle_record_id=v.id).first_or_404() if ident else None
            kind, mon = normalize_kind(raw.get('kind')), month(raw.get('planned_month'))
            if isinstance(kind, str) and kind in {'12month', 'vehicle_inspection'} and payload.get('kind_contract') != 'independent-v1':
                abort(409, '点検種別が更新されました。画面を再読み込みして確認してください。')
            key = row.period_key if row else month(raw.get('period_key') or mon)
            if not row and kind == 'ad_hoc':
                # Distinct one-off bookings can share a month. Stable across preview/save.
                key = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:7]
            if not isinstance(kind, str) or kind not in KINDS or not mon or not key or not 2000 <= int(mon[:4]) <= 2099 or (kind != 'ad_hoc' and not 2000 <= int(key[:4]) <= 2099) or (row and plan_kind(row) != kind):
                abort(400, '点検種別・予定月を確認してください。')
            if row and (row.version != version or row.status not in {'planned', 'cancelled'}):
                abort(409, '予定が更新済み又は実施済みです。最新の内容を開き直してください。')
            if not row and (version or any(plan_kind(p) == kind for p in Plan.query.filter(Plan.kind.in_(kind_values(kind))).filter_by(company_code=code, vehicle_record_id=vid, period_key=key).all())):
                abort(409, '同じ予定が登録済みです。最新の内容を開き直してください。')
            if not row and kind != 'ad_hoc' and key != mon:
                abort(400, '新しい予定の対象月を確認してください。')
            reservation = raw.get('reservation_date') or None
            if reservation and (not iso_date(reservation) or reservation[:7] != mon):
                abort(400, '予約日は予定月内の日付を入力してください。')
            factory, note = str(raw.get('factory') or '').strip(), str(raw.get('note') or '').strip()
            if len(factory) > 200 or len(note) > 1000:
                abort(400, '実施先・メモの文字数を確認してください。')
            status = raw.get('status', 'planned')
            if status not in {'planned', 'cancelled'} or (not row and status == 'cancelled'):
                abort(400)
            if status == 'planned' and kind != 'ad_hoc':
                overlap = Plan.query.filter(Plan.kind.in_(kind_values(kind))).filter_by(company_code=code, vehicle_record_id=vid, planned_month=mon, status='planned')
                if row:
                    overlap = overlap.filter(Plan.id != row.id)
                month_key = (vid, kind, mon)
                if any(plan_kind(p) == kind for p in overlap.all()) or month_key in month_keys:
                    abort(409, '同じ車両・点検種別の予定がこの月に登録済みです。')
                month_keys.add(month_key)
            unique = (vid, kind, key)
            if unique in keys:
                abort(400, '変更対象が重複しています。')
            keys.add(unique)
            uncertain = [p.id for p in Plan.query.filter_by(company_code=code, vehicle_record_id=vid, kind='12month').all()
                         if plan_kind(p) == UNCONFIRMED and (mon in (p.period_key, p.planned_month) or key == p.period_key)] if kind in {'12month', 'vehicle_inspection'} else []
            kind_confirmation = str(raw.get('kind_confirmation') or '').strip()
            if len(kind_confirmation) > 1000:
                abort(400, '種別確認の根拠は1000文字以内で入力してください。')
            if not row and uncertain and not kind_confirmation:
                abort(409, '区分未確認の旧予定と重なります。新規分の種別を確認した根拠を入力してください。旧予定は変更しません。')
            # Source provenance is derived server-side, never trusted from a browser.
            relevant = [r for r in facts_for(code, [vid]) if r.inspection_type == kind and iso_date(r.inspection_date) and r.inspection_date <= today().isoformat()]
            latest = relevant[-1] if relevant else None
            explicit = latest if latest and record_next(latest) == mon else None
            year = int(mon[:4]) if int(mon[5:]) >= 4 else int(mon[:4]) - 1
            candidates, _ = candidate_rows(code, [v], year)
            calculated = any(p['id'] is None and p['planned_month'] == mon and p['kind'] == kind and p['source'] == 'calculated' for p in candidates)
            source = row.source if row and row.planned_month == mon else ('document' if explicit and explicit.id > 0 else 'calculated' if calculated and not reservation else 'manual')
            normalized.append((row, {'vehicle_record_id': vid, 'kind': kind, 'period_key': key, 'planned_month': mon,
                'reservation_date': reservation, 'factory': factory, 'note': note, 'status': status,
                'kind_confirmation': kind_confirmation, 'duplicate_candidates': uncertain,
                'document_date': explicit.next_inspection_date if explicit else (row.document_date if row and row.planned_month == mon else None),
                'source': source, 'source_record_id': explicit.id if explicit and explicit.id > 0 else (row.source_record_id if row and row.planned_month == mon else None)}, number(v)))
        return normalized

    def preview(payload, code):
        rows = validated_rows(payload, code)
        changes = [{'before': serialize(row) if row else None, 'after': values, 'number': label} for row, values, label in rows]
        digest = hashlib.sha256(json.dumps(changes, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return rows, changes, digest

    @app.post('/api/vehicle/inspection-plans/preview')
    def vehicle_inspection_plans_preview():
        require_editor()
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            abort(400)
        _, changes, token = preview(payload, session['company_code'])
        return jsonify(changes=changes, token=token)

    @app.post('/api/vehicle/inspection-plans/save')
    def vehicle_inspection_plans_save():
        require_editor()
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            abort(400)
        code = session['company_code']
        try:
            # A write lock serializes on SQLite; UPDATE takes a row lock on PostgreSQL.
            if Company.query.filter_by(company_code=code).update({Company.company_code: Company.company_code}, synchronize_session=False) != 1:
                abort(403)
            db.session.expire_all()
            rows, changes, token = preview(payload, code)
            if token != payload.get('token'):
                abort(409, '確認後に予定が変わりました。変更内容を再確認してください。')
            for row, values, _ in rows:
                kind_confirmation = values.pop('kind_confirmation', None)
                duplicate_candidates = values.pop('duplicate_candidates', None)
                before = serialize(row) if row else None
                if row is None:
                    row = Plan(company_code=code, version=1, **{**values, 'kind': new_storage_kind(values['kind'])})
                    db.session.add(row)
                else:
                    for key, value in values.items():
                        if key != 'kind':
                            setattr(row, key, value)
                    row.version += 1
                record_event(row, 'cancelled' if row.status == 'cancelled' else 'saved', before,
                             kind_confirmation, duplicate_candidates)
            db.session.commit()
            return jsonify(saved=len(rows))
        except (IntegrityError, OperationalError):
            db.session.rollback()
            abort(409, '別の操作で更新されました。最新の予定を開き直してください。')
        except Exception:
            db.session.rollback()
            raise

    def certificate_documents(v, document_id=None):
        """Verified originals; one unambiguous case per vehicle/draft.

        Evidence.document_id remains an ImportDraft FK. A maintenance document
        UUID is never stored there, and an ambiguous multi-case draft is not
        guessed into a case association.
        """
        rows = []
        candidate_ids = {r[0] for r in db.session.query(Record.source_draft_id).filter_by(
            company_code=v.company_code, vehicle_record_id=v.id).all()}
        if Document is not None:
            candidate_ids.update(r[0] for r in db.session.query(Document.source_draft_id).filter_by(
                company_code=v.company_code, vehicle_record_id=v.id).all())
        if Maintenance is not None:
            for raw, in db.session.query(Maintenance.invoice_details_json).filter_by(
                    company_code=v.company_code, vehicle_record_id=v.id).all():
                try:
                    info = json.loads(raw or '{}')
                except (TypeError, ValueError):
                    continue
                source = info.get('source') if isinstance(info, dict) else None
                if isinstance(source, dict) and isinstance(source.get('draft_id'), str):
                    candidate_ids.add(source['draft_id'])
        query = Draft.query.filter_by(company_code=v.company_code).filter(
                Draft.document_type.in_(['certificate', 'inspection', 'maintenance']),
                Draft.status.in_(['certificate_linked', 'completed']),
                db.or_(Draft.document_type == 'certificate', Draft.id.in_(candidate_ids)))
        if document_id:
            query = query.filter_by(id=document_id)
        for draft in query.order_by(Draft.created_at.desc()).all():
            try:
                binding = json.loads(draft.result_json or '{}')
            except (TypeError, ValueError):
                continue
            if not isinstance(binding, dict) or not draft.source_file or hashlib.sha256(draft.source_file).hexdigest() != draft.source_sha256:
                continue
            case_id = None
            if draft.document_type == 'certificate':
                valid = draft.status == 'certificate_linked' and binding.get('vehicle_record_id') == v.id
            else:
                registered = binding.get('records')
                if draft.status != 'completed' or not isinstance(registered, list):
                    continue
                matches = [r for r in registered if isinstance(r, dict) and r.get('vehicle_record_id') == v.id]
                matches = [r for r in matches if type(r.get('record_index')) is int and
                    sum(1 for entry in registered if isinstance(entry, dict) and
                        entry.get('record_index') == r['record_index']) == 1]
                valid = False
                if draft.document_type == 'inspection':
                    valid = any(type(r.get('record_index')) is int and r.get('document_type') == 'inspection' and
                        Record.query.filter_by(id=r.get('record_id'), company_code=v.company_code,
                            vehicle_record_id=v.id, source_draft_id=draft.id, source_record_index=r['record_index']).first()
                        for r in matches)
                elif Document is not None and Maintenance is not None:
                    documents = Document.query.filter_by(company_code=v.company_code, vehicle_record_id=v.id,
                        source_draft_id=draft.id, financial_status='confirmed').all()
                    case_ids = {d.maintenance_record_id for d in documents if d.maintenance_record_id}
                    if len(case_ids) == 1:
                        candidate = next(iter(case_ids))
                        case = Maintenance.query.filter_by(id=candidate, company_code=v.company_code, vehicle_record_id=v.id).first()
                        valid = bool(case and any(r.get('record_id') == candidate and r.get('document_type') == 'maintenance'
                            and type(r.get('record_index')) is int and any(d.maintenance_record_id == candidate
                                and d.source_record_index == r['record_index'] for d in documents) for r in matches))
                        case_id = candidate if valid else None
                    elif not documents:
                        # Older confirmed invoices retain the exact draft/index
                        # in their existing source JSON instead of Document.
                        cases = []
                        for entry in matches:
                            if entry.get('document_type') != 'maintenance':
                                continue
                            case = Maintenance.query.filter_by(id=entry.get('record_id'),
                                company_code=v.company_code, vehicle_record_id=v.id).first()
                            if not case:
                                continue
                            try:
                                info = json.loads(case.invoice_details_json or '{}')
                            except (TypeError, ValueError):
                                continue
                            source = info.get('source') if isinstance(info, dict) else None
                            if (isinstance(source, dict) and source.get('draft_id') == draft.id
                                    and source.get('record_index') == entry['record_index']
                                    and source.get('sha256') == draft.source_sha256):
                                cases.append(case.id)
                        if len(set(cases)) == 1:
                            case_id = cases[0]
                            valid = True
            if valid:
                rows.append({'id': draft.id, 'name': draft.source_filename,
                             'maintenance_record_id': case_id})
        return rows

    def certificate_evidence(v, payload, performed, kind='vehicle_inspection'):
        confirmation = str(payload.get('confirmation') or '').strip()
        if payload.get('confirmed') is not True or not confirmation or len(confirmation) > 1000:
            abort(400, '選択した種別と実施日を確認した根拠を入力し、確認済みにしてください。')
        expiry = payload.get('new_expiry') or None
        if expiry and kind != 'vehicle_inspection':
            abort(400, '車検証満了日は車検の情報です。12か月点検の実績では更新しません。')
        if expiry and (not iso_date(expiry) or expiry <= performed.isoformat()):
            abort(400, '更新後満了日を確認してください。実施日より後の日付を入力してください。')
        document_id = payload.get('document_id') or None
        if document_id is not None and not isinstance(document_id, str):
            abort(400, '原本の識別子を確認してください。')
        if document_id and document_id not in {d['id'] for d in certificate_documents(v, document_id)}:
            abort(400, '会社・車両・登録明細を確認できる原本を選択してください。')
        return {'new_expiry': expiry, 'document_id': document_id, 'confirmation': confirmation}

    @app.get('/vehicle/inspection-plans/executions/<int:execution_id>/source')
    def vehicle_inspection_execution_source(execution_id):
        from io import BytesIO
        from flask import send_file
        execution = Execution.query.filter_by(id=execution_id, company_code=session['company_code']).first_or_404()
        ev = db.session.get(Evidence, execution.id)
        v = Vehicle.query.filter_by(company_code=execution.company_code, id=execution.vehicle_record_id).first_or_404()
        if not ev or ev.document_id not in {d['id'] for d in certificate_documents(v, ev.document_id)}:
            abort(404)
        draft = db.session.get(Draft, ev.document_id)
        response = send_file(BytesIO(draft.source_file), download_name=draft.source_filename, as_attachment=True)
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    def execution_preview(payload, code):
        if not isinstance(payload, dict):
            abort(400)
        try:
            vid, pid = int(payload['vehicle_record_id']), int(payload.get('plan_id') or 0)
            version = int(payload.get('version') or 0)
        except (ValueError, TypeError, KeyError):
            abort(400)
        v = Vehicle.query.filter_by(company_code=code, id=vid, deleted=False).first_or_404()
        kind, performed = normalize_kind(payload.get('kind')), iso_date(payload.get('performed_date'))
        if isinstance(kind, str) and kind in {'12month', 'vehicle_inspection'} and payload.get('kind_contract') != 'independent-v1':
            abort(409, '点検種別が更新されました。画面を再読み込みして確認してください。')
        if not isinstance(kind, str) or kind not in KINDS or not performed or performed > today() or performed.year < 2000:
            abort(400, '点検種別と実施日を確認してください。未来の日は実施済みにできません。')
        plan = Plan.query.filter(Plan.kind.in_(kind_values(kind))).filter_by(company_code=code, vehicle_record_id=vid, id=pid).first_or_404() if pid else None
        if plan and plan_kind(plan) != kind:
            abort(409, '旧予定の種別を確定できません。新規分の根拠を確認し、別の実績として登録してください。')
        if plan and (plan.version != version or plan.status != 'planned'):
            abort(409, '予定が更新済み又は実施済みです。最新の内容を開き直してください。')
        actual = performed.isoformat()
        existing_execution = next((e for e in Execution.query.filter(Execution.kind.in_(kind_values(kind))).filter_by(company_code=code, vehicle_record_id=vid, performed_date=actual).all() if execution_kind(e) == kind), None)
        evidence = certificate_evidence(v, payload, performed, kind) if kind in {'12month', 'vehicle_inspection'} and (payload.get('confirmed') or payload.get('new_expiry') or payload.get('document_id') or payload.get('confirmation')) else None
        old_evidence = db.session.get(Evidence, existing_execution.id) if existing_execution else None
        attaching = bool(evidence and evidence['document_id'] and existing_execution and old_evidence and not old_evidence.document_id and (not pid or existing_execution.plan_id == pid))
        if attaching and kind == 'vehicle_inspection' and old_evidence.new_expiry and evidence['new_expiry'] and old_evidence.new_expiry != evidence['new_expiry']:
            abort(409, '保存済みの更新後満了日と異なります。元の実施記録を確認してください。')
        if attaching and kind == 'vehicle_inspection' and old_evidence.new_expiry:
            evidence['new_expiry'] = old_evidence.new_expiry
        if (existing_execution and not attaching) or any(record_kind(r) == kind for r in Record.query.filter(Record.inspection_type.in_(kind_values(kind))).filter_by(company_code=code, vehicle_record_id=vid, inspection_date=actual).all()):
            abort(409, '同じ車両・点検種別・実施日の記録が登録済みです。点検記録を確認してください。')
        uncertain = [e.id for e in Execution.query.filter_by(company_code=code, vehicle_record_id=vid, performed_date=actual, kind='12month').all() if execution_kind(e) == UNCONFIRMED]
        uncertain_records = [r.id for r in Record.query.filter_by(company_code=code, vehicle_record_id=vid, inspection_date=actual, inspection_type='12month').all() if record_kind(r) == UNCONFIRMED]
        uncertain_plans = [p.id for p in Plan.query.filter_by(company_code=code, vehicle_record_id=vid, kind='12month').all() if plan_kind(p) == UNCONFIRMED and actual[:7] in (p.period_key, p.planned_month)]
        if kind in {'12month', 'vehicle_inspection'} and (uncertain or uncertain_records or uncertain_plans) and not evidence:
            abort(409, '区分未確認の旧記録と重なります。新規分の種別と実施を確認した根拠を入力してください。旧記録は変更しません。')
        factory, note = str(payload.get('factory') or '').strip(), str(payload.get('note') or '').strip()
        if len(factory) > 200 or len(note) > 1000:
            abort(400, '実施先・メモの文字数を確認してください。')
        explicit = payload.get('next_month') or None
        if kind == 'ad_hoc':
            nxt = None
        elif kind == 'vehicle_inspection':
            nxt = evidence['new_expiry'][:7] if evidence and evidence['new_expiry'] else month(explicit)
        else:
            nxt = month(explicit) if explicit else add_months(performed, 3 if kind == '3month' else 12).isoformat()[:7]
        if kind != 'ad_hoc' and ((explicit and not month(explicit)) or
                (nxt and (nxt <= actual[:7] or not 2000 <= int(nxt[:4]) <= 2099))):
            abort(400, '次回予定月は実施月より後の年月を入力してください。')
        values = {'vehicle_record_id': vid, 'kind': kind, 'performed_date': actual,
                  'plan_id': plan.id if plan else None, 'version': plan.version if plan else 0,
                  'next_month': nxt, 'next_source': 'manual' if explicit or kind in {'vehicle_inspection', 'ad_hoc'} else 'calculated', 'factory': factory, 'note': note}
        facts = facts_for(code, [vid])
        newer = any(r.inspection_type == kind and r.inspection_date > actual and r.inspection_date <= today().isoformat() for r in facts)
        upcoming = [serialize(p) for p in Plan.query.filter(Plan.kind.in_(kind_values(kind))).filter_by(company_code=code, vehicle_record_id=vid, status='planned').order_by(Plan.planned_month, Plan.id).all() if plan_kind(p) == kind and (not plan or p.id != plan.id)]
        # Match only a uniquely identifiable booking; otherwise keep its state untouched.
        if plan is None:
            matches = [p for p in upcoming if p['reservation_date'] == actual or (not p['reservation_date'] and p['planned_month'] == actual[:7])]
            if len(matches) == 1:
                p = matches[0]
                plan = Plan.query.filter_by(company_code=code, id=p['id']).one()
                values.update(plan_id=plan.id, version=plan.version)
                upcoming = [p for p in upcoming if p['id'] != plan.id]
        result = {'number': number(v), 'execution': values, 'before': serialize(plan) if plan else None,
                  'existing_next': upcoming, 'skip_next_for_newer_record': newer,
                  'certificate_evidence': evidence, 'attach_execution_id': existing_execution.id if attaching else None,
                  'master_expiry': v.inspection_expiry,
                  'duplicate_candidates': {'executions': uncertain, 'records': uncertain_records, 'plans': uncertain_plans},
                  'warning': '対象予定月と実施月が異なります。この予定の実施として登録するか確認してください。' if plan and plan.planned_month != actual[:7] else ''}
        token = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return v, plan, result, token

    @app.post('/api/vehicle/inspection-plans/execution/preview')
    def vehicle_inspection_execution_preview():
        require_editor()
        _, _, result, token = execution_preview(request.get_json(silent=True), session['company_code'])
        return jsonify(result=result, token=token)

    @app.post('/api/vehicle/inspection-plans/execution/save')
    def vehicle_inspection_execution_save():
        require_editor()
        payload, code = request.get_json(silent=True), session['company_code']
        try:
            if Company.query.filter_by(company_code=code).update({Company.company_code: Company.company_code}, synchronize_session=False) != 1:
                abort(403)
            db.session.expire_all()
            v, plan, result, token = execution_preview(payload, code)
            if token != payload.get('token'):
                abort(409, '確認後に予定が変わりました。内容を再確認してください。')
            values = result['execution']
            if result.get('attach_execution_id'):
                execution = db.session.get(Execution, result['attach_execution_id'])
                ev = db.session.get(Evidence, execution.id)
                ev.document_id = result['certificate_evidence']['document_id']
                ev.attachment_confirmation = result['certificate_evidence']['confirmation']
                ev.attached_at = datetime.now(ZoneInfo('UTC')).isoformat()
                ev.attached_by = session['username']
                ev.new_expiry = ev.new_expiry or result['certificate_evidence']['new_expiry']
                if values['kind'] == 'vehicle_inspection':
                    execution.next_month = ev.new_expiry[:7] if ev.new_expiry else None
                if values['kind'] == 'vehicle_inspection' and ev.new_expiry and not result['skip_next_for_newer_record'] and (not iso_date(v.inspection_expiry) or ev.new_expiry > v.inspection_expiry):
                    v.inspection_expiry = ev.new_expiry
                if execution.plan_id:
                    original = Plan.query.filter_by(company_code=code, id=execution.plan_id).one()
                    before = serialize(original)
                    original.version += 1
                    record_event(original, 'document_attached', before)
                db.session.commit()
                return jsonify(saved=1, execution_id=execution.id)
            if plan:
                before = serialize(plan)
                plan.status, plan.version = 'completed', plan.version + 1
                record_event(plan, 'completed_manual', before)
            execution = Execution(company_code=code, vehicle_record_id=v.id, kind=new_storage_kind(values['kind']),
                performed_date=values['performed_date'], plan_id=plan.id if plan else None,
                next_month=values['next_month'], factory=values['factory'], note=values['note'],
                created_by=session['username'], created_at=datetime.now(ZoneInfo('UTC')).isoformat())
            db.session.add(execution)
            db.session.flush([execution])
            if result['certificate_evidence']:
                ev = result['certificate_evidence']
                db.session.add(Evidence(execution_id=execution.id, company_code=code,
                    previous_expiry=result['master_expiry'] if values['kind'] == 'vehicle_inspection' and iso_date(result['master_expiry']) else None, **ev))
                # Only advance a known expiry for the latest confirmed execution.
                if values['kind'] == 'vehicle_inspection' and ev['new_expiry'] and not result['skip_next_for_newer_record'] and (not iso_date(v.inspection_expiry) or ev['new_expiry'] > v.inspection_expiry):
                    v.inspection_expiry = ev['new_expiry']
            nxt = values['next_month']
            existing = [p for p in Plan.query.filter_by(company_code=code, vehicle_record_id=v.id).filter(Plan.kind.in_(kind_values(values['kind']))).all() if plan_kind(p) == values['kind']]
            if values['kind'] != 'ad_hoc' and nxt and not result['skip_next_for_newer_record'] and not any(p.period_key == nxt or p.planned_month == nxt for p in existing):
                next_plan = Plan(company_code=code, vehicle_record_id=v.id, kind=new_storage_kind(values['kind']), period_key=nxt,
                    planned_month=nxt, source=values['next_source'], version=1, status='planned', factory='', note='')
                db.session.add(next_plan)
                record_event(next_plan, 'created_after_execution')
            db.session.commit()
            return jsonify(saved=1, execution_id=execution.id)
        except (IntegrityError, OperationalError):
            db.session.rollback()
            abort(409, '別の操作で更新されました。最新の記録を確認してください。')
        except Exception:
            db.session.rollback()
            raise

    service = SimpleNamespace(summary=summary, latest=latest, manual_records=manual_records, Execution=Execution, Evidence=Evidence,
        sync_pending=sync_pending, sync_record=sync_record, candidate_rows=candidate_rows,
        record_kind=record_kind, plan_kind=plan_kind, execution_kind=execution_kind, facts_for=facts_for)
    app.extensions['inspection_plan_sync'] = service
    return Plan, Event, service
