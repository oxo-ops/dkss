"""Compare acquired vehicle facts; registration attributes are not historical snapshots."""
from collections import defaultdict
import re
from driving_report_insights import digest, summarize


FIELDS={'vehicle_make':('manufacturer','メーカー'),'vehicle_model':('model_code','型式'),
        'vehicle_body':('body_type','車体形状'),'vehicle_year':('first_registration_date','初年度')}


def value(vehicle, field):
    raw=str(getattr(vehicle,FIELDS[field][0],None) or '').strip()
    if field=='vehicle_year':
        match=re.match(r'^(\d{4})(?:[-/年]|$)',raw)
        return match[1] if match else None
    return raw or None


def choices(vehicles):
    return {field:[{'key':digest([field,v]),'name':v or '未登録・不明'}
                   for v in sorted({value(vehicle,field) for vehicle in vehicles},key=lambda v:(v is None,v or ''))]
            for field in FIELDS}


def apply(rows,vehicles,args):
    available=choices(vehicles)
    for field in FIELDS:
        key=args.get(field,'')
        if not key:continue
        if key not in {item['key'] for item in available[field]}:
            raise ValueError('表示できる台帳の車両条件を選択してください。')
        ids={v.id for v in vehicles if digest([field,value(v,field)])==key}
        rows=[r for r in rows if r.vehicle_record_id in ids]
    return rows


def metadata(vehicle):
    return {'id':vehicle.id,**{field:value(vehicle,field) for field in FIELDS}}


def usage(facts):
    groups=defaultdict(list)
    for fact in facts:groups[(fact['vehicle_id'],fact['driver_key'])].append(fact)
    result=defaultdict(list)
    for (vid,key),items in groups.items():
        dates=sorted({f['date'] for f in items if f['date']})
        result[vid].append({'key':key,'name':items[-1]['driver_name'], 'identified':all(f['identified'] for f in items),
            'first_date':dates[0] if dates else None,'last_date':dates[-1] if dates else None,'recorded_days':len(dates),
            'summary':summarize(items)})
    for items in result.values():items.sort(key=lambda item:(item['name'],item['key']))
    return dict(result)
