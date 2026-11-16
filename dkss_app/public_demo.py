"""Disabled-by-default, isolated-test candidate for the REAL application UI.
No template replacement and no passwordless access to ordinary accounts.
Production activation is intentionally prohibited pending deployment review.
"""
import os
import time
from flask import abort, current_app, g, redirect, request, session

MARKER = 'aonagi_readonly_demo'
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

    def target_user():
        from .models import User, Company
        company = Company.query.filter_by(company_code=current_app.config['PUBLIC_DEMO_COMPANY'], active=True).first()
        user = User.query.filter_by(company_code=current_app.config['PUBLIC_DEMO_COMPANY'],
                                   username=expected_username()).first()
        # The deployment must provision a separate display-only principal, never an ITC account.
        if not company or not user or user.role not in {'user', 'admin'} or user.login_locked or not user.account_identity:
            abort(404)
        if current_app.config.get('PUBLIC_DEMO_RELEASE'):
            key = 'MANAGER' if session.get('demo_role') == 'manager' else 'DRIVER'
            expected_role = 'admin' if key == 'MANAGER' else 'user'
            if user.role != expected_role or user.account_identity != current_app.config['PUBLIC_DEMO_'+key+'_IDENTITY']:
                abort(404)
        return user

    def guard():
        if not current_app.config.get('PUBLIC_DEMO_CANDIDATE'):
            if is_demo():
                session.clear()
                abort(410)
            if request.path == '/demo':
                abort(404)
            return None
        if request.path == '/demo':
            from .extensions import limiter
            if limiter.enabled:
                with limiter.limit('30 per minute', scope='public_demo_entry'):
                    pass
            if request.method != 'GET':
                abort(405)
            if request.args:
                abort(400)  # No user/company/role/redirect overrides from callers.
            if int(time.time()) < current_app.config.get('PUBLIC_DEMO_FROM',0):
                abort(404)
            if expired():
                session.clear() if is_demo() else None
                abort(410)
            if session.get('username') and not is_demo():
                abort(409)  # Do not replace an ordinary authenticated session.
            user = target_user()
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
                state[MARKER] = True
                issue(state)
                session.clear()
                session.update(state)
            session.setdefault('demo_role', 'driver')
            session[MARKER] = True
            session['demo_epoch'] = current_app.config['PUBLIC_DEMO_EPOCH']
            session['demo_until'] = current_app.config['PUBLIC_DEMO_UNTIL']
            from .public_demo_workflow import enabled, bind_shared_result
            from .public_demo_shared import enabled as shared
            if enabled() and not shared():
                bind_shared_result()
            if shared():
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
        if is_demo() or request.path == '/demo':
            response.headers['Cache-Control'] = 'private, no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    app.add_url_rule('/demo', 'public_demo_entry', lambda: abort(404), methods=['GET'])
    app.add_url_rule('/demo/role', 'public_demo_role', lambda: abort(404), methods=['POST'])
    app.before_request_funcs.setdefault(None, []).insert(0, guard)
    app.after_request(no_cache)
    from .public_demo_workflow import capture_result
    app.after_request(capture_result)
    from .public_demo_workflow import template_context
    app.context_processor(template_context)
