"""Role-aware presentation of existing, authorized driving facts."""
from datetime import date


CATEGORY_LABELS={'safety':'安全運転','economy':'経済運転','other':'運行・その他'}


def category(metric):
    name=metric['name'].lower()
    if metric['method']=='fuel' or any(word in name for word in ('燃費','燃料','アイドリング','回転','経済','fuel','idle','rpm')):
        return 'economy'
    if any(word in name for word in ('加速','発進','減速','ブレーキ','速度超過','安全','speed','acceleration','braking')):
        return 'safety'
    return 'other'


def enrich(board,facts,previous):
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


def finding(item):
    kind=item.get('kind','record')
    label=('次の振り返り' if kind.startswith('followup') else '使用車両の確認' if kind.startswith('maintenance')
           else '前期間からの変化' if kind=='change' else '条件別の比較' if kind=='comparison'
           else '営業所の傾向' if kind=='office' else '期間の傾向' if kind=='scope' else '記録の確認')
    return {**item,'display_label':label,'display_headline':item['finding'].split('。',1)[0],
            'display_tone':'attention' if kind=='followup_due' else 'vehicle' if kind.startswith('maintenance') else 'neutral'}
