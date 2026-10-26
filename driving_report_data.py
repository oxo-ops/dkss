"""Canonical driving facts. Preserves source values and never invents scores."""
import hashlib
import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace


def payload(row):
    try:
        value = json.loads(row.details_json or '{}')
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def decimal(value):
    if value is None or isinstance(value, bool) or str(value).strip() == '': return None
    try:
        n = Decimal(str(value).replace(',', ''))
        return n if n.is_finite() and abs(n) <= Decimal('999999999999999') else None
    except InvalidOperation: return None


def version(row):
    return hashlib.sha256((row.details_json or '{}').encode()).hexdigest()


def timestamp(day, value):
    value = str(value or '').strip().replace('/', '-').replace('T', ' ')
    if not value: return ''
    return (str(day) + ' ' + value) if len(value) <= 8 else value


def identity(row):
    p = payload(row)
    number = p.get('report_number') or getattr(row, 'report_number', None)
    if number: return (row.company_code, row.vehicle_record_id, row.operation_date, p.get('source_system'), number)
    start = timestamp(row.operation_date, p.get('operation_start_time'))
    end = timestamp(p.get('operation_end_date') or row.operation_date, p.get('operation_end_time'))
    return (row.company_code, row.vehicle_record_id, start, end, p.get('driver_code') or p.get('driver_name')) if start and end else ('unidentified', row.id)


def match_report(row, operations):
    p = payload(row); decision = p.get('reconciliation') or {}
    if decision.get('mode') == 'distinct': return {'status':'distinct', 'operation':None, 'candidates':[], 'conflicts':[]}
    candidates = [o for o in operations if o.company_code == row.company_code and o.vehicle_record_id == row.vehicle_record_id and o.operation_date == row.operation_date]
    selected = decision.get('operation_id') or getattr(row, 'operation_record_id', None)
    if selected:
        matches = [o for o in candidates if o.id == selected]
    else:
        number = p.get('report_number') or getattr(row, 'report_number', None)
        matches = [o for o in candidates if number and o.report_number == number]
        if not matches:
            start=timestamp(row.operation_date,p.get('operation_start_time'))
            end=timestamp(p.get('operation_end_date') or row.operation_date,p.get('operation_end_time'))
            matches=[o for o in candidates if start and end and timestamp(o.operation_date,o.departure_at)==start and timestamp(o.operation_date,o.arrival_at)==end]
    if len(matches) != 1:
        return {'status':'ambiguous' if candidates else 'standalone', 'operation':None, 'candidates':candidates, 'conflicts':[]}
    operation=matches[0]; conflicts=[]
    for field, raw in [('distance',p.get('distance')), ('departure_meter',p.get('start_mileage')), ('arrival_meter',p.get('mileage'))]:
        left=decimal(raw); right=decimal(getattr(operation,field))
        if left is not None and right is not None and left!=right: conflicts.append({'field':field,'pdf':str(left),'csv':str(right)})
    # A changed source invalidates a prior selection instead of silently retaining it.
    fingerprint=hashlib.sha256(json.dumps({'id':operation.id,'date':operation.operation_date,'distance':str(operation.distance),'start':str(operation.departure_meter),'end':str(operation.arrival_meter),'departure_at':operation.departure_at,'arrival_at':operation.arrival_at},sort_keys=True).encode()).hexdigest()
    resolved=decision.get('fingerprint')==fingerprint and decision.get('use') in {'pdf','csv'}
    return {'status':'resolved' if resolved else 'conflict' if conflicts else 'matched', 'operation':operation, 'candidates':candidates, 'conflicts':conflicts,'fingerprint':fingerprint,'use':decision.get('use') if resolved else 'csv'}


def eligible_reports(reports):
    rows = [r for r in reports if payload(r).get('lifecycle') not in {'cancelled','superseded'}
            and payload(r).get('report_scope') not in {'monthly','unknown'} and r.operation_date]
    trips = {(r.company_code,r.vehicle_record_id,r.operation_date) for r in rows if payload(r).get('report_scope') != 'daily'}
    # A day total and its trip details must never be added together.
    return [r for r in rows if payload(r).get('report_scope') != 'daily'
            or (r.company_code,r.vehicle_record_id,r.operation_date) not in trips]


