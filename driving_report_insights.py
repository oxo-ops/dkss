"""Read-only driver comparisons using documented facts and paired denominators."""
import hashlib
import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
import unicodedata
from driving_report_data import payload, decimal, identity, eligible_reports, match_report

BAD_STATUS = {'illegible', 'not_recorded', 'not_applicable', 'unknown'}
COUNT_UNITS = {'回', '件', 'count'}


def number(value):
    value=decimal(value)
    if value is None: return '—'
    rounded=value.quantize(Decimal('.01'))
    return format(rounded, 'f').rstrip('0').rstrip('.') if rounded else '0'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:24]


def periods(args, today):
    mode = args.get('period') or ('custom' if args.get('start') or args.get('end') else 'month')
    if mode == 'all':
        if args.get('compare')=='custom':raise ValueError('比較する場合は対象期間も指定してください。')
        return {'mode':mode, 'start':'', 'end':'', 'previous_start':'', 'previous_end':''}
    if mode == 'month': start, end = today.replace(day=1), today
    elif mode == '30d': start, end = today-timedelta(days=29), today
    elif mode == 'prev_month':
        end = today.replace(day=1)-timedelta(days=1); start = end.replace(day=1)
    elif mode == 'custom':
        if not args.get('start') or not args.get('end'): raise ValueError('開始日と終了日を指定してください。')
        start, end = date.fromisoformat(args['start']), date.fromisoformat(args['end'])
        if start.isoformat()!=args['start'] or end.isoformat()!=args['end']: raise ValueError('日付の形式を確認してください。')
    else: raise ValueError('対象期間を選択してください。')
    if start > end: raise ValueError('開始日と終了日を確認してください。')
    previous_end=start-timedelta(days=1); previous_start=previous_end-(end-start)
    comparison=args.get('compare','previous')
    if comparison not in {'previous','month','custom'}:raise ValueError('比較期間を選択してください。')
    if comparison=='month':
        previous_end=start.replace(day=1)-timedelta(days=1);previous_start=previous_end.replace(day=1)
    if comparison=='custom':
        if not args.get('compare_start') or not args.get('compare_end'):
            raise ValueError('比較期間の開始日と終了日を指定してください。')
        previous_start=date.fromisoformat(args['compare_start']);previous_end=date.fromisoformat(args['compare_end'])
        if previous_start.isoformat()!=args['compare_start'] or previous_end.isoformat()!=args['compare_end']:
            raise ValueError('比較期間の日付の形式を確認してください。')
        if previous_start>previous_end:raise ValueError('比較期間の開始日と終了日を確認してください。')
        if previous_end>=start:raise ValueError('比較期間は対象期間より前に指定してください。')
    return {'mode':mode, 'start':start.isoformat(), 'end':end.isoformat(),
            'previous_start':previous_start.isoformat(), 'previous_end':previous_end.isoformat()}


def driver_key(row):
    p=payload(row)
    if p.get('source_system') and p.get('driver_code'):
        return digest([row.company_code,p['source_system'],p['driver_code']])
    return digest([row.company_code,'unidentified',row.id])


def driver_keys(rows):
    names=defaultdict(set)
    for row in rows:
        p=payload(row)
        if p.get('driver_name'):
            names[driver_key(row)].add(''.join(unicodedata.normalize('NFKC',p['driver_name']).split()))
    # Reused codes or disagreeing identities cannot establish a person across reports.
    return {r.id:(digest([driver_key(r),r.id]) if len(names[driver_key(r)])>1 else driver_key(r)) for r in rows}, {k for k,v in names.items() if len(v)>1}


def display_metric_name(name):
    aliases={'Driving time / 走行時間':'走行時間','Rest / 休憩':'休憩','Speeding ratio / 速度超過率':'速度超過率',
             'Driving time':'走行時間','Rest':'休憩','Speeding ratio':'速度超過率'}
    return aliases.get(name,name)


def display_metric_raw(name,raw):
    import re
    if display_metric_name(name) not in {'走行時間','運行時間','ハンドル時間','休憩','休憩時間','アイドリング時間'}:return raw
    match=re.fullmatch(r'(\d{1,3}):([0-5]\d)',raw)
    if not match:return raw
    hours,minutes=map(int,match.groups())
    return (str(hours)+'時間' if hours else '')+str(minutes)+'分'


