"""Read-only UI projections of saved comparison and replacement facts.

No new cost aggregation, peer selection, AI input, database writes or thresholds.
"""
from decimal import Decimal, InvalidOperation

from vehicle_analysis_dates import parse_record_date


def finite_number(value, *, nonnegative=False):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not number.is_finite() or (nonnegative and number < 0):
        return None
    return number


def cost_comparison(summary, comparison):
    """Reuse the existing ratio and arithmetic peer mean, including known zero."""
    metric = next((row for row in comparison.get("metrics", [])
                   if row.get("unit") == "円/km"), {})
    current = finite_number(summary.get("cost_per_km"))
    average = finite_number(metric.get("average"))
    rows = [dict(key="current", label="この車両", value=current),
            dict(key="average", label="他車平均", value=average)]
    known = [row["value"] for row in rows if row["value"] is not None]
    low, high = min([Decimal(0)] + known), max([Decimal(0)] + known)
    span = high - low
    zero = -low / span * 100 if span else Decimal(0)
    for row in rows:
        value = row["value"]
        row["left"] = float((min(value, Decimal(0)) - low) / span * 100) if value is not None and span else 0
        row["width"] = float(abs(value) / span * 100) if value is not None and span else 0
    return dict(rows=rows, zero=float(zero), has_negative=low < 0,
                sample_count=metric.get("sample_count", 0 if comparison.get("vehicle_count") is not None else None),
                numerator=finite_number(summary.get("total_cost")),
                denominator=finite_number(summary.get("distance"), nonnegative=True),
                note=summary.get("cost_per_km_note", "費用または走行距離の記録が不足するため算出保留。"))


def replacement_distance(part, parent, reference, *, ambiguous_mileage=False):
    """Subtract only usable, dated same-vehicle odometer facts.

The caller fences parent/child/reference by company and vehicle. Invoice facts
use the model's existing is_invoice_actual contract, not a work-status guess.
"""
    reference = reference or {}
    replaced = parse_record_date(part.replacement_date)
    measured = parse_record_date(reference.get("date"))
    as_of = parse_record_date(reference.get("as_of"))
    completion = parse_record_date(parent.completion_date)
    current = finite_number(reference.get("value"), nonnegative=True)
    mileage = finite_number(part.mileage, nonnegative=True)
    reason = None
    if not (getattr(parent, "is_invoice_actual", False)
            or parent.status == "完了" or completion is not None):
        reason = "交換の実施未確認"
    elif replaced is None or as_of is None or replaced > as_of or (completion and completion > as_of):
        reason = "基準日までの交換を確認できません"
    elif ambiguous_mileage:
        reason = "同日の交換時距離が不一致"
    elif mileage is None:
        reason = "交換時距離が未取得・不正"
    elif reference.get("conflict_dates"):
        reason = "記録距離が不一致"
    elif reference.get("decrease_dates"):
        reason = "記録距離の逆転あり"
    elif current is None or measured is None:
        reason = "基準の記録距離が未取得・不正"
    elif measured < replaced:
        reason = "距離の記録日が交換前"
    elif measured > as_of:
        reason = "距離の記録日が基準日後"
    elif current < mileage:
        reason = "交換時距離より小さいため保留"
    elif reference.get("distance_usable") is not True:
        reason = "距離の計測根拠を確認要"
    return dict(distance_since=None if reason else current - mileage,
                distance_note=reason, mileage=mileage)
