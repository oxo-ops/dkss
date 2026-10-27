"""Role-aware presentation of existing, authorized driving facts."""
from datetime import date
from collections import defaultdict
from driving_report_insights import summarize


CATEGORY_LABELS={'safety':'安全運転','economy':'経済運転','other':'運行・その他'}


def category(metric):
    name=metric['name'].lower()
    if metric['method']=='fuel' or any(word in name for word in ('燃費','燃料','アイドリング','回転','経済','fuel','idle','rpm')):
        return 'economy'
    if any(word in name for word in ('加速','発進','減速','ブレーキ','速度超過','安全','speed','acceleration','braking')):
        return 'safety'
    return 'other'


def enrich(board,facts,previous):
    board['vehicle_count']=len({f['vehicle_id'] for f in facts})
    if not board.get('selected_driver'):
        days=defaultdict(list)
        for fact in facts:
            days[fact['date']].append(fact)
        trend=[{'date':day,**summarize(rows,board['metric_id'])} for day,rows in sorted(days.items())]
        series=[{'date':day['date'],'value':str(day['value']) if day['value'] is not None else None,
                 'report_id':day['report_ids'][0]} for day in trend]
        board.update(trend=trend,trend_series=series,chart=[point for point in series if point['value'] is not None])
    selected=category(board['metric']) if board.get('metric') else None
    available={category(m) for m in board['groups']}
    board['metric_categories']=[{'key':key,'label':label,
        'metric_id':next(m['id'] for m in board['groups'] if category(m)==key)}
        for key,label in CATEGORY_LABELS.items() if key in available]
    entries=board['available_highlights']
    entries=[e for e in entries if category(e['metric'])==selected]
    entries.sort(key=lambda e:e['metric']['id']!=board['metric_id'])
    board.update(display_metrics=entries[:3],metric_category=selected)
    candidates=[item for item in board.get('followups',[]) if item['review'].get('state')!='completed']
    dated=[]
    for item in candidates:
        try:scheduled=date.fromisoformat(item['review'].get('next_date') or '')
        except (ValueError,TypeError):continue
        dated.append((scheduled,item))
    board['next_followup']=min(dated,key=lambda pair:(pair[0],pair[1]['id']))[1] if dated else (candidates[0] if candidates else None)
    board['next_followup_date']=min(dated,key=lambda pair:(pair[0],pair[1]['id']))[0].isoformat() if dated else ''


def finding(item, board=None):
    kind=item.get('kind','record')
    label=('次の振り返り' if kind.startswith('followup') else '使用車両の確認' if kind.startswith('maintenance')
           else '前期間からの変化' if kind=='change' else '条件別の比較' if kind=='comparison'
           else '営業所の傾向' if kind=='office' else '期間の傾向' if kind=='scope' else '記録の確認')
    result={**item,'display_label':label,'display_title':item.get('title',''),
            'display_headline':item['finding'].split('。',1)[0],
            'display_tone':'attention' if kind=='followup_due' else 'vehicle' if kind.startswith(('maintenance','followup')) else 'neutral'}
    if board and kind in {'scope','record','change'}:
        entries=board.get('available_highlights',[])
        if kind!='scope':
            person=next((p for p in board['drivers'] if p['key']==item.get('driver_key')),None)
            entries=person.get('analysis_metrics',[]) if person else []
        matches=[e for e in entries if item.get('title') in {e['metric']['name']+'の傾向',e['metric']['name']+'の記録'}]
        entry=matches[0] if len(matches)==1 else None
        if entry and entry['change'] is not None:
            from decimal import Decimal
            change=Decimal(entry['change'])
            result['display_title']=entry['metric']['name']+'の記録'+('が減少' if change<0 else 'が増加' if change>0 else 'に変化なし')
            result['display_headline']='前期間 '+entry['previous']['display']+' → 今回 '+entry['current']['display']+' '+entry['metric']['unit']
            # Color the observed change without certifying improvement or blame.
            if category(entry['metric'])=='safety':
                result['display_label']='減少した記録' if change<0 else '気になる変化' if change>0 else '前期間との比較'
                result['display_tone']='attention' if change>0 else 'neutral'
    if kind.startswith('followup'):
        result['display_label']='次にすること'
        result['display_headline']=item['action']
        review=board.get('next_followup') if board else None
        if review and review['id'] in item.get('reports',[]):
            result['display_title']=review['review'].get('action') or item.get('title','')
            result['display_headline']=review['review'].get('note') or item['action']
            result['display_summary']='次の確認 '+(review['review'].get('next_date') or '日付未設定')

    return result