def metric(p, item, distance, distance_ok):
    """Retain the original; derive rates only from explicit compatible inputs."""
    if item.get('status') in BAD_STATUS: return None
    name=str(item.get('item_name') or '').strip()
    if not name:return None
    value=decimal(item.get('value'));score=decimal(item.get('score'))
    original=item.get('raw_result')
    unit=item.get('unit') or ''
    known=bool(p.get('source_system') and p.get('definition_version') and item.get('definition') and unit)
    raw=str(original) if original is not None else number(value if value is not None else score)+(unit or ('点' if score is not None else ''))
    if raw=='—' and not item.get('result_text'):return None
    if item.get('result_text'):raw += ' ／ '+str(item['result_text'])
    method='raw'; n=d=None;scale=Decimal(1);output_unit=unit or ('点' if score is not None else '')
    num=decimal(item.get('numerator'));den=decimal(item.get('denominator'));du=item.get('denominator_unit')
    if known and distance_ok and item.get('threshold'):
        if unit in COUNT_UNITS and value is not None and value>=0 and distance is not None and distance>0:
            method='rate';n=value;d=distance;scale=Decimal(100);output_unit='回/100km' if unit!='件' else '件/100km'
        elif num is not None and num>=0 and den is not None and den>0 and du=='km' and unit in {'回/km','回/100km','件/km','件/100km'}:
            method='rate';n=num;d=den;scale=Decimal(100);output_unit='件/100km' if unit.startswith('件') else '回/100km'
    if known and num is not None and num>=0 and den is not None and den>0 and du and unit in {'%','％'} and num<=den:
        method='ratio';n=num;d=den;scale=Decimal(100);output_unit='%'
    if known and item.get('threshold') and num is not None and num>=0 and den is not None and den>0 and du in {'h','時間'} and unit in {'回/h','件/h'}:
        method='rate';n=num;d=den;scale=Decimal(1);output_unit=unit
    if method=='raw' and not known:reason='比較条件未確認'
    elif method=='raw':reason='原本値を表示'
    else:reason=''
    signature=[p.get('source_system'),p.get('definition_version'),name,item.get('definition'),
               item.get('threshold'),unit,item.get('road_type'),p.get('report_scope'),method,du if method=='ratio' else None]
    return {'id':digest(signature),'name':display_metric_name(name),'unit':output_unit,'method':method,'numerator':n,'denominator':d,
            'scale':scale,'raw':display_metric_raw(name,raw),'value':value if value is not None else score,'known':known,
            'source':p.get('source_system') or '提供元不明','version':p.get('definition_version') or '未記載',
            'definition':item.get('definition') or '未記載','threshold':item.get('threshold') or '未記載',
            'road':item.get('road_type') or '区分なし','scope':p.get('report_scope') or 'unknown','reason':reason}


