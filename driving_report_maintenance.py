"""Factual vehicle context for administrator-authorized driving reports."""
from collections import defaultdict
from datetime import date
from decimal import Decimal
import json
import unicodedata
from driving_report_data import decimal
from dkss_app.analysis import build_vehicle_karte_mileage_reference, filter_vehicle_maintenance_factual_history


def day(value):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def cost_summary(records, start, end):
    """Use one saved total per invoice; ambiguous duplicates stay out of the total."""
    groups = defaultdict(list)
    unknown = 0
    for row in records:
        performed = day(row.completion_date)
        if not performed or performed > day(end) or (day(start) and performed < day(start)):
            continue
        if row.status not in {'完了', 'completed', '', None}:
            continue
        value = decimal(row.total_cost)
        if value is None:
            unknown += 1
            continue
        try:
            details = json.loads(row.invoice_details_json or '{}')
        except (TypeError, ValueError):
            details = {}
        source = details.get('source') if isinstance(details, dict) else None
        source = source if isinstance(source, dict) else {}
        if source.get('sha256') and source.get('record_index') is not None:
            key = ('document', row.company_code, row.vehicle_record_id, source['sha256'], str(source['record_index']))
        elif row.invoice_number and row.invoice_date and row.maintenance_company:
            key = ('invoice', row.company_code, row.vehicle_record_id, row.maintenance_company.strip(), row.invoice_date, row.invoice_number.strip())
        else:
            key = ('record', row.id)
        groups[key].append((row, value))
    total, ids, duplicate_count, held = Decimal(0), [], 0, 0
    for rows in groups.values():
        duplicate_count += max(0, len(rows)-1)
        values = {value for _, value in rows}
        if len(values) != 1:
            held += len(rows)
            continue
        row, value = min(rows, key=lambda entry: entry[0].id)
        total += value
        ids.append(row.id)
    return {'total': str(total) if ids else None, 'count': len(ids), 'source_ids': sorted(ids),
            'missing': unknown, 'duplicates': duplicate_count, 'held': held, 'start': start, 'end': end}


def build(vehicle, maintenance, parts, operations, periodic, start, end):
    # Recheck boundaries before passing records to the shared factual readers.
    def own(rows):
        return [r for r in rows if r.company_code==vehicle.company_code and r.vehicle_record_id==vehicle.id]
    maintenance, parts, _ = filter_vehicle_maintenance_factual_history(own(maintenance), own(parts))
    reference = build_vehicle_karte_mileage_reference(maintenance, own(operations), end, own(periodic))
    end = reference['as_of']
    maintenance = [r for r in maintenance if not day(r.completion_date) or day(r.completion_date)<=day(end)]
    parents = {r.id: r for r in maintenance}
    grouped = defaultdict(list)
    for part in parts:
        if part.maintenance_record_id not in parents:
            continue
        parent = parents[part.maintenance_record_id]
        performed = day(part.replacement_date)
        if not performed or performed > day(end) or parent.status not in {'完了','completed','',None}:
            continue
        key = (unicodedata.normalize('NFKC', part.part_name).strip().casefold(), part.part_number or '')
        grouped[key].append(part)
    result = []
    for rows in grouped.values():
        latest_date = max(day(r.replacement_date) for r in rows).isoformat()
        latest = [r for r in rows if day(r.replacement_date).isoformat()==latest_date]
        part = min(latest, key=lambda r:r.id)
        meters = {decimal(r.mileage) for r in latest}
        meter = next(iter(meters)) if len(meters)==1 else None
        compatible = all(
            (parents[r.maintenance_record_id].mileage is None or decimal(parents[r.maintenance_record_id].mileage)==decimal(r.mileage))
            and (not day(parents[r.maintenance_record_id].completion_date or parents[r.maintenance_record_id].entry_date)
                 or day(parents[r.maintenance_record_id].completion_date or parents[r.maintenance_record_id].entry_date)==day(r.replacement_date))
            for r in latest)
        elapsed = None
        current = decimal(reference['value'])
        if (compatible and reference['distance_usable'] and meter is not None and meter>=0 and current is not None
                and day(reference['date']) and day(reference['date'])>=day(latest_date) and current>=meter):
            elapsed = str(current-meter)
        result.append({'id': part.id, 'name': part.part_name, 'number': part.part_number or '',
            'date': latest_date, 'days_since': (day(end)-day(latest_date)).days if compatible else None,
            'mileage': str(meter) if meter is not None else None, 'distance_since': elapsed,
            'maintenance_id': part.maintenance_record_id,
            'source_ids': sorted(r.id for r in latest), 'needs_review': not compatible or len(meters)>1})
    result.sort(key=lambda p:(p['date'],p['id']), reverse=True)
    return {'as_of': end, 'meter': {'value': str(reference['value']) if reference['value'] is not None else None,
            'date': reference['date'], 'usable': reference['distance_usable'], 'sources': reference['sources']},
            'cost': cost_summary(maintenance,start,end), 'parts': result[:3], 'part_count': len(result)}
