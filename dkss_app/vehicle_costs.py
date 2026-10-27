"""Vehicle Costs responsibilities; routes are registered by the application factory."""
from .maintenance_facts import factual_history
from . import analysis as _dkss_analysis, checklists as _dkss_checklists, common as _dkss_common, models as _dkss_models, vehicle_karte as _dkss_vehicle_karte, vehicle_readers as _dkss_vehicle_readers


def vehicle_karte_costs(vehicle_record_id):
    from flask import abort

    if not _dkss_common.session.get("username"):
        return _dkss_common.redirect(_dkss_common.url_for("login"))

    vehicle = _dkss_models.Vehicle.query.filter_by(
        id=vehicle_record_id,
        company_code=_dkss_common.session.get("company_code"),
    ).first_or_404()

    current_year = _dkss_common.datetime.now(
        _dkss_common.ZoneInfo("Asia/Tokyo")
    ).year
    selected_year = _dkss_common.request.args.get(
        "year", current_year, type=int
    )
    if not 1900 <= selected_year <= current_year + 1:
        abort(400)

    records = _dkss_models.VehicleMaintenanceRecord.query.filter_by(
        company_code=vehicle.company_code,
        vehicle_record_id=vehicle.id,
    ).all()

    details = get_vehicle_maintenance_cost_details(
        records, selected_year
    )
    details["available_years"] = sorted(
        set(details["available_years"]) | {current_year},
        reverse=True,
    )

    number = _dkss_vehicle_readers.vehicle_number({
        "plate_area": vehicle.plate_area or "",
        "plate_class": vehicle.plate_class or "",
        "plate_kana": vehicle.plate_kana or "",
        "plate_number": vehicle.plate_number or "",
    })

    return _dkss_common.render_template(
        "vehicle_karte_costs.html",
        vehicle=vehicle,
        vehicle_number=number,
        open_defects=_dkss_checklists.get_vehicle_open_inspection_defects(
            vehicle.company_code,
            vehicle.id,
        ),
        cost_details=details,
        format_cost_number=_dkss_vehicle_karte.format_vehicle_maintenance_number,
        cost_current_year=current_year,
    )



