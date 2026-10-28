"""Conservative capacity reservations without assigning meaning to NULL state."""
from .models import Vehicle


def reserved_vehicle_count(company_code):
    # Only an explicitly inactive row frees capacity. NULL is unresolved, not active.
    return Vehicle.query.filter(Vehicle.company_code == company_code,
                                Vehicle.deleted.is_not(True)).count()


UNKNOWN_VEHICLE_STATE = '有効・無効が未確認の車両があります。状態を確認してから操作してください。'
