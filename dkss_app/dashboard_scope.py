"""The office and period selected for one dashboard request."""

from dataclasses import dataclass
from datetime import date, timedelta
from .serialization import safe_json_dict


@dataclass(frozen=True)
class DashboardScope:
    company_code: str
    username: str
    role: str
    user_name: str
    today: date
    settings: dict
    office: str
    office_missing: bool
    start_date: str
    end_exclusive: str

    @classmethod
    def for_user(cls, user, *, company_code, username, role, user_name, today):
        settings = dict(
            office="",
            period="30d",
            show_summary=True,
            show_vehicles=True,
            show_my_checklists=True,
            show_analysis=True,
            show_ranking=True,
            show_inspection=True,
            show_pending=True,
        )
        if user:
            settings.update(safe_json_dict(user.dashboard_settings_json))
        # A saved display preference must never expand the user's office scope.
        office = str(user.office or "").strip() if user else ""
        settings["office"] = office
        days = {"7d": 7, "30d": 30, "90d": 90, "365d": 365}.get(settings.get("period"), 30)
        return cls(
            company_code,
            username,
            role,
            user_name,
            today,
            settings,
            office,
            not bool(office),
            (today - timedelta(days=days - 1)).strftime("%Y-%m-%d"),
            (today + timedelta(days=1)).strftime("%Y-%m-%d"),
        )
