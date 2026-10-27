"""Read-only comparison details built exclusively from authorized, deduplicated facts."""
from collections import defaultdict
from datetime import date
from decimal import Decimal
from driving_report_data import payload
from driving_report_insights import number, summarize


def conditions(facts, labels):
    return {
        'vehicle_ids': sorted({f['vehicle_id'] for f in facts}),
        'vehicles': sorted({labels.get(f['vehicle_id'], '車両 '+str(f['vehicle_id'])) for f in facts}),
        'roads': sorted({m['road'] for f in facts for m in f['metrics'] if m['road'] != '区分なし'}),
        'definitions': sorted({(m['source'], m['version'], m['scope']) for f in facts for m in f['metrics']}),
    }


def coverage(summary):
    return number(Decimal(summary['metric_count']) * 100 / summary['count']) if summary['count'] else '—'


def build(board, facts, previous, mode, administrator):
    """Never fetch peers here: caller has already enforced company, office and readership."""
    if not administrator:
        mode = 'vehicles'
    labels = board['labels']
    metric = board['metric']
    mid = board['metric_id']
    now, old = defaultdict(list), defaultdict(list)
    def key(f):
        return f['office'] if mode == 'offices' else f['vehicle_id'] if mode == 'vehicles' else f['driver_key']
    for f in facts:
        now[key(f)].append(f)
    for f in previous:
        old[key(f)].append(f)
    rows = []
    for k in now.keys() | old.keys():
        current, before = summarize(now[k], mid), summarize(old[k], mid)
        sample = (now[k] or old[k])[-1]
        label = k if mode == 'offices' else labels.get(k, '車両 '+str(k)) if mode == 'vehicles' else sample['driver_name']
        comparable = current['value'] is not None and before['value'] is not None
        current_conditions, previous_conditions = conditions(now[k], labels), conditions(old[k], labels)
        rows.append({'key': k, 'label': label, 'current': current, 'previous': before,
                     'coverage': coverage(current), 'previous_coverage': coverage(before),
                     'change': number(current['value'] - before['value']) if comparable else None,
                     'conditions': current_conditions, 'previous_conditions': previous_conditions,
                     'conditions_changed': bool(now[k] and old[k] and current_conditions != previous_conditions),
                     'driver_key': sample['driver_key'], 'vehicle_id': sample['vehicle_id']})
    rows.sort(key=lambda r: (r['label'], str(r['key'])))
    return {'mode': mode, 'rows': rows, 'metric': metric,
            'current_conditions': conditions(facts, labels), 'previous_conditions': conditions(previous, labels),
            'title': {'offices': '営業所ごとの比較', 'people': '乗務員ごとの変化',
                      'vehicle': '同じ車両を使う乗務員の比較', 'vehicles': '同じ乗務員が使う車両の比較'}[mode]}


def followups(rows):
    """Show permitted review fields, not arbitrary audit blobs or other users' identifiers."""
    result = []
    for row in rows:
        p = payload(row)
        if p.get('lifecycle') in {'cancelled', 'superseded'}:
            continue
        review = p.get('review') or {}
        if not any(review.get(k) for k in ('note', 'action', 'driver_explanation', 'next_date', 'outcome')):
            continue
        events = []
        for event in p.get('audit', []):
            if not isinstance(event, dict):
                continue
            detail = event.get('detail') or {}
            if event.get('kind') != 'review' or not isinstance(detail, dict):
                continue
            events.append({k: detail.get(k, '') for k in
                           ('state', 'note', 'action', 'driver_explanation', 'next_date', 'outcome', 'comparison_note')} |
                          {'at': str(event.get('at') or '')[:16].replace('T', ' ')})
        result.append({'id': row.id, 'date': row.operation_date, 'name': p.get('driver_name') or '乗務員不明',
                       'review': review, 'events': list(reversed(events))})
    return sorted(result, key=lambda x: (x['date'] or '', x['id']), reverse=True)


def followup_status(row, today):
    p=payload(row)
    review=p.get('review') or {}
    if p.get('lifecycle') in {'cancelled','superseded'} or review.get('state')=='completed':
        return ''
    try:scheduled=date.fromisoformat(review.get('next_date') or '')
    except (TypeError,ValueError):return ''
    return 'due' if scheduled<=today else 'upcoming'
