"""Company-scoped reads and request-lifetime caches for the dashboard."""

from datetime import timedelta
from . import models
from .extensions import db
from .master_readers import ordered_master_query


class DashboardRepository:
    def __init__(self, scope):
        self.scope = scope
        self._vehicles = {}
        self._office_vehicle_ids = None
        self._personal_results = {}
        self._assigned_ids = ()

    @staticmethod
    def current_user(company_code, username):
        return models.User.query.filter_by(company_code=company_code, username=username).first()

    def driver(self):
        return models.Driver.query.filter_by(
            company_code=self.scope.company_code, employee_id=self.scope.username
        ).first()

    def _office_query(self, query, office_column):
        if self.scope.office_missing:
            return query.filter(db.false())
        return query.filter(office_column == self.scope.office)

    def ranking_drivers(self):
        query = models.Driver.query.filter(
            models.Driver.company_code == self.scope.company_code,
            models.Driver.safe_start_date.isnot(None),
            models.Driver.safe_start_date != "",
        )
        return (
            self._office_query(query, models.Driver.office)
            .order_by(models.Driver.safe_start_date.asc())
            .limit(10)
            .all()
        )

    def good_count(self):
        return models.PatrolResult.query.filter_by(
            company_code=self.scope.company_code,
            target_type="user",
            target_user_id=self.scope.user_id if self.scope.user_id is not None else -1,
            category="Good",
        ).count()

    def pending_pointouts(self):
        return (
            models.PatrolResult.query.filter_by(
                company_code=self.scope.company_code,
                target_type="user",
                target_user_id=self.scope.user_id if self.scope.user_id is not None else -1,
            )
            .filter(
                models.PatrolResult.category != "Good",
                models.PatrolResult.approval_status != "承認済み",
            )
            .order_by(models.PatrolResult.id.desc())
            .all()
        )

    def inspection_vehicles(self):
        limit = (self.scope.today + timedelta(days=90)).strftime("%Y-%m-%d")
        query = models.Vehicle.query.filter(
            models.Vehicle.company_code == self.scope.company_code,
            models.Vehicle.deleted == False,
            models.Vehicle.inspection_expiry.isnot(None),
            models.Vehicle.inspection_expiry != "",
            models.Vehicle.inspection_expiry <= limit,
        )
        return (
            self._office_query(query, models.Vehicle.office)
            .order_by(models.Vehicle.inspection_expiry.asc())
            .all()
        )

    def missing_master_kinds(self):
        specifications = [
            ("offices", models.Office, {}),
            ("vehicle-types", models.VehicleType, {}),
            ("license-types", models.LicenseType, {}),
            ("delivery-places", models.DeliveryPlace, {}),
            ("vehicles", models.Vehicle, {"deleted": False}),
            ("checklists", models.Checklist, {}),
        ]
        return {
            kind
            for kind, model, filters in specifications
            if model.query.filter_by(company_code=self.scope.company_code, **filters).count() == 0
        }

    def checklists(self):
        return (
            ordered_master_query(models.Checklist, self.scope.company_code)
            .filter(
                models.Checklist.active.is_(True),
                models.Checklist.target.in_(["安全管理", "車両管理"]),
            )
            .all()
        )

    def checklist_results(self, checklist):
        vehicle = checklist.target == "車両管理"
        model = models.VehicleChecklistResult if vehicle else models.ChecklistResult
        query = model.query.filter_by(
            company_code=self.scope.company_code, checklist_id=checklist.id
        ).filter(
            model.checked_date >= self.scope.start_date,
            model.checked_date < self.scope.end_exclusive,
        )
        if self.scope.office_missing:
            query = query.filter(db.false())
        elif vehicle:
            if self._office_vehicle_ids is None:
                self._office_vehicle_ids = [
                    row.id
                    for row in models.Vehicle.query.filter_by(
                        company_code=self.scope.company_code,
                        office=self.scope.office,
                        deleted=False,
                    ).all()
                ]
            query = query.filter(model.vehicle_record_id.in_(self._office_vehicle_ids))
        else:
            query = query.filter(model.target_office == self.scope.office)
        rows = query.all()
        ids = [row.vehicle_record_id if vehicle else row.target_vehicle_record_id for row in rows]
        self.preload_vehicles(ids)
        return rows

    def preload_vehicles(self, ids):
        missing = {ident for ident in ids if ident is not None and ident not in self._vehicles}
        if not missing:
            return
        rows = models.Vehicle.query.filter(
            models.Vehicle.company_code == self.scope.company_code, models.Vehicle.id.in_(missing)
        ).all()
        self._vehicles.update({ident: None for ident in missing})
        self._vehicles.update({row.id: row for row in rows})

    def vehicle(self, ident, *, active_only=False):
        self.preload_vehicles([ident])
        row = self._vehicles.get(ident)
        return None if row is not None and active_only and row.deleted else row

    def assigned_vehicles(self, ids):
        self._assigned_ids = tuple(ids)
        self.preload_vehicles(ids)
        # Keep the existing database ordering of the personal vehicle panel.
        return (
            models.Vehicle.query.filter(
                models.Vehicle.company_code == self.scope.company_code,
                models.Vehicle.deleted == False,
                models.Vehicle.id.in_(ids),
            ).all()
            if ids
            else []
        )

    def personal_vehicle_results(self, checklist_id, vehicle_id):
        if checklist_id not in self._personal_results:
            # This panel follows assigned vehicles, including those in another office.
            rows = (
                models.VehicleChecklistResult.query.filter_by(
                    company_code=self.scope.company_code, checklist_id=checklist_id
                )
                .filter(
                    models.VehicleChecklistResult.vehicle_record_id.in_(self._assigned_ids),
                    models.VehicleChecklistResult.checked_date >= self.scope.start_date,
                    models.VehicleChecklistResult.checked_date < self.scope.end_exclusive,
                )
                .all()
            )
            grouped = {}
            for row in rows:
                grouped.setdefault(row.vehicle_record_id, []).append(row)
            self._personal_results[checklist_id] = grouped
        return self._personal_results[checklist_id].get(vehicle_id, [])
