"""Evaluate adopted inspection/replacement criteria against recorded evidence.

Both policies share strict value parsing and calendar arithmetic. Evidence matching
stays separate: inspection of an assembly does not establish component replacement.
"""
import calendar
import re
import unicodedata
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from . import common as _dkss_common


class AdoptedMaintenanceTimingService:
    def __init__(self, *, procedure_matches, related_assembly_history):
        self.procedure_matches = procedure_matches
        self.related_assembly_history = related_assembly_history

    @staticmethod
    def day(value):
        if not isinstance(value, str) or len(value) != 10:
            return None
        try:
            parsed = _dkss_common.datetime.strptime(value, "%Y-%m-%d").date()
            return parsed if parsed.isoformat() == value else None
        except ValueError:
            return None

    @staticmethod
    def number(value):
        if type(value) not in {int, float, Decimal}:
            return None
        try:
            parsed = Decimal(str(value))
            return parsed if parsed.is_finite() and parsed >= 0 else None
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def normalize_name(value):
        text = unicodedata.normalize(
            "NFKC", str(value or ""),
        ).casefold()
        return re.sub(r"[\s・･]+", "", text).replace(
            "フィルター", "フィルタ",
        )

    def inspection(
        self, rule, part_name, preventive_facts, summary,
    ):
        """採用済み点検基準を、原本と項目の実施を確認できた点検実績へ照合する。"""

        criteria_results = []
        source_ids = []
        related_assembly_history = []

        def result(status, reason):
            if status == "held":
                criteria_results.clear()
            return {
                "status": status,
                "reason": reason,
                "scope": "registered_inspection_and_reading_dates",
                "calculation_permitted": any(
                    item.get("calculation_permitted") is True
                    for item in criteria_results
                ),
                "criteria": criteria_results,
                "related_assembly_replacements": related_assembly_history,
                "source_ids": list(dict.fromkeys(source_ids)),
            }

        if (
            not isinstance(rule, dict)
            or not isinstance(preventive_facts, dict)
            or not isinstance(summary, dict)
        ):
            return result("held", "invalid_input")

        adoption = rule.get("analysis_adoption") or {}
        if adoption.get("status") != "adopted_for_analysis":
            return result("held", "rule_not_adopted")
        if rule.get("action") != "inspect":
            return result("held", "rule_not_inspection")
        if rule.get("cycle") not in {"repeat", "all"}:
            return result("held", "initial_baseline_not_available")

        criteria = rule.get("criteria")
        relation = rule.get("relation")
        if (
            not isinstance(criteria, list)
            or not 1 <= len(criteria) <= 4
            or (
                relation != "single" if len(criteria) == 1
                else relation not in {"any", "all"}
            )
        ):
            return result("held", "invalid_criteria_relation")

        as_of = self.day(summary.get("end_date"))
        if (
            as_of is None
            or as_of > _dkss_common.datetime.now(_dkss_common.ZoneInfo("Asia/Tokyo")).date()
            or preventive_facts.get("as_of") != as_of.isoformat()
        ):
            return result("held", "invalid_reference_date")

        name = self.normalize_name(part_name)
        facts = preventive_facts.get("inspection_items")
        if not name or not isinstance(facts, list):
            return result("held", "inspection_baseline_not_available")
        matches = [
            fact for fact in facts
            if isinstance(fact, dict)
            and self.procedure_matches(rule, part_name, fact)
        ]
        if not matches:
            return result("held", "inspection_procedure_not_matched" if facts else "inspection_baseline_not_available")
        if any(fact.get("inspection_date_usable") is not True or self.day(fact.get("inspection_date")) is None for fact in matches):
            return result("held", "inspection_date_not_confirmed")
        latest = max(self.day(fact["inspection_date"]) for fact in matches)
        matches = [fact for fact in matches if self.day(fact["inspection_date"]) == latest]
        if len(matches) != 1:
            return result("held", "inspection_baseline_not_uniquely_matched")

        fact = matches[0]
        inspected_on = self.day(fact.get("inspection_date"))
        if (
            fact.get("inspection_date_usable") is not True
            or inspected_on is None
            or inspected_on > as_of
        ):
            return result("held", "inspection_date_not_confirmed")

        ids = fact.get("source_ids")
        if (
            not isinstance(ids, list)
            or not ids
            or any(
                not isinstance(value, str) or not value.startswith("periodic:")
                for value in ids
            )
        ):
            return result("held", "inspection_evidence_missing")
        source_ids.extend(ids)
        for name in ("knowledge_source_id", "vehicle_source_id"):
            value = adoption.get(name)
            if not isinstance(value, str) or not value:
                return result("held", "adoption_evidence_missing")
            source_ids.append(value)

        seen = set()
        for criterion in criteria:
            if not isinstance(criterion, dict):
                return result("held", "invalid_criterion")
            metric = criterion.get("metric")
            threshold = self.number(criterion.get("value"))
            if (
                not isinstance(metric, str)
                or metric not in {
                    "distance_km", "period_days",
                    "period_months", "engine_hours",
                }
                or metric in seen
                or threshold is None
                or threshold <= 0
            ):
                return result("held", "invalid_criterion")
            seen.add(metric)
            criteria_results.append(self.evaluate_criterion(
                criterion, metric, threshold, fact, inspected_on, summary, as_of,
                "inspection",
            ))

        statuses = [item["status"] for item in criteria_results]
        if relation in {"single", "any"} and "reached" in statuses:
            return result("threshold_reached", "recorded_threshold_reached")
        if relation == "all" and all(value == "reached" for value in statuses):
            return result("threshold_reached", "all_recorded_thresholds_reached")
        if "unknown" in statuses:
            return result("unknown", "some_criteria_not_calculable")
        return result(
            "not_reached_at_reference_dates",
            "threshold_not_reached_at_recorded_reference_dates",
        )


    def replacement(
        self, rule, part_name, preventive_facts, summary,
    ):
        """採用済み交換基準を実績と照合する。故障予測・整備要否は判定しない。"""

        criteria_results = []
        source_ids = []
        related_assembly_history = []

        def result(status, reason):
            if status == "held":
                criteria_results.clear()
            return {
                "status": status,
                "reason": reason,
                "scope": "registered_replacement_and_reading_dates",
                "calculation_permitted": any(
                    item.get("calculation_permitted") is True
                    for item in criteria_results
                ),
                "criteria": criteria_results,
                "related_assembly_replacements": related_assembly_history,
                "source_ids": list(dict.fromkeys(source_ids)),
            }

        if (
            not isinstance(rule, dict)
            or not isinstance(preventive_facts, dict)
            or not isinstance(summary, dict)
        ):
            return result("held", "invalid_input")

        adoption = rule.get("analysis_adoption") or {}
        if adoption.get("status") != "adopted_for_analysis":
            return result("held", "rule_not_adopted")
        def related_history():
            values = self.related_assembly_history(part_name, preventive_facts)
            for value in values:
                source_ids.extend(value["source_ids"])
            if values:
                for key in ("knowledge_source_id", "vehicle_source_id"):
                    value = adoption.get(key)
                    if isinstance(value, str) and value:
                        source_ids.append(value)
            return values

        if rule.get("action") == "inspect":
            timing = self.inspection(rule, part_name, preventive_facts, summary)
            if timing.get("status") == "held":
                timing["related_assembly_replacements"] = related_history()
                timing["source_ids"] = list(dict.fromkeys(timing.get("source_ids", []) + source_ids))
            return timing
        if rule.get("action") != "replace":
            return result("held", "unsupported_action")
        if rule.get("cycle") not in {"repeat", "all"}:
            return result("held", "initial_baseline_not_available")

        criteria = rule.get("criteria")
        relation = rule.get("relation")
        if (
            not isinstance(criteria, list)
            or not 1 <= len(criteria) <= 4
            or (
                relation != "single" if len(criteria) == 1
                else relation not in {"any", "all"}
            )
        ):
            return result("held", "invalid_criteria_relation")

        as_of = self.day(summary.get("end_date"))
        if (
            as_of is None
            or as_of > _dkss_common.datetime.now(_dkss_common.ZoneInfo("Asia/Tokyo")).date()
            or preventive_facts.get("as_of") != as_of.isoformat()
        ):
            return result("held", "invalid_reference_date")

        name = self.normalize_name(part_name)
        facts = preventive_facts.get("part_replacements")
        if not name or not isinstance(facts, list):
            return result("held", "part_history_not_matched")
        matches = [
            fact for fact in facts
            if isinstance(fact, dict)
            and self.normalize_name(fact.get("part_name")) == name
        ]
        if not matches:
            related_assembly_history = related_history()
            return result("held", "related_assembly_component_scope_unconfirmed" if related_assembly_history else "part_history_not_matched")
        if len(matches) != 1:
            return result("held", "part_history_not_uniquely_matched")

        fact = matches[0]
        replaced_on = self.day(fact.get("latest_dated_replacement"))
        if (
            fact.get("replacement_date_usable") is not True
            or replaced_on is None
            or replaced_on > as_of
        ):
            return result("held", "replacement_date_not_confirmed")

        ids = fact.get("source_ids")
        if (
            not isinstance(ids, list)
            or not ids
            or any(
                not isinstance(value, str) or not value.startswith("part:")
                for value in ids
            )
        ):
            return result("held", "replacement_evidence_missing")
        source_ids.extend(ids)
        for name in ("knowledge_source_id", "vehicle_source_id"):
            value = adoption.get(name)
            if not isinstance(value, str) or not value:
                return result("held", "adoption_evidence_missing")
            source_ids.append(value)

        seen = set()
        for criterion in criteria:
            if not isinstance(criterion, dict):
                return result("held", "invalid_criterion")
            metric = criterion.get("metric")
            threshold = self.number(criterion.get("value"))
            if (
                not isinstance(metric, str)
                or metric not in {
                    "distance_km", "period_days",
                    "period_months", "engine_hours",
                }
                or metric in seen
                or threshold is None
                or threshold <= 0
            ):
                return result("held", "invalid_criterion")
            seen.add(metric)
            criteria_results.append(self.evaluate_criterion(
                criterion, metric, threshold, fact, replaced_on, summary, as_of,
                "replacement",
            ))

        statuses = [item["status"] for item in criteria_results]
        if relation in {"single", "any"} and "reached" in statuses:
            return result("threshold_reached", "recorded_threshold_reached")
        if relation == "all" and all(value == "reached" for value in statuses):
            return result("threshold_reached", "all_recorded_thresholds_reached")
        if "unknown" in statuses:
            return result("unknown", "some_criteria_not_calculable")
        return result(
            "not_reached_at_reference_dates",
            "threshold_not_reached_at_recorded_reference_dates",
        )

    def evaluate_criterion(self, criterion, metric, threshold, fact,
                           baseline_date, summary, as_of, kind):
        entry = {
            "metric": metric,
            "threshold": criterion["value"],
            "baseline_date": baseline_date.isoformat(),
            "status": "unknown",
            "calculation_permitted": False,
        }

        if metric == "distance_km":
            measured_on = self.day(summary.get("current_mileage_date"))
            reference = summary.get("mileage_reference") or {}
            current = self.number(summary.get("current_mileage"))
            baseline_meter = self.number(fact.get(f"{kind}_mileage"))
            recorded_distance = self.number(fact.get("distance_since_km"))
            if (
                fact.get(f"{kind}_mileage_usable") is True
                and reference.get("distance_usable") is True
                and current is not None
                and baseline_meter is not None
                and current >= baseline_meter
                and measured_on is not None
                and baseline_date <= measured_on <= as_of
                and recorded_distance == current - baseline_meter
            ):
                elapsed = current - baseline_meter
                entry.update({
                    "status": (
                        "reached" if elapsed >= threshold
                        else "not_reached_at_reference"
                    ),
                    "calculation_permitted": True,
                    "reference_date": measured_on.isoformat(),
                    f"{kind}_mileage": baseline_meter,
                    "recorded_mileage": current,
                    "elapsed_km": elapsed,
                    "remaining_km": max(Decimal(0), threshold - elapsed),
                    "excess_km": max(Decimal(0), elapsed - threshold),
                })
            else:
                entry["reason"] = "comparable_mileage_not_available"

        elif metric in {"period_days", "period_months"}:
            if threshold != threshold.to_integral_value():
                entry["reason"] = "fractional_calendar_period"
            else:
                try:
                    amount = int(threshold)
                    if metric == "period_days":
                        due = baseline_date + timedelta(days=amount)
                    else:
                        total = baseline_date.month - 1 + amount
                        year = baseline_date.year + total // 12
                        month = total % 12 + 1
                        if not 1 <= year <= 9999:
                            raise ValueError("DATE_OUT_OF_RANGE")
                        due = baseline_date.replace(
                            year=year,
                            month=month,
                            day=min(
                                baseline_date.day,
                                calendar.monthrange(year, month)[1],
                            ),
                        )
                    entry.update({
                        "status": (
                            "reached" if as_of >= due
                            else "not_reached_at_reference"
                        ),
                        "calculation_permitted": True,
                        "reference_date": as_of.isoformat(),
                        "due_date": due.isoformat(),
                        "elapsed_days": (as_of - baseline_date).days,
                        "remaining_days": max(0, (due - as_of).days),
                        "overdue_days": max(0, (as_of - due).days),
                    })
                except (ValueError, OverflowError):
                    entry["reason"] = "calendar_date_out_of_range"
        else:
            entry["reason"] = "engine_hours_not_available"

        if kind == "inspection":
            entry["baseline_kind"] = "inspection"
            entry["inspection_item_index"] = fact.get("inspection_item_index")
        return entry
