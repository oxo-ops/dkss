"""Operational plan reminders. In-app only; no inferred legal deadlines."""
import hashlib
import json
import time
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from urllib.parse import urlencode

import click
from flask import request, session
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import load_only

from vehicle_inspection_plans import KINDS, UNCONFIRMED, normalize_kind, kind_values, add_months, iso_date, month


def local_today():
    return datetime.now(ZoneInfo('Asia/Tokyo')).date()


def reminder_phase(plan, today):
    mon = month(plan.planned_month)
    if plan.status != 'planned' or not mon:
        return None
    booked = iso_date(plan.reservation_date)
    if booked:
        if booked.isoformat()[:7] != mon:
            return None
        if today > booked:
            return 'execution_check', booked + timedelta(days=1), '予約日経過・実施確認'
        if today >= booked - timedelta(days=1):
            return 'booking_1day', booked - timedelta(days=1), '予約日の確認'
        if today >= booked - timedelta(days=7):
            return 'booking_7days', booked - timedelta(days=7), '予約日の事前確認'
        return None
    start = date.fromisoformat(mon + '-01')
    if today >= add_months(start, 1):
        return 'month_elapsed', add_months(start, 1), '予定月経過・実施確認'
    if today >= start:
        return 'month_booking', start, '予定月・予約確認'
    previous = add_months(start, -1)
    if today >= previous:
        return 'prior_booking', previous, '翌月の点検予約確認'
    return None



def expiry_phase(expiry, today):
    if today > expiry:
        return 'expiry_elapsed', expiry + timedelta(days=1), '車検証満了日経過・実施確認'
    if today == expiry:
        return 'expiry_today', expiry, '本日が車検証満了日'
    if today >= expiry - timedelta(days=1):
        return 'expiry_1day', expiry - timedelta(days=1), '車検証満了日の前日'
    if today >= expiry - timedelta(days=7):
        return 'expiry_7days', expiry - timedelta(days=7), '車検証満了日まで7日以内'
    start = expiry.replace(day=1)
    if today >= start:
        return 'expiry_month', start, '今月が車検証満了日'
    previous = add_months(start, -1)
    if today >= previous:
        return 'expiry_prior', previous, '翌月が車検証満了日'
    return None


def confirmed_twelve_month_source(plan, record, draft):
    """Recognize an explicitly confirmed document source; never reclassify rows.

    The legacy stored kind alone is not proof. Require the registered source,
    its confirmed values and its preserved original label to agree. Other or
    ambiguous evidence returns False, not a new classification/holding rule.
    """
    if not record or not draft or plan.kind != '12month' or plan.source != 'document':
        return False
    if (plan.source_record_id != record.id or record.inspection_type != '12month'
            or record.company_code != plan.company_code or draft.company_code != plan.company_code
            or record.vehicle_record_id != plan.vehicle_record_id
            or record.source_draft_id != draft.id or draft.document_type != 'inspection'
            or draft.status != 'completed'):
        return False
    index = record.source_record_index
    if type(index) is not int or index < 0:
        return False
    try:
        details = json.loads(record.details_json or '{}')
        preview = json.loads(draft.preview_json or '{}')
        result = json.loads(draft.result_json or '{}')
    except (TypeError, ValueError):
        return False
    if not all(isinstance(value, dict) for value in (details, preview, result)):
        return False
    originals, registered = preview.get('original_records'), result.get('records')
    if not isinstance(originals, list) or index >= len(originals) or not isinstance(registered, list):
        return False
    original = originals[index]
    if not isinstance(original, dict):
        return False
    # Exact unambiguous labels, not substring/OCR guessing or a date cutoff.
    labels = {'12か月点検', '12か月定期点検', '12ヶ月点検', '12ヶ月定期点検'}
    raw_label = details.get('inspection_type_raw')
    if (not isinstance(raw_label, str) or details.get('inspection_type') != '12month'
            or details.get('vehicle_record_id') != plan.vehicle_record_id
            or raw_label not in labels
            or original.get('inspection_type_raw') != details.get('inspection_type_raw')
            or original.get('inspection_type') != '12month'):
        return False
    next_month = month(details.get('next_inspection_month'))
    next_day = iso_date(record.next_inspection_date)
    if next_month and next_day and next_month != next_day.isoformat()[:7]:
        return False
    if (next_month or (next_day.isoformat()[:7] if next_day else None)) != plan.period_key:
        return False
    matches = [row for row in registered if isinstance(row, dict)
               and row.get('record_id') == record.id and row.get('record_index') == index
               and row.get('vehicle_record_id') == plan.vehicle_record_id
               and row.get('document_type') == 'inspection']
    return len(matches) == 1


