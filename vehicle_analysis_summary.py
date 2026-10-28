"""Vehicle fact aggregation without database queries or Flask state.

Rows are supplied by the caller. Explicit source exclusion policies and the
Japan-local clock are injected so the same calculations can run independently.
"""
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from vehicle_analysis_dates import maintenance_cost_date, parse_record_date


class VehicleAnalysisSummaryService:
    def __init__(self, *, filter_factual_history, periodic_synthetic_evidence, today):
        self.filter_factual_history = filter_factual_history
        self.periodic_synthetic_evidence = periodic_synthetic_evidence
        self.today = today

    def mileage_reference(
        self,
        maintenance_records, operation_records, as_of,
        periodic_records=(), include_points=False,
    ):
        """記録距離と出典を選ぶ。現在の実測値とは断定しない。"""
        from decimal import Decimal, InvalidOperation

        def day(value):
            return parse_record_date(value, normalize=True)

        today = self.today()
        requested = day(as_of)
        if requested is None:
            raise ValueError("走行距離の基準日が不正です。")
        limit = min(requested, today)

        readings = []
        excluded = {
            "invalid_value": 0,
            "unknown_date": 0,
            "future_date": 0,
            "after_as_of": 0,
        }

        def add(value, date_value, source_id, source, date_basis, time=""):
            if value is None or str(value).strip() == "":
                return
            try:
                if isinstance(value, bool):
                    raise ValueError()
                number = Decimal(str(value))
                if not number.is_finite() or number < 0:
                    raise ValueError()
            except (InvalidOperation, ValueError, TypeError):
                excluded["invalid_value"] += 1
                return

            recorded = day(date_value)
            if recorded is None:
                excluded["unknown_date"] += 1
                return
            if recorded > today:
                excluded["future_date"] += 1
                return
            if recorded > limit:
                excluded["after_as_of"] += 1
                return

            readings.append({
                "value": number,
                "date": recorded.isoformat(),
                "time": str(time or "").strip(),
                "source_id": source_id,
                "source": source,
                "date_basis": date_basis,
            })

        for row in operation_records:
            add(
                row.arrival_meter,
                row.operation_date,
                f"operation:{row.id}",
                "運行実績",
                "operation_date",
                row.arrival_at,
            )

        maintenance_records, _, synthetic_exclusions = self.filter_factual_history(maintenance_records)
        excluded["explicit_synthetic_document"] = len(synthetic_exclusions)
        for row in maintenance_records:
            entry = str(row.entry_date or "").strip()
            add(
                row.mileage,
                entry or row.completion_date,
                f"maintenance:{row.id}",
                "整備・修理記録",
                "entry_date" if entry else "completion_date",
            )

        for row in periodic_records:
            if self.periodic_synthetic_evidence(row):
                excluded["explicit_synthetic_document"] += 1
                continue
            add(
                row.mileage,
                row.inspection_date,
                f"periodic:{row.id}",
                "定期点検記録",
                "inspection_date",
            )

        by_date = {}
        for reading in readings:
            by_date.setdefault(reading["date"], []).append(reading)

        daily = []
        conflicts = []
        decreases = []
        previous = None

        for recorded, rows in sorted(by_date.items()):
            operations = [
                row for row in rows if row["source"] == "運行実績"
            ]
            others = [
                row for row in rows if row["source"] != "運行実績"
            ]

            timed_operations = []
            for row in operations:
                try:
                    timestamp = datetime.fromisoformat(row["time"])
                except ValueError:
                    break
                if timestamp.tzinfo is not None:
                    timestamp = timestamp.astimezone(
                        ZoneInfo("Asia/Tokyo")
                    )
                if timestamp.date().isoformat() != recorded:
                    break
                timed_operations.append((
                    timestamp.replace(tzinfo=None), row,
                ))

            if operations and len(timed_operations) == len(operations):
                timed_operations.sort(key=lambda item: item[0])
                previous_values = (
                    {previous} if previous is not None else None
                )
                for timestamp in sorted({
                    item[0] for item in timed_operations
                }):
                    values_at_time = {
                        row["value"]
                        for time_value, row in timed_operations
                        if time_value == timestamp
                    }
                    if len(values_at_time) != 1:
                        if recorded not in conflicts:
                            conflicts.append(recorded)
                    if (
                        previous_values is not None
                        and min(values_at_time) < max(previous_values)
                        and recorded not in decreases
                    ):
                        decreases.append(recorded)
                    previous_values = values_at_time

                latest_time = timed_operations[-1][0]
                operations = [
                    row for timestamp, row in timed_operations
                    if timestamp == latest_time
                ]

            candidates = operations + others
            values = {row["value"] for row in candidates}
            if len(values) != 1:
                conflicts.append(recorded)
                daily.append({
                    "date": recorded,
                    "value": None,
                    "sources": candidates,
                })
                continue

            value = next(iter(values))
            if previous is not None and value < previous:
                decreases.append(recorded)
            previous = value
            daily.append({
                "date": recorded,
                "value": value,
                "sources": candidates,
            })

        latest = daily[-1] if daily else None
        status = (
            "unknown" if latest is None
            else "conflicting" if latest["value"] is None
            else "recorded"
        )
        result = {
            "as_of": limit.isoformat(),
            "status": status,
            "value": latest["value"] if latest else None,
            "date": latest["date"] if latest else None,
            "sources": latest["sources"] if latest else [],
            "conflict_dates": conflicts,
            "decrease_dates": decreases,
            "distance_usable": (
                status == "recorded"
                and not conflicts
                and not decreases
                and all(
                    row["date_basis"] == "operation_date"
                    for row in latest["sources"]
                )
            ),
            "excluded": excluded,
            "note": (
                "最後に登録された距離であり、現在の実測値ではありません。"
                "整備の入庫日・完了日は距離の計測日とは限りません。"
                "距離の減少だけでメーター交換や入力誤りを確定しません。"
            ),
        }
        if include_points:
            result["points"] = [
                {"date": row["date"], "mileage": float(row["value"]) if row["value"] is not None else None}
                for row in daily
            ]
        return result


    def summarize(
        self,
        maintenance_records, operation_records, part_records,
        defect_records, start_date, end_date,
        periodic_records=(),
    ):
        from collections import Counter

        parse_date = parse_record_date

        start = parse_date(start_date)
        end = parse_date(end_date)
        if start is None or end is None or start > end:
            raise ValueError("分析期間が不正です。")

        def in_period(value):
            day = parse_date(value)
            return day is not None and start <= day <= end

        maintenance, factual_parts, synthetic_exclusions = self.filter_factual_history(maintenance_records, part_records)
        periodic_records = list(periodic_records)
        synthetic_exclusions.extend(evidence for row in periodic_records if (evidence := self.periodic_synthetic_evidence(row)))
        periodic_records = [row for row in periodic_records if not self.periodic_synthetic_evidence(row)]
        operations = list(operation_records)
        parts = factual_parts
        defects = list(defect_records)

        selected_maintenance = [
            row for row in maintenance
            if (day := maintenance_cost_date(row)) is not None
            and start <= day <= end
        ]
        selected_operations = [
            row for row in operations
            if in_period(row.operation_date)
        ]
        selected_parts = [
            row for row in parts
            if in_period(row.replacement_date)
        ]
        failures = [
            row for row in defects
            if row.category == "故障"
            and in_period(row.occurred_date)
        ]

        def known_total(rows, field):
            values = [getattr(row, field) for row in rows]
            known = [
                Decimal(str(value))
                for value in values if value is not None
            ]
            return sum(known, Decimal("0")) if known else None

        monthly = {}
        month_count = (
            (end.year - start.year) * 12
            + end.month - start.month + 1
        )
        for offset in range(month_count):
            year, month = divmod(
                start.year * 12 + start.month - 1 + offset,
                12,
            )
            key = f"{year:04d}-{month + 1:02d}"
            monthly[key] = {
                "month": key,
                "cost": None,
                "distance": None,
                "failures": 0,
            }

        for rows, field, date_field, result_field in (
            (
                selected_maintenance,
                "total_cost", "entry_date", "cost",
            ),
            (
                selected_operations,
                "distance", "operation_date", "distance",
            ),
        ):
            for row in rows:
                day = maintenance_cost_date(row) if date_field == "entry_date" else parse_date(
                    getattr(row, date_field)
                    or getattr(row, "completion_date", None)
                )
                value = getattr(row, field)
                if value is not None:
                    bucket = monthly[day.strftime("%Y-%m")]
                    bucket[result_field] = (
                        bucket[result_field] or Decimal("0")
                    ) + Decimal(str(value))

        for row in failures:
            key = parse_date(
                row.occurred_date
            ).strftime("%Y-%m")
            monthly[key]["failures"] += 1

        cost = known_total(selected_maintenance, "total_cost")
        distance = known_total(selected_operations, "distance")
        missing_cost = sum(
            row.total_cost is None
            for row in selected_maintenance
        )
        missing_distance = sum(
            row.distance is None
            for row in selected_operations
        )

        # Compare only matched months of registered facts. Missing months are not zero.
        cost_months = {key for key, bucket in monthly.items() if bucket["cost"] is not None}
        distance_months = {key for key, bucket in monthly.items() if bucket["distance"] is not None}
        cost_per_km_status = (
            "missing_values" if cost is None or distance is None or distance <= 0
            else "incomplete_values" if missing_cost or missing_distance
            else "record_months_do_not_match" if cost_months != distance_months
            else "matched_record_months"
        )

        mileage_reference = self.mileage_reference(
            maintenance,
            operations,
            end.isoformat(),
            periodic_records=periodic_records,
        )

        mileage_reference["excluded"]["explicit_synthetic_document"] += len(synthetic_exclusions)

        category_costs = {}
        for row in selected_maintenance:
            if row.total_cost is not None:
                category = (
                    row.category or ""
                ).strip() or "未分類"
                category_costs[category] = (
                    category_costs.get(category, Decimal("0"))
                    + Decimal(str(row.total_cost))
                )

        return {
            "source_exclusions": synthetic_exclusions,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "total_cost": cost,
            "all_time_cost": known_total(
                maintenance, "total_cost"
            ),
            "distance": distance,
            "mileage_reference": mileage_reference,
            "current_mileage": (
                mileage_reference["value"]
                if mileage_reference["distance_usable"] else None
            ),
            "current_mileage_date": (
                mileage_reference["date"]
                if mileage_reference["distance_usable"] else None
            ),
            "cost_per_km": (
                cost / distance
                if cost is not None
                and distance is not None
                and distance > 0
                and not missing_cost
                and not missing_distance
                and cost_per_km_status == "matched_record_months"
                else None
            ),
            "cost_per_km_status": cost_per_km_status,
            "cost_per_km_note": (
                "費用と走行距離の記録月が異なるため算出保留。"
                if cost_per_km_status == "record_months_do_not_match"
                else "費用・距離が揃う登録月の比率。期間全体の記録の完全性は未確認。"
                if cost_per_km_status == "matched_record_months"
                else "費用または走行距離の記録が不足するため算出保留。"
            ),
            "maintenance_count": len(selected_maintenance),
            "failure_count": len(failures),
            "part_replacement_count": len({
                (
                    row.maintenance_record_id,
                    row.part_name,
                    row.part_number or "",
                )
                for row in selected_parts
            }),
            "missing_cost_count": missing_cost,
            "missing_distance_count": missing_distance,
            "undated_maintenance_count": sum(
                maintenance_cost_date(row) is None
                for row in maintenance
            ),
            "monthly": list(monthly.values()),
            "category_costs": sorted(
                category_costs.items(),
                key=lambda item: (-item[1], item[0]),
            ),
            "repeated_failure_contents": Counter(
                (row.content or "内容未登録").strip()
                or "内容未登録"
                for row in failures
            ).most_common(5),
        }
