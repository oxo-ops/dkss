"""Disabled-by-default, isolated-test candidate for the REAL application UI.
No template replacement and no passwordless access to ordinary accounts.
Production activation is intentionally prohibited pending deployment review.
"""
import os
import time
from flask import abort, current_app, g, redirect, request, session, url_for
from urllib.parse import urlencode

MARKER = 'aonagi_readonly_demo'
SHARE_QUERY = '__aonagi_entry'
RECOVERY_COOKIE = 'dkss_demo_return'
RECOVERY_ENDPOINTS = frozenset({'dashboard', 'safety', 'pointouts', 'pointout_detail', 'new_pointout', 'edit_pointout', 'safety_checklists', 'safety_checklist_results', 'driving_reports', 'vehicle_daily_inspection_entry', 'vehicle_checklists', 'vehicle_checklist_results', 'vehicle_karte', 'vehicle_karte_list', 'vehicle_karte_history', 'vehicle_karte_parts', 'vehicle_karte_costs', 'vehicle_karte_documents', 'vehicle_karte_inspections', 'vehicle_karte_analysis', 'vehicle_inspection_plans'})


def recovery_signer():
    from itsdangerous import URLSafeSerializer
    return URLSafeSerializer(current_app.secret_key, salt='public-demo-return-v1')


def recovery_valid():
    # This hint never authenticates a user. It only selects the existing /demo entry.
    from itsdangerous import BadData
    try:
        value = recovery_signer().loads(request.cookies.get(RECOVERY_COOKIE, ''))
    except BadData:
        return False
    return value == {'epoch': current_app.config['PUBLIC_DEMO_EPOCH'],
                     'until': current_app.config['PUBLIC_DEMO_UNTIL']}

SHARE_ENDPOINTS = {'dashboard': frozenset(), 'vehicle_checklist_results': frozenset({'vehicle_record_id', 'year', 'month', 'active_day', 'vehicle_return_year', 'vehicle_return_month', 'vehicle_return_day', 'vehicle_saved'})}
READ_ENDPOINTS = frozenset({
    'vehicle_karte', 'vehicle_karte_list', 'vehicle_karte_history',
    'vehicle_karte_parts', 'vehicle_karte_costs', 'vehicle_karte_documents',
    'vehicle_karte_inspections',
})


def is_demo():
    return session.get(MARKER) is True


