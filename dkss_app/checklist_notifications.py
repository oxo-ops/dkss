"""Checklist Notifications responsibilities; routes are registered by the application factory."""
from . import checklist_common as _dkss_checklist_common, models as _dkss_models, notifications_delivery as _dkss_notifications_delivery, serialization as _dkss_serialization
from .checklist_notify_identity import resolved_notify_users


def get_vehicle_checklist_notify_users(
    company_code,
    checklist_id,
    vehicle_record_id
):
    return [user.username for user in resolved_notify_users(company_code, checklist_id, vehicle_record_id)]



def send_vehicle_checklist_reminders(company_code):
    checklists = _dkss_models.Checklist.query.filter_by(
        company_code=company_code,
        target="車両管理",
        reminder_enabled=True,
        active=True
    ).all()

    for checklist in checklists:

        # 今回は日次点検のみ対象
        if (
            checklist.frequency_unit != "day"
            or str(checklist.frequency_value or "1") != "1"
        ):
            continue

        reminder_time = (
            checklist.reminder_time
            or "08:00"
        )

        vehicles = _dkss_models.Vehicle.query.filter_by(
            company_code=company_code,
            deleted=False
        ).all()

        for vehicle in vehicles:

            for target_user in resolved_notify_users(company_code, checklist.id, vehicle.id):
                target_username = target_user.username

                local_now = _dkss_checklist_common.get_user_local_now(
                    company_code,
                    target_username
                )

                current_time = local_now.strftime(
                    "%H:%M"
                )

                if current_time < reminder_time:
                    continue

                local_date = local_now.date()

                if _dkss_checklist_common.is_vehicle_checklist_completed_on_date(
                    company_code,
                    checklist.id,
                    vehicle.id,
                    local_date
                ):
                    continue

                reminder_date = (
                    local_date.strftime("%Y-%m-%d")
                )

                title = "車両点検が未実施です"

                if checklist.frequency_unit == "year":
                    active_day = str(local_date.year)
                elif checklist.display_type == "month":
                    active_day = str(local_date.day).zfill(2)
                else:
                    active_day = str(local_date.month).zfill(2)

                link = (
                    f"/vehicle/checklists/{checklist.id}"
                    f"?vehicle_record_id={vehicle.id}"
                    f"&year={local_date.year}"
                    f"&month={str(local_date.month).zfill(2)}"
                    f"&active_day={active_day}"
                )

                # 同じ人・車両・現地日付では1回だけ
                already_sent = _dkss_models.Notification.query.filter_by(
                    company_code=company_code,
                    owner_identity=target_user.account_identity,
                    title=title,
                    link=link
                ).first()

                if already_sent:
                    continue

                _dkss_notifications_delivery.add_notification(
                    (
                        f"{target_user.last_name or ''}"
                        f"{target_user.first_name or ''}"
                    ),
                    title,
                    (
                        f"{checklist.name}："
                        f"車両 {' '.join(value for value in [vehicle.plate_area or '', vehicle.plate_class or '', vehicle.plate_kana or '', vehicle.plate_number or ''] if value) or 'ナンバー未登録'} の"
                        f"本日の点検が完了していません。"
                    ),
                    link,
                    company_code=company_code,
                    target_identity=target_user.account_identity,
                    target_username=target_username
                )
