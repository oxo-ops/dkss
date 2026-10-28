"""Office navigation and roster; organizational filters never grant readership."""
from collections import defaultdict
from driving_report_data import payload
from driving_report_insights import dashboard, digest, number, summarize, identity_counts, attributed


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
    if scope not in {'', 'office', 'company', 'self'}:
        raise ValueError('表示範囲を選択してください。')
    # Old bookmarked office names remain exact matches, never substring matching.
    value = args.get('office', '')
    if value == '__self__':
        scope = 'self'
    if value == '__company__':
        scope = 'company'
    if scope == 'self':
        return dict(args, scope='self', office='', focus='', driver='', listing='offices', breakdown='vehicles')
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
    if not administrator or filters.get('scope') == 'self':
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


def current_affiliation(person, facts, bindings, users, drivers, selected_office, company_scope):
    """A confirmed account plus a unique employee master identifies today's office.

    OCR codes/names alone never link a report to a current master. A differing
    office is an observed difference, not evidence of a transfer date or reason.
    """
    user_ids = {bindings[rid].user_id for fact in facts if fact['driver_key'] == person['key']
                for rid in fact['copies'] if rid in bindings}
    accounts = [u for u in users if u.id in user_ids]
    master = None
    if len(accounts) == 1:
        account = accounts[0]
        matches = [d for d in drivers if d.company_code == account.company_code and d.employee_id == account.username]
        if len(matches) == 1:
            master = matches[0]
    office = (master.office or '').strip() if master else ''
    if not office:
        status, label = 'unknown', '現在所属未確認'
    elif all(o == UNKNOWN_OFFICE for o in person['offices']):
        status, label = 'history_unknown', '日報当時の所属未確認'
    elif not company_scope and office != selected_office:
        status, label = 'other', '他営業所所属・期間内の運行あり'
    elif company_scope and any(o not in {office, UNKNOWN_OFFICE} for o in person['offices']):
        status, label = 'other', '日報当時と所属が異なる記録あり'
    else:
        status, label = 'current', '現在所属'
    return {'current_office': office, 'affiliation_status': status,
            'affiliation_label': label, 'master_id': master.id if master else None}


def enrich(board, facts, previous, drivers, users, bindings, choices, filters, administrator):
    """Master roster includes no-report members; historical office stays on the report."""
    by_key = {p['key']: p for p in board['drivers']}
    provenance = facts + board.get('personal_held_facts', [])
    selected_office = scope_name(filters, choices, administrator)
    keys_by_user = defaultdict(set)
    for fact in facts:
        for rid in fact['copies']:
            grant = bindings.get(rid)
            if grant:
                keys_by_user[grant.user_id].add(fact['driver_key'])
    for person in board['drivers']:
        person['has_records'] = True
        person['reader_confirmed'] = any(rid in bindings for f in provenance if f['driver_key']==person['key'] for rid in f['copies'])
        person['master_id'] = None
        if administrator:
            person.update(current_affiliation(person, provenance, bindings, users, drivers,
                                               selected_office, filters['scope'] == 'company'))
        person['review_states'] = sorted({(payload(f['row']).get('review') or {}).get('state', 'unreviewed')
                                         for f in facts if f['driver_key'] == person['key']})
        person['next_date'] = min(((payload(f['row']).get('review') or {}).get('next_date')
                                   for f in facts if f['driver_key'] == person['key'] and
                                   (payload(f['row']).get('review') or {}).get('next_date')), default='')
        person['analysis_metrics'] = metric_changes(attributed([f for f in facts if f['driver_key'] == person['key']]),
                                                    attributed([f for f in previous if f['driver_key'] == person['key']]), board['labels'])
        person['highlights'] = person['analysis_metrics'][:2]
    if administrator and not filters.get('focus') and not filters.get('state') and not filters.get('vehicle') and not filters.get('followup_due') and not any(filters.get(field) for field in ('vehicle_make','vehicle_model','vehicle_body','vehicle_year')):
        for master in drivers:
            if filters['scope'] == 'office' and master.office != selected_office:
                continue
            if filters.get('driver') and filters['driver'] not in master.name and filters['driver'] not in master.employee_id:
                continue
            account = next((u for u in users if u.username == master.employee_id), None)
            keys = keys_by_user.get(account.id, set()) if account else set()
            matches = [by_key[k] for k in keys if k in by_key]
            # Ambiguous employee IDs must not merge multiple master people.
            matches = [match for match in matches if match.get('master_id') == master.id]
            if matches:
                continue
            board['drivers'].append({'key': digest(['master', master.company_code, master.id]), 'name': master.name,
                'code': master.employee_id, 'offices': [master.office or UNKNOWN_OFFICE], 'vehicles': [],
                'current': summarize([]), 'previous': summarize([]), 'cells': [], 'change': None,
                'identified': bool(account), 'identity_warning': False, 'has_records': False,
                'master_id': master.id, 'highlights': [], 'review_states': [], 'next_date': '', 'reader_confirmed': False,
                'current_office': master.office or '', 'affiliation_status': 'current', 'affiliation_label': '現在所属'})
    board['drivers'].sort(key=lambda p: ({'current':0,'other':1,'history_unknown':2,'unknown':3}.get(p.get('affiliation_status'),0), p['name'], p['key']))
    board['current_affiliations'] = [{'key': p['key'], 'office': p['current_office'], 'status':p['affiliation_status']}
                                    for p in board['drivers'] if administrator and p.get('has_records')]
    recognized={p['key'] for p in board['drivers'] if p.get('has_records') and p['identified'] and not p.get('identity_warning')}
    board['recognized_driver_keys']=sorted(recognized)
    board['identity_counts']=identity_counts(facts,recognized)
    offices = []
    for office in choices:
        now = [f for f in facts if f['office'] == office['name']]
        old = [f for f in previous if f['office'] == office['name']]
        offices.append({**office, 'summary': summarize(now), **identity_counts(now,recognized),
                        'highlights': metric_changes(now, old, board['labels'])[:2],
                        'pending': sum((payload(f['row']).get('review') or {}).get('state') in {'coaching', 'followup'} for f in now)})
    highlights=metric_changes(facts,previous,board['labels'])
    board.update(office_choices=choices, office_summaries=offices, scope_name=selected_office,
                 scope_missing=administrator and filters['scope']=='office' and not selected_office,
                 highlights=highlights[:4],available_highlights=highlights)
    return board
