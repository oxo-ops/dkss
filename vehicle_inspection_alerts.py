"""Operational plan reminders. In-app only; no inferred legal deadlines."""
import hashlib
import json
import time
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import click
from flask import request, session
from sqlalchemy.exc import IntegrityError, OperationalError

from vehicle_inspection_plans import KINDS, add_months, iso_date, month


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


def register_inspection_alerts(app, db, Plan, PlanEvent, Execution, Record, Vehicle, Company, User, Notification):
    class InspectionPlanAlertDelivery(db.Model):
        __table_args__ = (db.UniqueConstraint('company_code', 'plan_id', 'revision', 'phase', 'bucket', 'target_username', name='uq_inspection_alert_delivery'),)
        id = db.Column(db.Integer, primary_key=True)
        company_code = db.Column(db.String(50), nullable=False, index=True)
        plan_id = db.Column(db.Integer, db.ForeignKey('vehicle_inspection_plan.id'), nullable=False, index=True)
        notification_id = db.Column(db.Integer, db.ForeignKey('notification.id'), nullable=False, index=True)
        target_username = db.Column(db.String(50), nullable=False)
        office = db.Column(db.String(100), nullable=False)
        revision = db.Column(db.String(64), nullable=False)
        phase = db.Column(db.String(30), nullable=False)
        bucket = db.Column(db.Integer, nullable=False)
        sent_day = db.Column(db.String(10), nullable=False)
        ended_status = db.Column(db.String(16))

    class InspectionPlanAlertRun(db.Model):
        company_code = db.Column(db.String(50), primary_key=True)
        checked_at = db.Column(db.String(40), nullable=False)
        local_day = db.Column(db.String(10), nullable=False)
        report_json = db.Column(db.Text, nullable=False, default='{}')
        input_signature = db.Column(db.String(64), nullable=False)

    Delivery, Run = InspectionPlanAlertDelivery, InspectionPlanAlertRun

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
        def match(day):
            return bool(iso_date(day) and day <= today.isoformat() and
                        (day == plan.reservation_date if plan.reservation_date else day[:7] == plan.planned_month))
        actuals = Record.query.filter_by(company_code=plan.company_code, vehicle_record_id=plan.vehicle_record_id, inspection_type=plan.kind).all()
        if any(match(r.inspection_date) for r in actuals):
            return True
        return any(match(e.performed_date) for e in Execution.query.filter_by(company_code=plan.company_code, vehicle_record_id=plan.vehicle_record_id, kind=plan.kind).all())

    def certificate_updated(plan, vehicle):
        expiry = iso_date(vehicle.inspection_expiry)
        return bool(plan.kind == 'vehicle_inspection' and expiry and month(plan.period_key) and expiry.isoformat()[:7] > plan.period_key)

    def current_delivery(delivery, today):
        if delivery.ended_status:
            return delivery.ended_status
        plan = Plan.query.filter_by(company_code=delivery.company_code, id=delivery.plan_id).first()
        vehicle = Vehicle.query.filter_by(company_code=delivery.company_code, id=plan.vehicle_record_id, deleted=False).first() if plan else None
        company = Company.query.filter_by(company_code=delivery.company_code, active=True).first()
        recipient = User.query.filter_by(company_code=delivery.company_code, username=delivery.target_username, role='admin', login_locked=False).first()
        if not company or not vehicle or not recipient or not vehicle.office or recipient.office != vehicle.office or delivery.office != vehicle.office:
            return 'closed'
        if certificate_updated(plan, vehicle):
            return 'closed'
        if plan.status == 'completed' or has_actual(plan, today):
            return 'completed'
        phase = reminder_phase(plan, today)
        events = PlanEvent.query.filter_by(company_code=delivery.company_code, plan_id=plan.id).all()
        if not phase or phase[0] != delivery.phase or revision(plan, events, vehicle.office) != delivery.revision:
            return 'closed'
        return 'pending'

    def workflow(notification, today=None):
        today = today or local_today()
        deliveries = Delivery.query.filter_by(company_code=notification.company_code, notification_id=notification.id, target_username=notification.target_username).all()
        statuses = [current_delivery(d, today) for d in deliveries]
        remaining = statuses.count('pending')
        if remaining:
            return {'workflow_status': 'pending', 'workflow_label': f'点検予定の確認待ち {remaining}件', 'requires_action': True}
        completed = bool(statuses) and all(s == 'completed' for s in statuses)
        return {'workflow_status': 'completed' if completed else 'closed',
                'workflow_label': '点検実施済み' if completed else '予定・対象変更により終了', 'requires_action': False}

    def process_company(code, today, force=False):
        now = datetime.now(ZoneInfo('UTC'))
        report = {'notifications': 0, 'plans': 0, 'no_recipient': 0, 'invalid': 0, 'skipped': False}
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
            old_ids = [row[0] for row in db.session.query(Delivery.notification_id).filter_by(company_code=code).distinct().all()]
            if old_ids:
                for delivery in Delivery.query.filter_by(company_code=code).all():
                    state = current_delivery(delivery, today)
                    if state != 'pending':
                        delivery.ended_status = state
                for notification in Notification.query.filter(Notification.company_code == code, Notification.id.in_(old_ids)).all():
                    if not workflow(notification, today)['requires_action']:
                        notification.read = True
            groups = {}
            notified_plan_ids = set()
            for plan in plans:
                vehicle = vehicles.get(plan.vehicle_record_id)
                if not vehicle or certificate_updated(plan, vehicle) or has_actual(plan, today):
                    continue
                if plan.kind not in KINDS or not month(plan.planned_month) or (plan.reservation_date and (not iso_date(plan.reservation_date) or plan.reservation_date[:7] != plan.planned_month)):
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
                    sent = Delivery.query.filter_by(company_code=code, plan_id=plan.id, revision=rev, phase=phase_key, target_username=user.username).all()
                    if any(d.bucket == bucket or (iso_date(d.sent_day) and (today - iso_date(d.sent_day)).days < 7) for d in sent):
                        continue
                    groups.setdefault((vehicle.office, user.username, year), []).append((plan, vehicle, user, rev, phase_key, bucket, label))
            for (office, username, year), items in groups.items():
                # Keep each message short while retaining a receipt for every listed plan.
                for offset in range(0, len(items), 25):
                    batch = items[offset:offset + 25]
                    lines = [office + 'の点検予定を確認してください。']
                    for p, v, _, _, _, _, label in batch:
                        plate = ' '.join(str(x) for x in (v.plate_area, v.plate_class, v.plate_kana, v.plate_number) if x) or v.chassis_number or f'車両#{v.id}'
                        lines.append(f'・{plate} / {KINDS[p.kind]} / {label} / 予定月 {p.planned_month}' + (f' / 予約日 {p.reservation_date}' if p.reservation_date else ' / 予約日未定'))
                    lines.append('実施済みの場合は点検計画から実施日を登録してください。書類未受領でも登録できます。')
                    link = '/vehicle/inspection-plans?scope=office&vehicle_id=' + str(batch[0][1].id) + '&year=' + str(year)
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
            if old_ids:
                for notification in Notification.query.filter(Notification.company_code == code, Notification.id.in_(old_ids)).all():
                    if not workflow(notification, today)['requires_action']:
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
                               'recipients': '同じ営業所の管理者', 'channel': 'アプリ内通知'})

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

    return SimpleNamespace(run=run, workflow=workflow, Delivery=Delivery, Run=Run, phase=reminder_phase)