def get_vehicle_maintenance_cost_details(maintenance_records, selected_year):
    selected_year = int(selected_year)
    if not 2 <= selected_year <= 9999:
        raise ValueError("集計年が不正です。")

    records, _, synthetic_exclusions = factual_history(maintenance_records)
    dated_records = []
    undated_records = []

    for record in records:
        date_text = (
            (record.entry_date or "").strip()
            or (record.completion_date or "").strip()
        )
        try:
            record_date = _dkss_common.datetime.strptime(
                date_text, "%Y-%m-%d"
            ).date()
        except ValueError:
            undated_records.append(record)
            continue

        dated_records.append((record_date, record))

    def summarize(items):
        return get_vehicle_maintenance_cost_summary(items)

    def year_records(year):
        return [
            record for record_date, record in dated_records
            if record_date.year == year
        ]

    selected_records = year_records(selected_year)
    previous_records = year_records(selected_year - 1)
    selected_summary = summarize(selected_records)
    previous_summary = summarize(previous_records)

    selected_total = selected_summary["total_cost"]
    previous_total = previous_summary["total_cost"]

    change_amount = None
    change_percentage = None
    if selected_total is not None and previous_total is not None:
        change_amount = selected_total - previous_total
        if previous_total > 0:
            change_percentage = (
                change_amount / previous_total * _dkss_common.Decimal("100")
            )

    monthly_costs = []
    for month in range(1, 13):
        items = [
            record for record_date, record in dated_records
            if record_date.year == selected_year
            and record_date.month == month
        ]
        monthly_costs.append({
            "month": month,
            "amount": summarize(items)["total_cost"],
            "record_count": len(items),
            "missing_amount_count": sum(
                record.total_cost is None for record in items
            ),
        })

    yearly_costs = []
    for year in range(max(1, selected_year - 2), selected_year + 1):
        items = year_records(year)
        yearly_costs.append({
            "year": year,
            "amount": summarize(items)["total_cost"],
            "record_count": len(items),
            "missing_amount_count": sum(
                record.total_cost is None for record in items
            ),
        })

    selected_dated = [
        (record_date, record)
        for record_date, record in dated_records
        if record_date.year == selected_year
    ]

    high_cost_records = [
        record
        for record_date, record in sorted(
            selected_dated,
            key=lambda item: (
                item[1].total_cost
                if item[1].total_cost is not None
                else _dkss_common.Decimal("0"),
                item[0],
                item[1].id,
            ),
            reverse=True,
        )
        if record.total_cost is not None
    ][:5]

    recent_records = [
        record
        for record_date, record in sorted(
            selected_dated,
            key=lambda item: (item[0], item[1].id),
            reverse=True,
        )
    ][:5]

    today = _dkss_common.datetime.now(_dkss_common.ZoneInfo("Asia/Tokyo")).date()
    average_end = today.replace(day=1)
    average_start = average_end.replace(year=average_end.year - 1)
    rolling_records = [
        record for record_date, record in dated_records
        if average_start <= record_date < average_end
    ]
    rolling_total = summarize(rolling_records)["total_cost"]
    rolling_average = (
        rolling_total / _dkss_common.Decimal("12")
        if rolling_total is not None else None
    )

    return {
        "source_exclusions": synthetic_exclusions,
        "rolling_average": rolling_average,
        "average_start": average_start.isoformat(),
        "average_end_exclusive": average_end.isoformat(),
        "average_last_month": _dkss_common.datetime.fromordinal(
            average_end.toordinal() - 1
        ).strftime("%Y/%m"),
        "rolling_missing_amount_count": sum(
            record.total_cost is None for record in rolling_records
        ),
        "selected_year": selected_year,
        "all_time_summary": summarize(records),
        "selected_summary": selected_summary,
        "previous_total": previous_total,
        "change_amount": change_amount,
        "change_percentage": change_percentage,
        "monthly_costs": monthly_costs,
        "yearly_costs": yearly_costs,
        "high_cost_records": high_cost_records,
        "recent_records": recent_records,
        "selected_record_count": len(selected_records),
        "missing_amount_count": sum(
            record.total_cost is None for record in selected_records
        ),
        "undated_record_count": len(undated_records),
        "available_years": sorted({
            record_date.year for record_date, record in dated_records
        } | {selected_year}, reverse=True),
    }



def get_vehicle_maintenance_cost_summary(maintenance_records):
    maintenance_records, _, synthetic_exclusions = _dkss_analysis.filter_vehicle_maintenance_factual_history(maintenance_records)
    maintenance_summary = {"total_cost": None, "annual_costs": [], "source_exclusions": synthetic_exclusions}
    costs = [
        record.total_cost
        for record in maintenance_records
        if record.total_cost is not None
    ]
    if costs:
        maintenance_summary["total_cost"] = sum(
            costs, _dkss_common.Decimal("0")
        )

    current_year = _dkss_common.datetime.now(_dkss_common.ZoneInfo("Asia/Tokyo")).year
    annual_totals = {}
    annual_counts = {}

    for record in maintenance_records:
        if record.total_cost is None:
            continue

        date_text = (
            (record.entry_date or "").strip()
            or (record.completion_date or "").strip()
        )
        try:
            record_date = _dkss_common.datetime.strptime(
                date_text, "%Y-%m-%d"
            ).date()
        except ValueError:
            continue

        year = record_date.year
        if current_year - 4 <= year <= current_year:
            annual_totals[year] = (
                annual_totals.get(year, _dkss_common.Decimal("0"))
                + record.total_cost
            )
            annual_counts[year] = annual_counts.get(year, 0) + 1

    maintenance_summary["annual_costs"] = [
        {
            "year": year,
            "amount": (
                str(annual_totals[year])
                if year in annual_totals else None
            ),
            "count": annual_counts.get(year, 0),
        }
        for year in range(current_year - 4, current_year + 1)
    ]

    category_totals = {}
    for record in maintenance_records:
        if record.total_cost is None:
            continue
        category = (record.category or "").strip() or "未分類"
        category_totals[category] = (
            category_totals.get(category, _dkss_common.Decimal("0"))
            + record.total_cost
        )

    category_total = sum(category_totals.values(), _dkss_common.Decimal("0"))
    show_cost_ring = (
        category_total > 0
        and all(amount >= 0 for amount in category_totals.values())
    )
    category_colors = (
        "#397dea", "#72adef", "#49bda9",
        "#e8b64b", "#9982ce", "#94a3b8",
    )
    maintenance_summary["show_cost_ring"] = show_cost_ring
    maintenance_summary["category_costs"] = [
        {
            "label": category,
            "amount": amount,
            "percentage": (
                amount / category_total * _dkss_common.Decimal("100")
                if show_cost_ring else None
            ),
            "color": category_colors[index % len(category_colors)],
        }
        for index, (category, amount) in enumerate(sorted(
            category_totals.items(),
            key=lambda item: (-item[1], item[0]),
        ))
    ]

    return maintenance_summary



