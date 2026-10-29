"""Source-scoped invoice read revisions; originals and confirmed ledgers stay intact."""
import copy
import hashlib
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from sqlalchemy.orm import defer

from flask import session

from .extensions import db
from .models import VehicleDocumentImportDraft as Draft, VehicleMaintenanceDocument as Document

FIELDS = ('labor_cost', 'parts_cost', 'other_cost', 'tax_amount', 'total_cost')
KEY = 'invoice_cost_reads'
LIMIT = Decimal('999999999999.99')


def costs(values):
    if not isinstance(values, dict) or any(f not in values for f in FIELDS):
        raise ValueError('請求額の確認履歴が不足しています。')
    result = {}
    for f in FIELDS:
        raw = values[f]
        try:
            value = None if raw is None else Decimal(str(raw))
            if value is not None and (not value.is_finite() or abs(value) > LIMIT
                                      or value != value.quantize(Decimal('0.01'))):
                raise ValueError()
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError('請求額の確認履歴が不正です。') from None
        result[f] = value
    return result


def encoded(values):
    return {f: str(values[f]) if values[f] is not None else None for f in FIELDS}


def record_costs(target):
    return {f: getattr(target, f) for f in FIELDS}


def read_values(payload):
    return costs({f: None if payload.get(f) in (None, '') else payload[f] for f in FIELDS})


def detail(target):
    try:
        value = json.loads(target.invoice_details_json or '{}')
    except (ValueError, TypeError):
        raise ValueError('請求書の参照情報を確認できません。') from None
    if not isinstance(value, dict):
        raise ValueError('請求書の参照情報を確認できません。')
    return value


def original(target, draft_id, index, verify_bytes):
    draft = Draft.query.options(defer(Draft._source_file)).filter_by(id=draft_id, company_code=target.company_code,
                                  document_type='maintenance', status='completed').first()
    if draft is None or type(index) is not int or index < 0:
        raise ValueError('訂正対象の原本を確認できません。')
    if verify_bytes and hashlib.sha256(draft.source_file).hexdigest() != draft.source_sha256:
        raise ValueError('訂正対象の原本が一致しません。')
    try:
        preview = json.loads(draft.preview_json)
        result = json.loads(draft.result_json)
        if not isinstance(preview, dict) or not isinstance(result, dict):
            raise ValueError()
        rows = preview['records']
        registered = result.get('records', [])
        if not isinstance(registered, list):
            raise ValueError()
        payload = rows[index]
    except (ValueError, TypeError, KeyError, IndexError):
        raise ValueError('訂正対象の保存済み読取値を確認できません。') from None
    if not isinstance(rows, list) or not isinstance(payload, dict):
        raise ValueError('訂正対象の明細を確認できません。')
    # A source must actually have been registered to this record/vehicle.
    if not any(isinstance(r, dict) and r.get('record_index') == index
               and r.get('record_id') == target.id
               and r.get('vehicle_record_id') == target.vehicle_record_id for r in registered):
        raise ValueError('訂正対象の原本と整備記録の対応を確認できません。')
    return draft, payload


def reference(draft, index, document_id=None):
    return dict(draft_id=draft.id, record_index=index, sha256=draft.source_sha256,
                filename=draft.source_filename, document_id=document_id)


def ledger(target, lock=False):
    query = Document.query.filter(Document.company_code == target.company_code,
        Document.vehicle_record_id == target.vehicle_record_id,
        Document.maintenance_record_id == target.id,
        Document.financial_status.in_(('confirmed', 'superseded')))
    if lock:
        query = query.with_for_update().populate_existing()
    rows = []
    for doc in query.all():
        try:
            decision = json.loads(doc.decision_json or '{}')
            if not isinstance(decision, dict):
                raise ValueError()
            history = decision['review_history']
            if not isinstance(history, list):
                raise ValueError()
            confirmed = costs(decision['confirmed_costs'])
            actions = [h for h in history if isinstance(h, dict)
                       and h.get('action') in {'initial_cost', 'additional_cost', 'correction'}]
            if (decision.get('costs_applied') is not True or not isinstance(history, list)
                    or not all(isinstance(h, dict) for h in history)
                    or len(actions) != 1 or confirmed['total_cost'] is None):
                raise ValueError()
            when = datetime.fromisoformat(actions[0]['reviewed_at'])
            if when.tzinfo is None:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise ValueError('費用の反映履歴を確認できません。') from None
        rows.append(dict(doc=doc, decision=decision, costs=confirmed,
                         action=actions[0]['action'], when=when))
    rows.sort(key=lambda r: (r['when'], r['doc'].id))
    if rows and any(r['action'] == 'initial_cost' for r in rows[1:]):
        raise ValueError('初回費用の履歴が重複しています。')
    return rows