def install(app):
    from .public_demo_release import load
    load(app)
    if not app.config.get('PUBLIC_DEMO_CANDIDATE'):
        def reject_retired_demo():
            if SHARE_QUERY in request.args:
                abort(404)
            if is_demo():
                session.clear()
                abort(410)
        app.before_request_funcs.setdefault(None, []).insert(0, reject_retired_demo)
        return
    if not app.config.get('PUBLIC_DEMO_RELEASE') and (not app.testing or os.environ.get('RENDER') == 'true'):
        raise RuntimeError('Public demo candidate is isolated-test-only; production review required')
    required = ('PUBLIC_DEMO_COMPANY', 'PUBLIC_DEMO_USERNAME', 'PUBLIC_DEMO_EPOCH', 'PUBLIC_DEMO_UNTIL')
    if not app.config.get('PUBLIC_DEMO_SHARED_COMPANY'):
        required += ('PUBLIC_DEMO_VEHICLE_ID',)
    if not all(app.config.get(key) for key in required):
        raise RuntimeError('Explicit demo company, dedicated user, expiry, epoch and vehicle required')
    if type(app.config['PUBLIC_DEMO_UNTIL']) is not int:
        raise RuntimeError('Explicit integer UTC expiration required')

    def expired():
        return int(time.time()) >= current_app.config['PUBLIC_DEMO_UNTIL']

    def expected_username():
        from .public_demo_workflow import enabled, username
        return username() if enabled() else current_app.config['PUBLIC_DEMO_USERNAME']

    def target_user(force_driver=False):
        from .models import User, Company
        company = Company.query.filter_by(company_code=current_app.config['PUBLIC_DEMO_COMPANY'], active=True).first()
        user = User.query.filter_by(company_code=current_app.config['PUBLIC_DEMO_COMPANY'],
                                   username=(current_app.config.get('PUBLIC_DEMO_DRIVER', current_app.config['PUBLIC_DEMO_USERNAME']) if force_driver else expected_username())).first()
        # The deployment must provision a separate display-only principal, never an ITC account.
        if not company or not user or user.role not in {'user', 'admin'} or user.login_locked or not user.account_identity:
            abort(404)
        if current_app.config.get('PUBLIC_DEMO_RELEASE'):
            key = 'MANAGER' if not force_driver and session.get('demo_role') == 'manager' else 'DRIVER'
            expected_role = 'admin' if key == 'MANAGER' else 'user'
            if user.role != expected_role or user.account_identity != current_app.config['PUBLIC_DEMO_'+key+'_IDENTITY']:
                abort(404)
        return user

    def guard():
        g.public_demo_entry_ok = False
        g.public_demo_recovery_redirect = False
        marked = SHARE_QUERY in request.args
        recovery_target = None
        # /login is the explicit ordinary-account entry, not a demo recovery URL.
        # Only leave the synthetic identity here; ordinary and MFA sessions keep
        # their existing authentication rules. Never authenticate a real company.
        if request.endpoint == 'login' and request.method == 'GET' and not marked and is_demo():
            session.clear()
            return None
        if (request.endpoint == 'dashboard' and request.method == 'GET' and not marked
                and (is_demo() or (not session and recovery_valid()))):
            if is_demo():
                session.clear()
            g.public_demo_normal_entry = True
            return redirect('/login')
        if marked:
            if request.method != 'GET':
                abort(405)
            allowed = SHARE_ENDPOINTS.get(request.endpoint)
            if allowed is None or not current_app.config.get('PUBLIC_DEMO_SHARED_COMPANY'):
                abort(404)
            if request.args.getlist(SHARE_QUERY) != ['1'] or any(
                key != SHARE_QUERY and (key not in allowed or len(request.args.getlist(key)) != 1)
                for key in request.args
            ):
                abort(400)
            if request.args.get('vehicle_saved') not in (None, 'complete'):
                abort(400)
            if not is_demo() and (session.get('username') or any(key.startswith('mfa_') for key in session)):
                abort(409)
            # Never turn a retired, invalid or partial demo cookie into a fresh identity.
            if not is_demo() and any(key in session for key in (MARKER, 'public_demo_token', 'demo_epoch')):
                abort(410)
        if not current_app.config.get('PUBLIC_DEMO_CANDIDATE'):
            if is_demo():
                session.clear()
                abort(410)
            if request.path == '/demo' or marked:
                abort(404)
            return None
        if (not marked and not session and request.method == 'GET'
                and request.endpoint in RECOVERY_ENDPOINTS
                and current_app.config.get('PUBLIC_DEMO_SHARED_COMPANY')
                and int(time.time()) >= current_app.config.get('PUBLIC_DEMO_FROM', 0)
                and not expired() and recovery_valid()):
            # Build a local route from Flask's matched endpoint, never a caller's
            # return URL. Reissue only the dedicated driver; do not recover roles
            # or replay a business POST. The following GET runs all normal guards.
            recovery_target = url_for(request.endpoint, **(request.view_args or {}))
            if request.args:
                recovery_target += '?' + urlencode(list(request.args.items(multi=True)))
            g.public_demo_recovery_redirect = True
        if request.path == '/demo' or (marked and not is_demo()) or recovery_target:
            from .extensions import limiter
            if limiter.enabled:
                with limiter.limit('30 per minute', scope='public_demo_entry'):
                    pass
            if request.method != 'GET':
                abort(405)
            if request.args and not marked and recovery_target is None:
                abort(400)  # No user/company/role/redirect overrides from callers.
            if int(time.time()) < current_app.config.get('PUBLIC_DEMO_FROM',0):
                abort(404)
            if expired():
                session.clear() if is_demo() else None
                abort(410)
            if session.get('username') and not is_demo():
                abort(409)  # Do not replace an ordinary authenticated session.
            user = target_user(force_driver=marked or recovery_target is not None)
            from .public_demo_shared import enabled as shared
            if not shared():
                from .models import Vehicle
                vehicle = Vehicle.query.filter_by(id=current_app.config['PUBLIC_DEMO_VEHICLE_ID'],
                                                  company_code=user.company_code, deleted=False).first()
                if vehicle is None:
                    abort(404)
            if not is_demo():
                from .public_demo_sessions import issue
                state = dict(company_code=user.company_code, username=user.username,
                               account_identity=user.account_identity, role=user.role,
                               name=(user.last_name or '')+(user.first_name or ''), office=user.office,
                               password_changed_at=user.password_changed_at, password_expired=False)
                if marked or recovery_target is not None:
                    state['demo_role'] = 'driver'
                state[MARKER] = True
                issue(state)
                session.clear()
                session.update(state)
            g.public_demo_entry_ok = True
            session.setdefault('demo_role', 'driver')
            session[MARKER] = True
            session['demo_epoch'] = current_app.config['PUBLIC_DEMO_EPOCH']
            session['demo_until'] = current_app.config['PUBLIC_DEMO_UNTIL']
            from .public_demo_workflow import enabled, bind_shared_result
            from .public_demo_shared import enabled as shared
            if enabled() and not shared():
                bind_shared_result()
            if recovery_target is not None:
                session.pop('demo_role_selected', None)
                return redirect(recovery_target)
            if marked:
                # Redirect to the same reviewed URL, then run the complete normal guard.
                return redirect(request.full_path.rstrip('?'))
            if shared():
                session.pop('demo_role_selected', None)
                return redirect('/')
            return redirect('/vehicle/karte/' + str(vehicle.id))
        if not is_demo():
            return None
        if (int(time.time()) < current_app.config.get('PUBLIC_DEMO_FROM',0) or expired() or session.get('demo_until') != current_app.config['PUBLIC_DEMO_UNTIL']
                or session.get('demo_epoch') != current_app.config['PUBLIC_DEMO_EPOCH']
                or session.get('company_code') != current_app.config['PUBLIC_DEMO_COMPANY']
                or session.get('username') != expected_username()):
            session.clear()
            abort(410)
        from .public_demo_sessions import verify, revoke
        verify()
        user = target_user()
        if session.get('account_identity') != user.account_identity:
            session.clear()
            abort(410)
        if request.endpoint == 'logout' and request.method == 'POST':
            from .access import require_login
            denial = require_login()
            if denial is not None:
                return denial
            from flask_wtf.csrf import validate_csrf
            from wtforms.validators import ValidationError
            try:
                validate_csrf(request.form.get('csrf_token'))
            except ValidationError:
                abort(400)
            revoke()
            return None
        if request.path == '/demo/role':
            from .access import require_login
            denial = require_login()
            if denial is not None:
                return denial
        from .public_demo_shared import enabled as shared, guard as shared_guard
        if shared() and request.path != '/demo/role':
            return shared_guard()
        from .public_demo_workflow import guard as workflow_guard
        handled, response = workflow_guard()
        if handled:
            return response
        if request.method not in {'GET', 'HEAD'}:
            abort(403)
        if request.endpoint == 'static':
            filename = (request.view_args or {}).get('filename', '')
            # Only non-user-authored assets; never uploads/manuals or traversal.
            if not filename.startswith(('css/', 'js/', 'images/', 'icons/', 'vendor/')) or '..' in filename.split('/'):
                abort(403)
            return None
        if request.endpoint not in READ_ENDPOINTS:
            abort(403)
        if request.args.get('priority_preview'):
            abort(403)
        g.public_demo_readonly = True
        # Existing normal access.require_login validates user/password generation,
        # durable session revocation and company state after this guard.

    def no_cache(response):
        # Keep every synthetic home redirect explicit, including completion/role
        # returns. Ordinary home URLs remain ordinary-account entry points.
        if is_demo() and response.status_code in (301, 302, 303, 307, 308) and response.headers.get('Location') == '/':
            response.headers['Location'] = '/?' + SHARE_QUERY + '=1'
        if getattr(g, 'public_demo_entry_ok', False) and response.status_code < 400:
            remaining = max(0, current_app.config['PUBLIC_DEMO_UNTIL'] - int(time.time()))
            response.set_cookie(RECOVERY_COOKIE, recovery_signer().dumps({
                'epoch': current_app.config['PUBLIC_DEMO_EPOCH'],
                'until': current_app.config['PUBLIC_DEMO_UNTIL']}),
                max_age=remaining, secure=True, httponly=True, samesite='Lax')
        elif (getattr(g, 'public_demo_normal_entry', False) or request.endpoint in {'login', 'logout', 'mfa'} or response.status_code in {410, 503}
              or (session.get('username') and not is_demo())):
            if RECOVERY_COOKIE in request.cookies:
                response.delete_cookie(RECOVERY_COOKIE, secure=True, httponly=True, samesite='Lax')
        if is_demo() or request.path == '/demo' or SHARE_QUERY in request.args or getattr(g, 'public_demo_recovery_redirect', False) or getattr(g, 'public_demo_normal_entry', False):
            response.headers['Cache-Control'] = 'private, no-store'
            # Keep HTTPS same-origin CSRF checks working without leaking demo URLs externally.
            response.headers['Referrer-Policy'] = 'same-origin'
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        from .bundled_asset_cache import apply_bundled_asset_cache
        return apply_bundled_asset_cache(response)

    app.add_url_rule('/demo', 'public_demo_entry', lambda: abort(404), methods=['GET'])
    app.add_url_rule('/demo/role', 'public_demo_role', lambda: abort(404), methods=['POST'])
    app.before_request_funcs.setdefault(None, []).insert(0, guard)
    # Run last so general security headers cannot weaken demo sharing privacy.
    app.after_request_funcs.setdefault(None, []).insert(0, no_cache)
    from .public_demo_workflow import capture_result
    app.after_request(capture_result)
    from .public_demo_workflow import template_context
    app.context_processor(template_context)