def collect(rows, operations, keys=None, context=None):
    """A report and its copies contribute once; conflicting facts stay reviewable."""
    rows=list(rows);context=list(context) if context is not None else rows
    allowed={r.id for r in rows}; keys=keys or driver_keys(context)[0]
    bundles=defaultdict(list)
    for row in eligible_reports(context):
        matched=match_report(row,operations.get((row.company_code,row.vehicle_record_id),[]))
        op=matched.get('operation')
        key=('csv',row.company_code,row.vehicle_record_id,op.id) if op else identity(row)
        bundles[key].append(row)
    facts=[];issues=[]
    for bundle in bundles.values():
        if not any(r.id in allowed for r in bundle):continue
        bundle=sorted(bundle,key=lambda r:r.id);row=bundle[0];p=payload(row)
        for field in ('driver_code','operation_start_time','operation_end_time'):
            values={payload(r).get(field) for r in bundle if payload(r).get(field)}
            if len(values)>1:
                issues.append({'id':row.id,'reason':'同じ運行の乗務員・時刻を確認'})
                break
        else:
            values=set()
        if len(values)>1:continue
        def choose(field):
            values={str(payload(r)[field]) for r in bundle if payload(r).get(field) is not None}
            return next(iter(values)) if len(values)==1 else None
        match=match_report(row,operations.get((row.company_code,row.vehicle_record_id),[]))
        raw_dist={decimal(payload(r).get('distance')) for r in bundle if decimal(payload(r).get('distance')) is not None}
        distance=next(iter(raw_dist)) if len(raw_dist)==1 else None
        distance_ok=len(raw_dist)<=1 and match['status'] not in {'conflict','ambiguous'}
        if match['status']=='ambiguous':issues.append({'id':row.id,'reason':'CSVとの対応を確認'})
        if match['status']=='conflict' or len(raw_dist)>1:issues.append({'id':row.id,'reason':'距離の照合待ち'})
        if match.get('operation') and match['status'] in {'matched','resolved'} and match.get('use')=='csv':
            csv=decimal(match['operation'].distance)
            if csv is not None:distance=csv
        if distance is not None and distance<0:distance=None;distance_ok=False
        if not distance_ok:distance=None
        fact={'row':row,'date':row.operation_date,'driver_key':keys[row.id],
              'driver_name':p.get('driver_name') or '乗務員不明','driver_code':p.get('driver_code') or '',
              'identified':bool(p.get('source_system') and p.get('driver_code')),
              'office':p.get('driver_office') or p.get('office_name') or '所属不明',
              'vehicle_id':row.vehicle_record_id,'distance':distance,'metrics':[],'copies':[r.id for r in bundle]}
        item_groups=defaultdict(list)
        for source in bundle:
            for item in payload(source).get('report_items',[]):
                m=metric(payload(source),item,distance,distance_ok)
                if m:item_groups[m['id']].append(m)
        for mid,values in item_groups.items():
            comparable={(str(m['numerator']),str(m['denominator']),m['raw'] if m['method']=='raw' else '',str(m['value'])) for m in values}
            if len(comparable)>1:
                issues.append({'id':row.id,'reason':values[0]['name']+'の値が不一致'});continue
            fact['metrics'].append(values[0])
        fuel=decimal(choose('fuel_consumption'));fuel_unit=choose('fuel_unit')
        if distance_ok and distance is not None and distance>0 and fuel is not None and fuel>0 and fuel_unit in {'L','l','ℓ','リットル'}:
            source=choose('source_system') or '提供元不明'
            fact['metrics'].append({'id':digest(['fuel',source,p.get('report_scope')]),'name':'期間燃費','unit':'km/L',
                'method':'fuel','numerator':distance,'denominator':fuel,'scale':Decimal(1),'raw':number(distance/fuel),
                'value':distance/fuel,'known':True,'source':source,'version':'消費量から算出',
                'definition':'対象運行の距離合計 ÷ 消費燃料合計','threshold':'対象運行を一致','road':'区分なし',
                'scope':p.get('report_scope') or 'trip','reason':''})
        facts.append(fact)
    return facts,issues


def identity_counts(facts, recognized_keys):
    recognized=set(recognized_keys)
    count=len({f['driver_key'] for f in facts if f['driver_key'] in recognized})
    unknown=sum(f['driver_key'] not in recognized for f in facts)
    return {'driver_count':count, 'unidentified_count':unknown,
            'identity_display':' ／ '.join(([f'識別済み {count}人'] if count else [])+
                                           ([f'乗務員未確認 {unknown}運行'] if unknown else [])) or '記録なし'}


def summarize(facts, metric_id=None):
    chosen=[(f,m) for f in facts for m in f['metrics'] if m['id']==metric_id]
    count=len(facts);known=[f['distance'] for f in facts if f['distance'] is not None]
    summary={'count':count,'distance':sum(known) if known else None,'distance_count':len(known),
             'metric_count':len(chosen),'value':None,'display':'—','raw_count':0,'sources':[f['row'].id for f,_ in chosen],
             'report_ids':[f['row'].id for f in facts],'paired_distance':None,'numerator':None,'denominator':None,'unit':'','method':'raw'}
    summary['distance_state']='記録なし' if not count else '未取得' if not known else '一部取得' if len(known)<count else '取得済み'
    summary['distance_display']=('記録なし' if not count else '距離未取得' if not known else number(summary['distance'])+' km')
    if known and len(known)<count:
        summary['distance_display']+=f'（距離取得 {len(known)}／{count}運行）'
    if not chosen:return summary
    m=chosen[0][1];summary.update(unit=m['unit'],method=m['method'])
    if m['method']!='raw':
        n=sum(v['numerator'] for _,v in chosen);den=sum(v['denominator'] for _,v in chosen)
        value=n/den*m['scale']
        summary.update(value=value,display=number(value),numerator=n,denominator=den,
            paired_distance=sum(f['distance'] for f,_ in chosen if f['distance'] is not None))
    else:
        last_f,last_m=max(chosen,key=lambda item:(item[0]['date'],item[0]['row'].id))
        summary.update(display=last_m['raw'],raw_count=len(chosen),latest_date=last_f['date'])
    return summary


