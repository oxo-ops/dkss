"""Explicit, short-lived reads shared by one vehicle overview build."""


class VehicleReadSnapshot:
    """Read each model once for a single company/vehicle.

    Create a new instance for each overview build. Do not retain it in app
    globals, a session or a worker. Use only while building read-only output;
    create another instance after any writes.
    """

    def __init__(self, company_code, vehicle_record_id):
        if not company_code or not vehicle_record_id:
            raise ValueError("A company and vehicle scope are required.")
        self.company_code = company_code
        self.vehicle_record_id = vehicle_record_id
        self._rows = {}

    def require_scope(self, company_code, vehicle_record_id):
        if (company_code, vehicle_record_id) != (self.company_code, self.vehicle_record_id):
            raise ValueError("Vehicle read scope mismatch.")

    def rows(self, model):
        if model not in self._rows:
            self._rows[model] = tuple(model.query.filter_by(
                company_code=self.company_code,
                vehicle_record_id=self.vehicle_record_id,
            ).all())
        return self._rows[model]
