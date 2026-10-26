"""Display-only formatting; never round stored or calculated mileage."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def format_distance_km(value):
    """Show the nearest whole kilometre, with .5 rounded away from zero."""
    if value is None or value == "" or isinstance(value, bool):
        return "—"
    try:
        distance = Decimal(str(value).replace(",", ""))
        if not distance.is_finite() or abs(distance) > Decimal("99999999999999.99"):
            return "—"
        rounded = distance.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return format(rounded if rounded else Decimal(0), ",.0f")
    except (InvalidOperation, ValueError, TypeError):
        return "—"