def aggregate(values):
    result = {}
    for f in FIELDS:
        parts = [v[f] for v in values]
        value = None if any(v is None for v in parts) else sum(parts, Decimal('0'))
        if value is not None and abs(value) > LIMIT:
            raise ValueError('訂正後の費用が登録可能な金額を超えます。')
        result[f] = value
    return result


def effective(source, saved):
    if saved is None:
        return source['basis']
    if not isinstance(saved, dict):
        raise ValueError('訂正履歴の形式を確認できません。')
    if (saved.get('reference') != source['reference']
            or costs(saved.get('read_values')) != source['read_values']):
        raise ValueError('訂正履歴の原本参照が一致しません。')
    basis = costs(saved.get('confirmed_values'))
    chain = saved.get('revisions')
    if not isinstance(chain, list) or not chain:
        raise ValueError('訂正履歴を確認できません。')
    states = [basis]
    for event in chain:
        if not isinstance(event, dict) or costs(event.get('before')) != states[-1]:
            raise ValueError('訂正履歴の前後が一致しません。')
        states.append(costs(event.get('after')))
    if source['key'].startswith('document:'):
        valid = source['basis'] == basis
    else:
        # The first addition may have acknowledged an earlier source read revision.
        valid = source['basis'] in states
    if not valid:
        raise ValueError('請求額の反映履歴と訂正履歴が一致しません。')
    return states[-1]


