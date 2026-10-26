"""Office navigation and roster; organizational filters never grant readership."""
from collections import defaultdict
from driving_report_data import payload
from driving_report_insights import dashboard, digest, number, summarize


UNKNOWN_OFFICE = '所属不明'


def report_office(row):
    p = payload(row)
    return p.get('driver_office') or p.get('office_name') or UNKNOWN_OFFICE


def office_choices(registered, drivers, rows):
    names = {o.name for o in registered if o.name}
    names.update(d.office for d in drivers if d.office)
    names.update(report_office(r) for r in rows)
    return [{'key': digest(['office', name]), 'name': name} for name in sorted(names)]


def scope_filter(args, choices, default_office, administrator):
    if not administrator:
        return dict(args, scope='self', office='')
    args = dict(args)
    scope = args.get('scope', '')
    if scope not in {'', 'office', 'company'}:
        raise ValueError('表示範囲を選択してください。')
    # Old bookmarked office names remain exact matches, never substring matching.
    value = args.get('office', '')
    if value == '__company__':
        scope = 'company'
    if scope == 'company':
        args.update(scope='company', office='')
    else:
        selected = next((o for o in choices if value in {o['key'], o['name']}), None) if value else None
        if value and selected is None:
            raise ValueError('同じ会社の営業所を選択してください。')
        if not value:
            selected = next((o for o in choices if o['name'] == default_office), None)
        args.update(scope='office', office=selected['key'] if selected else '')
    return args


def scope_name(filters, choices, administrator):
    if not administrator:
        return '自分'
    if filters['scope'] == 'company':
        return '会社全体'
    return next((o['name'] for o in choices if o['key'] == filters.get('office')), '')


def metric_changes(current, previous, labels):
    board = dashboard(current, previous, labels)
    values = []
    for metric in board['groups']:
        now = summarize(current, metric['id'])
        old = summarize(previous, metric['id'])
        change = now['value'] - old['value'] if now['value'] is not None and old['value'] is not None else None
        values.append({'metric': metric, 'current': now, 'previous': old,
                       'change': number(change) if change is not None else None})
    return values


def enrich(board, facts, previous, drivers, users, bindings, choices, filters, administrator):
    """Master roster includes no-report members; historical office stays on the report."""
    by_key = {p['key']: p for p in board['drivers']}
    by_user = {u.id: u for u in users}
    selected_office = scope_name(filters, choices, administrator)
    keys_by_user = defaultdict(set)
    for fact in facts:
        for rid in fact['copies']:
            grant = bindings.get(rid)
            if grant:
                keys_by_user[grant.user_id].add(fact['driver_key'])
    for person in board['drivers']:
        person['has_records'] = True
        person['master_id'] = None
        person['review_states'] = sorted({(payload(f['row']).get('review') or {}).get('state', 'unreviewed')
                                         for f in facts if f['driver_key'] == person['key']})
        person['next_date'] = min(((payload(f['row']).get('review') or {}).get('next_date')
                                   for f in facts if f['driver_key'] == person['key'] and
                                   (payload(f['row']).get('review') or {}).get('next_date')), default='')
        person['analysis_metrics'] = metric_changes([f for f in facts if f['driver_key'] == person['key']],
                                                    [f for f in previous if f['driver_key'] == person['key']], board['labels'])
        person['highlights'] = person['analysis_metrics'][:2]
    if administrator and not filters.get('focus') and not filters.get('state') and not filters.get('vehicle'):
        for master in drivers:
            if filters['scope'] == 'office' and master.office != selected_office:
                continue
            if filters.get('driver') and filters['driver'] not in master.name and filters['driver'] not in master.employee_id:
                continue
            account = next((u for u in users if u.username == master.employee_id), None)
            keys = keys_by_user.get(account.id, set()) if account else set()
            matches = [by_key[k] for k in keys if k in by_key]
            for match in matches:
                match['master_id'] = master.id
            if matches:
                continue
            board['drivers'].append({'key': digest(['master', master.company_code, master.id]), 'name': master.name,
                'code': master.employee_id, 'offices': [master.office or UNKNOWN_OFFICE], 'vehicles': [],
                'current': summarize([]), 'previous': summarize([]), 'cells': [], 'change': None,
                'identified': bool(account), 'identity_warning': False, 'has_records': False,
                'master_id': master.id, 'highlights': [], 'review_states': [], 'next_date': ''})
    board['drivers'].sort(key=lambda p: (p['name'], p['key']))
    offices = []
    for office in choices:
        now = [f for f in facts if f['office'] == office['name']]
        old = [f for f in previous if f['office'] == office['name']]
        offices.append({**office, 'summary': summarize(now), 'driver_count': len({f['driver_key'] for f in now}),
                        'highlights': metric_changes(now, old, board['labels'])[:2],
                        'pending': sum((payload(f['row']).get('review') or {}).get('state') in {'coaching', 'followup'} for f in now)})
    board.update(office_choices=choices, office_summaries=offices, scope_name=selected_office,
                 scope_missing=administrator and filters['scope']=='office' and not selected_office,
                 highlights=metric_changes(facts, previous, board['labels'])[:4])
    return board
