"""HTTP boundary for expiring, reusable company registration invitations."""
from flask import abort, current_app, make_response, redirect, render_template, request, session, url_for
from sqlalchemy.exc import SQLAlchemyError
from .extensions import db
from .master_readers import ordered_master_query
from .models import Company, User, Office, CompanyRegistrationInvite, CompanyRegistrationApplication
from . import company_invites as service


def _private_response(body, status=200):
    response = make_response(body, status)
    response.headers['Cache-Control'] = 'no-store'
    # Keep HTTPS strict CSRF Referer checks working without cross-origin leaks.
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


def _actor():
    return User.query.filter_by(company_code=session.get('company_code'), username=session.get('username')).first()


def public_registration():
    token = request.args.get('invite', '')
    error = None
    try:
        invite, company = service.validate_invite(token)
        if request.method == 'POST':
            service.submit_application(token, request.form)
            return _private_response(render_template('registration_result.html',
                message='登録申請を受け付けました。会社の管理者による確認・承認後、設定したログインIDとパスワードでログインしてください。', company_code=company.company_code))
        offices = ordered_master_query(Office, company.company_code).all()
        return _private_response(render_template('register.html', error=None,
            company_code=company.company_code, company_name=company.company_name,
            invite_token=token, offices=offices))
    except service.InviteError as exc:
        db.session.rollback()
        try:
            _, company = service.validate_invite(token)
            offices = ordered_master_query(Office, company.company_code).all()
            return _private_response(render_template('register.html', error=str(exc),
                company_code=company.company_code, company_name=company.company_name,
                invite_token=token, offices=offices), exc.status)
        except service.InviteError:
            return _private_response(render_template('registration_result.html', message=str(exc), company_code=None), exc.status)
    except SQLAlchemyError:
        db.session.rollback()
        return _private_response(render_template('registration_result.html',
            message='現在、登録申請を受け付けられません。会社の管理者に確認してください。', company_code=None), 503)


def itc_registration(index):
    actor = _actor()
    if not actor or actor.role != 'itc':
        abort(403)
    company = Company.query.filter_by(id=index).first_or_404()
    return _manage(company, actor)


def company_registration():
    actor = _actor()
    if not actor or actor.role != 'admin':
        abort(403)
    company = Company.query.filter_by(company_code=actor.company_code).first_or_404()
    return _manage(company, actor)


def _manage(company, actor):
    if not company.active or company.company_code.upper() == 'ITC':
        abort(403)
    error, generated_url, status = None, None, 200
    try:
        if request.method == 'POST':
            action = request.form.get('action')
            if action == 'issue':
                invite, token = service.issue_invite(company.company_code, actor, days=7)
                # Display only once; never store the bearer URL in a cookie/flash.
                generated_url = url_for('register', invite=token, _external=True)
            elif action == 'revoke':
                item = CompanyRegistrationInvite.query.filter_by(id=request.form.get('invite_id'), company_code=company.company_code).first()
                if not item: abort(404)
                service.revoke_invite(item.id, actor)
                return redirect(request.path, code=303)
            elif action in ('approve', 'reject'):
                item = CompanyRegistrationApplication.query.filter_by(id=request.form.get('application_id'), company_code=company.company_code).first()
                if not item: abort(404)
                if action == 'approve':
                    service.approve_application(item.id, actor, role=request.form.get('role', 'user'),
                        verification_reason=request.form.get('verification_reason', ''))
                else:
                    service.reject_application(item.id, actor)
                return redirect(request.path, code=303)
            else:
                abort(400)
        invites = CompanyRegistrationInvite.query.filter_by(company_code=company.company_code).order_by(CompanyRegistrationInvite.id.desc()).limit(20).all()
        page = request.args.get('page', 1, type=int)
        pagination = CompanyRegistrationApplication.query.filter_by(company_code=company.company_code).order_by(
            (CompanyRegistrationApplication.status == 'pending').desc(), CompanyRegistrationApplication.id.asc()
        ).paginate(page=max(1, page), per_page=50, error_out=False)
        applications = pagination.items
        has_admin = User.query.filter_by(company_code=company.company_code, role='admin').first() is not None
    except (service.InviteError, SQLAlchemyError) as exc:
        db.session.rollback()
        error = str(exc) if isinstance(exc, service.InviteError) else '登録受付の準備が完了していません。管理者に確認してください。'
        status = exc.status if isinstance(exc, service.InviteError) else 503
        invites, applications, has_admin, pagination = [], [], False, None
    return _private_response(render_template('company_registration.html', company=company,
        invites=invites, applications=applications, generated_url=generated_url,
        error=error, has_admin=has_admin, pagination=pagination, is_itc=actor.role == 'itc'), status)