def projection(target, lock=False):
    details = detail(target)
    rows = ledger(target, lock)
    source = details.get('source')
    managed = bool(isinstance(source, dict) or rows or KEY in details)
    if not managed:
        return None
    state = details.get(KEY, {'version': 1, 'sources': {}})
    if not isinstance(state, dict) or state.get('version') != 1 or not isinstance(state.get('sources'), dict):
        raise ValueError('請求書の訂正履歴の形式を確認できません。')
    if rows:
        first = rows[0]
        if first['action'] == 'initial_cost':
            baseline = {f: Decimal('0') for f in FIELDS}
        elif first['action'] == 'additional_cost':
            baseline = costs(first['decision'].get('costs_before'))
            if baseline['total_cost'] is None:
                raise ValueError('請求書の反映前の費用を確認できません。')
        else:
            raise ValueError('最初の費用の反映履歴を確認できません。')
    else:
        baseline = record_costs(target)
    sources = []
    if not rows or rows[0]['action'] != 'initial_cost':
        if isinstance(source, dict):
            draft, payload = original(target, source.get('draft_id'), source.get('record_index'), lock)
            if source.get('sha256') != draft.source_sha256:
                raise ValueError('元請求の原本参照が一致しません。')
            sources.append(dict(key=f"primary:{draft.id}:{source['record_index']}",
                reference=reference(draft, source['record_index']), label='元の請求書',
                read_values=read_values(payload), basis=baseline, doc=None))
        else:
            sources.append(dict(key='manual', reference=None, label='手入力の整備費用（請求書分を除く）',
                read_values=baseline, basis=baseline, doc=None))
    for row in rows:
        doc = row['doc']
        # Superseded sources remain in the saved history but do not contribute.
        if doc.financial_status != 'confirmed':
            continue
        draft, payload = original(target, doc.source_draft_id, doc.source_record_index, lock)
        try:
            if json.loads(doc.payload_json) != payload or read_values(payload) != row['costs']:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('訂正前の請求額・明細と反映履歴が一致しません。') from None
        sources.append(dict(key='document:' + doc.id, reference=reference(draft, doc.source_record_index, doc.id),
            label='反映済みの請求書', read_values=read_values(payload), basis=row['costs'], doc=doc))
    for item in sources:
        saved = state['sources'].get(item['key'])
        # A manual baseline can change as the entire old record before any invoice.
        if item['key'] == 'manual' and saved:
            item['read_values'] = costs(saved.get('read_values'))
        item['effective'] = effective(item, saved)
    expected = aggregate([s['effective'] for s in sources])
    actual = record_costs(target)
    descriptor = dict(record_id=target.id, company=target.company_code, vehicle=target.vehicle_record_id,
        actual=encoded(actual), expected=encoded(expected), state=state,
        sources=[dict(key=s['key'], reference=s['reference'], basis=encoded(s['basis']),
                      effective=encoded(s['effective'])) for s in sources])
    version = hashlib.sha256(json.dumps(descriptor, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return dict(sources=sources, state=state, expected=expected, actual=actual,
                unresolved=expected != actual, version=version, rows=rows)


def replace_costs(target, replacement_id, incoming):
    view = projection(target, lock=True)
    if view is None or view['unresolved']:
        raise ValueError('登録済み費用と請求書の履歴が一致しません。費用を再確認してください。')
    selected = next((s for s in view['sources'] if s['key'] == 'document:' + replacement_id), None)
    if selected is None:
        raise ValueError('訂正前の請求書は確認状態が変わっています。選び直してください。')
    return aggregate([s['effective'] for s in view['sources'] if s is not selected] + [incoming]), selected['doc']


def apply_read(target, view, key, submitted_version, values, confirm_evidence=False):
    if view is None or submitted_version != view['version']:
        raise ValueError('請求書の確認状態が変わりました。画面を開き直してください。')
    selected = next((s for s in view['sources'] if s['key'] == key), None)
    if selected is None:
        raise ValueError('訂正する請求書・原本を選択してください。')
    revised = costs(values)
    if revised['total_cost'] is None or any(v is not None and v < 0 for v in revised.values()):
        raise ValueError('請求書の合計金額・内訳を確認してください。')
    if all(revised[f] is not None for f in FIELDS[:-1]) and sum(revised[f] for f in FIELDS[:-1]) != revised['total_cost']:
        raise ValueError('内訳と合計金額が一致しません。')
    if view['unresolved'] and not confirm_evidence:
        raise ValueError('過去の合計訂正は未解決です。対象原本と訂正額の根拠を確認してください。')
    if revised == selected['effective'] and not view['unresolved']:
        return view['expected'], None
    state = copy.deepcopy(view['state'])
    saved = state['sources'].setdefault(key, dict(reference=selected['reference'],
        read_values=encoded(selected['read_values']), confirmed_values=encoded(selected['basis']), revisions=[]))
    total = aggregate([revised if s is selected else s['effective'] for s in view['sources']])
    if revised != selected['effective'] or view['unresolved']:
        saved['revisions'].append(dict(before=encoded(selected['effective']), after=encoded(revised),
            record_before=encoded(view['actual']), record_after=encoded(total),
            reconciled_legacy=view['unresolved'], evidence_confirmed=bool(confirm_evidence),
            actor_identity=session.get('account_identity'), username=session.get('username'),
            at=datetime.now(ZoneInfo('UTC')).isoformat()))
        details = detail(target)
        details[KEY] = state
        target.invoice_details_json = json.dumps(details, ensure_ascii=False)
    return total, dict(field='invoice_read_correction', source=selected['reference'],
                      before=encoded(selected['effective']), after=encoded(revised))


def form_context(view):
    if view is None:
        return None
    return dict(version=view['version'], unresolved=view['unresolved'],
        actual=encoded(view['actual']), expected=encoded(view['expected']),
        sources=[dict(key=s['key'], label=s['label'], reference=s['reference'],
                      read_values=encoded(s['read_values']), values=encoded(s['effective']),
                      confirmed_values=encoded(costs(view['state']['sources'][s['key']]['confirmed_values'])
                          if s['key'] in view['state']['sources'] else s['basis']))
                 for s in view['sources']])