def canonical_operations(operations, reports):
    operations=list(operations); reports=sorted(reports,key=lambda r:r.id)
    result={o.id:o for o in operations}; extras=[]; seen=set(); claimed=set()
    eligible = eligible_reports(reports)
    facts = defaultdict(lambda: defaultdict(set))
    for row in eligible:
        for name in ('distance','start_mileage','mileage'):
            value = decimal(payload(row).get(name))
            if value is not None: facts[identity(row)][name].add(value)
    conflicting = {key for key, values in facts.items() if any(len(v)>1 for v in values.values())}
    for row in eligible:
        p=payload(row)
        key=identity(row)
        if key in conflicting:
            match=match_report(row,operations)
            if match['operation']: result.pop(match['operation'].id,None)
            continue
        if key in seen: continue
        seen.add(key)
        match=match_report(row,operations); o=match['operation']
        if match['status']=='ambiguous': continue
        if o:
            if o.id in claimed: result.pop(o.id,None); continue
            claimed.add(o.id)
            if match['status']=='conflict': result.pop(o.id,None); continue
        use_csv = bool(o and match.get('use') == 'csv')
        def adopted(field, pdf_value):
            csv_value = getattr(o, field) if o else None
            return csv_value if use_csv and csv_value is not None else decimal(pdf_value) if decimal(pdf_value) is not None else csv_value
        proxy=SimpleNamespace(id='report-'+str(row.id),company_code=row.company_code,
            vehicle_record_id=row.vehicle_record_id,operation_date=row.operation_date,
            report_number=p.get('report_number') or 'PDF:'+str(row.id),
            departure_at=(o.departure_at if use_csv and o.departure_at else timestamp(row.operation_date,p.get('operation_start_time'))),
            arrival_at=(o.arrival_at if use_csv and o.arrival_at else timestamp(p.get('operation_end_date') or row.operation_date,p.get('operation_end_time'))),
            departure_meter=adopted('departure_meter',p.get('start_mileage')),arrival_meter=adopted('arrival_meter',p.get('mileage')),
            distance=adopted('distance',p.get('distance')),source_row_json=row.details_json,
            source_filename='安全運転日報',imported_at=str(row.created_at or ''),imported_by_username=row.created_by_username)
        if o: result[o.id]=proxy
        else: extras.append(proxy)
    return list(result.values())+extras


def metrics_summary(reports):
    """Only identical, explicitly documented definitions can be compared."""
    groups=defaultdict(list); unknown=[]; seen=set(); active=[]
    for row in sorted(reports,key=lambda r:r.id):
        p=payload(row)
        if p.get('lifecycle') in {'cancelled','superseded'}: continue
        key=identity(row)
        if key in seen:continue
        seen.add(key);active.append(row)
        for item in p.get('report_items',[]):
            value=decimal(item.get('value'))
            if value is None or item.get('status') in {'illegible','not_recorded','not_applicable','unknown'}:continue
            # Neither an empty threshold nor a shared label establishes comparability.
            definition=item.get('definition')
            if not p.get('source_system') or not definition or not p.get('definition_version') or not item.get('unit'):
                unknown.append({'report_id':row.id,'name':item.get('item_name'),'reason':'定義・単位・設定版の不足'});continue
            key=(p.get('source_system'),p.get('definition_version'),item.get('item_name'),definition,item.get('threshold'),item.get('unit'),item.get('road_type'),p.get('report_scope') or 'trip')
            groups[key].append({'date':row.operation_date,'value':str(value),'report_id':row.id,'numerator':item.get('numerator'),'denominator':item.get('denominator'),'denominator_unit':item.get('denominator_unit')})
    rows=[]
    for key,values in groups.items():
        numerator=[decimal(v['numerator']) for v in values];denominator=[decimal(v['denominator']) for v in values]
        units={v['denominator_unit'] for v in values}
        ratio=None
        if all(v is not None for v in numerator+denominator) and all(v>=0 for v in denominator) and sum(denominator)>0 and len(units)==1 and None not in units:
            ratio=str(sum(numerator)/sum(denominator))
        rows.append({'source_system':key[0],'version':key[1],'name':key[2],'definition':key[3],'threshold':key[4],'unit':key[5],'road_type':key[6],'scope':key[7],'values':values,'ratio':ratio,'count':len(values)})
    return {'groups':rows,'not_comparable':unknown,'report_count':len(active),
            'missing_distance':sum(decimal(payload(r).get('distance')) is None for r in active)}
