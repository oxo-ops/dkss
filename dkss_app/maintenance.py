"""Maintenance responsibilities; routes are registered by the application factory."""
from . import common as _dkss_common, models as _dkss_models


def add_vehicle_maintenance_record_event(
    record,
    action,
    changes=None,
    status_before=None,
):
    if action not in {
        "created",
        "updated",
        "status_changed",
        "imported",
    }:
        raise ValueError("整備記録の履歴種別が不正です。")

    if record.id is None:
        raise ValueError("整備記録の保存前に履歴を追加できません。")

    identity = _dkss_common.session.get('account_identity')
    actor = _dkss_models.User.query.filter_by(company_code=record.company_code,
        account_identity=identity).first() if identity else None
    event = _dkss_models.VehicleMaintenanceRecordEvent(
        actor_identity=actor.account_identity if actor else None,
        actor_name=f"{actor.last_name or ''}{actor.first_name or ''}" if actor else None,
        company_code=record.company_code,
        vehicle_record_id=record.vehicle_record_id,
        maintenance_record_id=record.id,
        action=action,
        status_before=status_before,
        status_after=record.status,
        changes_json=_dkss_common.json.dumps(
            changes or [],
            ensure_ascii=False,
            default=str,
        ),
        created_by_username=_dkss_common.session.get("username"),
        created_at=_dkss_common.datetime.now(
            _dkss_common.ZoneInfo("Asia/Tokyo")
        ).isoformat(timespec="seconds"),
    )
    _dkss_common.db.session.add(event)
    return event
