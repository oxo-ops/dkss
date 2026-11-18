"""Narrow shared synthetic-company workflow; uses existing forms and route handlers."""
from datetime import date
import re
from urllib.parse import parse_qsl, urlencode, urlsplit
from flask import abort, current_app, redirect, request, session
from flask_wtf.csrf import validate_csrf
from wtforms.validators import ValidationError

WRITE = {'save_vehicle_checklist_one', 'complete_vehicle_checklist', 'save_vehicle_operation_judgment'}
READ = {'vehicle_checklist_results'}


def enabled():
    return current_app.config.get('PUBLIC_DEMO_WORKFLOW') is True


def username():
    key = 'PUBLIC_DEMO_MANAGER' if session.get('demo_role') == 'manager' else 'PUBLIC_DEMO_DRIVER'
    return current_app.config.get(key, current_app.config['PUBLIC_DEMO_USERNAME'])


def day_parts():
    value = date.fromisoformat(current_app.config['PUBLIC_DEMO_DAY'])
    return value.year, value.month, value.day


def shared_entry_link():
    """Resolve the existing synthetic 101 and daily form without provisioning."""
    import json
    from .models import Vehicle, Checklist
    company = current_app.config.get('PUBLIC_DEMO_COMPANY')
    fallback = '/vehicle/checklists'
    if not company or session.get('company_code') != company:
        return fallback
    vehicles = Vehicle.query.filter_by(company_code=company, plate_area='品川',
        plate_class='100', plate_kana='か', plate_number='101', deleted=False).limit(2).all()
    if len(vehicles) != 1:
        return fallback
    candidates = []
    for row in Checklist.query.filter_by(company_code=company, target='車両管理').all():
        try:
            items = json.loads(row.items_json or '[]')
        except (TypeError, ValueError):
            continue
        if (isinstance(items, list) and items and isinstance(items[0], dict)
                and items[0].get('fixed_template_code') == 'daily_inspection_truck_trailer'):
            candidates.append(row)
    if len(candidates) != 1:
        return fallback
    return f'/vehicle/checklists/{candidates[0].id}?vehicle_record_id={vehicles[0].id}'


def link():
    from .public_demo_shared import enabled as shared
    if shared():
        return shared_entry_link()
    y, m, d = day_parts()
    return f"/vehicle/checklists/{current_app.config['PUBLIC_DEMO_CHECKLIST_ID']}?vehicle_record_id={current_app.config['PUBLIC_DEMO_VEHICLE_ID']}&year={y}&month={m}&active_day={d}"


def role_return_target():
    """Keep an opened checklist; never accept arbitrary redirect destinations."""
    raw = request.form.get('checklist_return', '')
    if len(raw) > 2048 or any(ord(char) < 32 for char in raw):
        return '/'
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return '/'
    if (parsed.scheme or parsed.netloc or parsed.fragment
            or not re.fullmatch(r'/vehicle/checklists/[0-9]+', parsed.path)):
        return '/'
    allowed = {'vehicle_record_id', 'year', 'month', 'active_day',
               'vehicle_return_year', 'vehicle_return_month', 'vehicle_return_day'}
    # Reconstruct only the existing numeric view parameters. Normal route
    # guards still enforce company, vehicle, checklist and role permissions.
    values = {}
    for key, value in parse_qsl(parsed.query):
        if key in allowed and re.fullmatch(r'[0-9]{1,10}', value):
            values[key] = value
    query = urlencode(values)
    return parsed.path + ('?' + query if query else '')


def result():
    from .models import VehicleChecklistResult, User
    driver = User.query.filter_by(company_code=current_app.config['PUBLIC_DEMO_COMPANY'], username=current_app.config['PUBLIC_DEMO_DRIVER']).first()
    row = VehicleChecklistResult.query.filter_by(id=session.get('demo_result_id'),
        company_code=current_app.config['PUBLIC_DEMO_COMPANY'],
        vehicle_record_id=current_app.config['PUBLIC_DEMO_VEHICLE_ID'],
        checklist_id=current_app.config['PUBLIC_DEMO_CHECKLIST_ID']).first()
    if row is None or not driver or row.checked_by_identity != driver.account_identity or row.status not in {"承認待ち", "承認済み"}:
        abort(404)
    try:
        actual = tuple(int(v) for v in (row.year, row.month, row.day))
    except (TypeError, ValueError):
        abort(404)
    if actual != day_parts():
        abort(404)
    return row


def guard():
    """Return (handled, response). Existing CSRF + authority run for normal routes."""
    if not enabled():
        return False, None
    if request.path == '/demo/role':
        if request.method != 'POST':
            abort(405)
        try:
            validate_csrf(request.form.get('csrf_token'))
        except ValidationError:
            abort(400)
        role = request.form.get('role')
        if role not in {'driver', 'manager'}:
            abort(400)
        from .public_demo_shared import enabled as shared
        if role == 'manager' and not shared():
            result()  # Cannot judge unrelated/pre-existing company results.
        from .models import User
        target = current_app.config['PUBLIC_DEMO_MANAGER' if role == 'manager' else 'PUBLIC_DEMO_DRIVER']
        user = User.query.filter_by(company_code=current_app.config['PUBLIC_DEMO_COMPANY'], username=target).first()
        if not user or user.login_locked or user.role != ('admin' if role == 'manager' else 'user'):
            abort(404)
        if current_app.config.get('PUBLIC_DEMO_RELEASE'):
            key = 'MANAGER' if role == 'manager' else 'DRIVER'
            if user.account_identity != current_app.config['PUBLIC_DEMO_'+key+'_IDENTITY']:
                abort(404)
        session.update(demo_role_selected=True, demo_role=role, username=user.username, account_identity=user.account_identity,
            role=user.role, name=(user.last_name or '')+(user.first_name or ''), office=user.office,
            password_changed_at=user.password_changed_at, password_expired=False)
        return True, redirect(role_return_target() if shared() else link())
    if request.endpoint in {'approval_candidates', 'mention_users', 'search_vehicles'}:
        if request.method not in {'GET', 'HEAD'}:
            abort(403)
        return True, None
    if request.endpoint in {'notification_detail', 'open_notification_target'}:
        if request.method not in {'GET', 'HEAD'}:
            abort(403)
        import json
        from .models import Notification
        row = result()
        notice = Notification.query.filter_by(id=(request.view_args or {}).get('index'),
            company_code=current_app.config['PUBLIC_DEMO_COMPANY'], owner_identity=session.get('account_identity')).first()
        try:
            context = json.loads(notice.workflow_context_json or '{}') if notice else {}
        except (TypeError, ValueError):
            abort(404)
        if context.get('result_id') != row.id or context.get('result_type') != 'vehicle':
            abort(404)
        return True, None
    if request.endpoint in READ:
        args = request.view_args or {}
        if args.get('index') != current_app.config['PUBLIC_DEMO_CHECKLIST_ID']:
            abort(404)
        try:
            y,m,d=day_parts()
            if (int(request.args.get('vehicle_record_id','0')) != current_app.config['PUBLIC_DEMO_VEHICLE_ID']
                    or int(request.args.get('year','0')) != y or int(request.args.get('month','0')) != m
                    or int(request.args.get('active_day','0')) != d):
                abort(403)
        except (TypeError, ValueError):
            abort(403)
        return request.method in {'GET','HEAD'}, None
    if request.endpoint not in WRITE:
        return False, None
    if request.method != 'POST' or request.files:
        abort(403)
    # Approval recipients cannot be redirected to actual users in the same company.
    for key in request.form:
        if 'notify' in key:
            if any(v != current_app.config['PUBLIC_DEMO_MANAGER'] for v in request.form.getlist(key)):
                abort(403)
    if request.endpoint == 'save_vehicle_operation_judgment':
        row = result()
        if session.get('demo_role') != 'manager' or (request.view_args or {}).get('result_index') != row.id:
            abort(403)
        return True, None
    if session.get('demo_role') != 'driver' or (request.view_args or {}).get('index') != current_app.config['PUBLIC_DEMO_CHECKLIST_ID']:
        abort(403)
    try:
        values = tuple(int(request.form.get(k,'')) for k in ('year','month','day'))
        if values != day_parts() or int(request.form.get('vehicle_record_id','0')) != current_app.config['PUBLIC_DEMO_VEHICLE_ID']:
            abort(403)
    except (TypeError,ValueError):
        abort(403)
    if request.endpoint == 'save_vehicle_checklist_one' and request.form.get('value') not in {'✓', '×', '−', '-', ''}:
        abort(403)
    return True, None


def capture_result(response):
    from .public_demo import is_demo
    from .public_demo_shared import enabled as shared
    if shared() or not is_demo() or not enabled() or request.endpoint != 'complete_vehicle_checklist' :
        return response
    payload = response.get_json(silent=True) if response.is_json else None
    if not (response.status_code == 302 or (response.status_code == 200 and isinstance(payload, dict) and payload.get('success') is True)):
        return response
    bind_shared_result()
    return response


def bind_shared_result():
    """Only the configured shared synthetic record, never arbitrary company history."""
    session.pop('demo_result_id', None)
    from .models import VehicleChecklistResult, User
    driver = User.query.filter_by(company_code=current_app.config['PUBLIC_DEMO_COMPANY'], username=current_app.config['PUBLIC_DEMO_DRIVER']).first()
    candidates = VehicleChecklistResult.query.filter_by(company_code=current_app.config['PUBLIC_DEMO_COMPANY'],
        vehicle_record_id=current_app.config['PUBLIC_DEMO_VEHICLE_ID'], checklist_id=current_app.config['PUBLIC_DEMO_CHECKLIST_ID'],
        checked_by_identity=driver.account_identity).all() if driver else []
    rows = [r for r in candidates if tuple(int(v) for v in (r.year,r.month,r.day)) == day_parts()]
    if len(rows) == 1 and rows[0].status in {'承認待ち', '承認済み'}:
        session['demo_result_id'] = rows[0].id



def template_context():
    from .public_demo import is_demo
    if not is_demo() or not enabled():
        return {}
    from .public_demo_shared import enabled as shared
    if shared():
        return {'public_demo_workflow':True,'public_demo_shared':True,'public_demo_workflow_link':link(),'public_demo_notices':[]}
    import json
    from .models import Notification
    notices = []
    if session.get('demo_result_id'):
        candidates = Notification.query.filter_by(company_code=current_app.config['PUBLIC_DEMO_COMPANY'],
            owner_identity=session.get('account_identity')).order_by(Notification.id.desc()).limit(30).all()
        for notice in candidates:
            try:
                context = json.loads(notice.workflow_context_json or '{}')
            except (TypeError, ValueError):
                continue
            if context.get('result_id') == session['demo_result_id'] and context.get('result_type') == 'vehicle':
                notices.append({'id': notice.id, 'title': notice.title})
    return {'public_demo_workflow': True, 'public_demo_workflow_link': link(), 'public_demo_notices': notices[:3]}


def input_rate_limit():
    from .public_demo import is_demo
    return '120 per minute' if is_demo() and enabled() else '20 per minute'
