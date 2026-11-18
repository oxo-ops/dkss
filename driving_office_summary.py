"""Restricted office totals, never return report/person records to the view."""
from datetime import date
from driving_report_insights import collect, summarize, number
from driving_report_workspace import report_office

METRICS = {'急加速','急減速','急ブレーキ','速度超過','期間燃費'}

def month_start(today, offset):
    serial=today.year*12+today.month-1+offset
    return date(serial//12,serial%12+1,1)

def build(company, office, rows, operations, today):
    if not office or office=='所属不明':return {'available':False,'months':[],'metrics':[]}
    start=month_start(today,-5).isoformat();end=today.isoformat()
    rows=[r for r in rows if r.company_code==company and report_office(r)==office and start<=r.operation_date<=end]
    ids={r.vehicle_record_id for r in rows};ops={}
    for op in operations:
        if op.company_code==company and op.vehicle_record_id in ids and start<=op.operation_date<=end:
            ops.setdefault((company,op.vehicle_record_id),[]).append(op)
    facts,_=collect(rows,ops)
    months=[]
    for offset in range(-5,1):
        month=month_start(today,offset).strftime('%Y-%m')
        group=[f for f in facts if f['date'][:7]==month]
        totals=summarize(group)
        months.append({'month':month,'count':totals['count'],'distance':number(totals['distance']),'distance_state':totals['distance_state']})
    current=[f for f in facts if f['date'][:7]==today.strftime('%Y-%m')]
    groups={}
    for fact in current:
        for m in fact['metrics']:
            if m['name'] in METRICS and m['method'] in {'rate','fuel'}:
                groups.setdefault(m['name'],set()).add(m['id'])
    metrics=[]
    for name,keys in sorted(groups.items()):
        # Multiple definitions cannot be combined or described using source prose.
        if len(keys)!=1:continue
        total=summarize(current,next(iter(keys)))
        if total['value'] is not None:
            metrics.append({'name':name,'value':total['display'],'unit':total['unit']})
    return {'available':True,'months':months,'metrics':metrics}
