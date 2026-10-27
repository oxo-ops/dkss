"""Shared factual history and explicitly confirmed historical cost ownership."""

import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from .serialization import safe_json_dict


def synthetic_evidence(row):
    """Explicit synthetic-document declarations only; never infer from 'test'."""
    import unicodedata

    details = safe_json_dict(getattr(row, "invoice_details_json", "{}"))
    for field, value in (
        ("notes", getattr(row, "notes", None)),
        ("attached_invoice_notes", details.get("attached_invoice_notes")),
    ):
        if not isinstance(value, str):
            continue
        normalized = re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))
        # A compound declaration from the source, not a generic maintenance/test term.
        declarations = ("テスト用資料・支払不要(発行元・取引内容は架空です)",)
        matched = next(
            (text for text in declarations if normalized.startswith(text)), None
        )
        if matched is None:
            continue
        source = details.get("source")
        source = source if isinstance(source, dict) else {}
        return {
            "source_id": f"maintenance:{row.id}",
            "company_code": row.company_code,
            "vehicle_record_id": row.vehicle_record_id,
            "reason": "explicit_synthetic_document_declaration",
            "evidence_field": field,
            "declaration": matched,
            "document_source": {
                key: source.get(key) for key in ("sha256", "pages", "record_index")
            },
            "scope": "Excluded from factual calculations; stored records retained.",
        }
    return None


def factual_history(maintenance, parts=()):
    """Apply one parent decision to children, retaining company/vehicle boundaries."""
    kept, excluded, parents = [], [], {}
    for row in maintenance:
        evidence = synthetic_evidence(row)
        key = (row.company_code, row.vehicle_record_id, row.id)
        if evidence is not None:
            excluded.append(evidence)
        else:
            kept.append(row)
            parents[key] = row
    kept_parts = [
        row
        for row in parts
        if (row.company_code, row.vehicle_record_id, row.maintenance_record_id)
        in parents
    ]
    return kept, kept_parts, excluded


def cost_office(record):
    value = safe_json_dict(record.invoice_details_json).get("cost_attribution")
    return (value.get("office") or None) if isinstance(value, dict) else None


def set_cost_office(record, office):
    details = safe_json_dict(record.invoice_details_json)
    details["cost_attribution"] = {
        "office": str(office or "").strip() or None,
        "basis": "user_confirmed",
    }
    record.invoice_details_json = json.dumps(details, ensure_ascii=False)


def cost_date(record):
    value = (
        str(record.entry_date or "").strip()
        or str(record.completion_date or "").strip()
    )
    try:
        return datetime.strptime(value[:10].replace("/", "-"), "%Y-%m-%d").date()
    except ValueError:
        return None


class MaintenanceCostService:
    @staticmethod
    def office_months(records, office, today, count=7):
        months = []
        for offset in range(count - 1, -1, -1):
            year, month = divmod(today.year * 12 + today.month - 1 - offset, 12)
            months.append(
                dict(
                    key=f"{year:04d}-{month+1:02d}",
                    label=f"{month+1}月",
                    amount=Decimal(0),
                    known=0,
                    missing=0,
                )
            )
        buckets = {m["key"]: m for m in months}
        kept, _, excluded = factual_history(records)
        unassigned = 0
        for row in kept:
            day = cost_date(row)
            key = day.strftime("%Y-%m") if day else ""
            if not day or day > today or key not in buckets:
                continue
            owner = cost_office(row)
            if not owner:
                unassigned += 1
                continue
            if owner != office:
                continue
            bucket = buckets[key]
            try:
                amount = Decimal(str(row.total_cost))
                if not amount.is_finite():
                    raise InvalidOperation()
            except (ValueError, InvalidOperation):
                bucket["missing"] += 1
                continue
            bucket["amount"] += amount
            bucket["known"] += 1
        return dict(
            months=months,
            available=any(m["known"] for m in months),
            unassigned_count=unassigned,
            source_exclusions=excluded,
        )