def get_vehicle_periodic_inspection_summary(company_code, vehicle_record_id):
    """Last performed inspection and explicitly recorded next date, per type."""
    def parsed(value):
        try:
            return _dkss_common.datetime.strptime(str(value or ""), "%Y-%m-%d").date()
        except ValueError:
            return None

    today = _dkss_common.datetime.now(_dkss_common.ZoneInfo("Asia/Tokyo")).date()
    latest = {}
    for record in _dkss_models.VehiclePeriodicInspectionRecord.query.filter_by(
        company_code=company_code, vehicle_record_id=vehicle_record_id
    ).all():
        performed = parsed(record.inspection_date)
        if record.inspection_type not in {"3month", "12month"} or performed is None or performed > today:
            continue
        previous = latest.get(record.inspection_type)
        if previous is None or (performed, record.id) > previous[:2]:
            latest[record.inspection_type] = (performed, record.id, record)
    result = {}
    for kind, (performed, _, record) in latest.items():
        due = parsed(record.next_inspection_date)
        result[kind] = {
            "record_id": record.id, "last_date": performed.isoformat(),
            "mileage": record.mileage,
            "next_date": due.isoformat() if due and due >= performed else None,
        }
    return result



def get_vehicle_overview_cost_summary(maintenance_records):
    """Overview financial components; keep shared cost/year/category summaries intact."""
    maintenance_records = list(maintenance_records)
    summary = dict(get_vehicle_maintenance_cost_summary(maintenance_records))
    factual, _, _ = _dkss_analysis.filter_vehicle_maintenance_factual_history(maintenance_records)
    fields = (
        ("labor_cost", "工賃", "#7863d7"),
        ("parts_cost", "部品代", "#43988e"),
        ("other_cost", "その他費用", "#478cbf"),
        ("tax_amount", "消費税", "#a0802e"),
    )
    amounts = {field: _dkss_common.Decimal("0") for field, _, _ in fields}
    present = set()
    residual = _dkss_common.Decimal("0")
    for record in factual:
        if record.total_cost is None:
            continue
        known = _dkss_common.Decimal("0")
        for field, _, _ in fields:
            value = getattr(record, field, None)
            if value is not None:
                amount = _dkss_common.Decimal(str(value))
                amounts[field] += amount
                known += amount
                present.add(field)
        residual += _dkss_common.Decimal(str(record.total_cost)) - known
    rows = [
        {"label": label, "amount": amounts[field], "color": color}
        for field, label, color in fields if field in present
    ]
    if residual:
        rows.append({
            "label": "内訳未確定" if residual > 0 else "内訳差額",
            "amount": residual, "color": "#94a3b8",
        })
    total = summary.get("total_cost")
    if total is not None and sum((row["amount"] for row in rows), _dkss_common.Decimal("0")) != total:
        raise ValueError("OVERVIEW_COST_COMPONENT_TOTAL_MISMATCH")
    show_ring = total is not None and total > 0 and all(row["amount"] >= 0 for row in rows)
    for row in rows:
        row["percentage"] = row["amount"] / total * _dkss_common.Decimal("100") if show_ring else None
    summary["category_costs"] = rows
    summary["show_cost_ring"] = show_ring
    return summary