def register_inspection_alerts(app, db, Plan, PlanEvent, Execution, Record, Vehicle, Company, User, Notification, *, Draft):
    from dkss_app.vehicle_inspection_alerts_models import get_models
    InspectionPlanAlertDelivery, InspectionPlanAlertRun, InspectionExpiryAlertDelivery, = get_models(db)



    identities = app.extensions['inspection_plan_sync']
    Delivery, Run = InspectionPlanAlertDelivery, InspectionPlanAlertRun
    ExpiryDelivery = InspectionExpiryAlertDelivery

    def json_dict(raw):
        try:
            value = json.loads(raw or '{}')
            return value if isinstance(value, dict) else {}
        except (ValueError, TypeError):
            return {}

    def revision(plan, events, office):
        fields = ('planned_month', 'reservation_date', 'status')
        last_change = 0
        for e in events:
            if e.plan_id != plan.id:
                continue
            detail = json_dict(e.detail_json)
            before, after = detail.get('before') or {}, detail.get('after') or {}
            if any(before.get(k) != after.get(k) for k in fields):
                last_change = max(last_change, e.id)
        return hashlib.sha256(json.dumps([plan.planned_month, plan.reservation_date, last_change, office]).encode()).hexdigest()

    def has_actual(plan, today):
        kind = identities.plan_kind(plan) if hasattr(plan, 'source_record_id') else normalize_kind(plan.kind)
        if kind == UNCONFIRMED:
            return False
        def match(day):
            return bool(iso_date(day) and day <= today.isoformat() and
                        (day == plan.reservation_date if plan.reservation_date else day[:7] == plan.planned_month))
        if kind == 'ad_hoc':
            return Execution.query.filter_by(company_code=plan.company_code,
                vehicle_record_id=plan.vehicle_record_id, plan_id=plan.id).first() is not None
        actuals = Record.query.filter_by(company_code=plan.company_code, vehicle_record_id=plan.vehicle_record_id).filter(Record.inspection_type.in_(kind_values(kind))).all()
        if any(identities.record_kind(r) == kind and match(r.inspection_date) for r in actuals):
            return True
        return any(identities.execution_kind(e) == kind and match(e.performed_date)
                   for e in Execution.query.filter_by(company_code=plan.company_code, vehicle_record_id=plan.vehicle_record_id).filter(Execution.kind.in_(kind_values(kind))).all())

    def certificate_updated(plan, vehicle):
        expiry = iso_date(vehicle.inspection_expiry)
        return bool(identities.plan_kind(plan) == 'vehicle_inspection' and expiry and month(plan.period_key)
                    and expiry.isoformat()[:7] > plan.period_key)

    def confirmed_completion(plan, kind):
        if plan.completed_record_id:
            record = Record.query.filter_by(id=plan.completed_record_id, company_code=plan.company_code,
                vehicle_record_id=plan.vehicle_record_id).first()
            if record and identities.record_kind(record) == kind:
                return True
        return any(identities.execution_kind(e) == kind for e in Execution.query.filter_by(
            company_code=plan.company_code, vehicle_record_id=plan.vehicle_record_id, plan_id=plan.id).all())

    def legacy_expiry_dependency(vehicle, expiry, today):
        mon = expiry[:7]
        plans = Plan.query.filter_by(company_code=vehicle.company_code, vehicle_record_id=vehicle.id,
            kind='12month').filter(Plan.status.in_(['planned', 'completed']),
                db.or_(Plan.period_key == mon, Plan.planned_month == mon)).all()
        if any(identities.plan_kind(p) == UNCONFIRMED for p in plans):
            return True
        records = Record.query.filter_by(company_code=vehicle.company_code, vehicle_record_id=vehicle.id,
            inspection_type='12month').all()
        if any(iso_date(r.inspection_date) and r.inspection_date <= today.isoformat() and r.inspection_date[:7] == mon and identities.record_kind(r) == UNCONFIRMED for r in records):
            return True
        return any(iso_date(e.performed_date) and e.performed_date <= today.isoformat() and e.performed_date[:7] == mon and identities.execution_kind(e) == UNCONFIRMED
            for e in Execution.query.filter_by(company_code=vehicle.company_code, vehicle_record_id=vehicle.id, kind='12month').all())

    def current_delivery(delivery, today):
        if delivery.ended_status:
            return delivery.ended_status
        plan = Plan.query.filter_by(company_code=delivery.company_code, id=delivery.plan_id).first()
        vehicle = Vehicle.query.filter_by(company_code=delivery.company_code, id=plan.vehicle_record_id, deleted=False).first() if plan else None
        company = Company.query.filter_by(company_code=delivery.company_code, active=True).first()
        recipient = User.query.filter_by(company_code=delivery.company_code, username=delivery.target_username, role='admin', login_locked=False).first()
        if not company or not vehicle or not recipient or not vehicle.office or recipient.office != vehicle.office or delivery.office != vehicle.office:
            return 'closed'
        kind = identities.plan_kind(plan)
        if kind == UNCONFIRMED or (kind in {'12month', 'vehicle_inspection'} and plan.status == 'completed' and not confirmed_completion(plan, kind)):
            return 'pending_unconfirmed'
        if certificate_updated(plan, vehicle):
            return 'closed'
        if plan.status == 'completed' or has_actual(plan, today):
            return 'completed'
        phase = reminder_phase(plan, today)
        events = PlanEvent.query.filter_by(company_code=delivery.company_code, plan_id=plan.id).all()
        if not phase or phase[0] != delivery.phase or revision(plan, events, vehicle.office) != delivery.revision:
            return 'closed'
        return 'pending'

    def expiry_is_planned(vehicle, expiry):
        return Plan.query.filter(Plan.company_code == vehicle.company_code,
            Plan.vehicle_record_id == vehicle.id, Plan.kind.in_(kind_values('vehicle_inspection')),
            Plan.status.in_(['planned', 'completed']),
            db.or_(Plan.period_key == expiry[:7], Plan.planned_month == expiry[:7])).first() is not None

    def expiry_has_actual(vehicle, expiry, today):
        return has_actual(SimpleNamespace(company_code=vehicle.company_code, vehicle_record_id=vehicle.id,
            kind='vehicle_inspection', reservation_date=None, planned_month=expiry[:7]), today)

    def current_expiry_delivery(delivery, today):
        if delivery.ended_status:
            return delivery.ended_status
        vehicle = Vehicle.query.filter_by(company_code=delivery.company_code, id=delivery.vehicle_record_id, deleted=False).first()
        recipient = User.query.filter_by(company_code=delivery.company_code, username=delivery.target_username, role='admin', login_locked=False).first()
        company = Company.query.filter_by(company_code=delivery.company_code, active=True).first()
        if not vehicle or not company or not recipient or not vehicle.office or vehicle.office != recipient.office or vehicle.office != delivery.office:
            return 'closed'
        if legacy_expiry_dependency(vehicle, delivery.expiry_date, today):
            return 'pending_unconfirmed'
        if vehicle.inspection_expiry != delivery.expiry_date:
            return 'closed'
        if expiry_has_actual(vehicle, delivery.expiry_date, today):
            return 'completed'
        if expiry_is_planned(vehicle, delivery.expiry_date):
            return 'closed'
        phase = expiry_phase(iso_date(delivery.expiry_date), today)
        return 'pending' if phase and phase[0] == delivery.phase else 'closed'

    def plan_link(office, months):
        months = sorted(set(months))
        mon = months[0]
        year = int(mon[:4]) - (1 if int(mon[5:]) < 4 else 0)
        return '/vehicle/inspection-plans?' + urlencode({'scope': 'office', 'office': office,
            'month': mon, 'year': year, 'view': 'month' if len(months) == 1 else 'year'})

    def target_link(notification):
        # Rebuild old digest links as well; never focus only the first vehicle.
        deliveries = Delivery.query.filter_by(company_code=notification.company_code,
            notification_id=notification.id, target_username=notification.target_username).all()
        expiry_deliveries = ExpiryDelivery.query.filter_by(company_code=notification.company_code,
            notification_id=notification.id, target_username=notification.target_username).all()
        months = []
        for d in deliveries:
            plan = Plan.query.filter_by(company_code=d.company_code, id=d.plan_id).first()
            if plan and month(plan.planned_month):
                months.append(plan.planned_month)
        months.extend(d.expiry_date[:7] for d in expiry_deliveries if iso_date(d.expiry_date))
        office = (deliveries or expiry_deliveries)[0].office if deliveries or expiry_deliveries else None
        return plan_link(office, months) if office and months else notification.link

    def workflow(notification, today=None):
        today = today or local_today()
        deliveries = Delivery.query.filter_by(company_code=notification.company_code, notification_id=notification.id, target_username=notification.target_username).all()
        statuses = [current_delivery(d, today) for d in deliveries]
        expiry_deliveries = ExpiryDelivery.query.filter_by(company_code=notification.company_code, notification_id=notification.id, target_username=notification.target_username).all()
        statuses.extend(current_expiry_delivery(d, today) for d in expiry_deliveries)
        held = statuses.count('pending_unconfirmed')
        remaining = statuses.count('pending') + held
        if held:
            return {'workflow_status': 'pending', 'workflow_label': f'車検／12か月点検・区分未確認 {held}件', 'requires_action': True}
        if remaining:
            return {'workflow_status': 'pending', 'workflow_label': f'点検予定の確認待ち {remaining}件', 'requires_action': True}
        completed = bool(statuses) and all(s == 'completed' for s in statuses)
        return {'workflow_status': 'completed' if completed else 'closed',
                'workflow_label': '点検実施済み' if completed else '予定・対象変更により終了', 'requires_action': False}

    def process_company(code, today, force=False):
        now = datetime.now(ZoneInfo('UTC'))
        report = {'notifications': 0, 'plans': 0, 'no_recipient': 0, 'invalid': 0, 'expiry_candidates': 0, 'skipped': False}
        try:
            # Same company lock as plan editing/importing; never notify a rolled-back plan.
            if Company.query.filter_by(company_code=code, active=True).update({Company.company_code: Company.company_code}, synchronize_session=False) != 1:
                db.session.rollback()
                return report
            db.session.expire_all()
            previous = Run.query.filter_by(company_code=code).first()
            plans = Plan.query.filter_by(company_code=code, status='planned').order_by(Plan.id).all()
            vehicles = {v.id: v for v in Vehicle.query.filter_by(company_code=code, deleted=False).all()}
            recipients = User.query.filter_by(company_code=code, role='admin', login_locked=False).order_by(User.id).all()
            signature = hashlib.sha256(json.dumps([
                [(p.id, p.version, p.planned_month, p.reservation_date) for p in plans],
                [(v.id, v.office, v.inspection_expiry) for v in vehicles.values()], [(u.id, u.office) for u in recipients],
                [(p.id, p.version, p.status) for p in Plan.query.filter_by(company_code=code).all()],
                Record.query.filter_by(company_code=code).count(), Execution.query.filter_by(company_code=code).count(),
            ], sort_keys=True).encode()).hexdigest()
            if previous and previous.input_signature == signature and not force and previous.local_day == today.isoformat():
                try:
                    checked = datetime.fromisoformat(previous.checked_at)
                    if (now - checked).total_seconds() < 300:
                        db.session.rollback()
                        return {**json_dict(previous.report_json), 'skipped': True}
                except (ValueError, TypeError):
                    pass
            events = PlanEvent.query.filter(PlanEvent.company_code == code, PlanEvent.plan_id.in_([p.id for p in plans])).all() if plans else []
            # Snapshot before this tick closes superseded phases. Live phase
            # transitions may continue, but the new certificate exemption must
            # not resurrect an already-ended revision in a different bucket.
            prior_receipts = Delivery.query.filter_by(company_code=code).all()
            previously_open = {(d.plan_id, d.target_username, d.revision)
                               for d in prior_receipts if not d.ended_status}
            previously_ended = {(d.plan_id, d.target_username, d.revision)
                                for d in prior_receipts if d.ended_status}
            receipt_plans = {p.id: p for p in Plan.query.filter(Plan.company_code == code,
                Plan.id.in_({d.plan_id for d in prior_receipts})).all()} if prior_receipts else {}
            preserve_read = set()
            for delivery in prior_receipts:
                key = (delivery.plan_id, delivery.target_username, delivery.revision)
                plan = receipt_plans.get(delivery.plan_id)
                vehicle = vehicles.get(plan.vehicle_record_id) if plan else None
                expiry = iso_date(vehicle.inspection_expiry) if vehicle else None
                if delivery.ended_status and plan:
                    kind = identities.plan_kind(plan)
                    if kind == UNCONFIRMED or (kind in {'12month', 'vehicle_inspection'}
                            and plan.status == 'completed' and not confirmed_completion(plan, kind)):
                        preserve_read.add(delivery.notification_id)
                if (delivery.ended_status and key not in previously_open and plan and expiry
                        and identities.plan_kind(plan) == '12month' and month(plan.period_key)
                        and expiry.isoformat()[:7] > plan.period_key and not certificate_updated(plan, vehicle)):
                    preserve_read.add(delivery.notification_id)
            old_ids = list({row[0] for model in (Delivery, ExpiryDelivery) for row in db.session.query(model.notification_id).filter_by(company_code=code).distinct().all()})
            if old_ids:
                for delivery in ExpiryDelivery.query.filter_by(company_code=code).all():
                    vehicle = vehicles.get(delivery.vehicle_record_id)
                    expiry = iso_date(delivery.expiry_date)
                    if delivery.ended_status and vehicle and expiry and legacy_expiry_dependency(vehicle, delivery.expiry_date, today):
                        preserve_read.add(delivery.notification_id)
                    state = current_expiry_delivery(delivery, today)
                    if state not in {'pending', 'pending_unconfirmed'}:
                        delivery.ended_status = state
                for delivery in prior_receipts:
                    state = current_delivery(delivery, today)
                    if state not in {'pending', 'pending_unconfirmed'}:
                        delivery.ended_status = state
                for notification in Notification.query.filter(Notification.company_code == code, Notification.id.in_(old_ids)).all():
                    if notification.id not in preserve_read and not workflow(notification, today)['requires_action']:
                        notification.read = True
            groups = {}
            notified_plan_ids = set()
            for plan in plans:
                vehicle = vehicles.get(plan.vehicle_record_id)
                if not vehicle or identities.plan_kind(plan) == UNCONFIRMED or certificate_updated(plan, vehicle) or has_actual(plan, today):
                    continue
                if identities.plan_kind(plan) not in KINDS or not month(plan.planned_month) or (plan.reservation_date and (not iso_date(plan.reservation_date) or plan.reservation_date[:7] != plan.planned_month)):
                    report['invalid'] += 1
                    continue
                year = int(plan.planned_month[:4]) - (1 if int(plan.planned_month[5:]) < 4 else 0)
                if not 2000 <= year <= 2098:
                    report['invalid'] += 1
                    continue
                phase = reminder_phase(plan, today)
                if not phase:
                    continue
                phase_key, began, label = phase
                users = [u for u in recipients if vehicle.office and u.office == vehicle.office]
                if not users:
                    report['no_recipient'] += 1
                    continue
                rev = revision(plan, events, vehicle.office)
                bucket = max(0, (today - began).days // 7)
                for user in users:
                    key = (plan.id, user.username, rev)
                    expiry = iso_date(vehicle.inspection_expiry)
                    certificate_exempt = (identities.plan_kind(plan) == '12month'
                        and expiry and month(plan.period_key) and expiry.isoformat()[:7] > plan.period_key)
                    if certificate_exempt and key in previously_ended and key not in previously_open:
                        continue
                    sent = Delivery.query.filter_by(company_code=code, plan_id=plan.id, revision=rev, phase=phase_key, target_username=user.username).all()
                    if any(d.bucket == bucket or (iso_date(d.sent_day) and (today - iso_date(d.sent_day)).days < 7) for d in sent):
                        continue
                    groups.setdefault((vehicle.office, user.username, plan.planned_month), []).append((plan, vehicle, user, rev, phase_key, bucket, label))
            for (office, username, planned_month), items in groups.items():
                # Keep each message short while retaining a receipt for every listed plan.
                for offset in range(0, len(items), 25):
                    batch = items[offset:offset + 25]
                    lines = [office + 'の点検予定を確認してください。']
                    for p, v, _, _, _, _, label in batch:
                        plate = ' '.join(str(x) for x in (v.plate_area, v.plate_class, v.plate_kana, v.plate_number) if x) or v.chassis_number or f'車両#{v.id}'
                        lines.append(f'・{plate} / {KINDS[identities.plan_kind(p)]} / {label} / 予定月 {p.planned_month}' + (f' / 予約日 {p.reservation_date}' if p.reservation_date else ' / 予約日未定'))
                    lines.append('実施済みの場合は点検計画から実施日を登録してください。書類未受領でも登録できます。')
                    link = plan_link(office, [planned_month])
                    user = batch[0][2]
                    notification = Notification(company_code=code, target_username=username,
                        target_user=((user.last_name or '') + (user.first_name or ''))[:100], title=f'点検予定の確認：{len(batch)}件',
                        message='\n'.join(lines), link=link, read=False,
                        workflow_context_json=json.dumps({'action': 'inspection_plan_alert'}, ensure_ascii=False),
                        created_at=now.strftime('%Y-%m-%dT%H:%M:%SZ'))
                    db.session.add(notification)
                    db.session.flush([notification])
                    for p, _, _, rev, phase_key, bucket, _ in batch:
                        for old in Delivery.query.filter_by(company_code=code, plan_id=p.id, target_username=username, ended_status=None).all():
                            old.ended_status = 'closed'
                        db.session.add(Delivery(company_code=code, plan_id=p.id, notification_id=notification.id,
                            target_username=username, office=office, revision=rev, phase=phase_key, bucket=bucket, sent_day=today.isoformat()))
                    report['notifications'] += 1
                    notified_plan_ids.update(item[0].id for item in batch)
                    report['plans'] = len(notified_plan_ids)
            expiry_groups = {}
            for vehicle in vehicles.values():
                expiry = iso_date(vehicle.inspection_expiry)
                if not expiry or not 2000 <= expiry.year - (expiry.month < 4) <= 2098:
                    continue
                phase = expiry_phase(expiry, today)
                if not phase or expiry_is_planned(vehicle, expiry.isoformat()) or legacy_expiry_dependency(vehicle, expiry.isoformat(), today) or expiry_has_actual(vehicle, expiry.isoformat(), today):
                    continue
                users = [u for u in recipients if vehicle.office and u.office == vehicle.office]
                if not users:
                    report['no_recipient'] += 1
                    continue
                phase_key, began, label = phase
                bucket = max(0, (today - began).days // 7)
                for user in users:
                    sent = ExpiryDelivery.query.filter_by(company_code=code, vehicle_record_id=vehicle.id,
                        expiry_date=expiry.isoformat(), office=vehicle.office, phase=phase_key, target_username=user.username).all()
                    if any(d.bucket == bucket or (iso_date(d.sent_day) and (today - iso_date(d.sent_day)).days < 7) for d in sent):
                        continue
                    expiry_groups.setdefault((vehicle.office, user.username, expiry.isoformat()[:7]), []).append((vehicle, user, expiry.isoformat(), phase_key, bucket, label))
            for (office, username, mon), items in expiry_groups.items():
                for offset in range(0, len(items), 25):
                    batch = items[offset:offset + 25]
                    lines = [office + 'の車検証満了日と予定未登録の車両を確認してください。']
                    for v, _, expiry, _, _, label in batch:
                        plate = ' '.join(str(x) for x in (v.plate_area, v.plate_class, v.plate_kana, v.plate_number) if x) or v.chassis_number or f'車両#{v.id}'
                        lines.append(f'・{plate} / 車検証満了日 {expiry} / {label} / 予定未登録')
                    lines.append('予約済みなら点検計画に日程を登録してください。期限の経過だけで未実施とは断定していません。')
                    user = batch[0][1]
                    notification = Notification(company_code=code, target_username=username,
                        target_user=((user.last_name or '') + (user.first_name or ''))[:100], title=f'点検予定の確認：車検証満了日・予定未登録 {len(batch)}件',
                        message='\n'.join(lines), link=plan_link(office, [mon]), read=False,
                        workflow_context_json=json.dumps({'action': 'inspection_plan_alert'}, ensure_ascii=False),
                        created_at=now.strftime('%Y-%m-%dT%H:%M:%SZ'))
                    db.session.add(notification);db.session.flush([notification])
                    for v, _, expiry, phase_key, bucket, _ in batch:
                        for old in ExpiryDelivery.query.filter_by(company_code=code, vehicle_record_id=v.id, target_username=username, ended_status=None).all():
                            old.ended_status = 'closed'
                        db.session.add(ExpiryDelivery(company_code=code, vehicle_record_id=v.id, expiry_date=expiry,
                            notification_id=notification.id, target_username=username, office=office,
                            phase=phase_key, bucket=bucket, sent_day=today.isoformat()))
                    report['notifications'] += 1
                    report['expiry_candidates'] += len(batch)
            if old_ids:
                for notification in Notification.query.filter(Notification.company_code == code, Notification.id.in_(old_ids)).all():
                    if notification.id not in preserve_read and not workflow(notification, today)['requires_action']:
                        notification.read = True
            if previous is None:
                previous = Run(company_code=code)
                db.session.add(previous)
            previous.checked_at, previous.local_day = now.isoformat(), today.isoformat()
            previous.report_json = json.dumps(report)
            previous.input_signature = signature
            db.session.commit()
            return report
        except (IntegrityError, OperationalError):
            db.session.rollback()
            # A competing poll/tick will finish the same transaction safely.
            return {**report, 'notifications': 0, 'plans': 0, 'retry': True}
        except Exception:
            db.session.rollback()
            raise

    def run(code=None, today=None, force=False):
        today = today or local_today()
        codes = [code] if code else [c.company_code for c in Company.query.filter_by(active=True).order_by(Company.company_code).all()]
        return {c: process_company(c, today, force) for c in codes}

    @app.before_request
    def refresh_in_app_reminders():
        if (request.method == 'GET' and request.path in {'/api/notifications/recent', '/api/notifications/unread-count', '/notifications', '/vehicle/inspection-plans'}
                and session.get('username') and session.get('company_code') and session.get('role') in {'admin', 'itc'}):
            try:
                run(session['company_code'])
            except Exception:
                db.session.rollback()
                app.logger.exception('点検予定の通知確認に失敗しました。')

    @app.get('/api/vehicle/inspection-plans/alerts/status')
    def inspection_alert_status():
        from flask import abort, jsonify
        if session.get('role') not in {'admin', 'itc'}:
            abort(403)
        row = Run.query.filter_by(company_code=session['company_code']).first()
        return jsonify(last_checked_at=row.checked_at if row else None, report=json_dict(row.report_json) if row else {},
                       policy={'prior_month_day': 1, 'planned_month_day': 1, 'booking_days_before': [7, 1],
                               'execution_check_days_after': 1, 'repeat_after_days': 7,
                               'recipients': '同じ営業所の管理者', 'channel': 'アプリ内通知',
                               'unregistered_vehicle_inspection': True, 'expiry_days_before': [7, 1], 'expiry_today': True})

    @app.cli.command('inspection-plan-alerts')
    @click.option('--watch', is_flag=True, help='1分ごとに確認する常駐処理。')
    def inspection_plan_alerts_command(watch):
        """登録済み点検予定からアプリ内通知を作る（外部送信なし）。"""
        try:
            while True:
                try:
                    click.echo(json.dumps(run(), ensure_ascii=False))
                except Exception:
                    db.session.rollback()
                    app.logger.exception('点検通知の定期処理に失敗しました。')
                    if not watch:
                        raise
                finally:
                    db.session.remove()
                if not watch:
                    return
                time.sleep(60)
        except KeyboardInterrupt:
            click.echo('点検通知を停止しました。')

    return SimpleNamespace(run=run, workflow=workflow, Delivery=Delivery, ExpiryDelivery=ExpiryDelivery, Run=Run, phase=reminder_phase, target_link=target_link)