def review_notes(rows, facts, issues, conflicting):
    """Explain held facts without changing sources or inventing comparison settings."""
    by_id={r.id:r for r in rows if payload(r).get('lifecycle') not in {'cancelled','superseded'}}
    reasons=defaultdict(list)
    def add(record_id, reason):
        if record_id in by_id and reason not in reasons[record_id]:reasons[record_id].append(reason)
    for issue in issues:add(issue['id'],issue['reason'])
    for fact in facts:
        row=fact['row']
        if not fact['identified']:add(row.id,'提供元または乗務員コードがなく、同じ乗務員としてまとめられません。')
        elif driver_key(row) in conflicting and not fact.get('identity_confirmed'):add(row.id,'同じ乗務員コードに異なる氏名があり、原本ごとに表示しています。')
        if fact['distance'] is None:add(row.id,'走行距離を確認できないため、距離あたりの比較に使っていません。')
        elif fact['distance']==0:add(row.id,'走行距離が0kmのため、距離あたりの比較に使っていません。')
        unknown=[m['name'] for m in fact['metrics'] if not m['known']]
        if unknown:add(row.id,'比較条件が未記載のため原本値を表示：'+'、'.join(dict.fromkeys(unknown)))
    return [{'id':rid,'date':by_id[rid].operation_date,'name':payload(by_id[rid]).get('driver_name') or '乗務員不明',
             'reasons':values} for rid,values in sorted(reasons.items(),key=lambda item:(by_id[item[0]].operation_date or '',item[0]),reverse=True)]


def dashboard(current, previous, labels, selected_metric='', selected_driver=''):
    available={}
    for fact in current+previous:
        for item in fact['metrics']:available[item['id']]=item
    current_ids={m['id'] for f in current for m in f['metrics']}
    groups=sorted(available.values(),key=lambda m:(m['id'] not in current_ids,m['method']=='raw',m['name'],m['source'],m['version']))
    metric_id=selected_metric if selected_metric in available else (groups[0]['id'] if groups else '')
    metric_info=available.get(metric_id)
    def person(facts):
        groups=defaultdict(list)
        for fact in facts:groups[fact['driver_key']].append(fact)
        return groups
    present,past=person(current),person(previous)
    drivers=[]
    for key,facts in present.items():
        now=summarize(facts,metric_id);before=summarize(past.get(key,[]),metric_id)
        value=now['value'];old=before['value'];change=value-old if value is not None and old is not None else None
        sample=facts[-1]
        drivers.append({'key':key,'name':sample['driver_name'],'code':sample['driver_code'],
            'identified':all(f['identified'] for f in facts),'offices':sorted({f['office'] for f in facts}),
            'vehicles':[{'id':vid,'label':labels.get(vid,'車両 '+str(vid))} for vid in sorted({f['vehicle_id'] for f in facts})],
            'current':now,'previous':before,'change':number(change) if change is not None else None})
    drivers.sort(key=lambda x:(x['name'],x['code'],x['key']))
    columns=[];column_names=set()
    for group in groups:
        if group['name'] not in column_names and len(columns)<4:
            columns.append(group);column_names.add(group['name'])
    if metric_info and metric_info not in columns:columns=columns[:3]+[metric_info]
    for driver in drivers:
        driver['cells']=[]
        for column in columns:
            now=summarize(present[driver['key']],column['id']);old=summarize(past.get(driver['key'],[]),column['id'])
            difference=now['value']-old['value'] if now['value'] is not None and old['value'] is not None else None
            driver['cells'].append({'current':now,'previous':old,'change':number(difference) if difference is not None else None})
    selected=next((r for r in drivers if r['key']==selected_driver),None)
    focused=[f for f in current if selected and f['driver_key']==selected['key']]
    days=defaultdict(list)
    for fact in focused:days[fact['date']].append(fact)
    trend=[{'date':day,**summarize(rows,metric_id)} for day,rows in sorted(days.items())]
    series=[{'date':day['date'],'value':str(day['value']) if day['value'] is not None else None,'report_id':day['report_ids'][0]} for day in trend]
    chart=[point for point in series if point['value'] is not None]
    return {'chart':chart,'trend_series':series,'groups':groups,'metric':metric_info,'metric_id':metric_id,'drivers':drivers,'selected_driver':selected,
            'columns':columns,'trend':trend,'summary':summarize(current,metric_id),'previous':summarize(previous,metric_id)}
