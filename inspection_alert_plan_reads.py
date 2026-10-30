"""Bounded, transaction-local hints for inspection alert plan predicates.

Missing entries always use the caller's original query. Limits are optimization
limits, never business limits: overfull batches are not used at all.
"""
from collections import defaultdict


class PlanReadHints:
    VEHICLES_PER_BATCH = 100
    ROWS_PER_BATCH = 200
    MAX_KEYS = 2000

    def __init__(self, db, Plan, identities, company, pairs):
        self.session = db.session()
        self.company = company
        self.valid = True
        self.flags = {}
        self.queries = 0
        self.peak_rows = 0
        grouped = defaultdict(set)
        selected = set()
        for pair in pairs:
            selected.add(pair)
            if len(selected) >= self.MAX_KEYS:
                break
        for vehicle, month in sorted(selected):
            grouped[month].add(vehicle)
        for month, vehicles in grouped.items():
            vehicles = sorted(vehicles)
            for offset in range(0, len(vehicles), self.VEHICLES_PER_BATCH):
                batch = vehicles[offset:offset + self.VEHICLES_PER_BATCH]
                rows = Plan.query.filter(
                    Plan.company_code == company,
                    Plan.vehicle_record_id.in_(batch),
                    Plan.kind.in_(['vehicle_inspection', '12month']),
                    Plan.status.in_(['planned', 'completed']),
                    db.or_(Plan.period_key == month, Plan.planned_month == month),
                ).order_by(Plan.id).limit(self.ROWS_PER_BATCH + 1).all()
                self.queries += 1
                self.peak_rows = max(self.peak_rows, len(rows))
                if len(rows) > self.ROWS_PER_BATCH:
                    continue  # No negative or partial answer from truncated history.
                flags = {vehicle: [False, False] for vehicle in batch}
                for plan in rows:
                    kind = identities.plan_kind(plan)
                    flags[plan.vehicle_record_id][0] |= kind == 'vehicle_inspection'
                    flags[plan.vehicle_record_id][1] |= (
                        plan.kind == '12month' and kind == 'annual_unconfirmed')
                self.flags.update({(vehicle, month): tuple(value)
                                   for vehicle, value in flags.items()})

    def get(self, company, vehicle, month):
        if not self.valid or company != self.company:
            return None
        return self.flags.get((vehicle, month))
