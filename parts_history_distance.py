"""Compare two recorded replacement meters without inventing chronology."""
from datetime import date
from decimal import Decimal, InvalidOperation


def replacement_interval(previous, current, *, ambiguous_previous=False, ambiguous_current=False):
    if previous is None:
        return None, "前回記録なし"
    try:
        before = date.fromisoformat(previous.replacement_date or "")
        after = date.fromisoformat(current.replacement_date or "")
        if before.isoformat() != previous.replacement_date or after.isoformat() != current.replacement_date:
            raise ValueError()
    except (TypeError, ValueError):
        return None, "交換日未確認のため比較不可"
    if after <= before:
        return None, "交換順序未確認のため比較不可"
    if ambiguous_current:
        return None, "交換時の走行距離が不一致のため比較不可"
    if ambiguous_previous:
        return None, "前回交換時の走行距離が不一致のため比較不可"
    try:
        values = []
        for value in (previous.mileage, current.mileage):
            if value is None or isinstance(value, bool):
                raise ValueError()
            number = Decimal(str(value))
            if not number.is_finite() or number < 0:
                raise ValueError()
            values.append(number)
    except (ValueError, InvalidOperation):
        return None, "走行距離未確認のため比較不可"
    if values[1] < values[0]:
        return None, "走行距離が逆転しているため比較不可"
    return values[1] - values[0], None
