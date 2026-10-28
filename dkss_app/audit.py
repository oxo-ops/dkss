"""Audit responsibilities; routes are registered by the application factory."""
from . import common as _dkss_common, models as _dkss_models


def add_audit_log(
    action,
    target_type="",
    target_id="",
    detail="",
    company_code=None,
    username=None,
):
    company_code = str(
        company_code
        or _dkss_common.session.get("company_code")
        or ""
    ).strip()

    username = str(
        username
        or _dkss_common.session.get("username")
        or ""
    ).strip()

    action = str(action or "").strip()
    target_type = str(target_type or "").strip()
    target_id = str(target_id or "").strip()
    detail = str(detail or "")
    ip_address = str(
        _dkss_common.request.remote_addr or ""
    ).strip()

    if len(detail) > 5000:
        detail = detail[:5000]

    if len(ip_address) > 100:
        ip_address = ip_address[:100]

    if len(company_code) > 50:
        company_code = company_code[:50]

    if len(username) > 100:
        username = username[:100]

    if len(action) > 100:
        action = action[:100]

    if len(target_type) > 100:
        target_type = target_type[:100]

    if len(target_id) > 100:
        target_id = target_id[:100]

    identity = _dkss_common.session.get('account_identity')
    actor = None
    # Enrichment must not move business writes outside the caller's commit/error
    # handling boundary (e.g. an optimistic master-order conflict).
    with _dkss_common.db.session.no_autoflush:
        if identity and username == _dkss_common.session.get('username'):
            actor = _dkss_models.User.query.filter_by(
                company_code=_dkss_common.session.get('company_code'), account_identity=identity
            ).first()
        elif action in {'login_success', 'user_registered'}:
            # These callers have just verified credentials or created the account.
            pending = [row for row in _dkss_common.db.session.new
                if isinstance(row, _dkss_models.User) and row.company_code == company_code and row.username == username]
            if action == 'user_registered' and len(pending) == 1:
                actor = pending[0]
                if not actor.account_identity:
                    actor.account_identity = str(_dkss_common.uuid4())
            else:
                actor = _dkss_models.User.query.filter_by(company_code=company_code, username=username).first()
    if action in {'login_failed', 'account_locked', 'mfa_failed', 'mfa_code_invalidated'}:
        actor = None  # An attempted login ID is not proof of the actor's identity.
    # Login failure may have no authenticated actor; never resolve on display.
    audit_log = _dkss_models.AuditLog(
        actor_identity=actor.account_identity if actor else None,
        actor_name=(f"{actor.last_name or ''}{actor.first_name or ''}") if actor else None,
        company_code=company_code,
        username=username,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        ip_address=ip_address,
        created_at=_dkss_common.datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    )

    _dkss_common.db.session.add(audit_log)



def cleanup_old_audit_logs(retention_days=365):
    cutoff = (
        _dkss_common.datetime.now() - _dkss_common.timedelta(days=retention_days)
    ).strftime("%Y-%m-%d %H:%M:%S")

    _dkss_models.AuditLog.query.filter(
        _dkss_models.AuditLog.created_at < cutoff
    ).delete(synchronize_session=False)

    _dkss_common.db.session.commit()



def update_company_usage_summary(
    company_code,
    increment_login=False
):
    if not company_code:
        return

    summary = _dkss_models.CompanyUsageSummary.query.filter_by(
        company_code=company_code
    ).first()

    if not summary:
        summary = _dkss_models.CompanyUsageSummary(
            company_code=company_code
        )
        _dkss_common.db.session.add(summary)

    summary.user_count = _dkss_models.User.query.filter_by(
        company_code=company_code
    ).count()

    summary.vehicle_count = _dkss_models.Vehicle.query.filter_by(
        company_code=company_code,
        deleted=False
    ).count()

    summary.checklist_result_count = (
        _dkss_models.ChecklistResult.query.filter_by(
            company_code=company_code
        ).count()
        +
        _dkss_models.VehicleChecklistResult.query.filter_by(
            company_code=company_code
        ).count()
    )

    if increment_login:
        summary.login_count = (
            summary.login_count or 0
        ) + 1

    summary.last_used_at = _dkss_common.datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    summary.updated_at = _dkss_common.datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )
