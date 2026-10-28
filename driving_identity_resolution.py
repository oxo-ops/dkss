"""Company-scoped identity resolution. Never compare a report code to a login ID.

Explicit report grants are also the durable evidence for subsequent code reuse.
Automatic resolutions are revalidated on every request; GET never writes a grant.
"""
from collections import defaultdict
from datetime import date
from types import SimpleNamespace
import unicodedata
import json

from flask import has_request_context, request, session
from driving_report_data import payload

AUTO = '__automatic_identity_v1__'


def name(value):
    return ''.join(unicodedata.normalize('NFKC', str(value or '')).split())


def account_name(user):
    return name((user.last_name or '') + (user.first_name or ''))


def code_key(row):
    p = payload(row)
    source, code = str(p.get('source_system') or '').strip(), str(p.get('driver_code') or '').strip()
    return (row.company_code, source, code) if source and code else None


def usable(user):
    return user.role in {'user', 'admin', 'itc'} and not user.login_locked


def revoked(row):
    p = payload(row)
    held = p.get('identity_resolution') or {}
    events = [e for e in p.get('audit', []) if e.get('kind') == 'reader']
    if events and str(events[-1].get('at') or '') >= str(held.get('at') or ''):
        return not (events[-1].get('detail') or {}).get('username')
    return held.get('basis') == 'hold'


class Resolver:
    def __init__(self, company):
        from dkss_app.models import User, VehicleDrivingReportRecord, DrivingReportReader
        from dkss_app.driving_access import fingerprint, ready
        self.company = company
        self.users = {u.id: u for u in User.query.filter_by(company_code=company).all()}
        self.by_name = defaultdict(list)
        # Locked accounts still participate in ambiguity detection.
        for u in self.users.values():
            if account_name(u): self.by_name[account_name(u)].append(u)
        self.rows = {r.id: r for r in VehicleDrivingReportRecord.query.filter_by(company_code=company).all()}
        self.grants = {g.report_id: g for g in DrivingReportReader.query.filter_by(company_code=company).all()} if ready() else {}
        self.code_names = defaultdict(set)
        self.evidence = defaultdict(list)
        for r in self.rows.values():
            if payload(r).get('lifecycle') in {'cancelled', 'superseded'}: continue
            key = code_key(r)
            n = name(payload(r).get('driver_name'))
            if key and n: self.code_names[key].add(n)
            grant = self.grants.get(r.id)
            user = self.users.get(grant.user_id) if grant else None
            if not (key and n and r.operation_date and user and usable(user) and
                    grant.identity_hash == fingerprint(r) and not revoked(r)):
                continue
            # A previous automatic guess must not defeat a newly ambiguous name.
            matches = self.by_name[n]
            if grant.confirmed_by == AUTO and not (len(matches) == 1 and matches[0].id == user.id):
                continue
            self.evidence[key].append((r.operation_date, n, user))

    def observe(self, row):
        """Include a just-inserted batch member without reloading the company."""
        self.rows[row.id] = row
        key, n = code_key(row), name(payload(row).get('driver_name'))
        if key and n: self.code_names[key].add(n)

    def resolve(self, row):
        from dkss_app.driving_access import fingerprint
        if row.company_code != self.company: return None, '会社を確認してください'
        p = payload(row)
        if revoked(row): return None, '本人への表示を解除しています'
        grant = self.grants.get(row.id)
        if grant:
            user = self.users.get(grant.user_id)
            if grant.identity_hash != fingerprint(row): return None, '乗務員情報が変更されています'
            if not user or not usable(user): return None, 'アカウントを確認してください'
            if grant.confirmed_by != AUTO: return user, 'manual'
        crew = {str(i.get('driver_code') or '').strip() for i in p.get('duties', []) if i.get('driver_code')}
        if p.get('driver_code'): crew.add(str(p['driver_code']).strip())
        if len(crew) > 1: return None, '複数運転者の乗務区間を確認してください'
        n = name(p.get('driver_name'))
        key = code_key(row)
        try: date.fromisoformat(row.operation_date)
        except (TypeError, ValueError): return None, '運行日を確認してください'
        # Missing identity is never borrowed from a vehicle or uploader.
        if not n: return None, '乗務員名を確認してください'
        if key:
            observed = self.code_names[key] | {n}
            if len(observed) > 1: return None, '同じ乗務員コードに異なる氏名があります'
            evidence = [u for day, original, u in self.evidence[key]
                        if day <= row.operation_date and original == n]
            ids = {u.id for u in evidence}
            if len(ids) > 1: return None, '登録済みの紐づけが重複しています'
            if len(ids) == 1: return evidence[0], 'code'
        matches = self.by_name[n]
        if len(matches) != 1:
            return None, '同姓同名のアカウントがあります' if matches else '該当するアカウントがありません'
        user = matches[0]
        if not usable(user): return None, 'アカウントを確認してください'
        return user, 'name'

    def bindings(self, rows):
        from dkss_app.driving_access import fingerprint
        result = {}
        for row in rows:
            user, basis = self.resolve(row)
            if user:
                result[row.id] = SimpleNamespace(company_code=self.company, report_id=row.id,
                    user_id=user.id, username=user.username, identity_hash=fingerprint(row), basis=basis)
        return result


def resolver(fresh=False):
    company = session.get('company_code')
    if not has_request_context(): return Resolver(company)
    key = ('dkss.driving.identity', company)
    if fresh or key not in request.environ: request.environ[key] = Resolver(company)
    return request.environ[key]


def preview(values):
    """Only an unresolved report gets an account selection control."""
    if session.get('role') not in {'admin', 'itc'}: return None
    row = SimpleNamespace(id=None, company_code=session['company_code'],
        operation_date=values.get('record_date'), details_json=json.dumps(values, ensure_ascii=False))
    service = resolver()
    user, basis = service.resolve(row)
    return {'resolved': bool(user), 'label': ((user.last_name or '') + (user.first_name or '')) if user else '',
            'reason': basis if not user else '', 'users': [u for u in service.users.values() if usable(u)]}
