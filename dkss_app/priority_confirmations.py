"""Optional source-bound confirmations in existing immutable checklist audit rows.

No score entry, operation judgment, inspection result, notification or saved AI
JSON is changed. Providers own source verification; this module owns authority,
versions, replay protection, cancellation and current-source revalidation.
"""
from copy import deepcopy
from datetime import datetime
import json
import re
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from flask import abort, current_app, jsonify, request, session
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.exc import SQLAlchemyError

from vehicle_priority_inputs import fingerprint

VERSION = 'vehicle-priority-confirmation-v1'
RESULT_TYPE = 'vehicle_priority'
CONFIRM = '優先度根拠確認'
WITHDRAW = '優先度根拠取消'
MAX_EVENTS = 1000
KINDS = {'progression': '再発・悪化の観測', 'manufacturer_immediate': 'メーカーの即時対応条件',
         'legal_deadline': '車検証の満了日と適用条件'}
MESSAGE = ('確認内容は次回の通常分析の入力に使います。分析が正常に完了すると、'
           '根拠の成立する確認済み条件をAIの採否にかかわらず対応候補へ補完します。'
           '更新完了までは前回の提案が表示されることがあります。'
           '更新状態と結果は、この画面の提案欄で確認してください。'
           '元の点検・整備・運行判断は変わりません。運行可否は責任者が判断してください。')


def _day():
    return datetime.now(ZoneInfo('Asia/Tokyo')).date()


def _provider(kind):
    if kind == 'progression':
        from .priority_progression import options, preview
    elif kind == 'manufacturer_immediate':
        from .priority_manufacturer_evidence import preview_manufacturer_confirmation as preview
        options = _manufacturer_options
    elif kind == 'legal_deadline':
        from .priority_certificate_sources import certificate_confirmation_options as options, preview_certificate_confirmation as preview
    else:
        raise ValueError('確認する根拠を選んでください。')
    return options, preview


def _object(raw):
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _rows(vehicle):
    from .models import ChecklistEvent, db
    with db.session.no_autoflush:
        rows = ChecklistEvent.query.filter_by(company_code=vehicle.company_code,
            result_type=RESULT_TYPE, result_id=vehicle.id).order_by(ChecklistEvent.id).limit(MAX_EVENTS + 1).all()
    if len(rows) > MAX_EVENTS:
        raise ValueError('根拠確認の履歴が読取上限を超えています。部分履歴では判定しません。')
    return rows


def _identity(actor):
    try:
        return (isinstance(actor, dict) and type(actor['user_id']) is int and actor['user_id'] > 0
                and str(UUID(actor['identity'])) == actor['identity'] and bool(actor['username'])
                and isinstance(actor['name'], str) and actor['role'] in {'admin', 'itc'})
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def _valid_row(row, detail):
    try:
        actor = detail['actor']
        timestamp = datetime.fromisoformat(detail['confirmed_at'])
        return (detail.get('version') == VERSION and detail.get('company_code') == row.company_code
                and detail.get('vehicle_id') == row.result_id and _identity(actor)
                and actor['identity'] == row.actor_identity and actor['user_id'] == row.actor_user_id
                and actor['username'] == row.actor_username and actor['name'] == row.actor_name
                and timestamp.utcoffset() is not None and detail['confirmed_at'] == row.created_at
                and re.fullmatch(r'[0-9a-f]{32}', detail.get('request_token', '')) is not None)
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def _checked_preview(vehicle, kind, selection, as_of):
    if (not isinstance(selection, dict) or len(json.dumps(selection, ensure_ascii=False)) > 24000
            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in selection.items())):
        raise ValueError('元記録の選択を確認してください。')
    _, preview = _provider(kind)
    value = preview(vehicle, deepcopy(selection), as_of=as_of)
    if (not isinstance(value, dict) or value.get('kind') != kind
            or not isinstance(value.get('selection'), dict) or not isinstance(value.get('sources'), dict)
            or not re.fullmatch('[0-9a-f]{64}', str(value.get('fingerprint', '')))
            or not isinstance(value.get('subject'), str) or not value['subject']
            or not isinstance(value.get('source_ids'), list) or not value['source_ids']
            or any(not isinstance(sid, str) or not sid for sid in value['source_ids'])):
        raise ValueError('元記録の根拠を確認できません。')
    statements = value.get('statements')
    if (not isinstance(statements, list) or not statements or len(statements) > 10
            or any(not isinstance(s, dict) or not isinstance(s.get('key'), str) or not s['key']
                   or not isinstance(s.get('label'), str) or not s['label'] for s in statements)
            or len({s['key'] for s in statements}) != len(statements)
            or len(json.dumps(value, ensure_ascii=False)) > 262144):
        raise ValueError('確認する内容を表示できません。')
    return value


def confirmation_statuses(vehicle, *, as_of=None):
    """Keep withdrawal separate from unavailable/currently changed source facts."""
    as_of = as_of or _day()
    rows = _rows(vehicle)
    entries = {}
    for row in rows:
        detail = _object(row.detail_json)
        if not _valid_row(row, detail):
            continue  # Never backfill an old actor from today's user account.
        if row.event_type == CONFIRM and detail.get('kind') in KINDS:
            entries[row.id] = {**deepcopy(detail), 'event_id': row.id, 'status': 'held', 'preview': None}
        elif row.event_type == WITHDRAW:
            target = detail.get('withdraws_event_id')
            if type(target) is int and target in entries:
                entries[target].update(status='withdrawn', withdrawal_event_id=row.id)
    for entry in entries.values():
        if entry['status'] == 'withdrawn':
            continue
        try:
            if entry['kind'] == 'progression':
                from .priority_progression import progression_terminal_reason
                reason = progression_terminal_reason(vehicle, entry['selection'], as_of=as_of)
                if isinstance(reason, str) and reason:
                    entry.update(status='resolved', terminal={'status': 'resolved', 'reason': reason})
                    continue
            if entry['kind'] == 'manufacturer_immediate':
                from .priority_manufacturer_evidence import manufacturer_confirmation_terminal
                terminal = manufacturer_confirmation_terminal(vehicle, entry, as_of=as_of)
                if isinstance(terminal, dict) and terminal.get('status') == 'resolved':
                    entry.update(status='resolved', terminal=terminal)
                    continue
            value = _checked_preview(vehicle, entry['kind'], entry.get('selection'), as_of)
            keys = [statement['key'] for statement in value['statements']]
            if (entry.get('fingerprint') == value['fingerprint'] and entry.get('selection') == value['selection']
                    and entry.get('sources') == value['sources'] and entry.get('statements') == keys
                    and entry.get('source_ids') == value['source_ids'] and entry.get('subject') == value['subject']):
                entry.update(status='active', preview=value)
        except (ValueError, TypeError, KeyError, SQLAlchemyError):
            pass
    return list(entries.values())


def active_priority_confirmations(vehicle, kind=None, *, as_of=None):
    return [entry for entry in confirmation_statuses(vehicle, as_of=as_of)
            if entry['status'] == 'active' and (kind is None or entry['kind'] == kind)]


def _serializer():
    return URLSafeTimedSerializer(current_app.secret_key, salt='vehicle-priority-source-confirmation-v1')


def _user():
    from .models import User
    user = User.query.filter_by(company_code=session.get('company_code'), username=session.get('username')).first()
    if (not user or user.login_locked or not user.account_identity
            or user.account_identity != session.get('account_identity')
            or user.password_changed_at != session.get('password_changed_at')):
        abort(401)
    return user


def _vehicle(vehicle_record_id):
    from .models import Vehicle
    return Vehicle.query.filter_by(id=vehicle_record_id, company_code=session.get('company_code'), deleted=False).first_or_404()


def _token(vehicle, user, action, revision, **values):
    return _serializer().dumps(dict(version=VERSION, company_code=vehicle.company_code,
        vehicle_id=vehicle.id, actor_identity=user.account_identity, action=action,
        revision=revision, request_token=uuid4().hex, **values))


def _manufacturer_options(vehicle, *, as_of, selection=None):
    from .priority_observations import inspection_observation_options
    from .priority_manufacturer_evidence import manufacturer_confirmation_options
    observations = inspection_observation_options(vehicle, as_of=as_of)
    selection = selection or {}
    fields = [dict(key='observation_input_ref', label='現在の現車観測', type='select', options=observations['options'])]
    result = dict(fields=fields, missing_conditions=observations.get('missing_conditions', []), originals=[])
    if not selection.get('observation_input_ref'):
        return result
    values = manufacturer_confirmation_options(vehicle, selection['observation_input_ref'], as_of=as_of)
    result['missing_conditions'] += values.get('missing_conditions', [])
    choices, quotes = [], []
    for bundle in values['bundles']:
        manufacturer = bundle['manufacturer']
        choice = json.dumps([manufacturer['knowledge_source_id'], manufacturer['rule_key']], ensure_ascii=False, separators=(',', ':'))
        label = manufacturer['knowledge'].get('title') or manufacturer['rule_key']
        if manufacturer.get('evidence_path') == 'original_instruction':
            label += '（原本通達・任意確認）'
        choices.append(dict(value=choice, label=label))
        if selection.get('manufacturer_rule') == choice:
            rule = manufacturer['rule']
            result['originals'].append(dict(label='メーカー原文', text=rule['source_quote'], url='/vehicle/knowledge-documents/' + manufacturer['document_id'] + '/source'))
            candidates = [rule['source_quote']] + [e['source_quote'] for e in rule.get('semantic_review', {}).get('evidence', []) if isinstance(e, dict) and isinstance(e.get('source_quote'), str)]
            quotes = [dict(value=q, label=q) for q in dict.fromkeys(candidates) if q]
    fields.append(dict(key='manufacturer_rule', label='対象となるメーカー原文', type='select', options=choices))
    if quotes:
        fields.extend([dict(key='condition_quote', label='現在成立している発動条件の原文', type='select', options=quotes),
                       dict(key='action_quote', label='その条件で即時対応を求める原文', type='select', options=quotes)])
    return result


def _selection(kind, value):
    if kind != 'manufacturer_immediate' or not isinstance(value, dict):
        return value
    value = dict(value)
    try:
        pair = json.loads(value.pop('manufacturer_rule'))
        if not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(s, str) for s in pair):
            raise ValueError()
        value.update(knowledge_source_id=pair[0], rule_key=pair[1])
        return value
    except (ValueError, TypeError, KeyError):
        raise ValueError('メーカーの元資料を選んでください。') from None


def priority_confirmation_data(vehicle_record_id):
    user = _user(); vehicle = _vehicle(vehicle_record_id)
    kind = request.args.get('kind', 'progression')
    try:
        selection = json.loads(request.args.get('selection', '{}'))
        if not isinstance(selection, dict):
            raise ValueError()
        provider, _ = _provider(kind)
        choices = (provider(vehicle, as_of=_day(), selection=selection) if kind == 'manufacturer_immediate'
                   else provider(vehicle, as_of=_day()))
        rows = _rows(vehicle); revision = rows[-1].id if rows else 0
        history = []
        for entry in reversed(confirmation_statuses(vehicle)):
            history.append({k: entry[k] for k in ('event_id', 'kind', 'selection', 'subject', 'status', 'actor', 'confirmed_at')})
            if entry['status'] != 'withdrawn' and user.role in {'admin', 'itc'}:
                history[-1]['cancel_token'] = _token(vehicle, user, 'cancel', revision, event_id=entry['event_id'])
        return jsonify(ok=True, can_confirm=user.role in {'admin', 'itc'}, kinds=KINDS,
            revision=revision, form=choices, history=history, message=MESSAGE)
    except (ValueError, TypeError, ImportError) as error:
        return jsonify(ok=False, message=str(error) if isinstance(error, ValueError) and str(error) else '選択した元記録を表示できません。'), 400


def preview_priority_confirmation(vehicle_record_id):
    user = _user(); vehicle = _vehicle(vehicle_record_id)
    if user.role not in {'admin', 'itc'}:
        abort(403)
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or len(request.get_data()) > 32000:
        abort(400)
    try:
        kind = body.get('kind')
        value = _checked_preview(vehicle, kind, _selection(kind, body.get('selection')), _day())
        rows = _rows(vehicle); revision = rows[-1].id if rows else 0
        replace = body.get('replace_event_id')
        if replace is not None:
            if type(replace) is not int or not any(e['event_id'] == replace and e['status'] != 'withdrawn' and e['kind'] == kind for e in confirmation_statuses(vehicle)):
                raise ValueError('訂正する確認記録を選び直してください。')
        token = _token(vehicle, user, 'confirm', revision, kind=kind, selection=value['selection'],
            fingerprint=value['fingerprint'], preview_hash=fingerprint(value), replace_event_id=replace)
        return jsonify(ok=True, preview=value, token=token, message=MESSAGE)
    except (ValueError, TypeError, KeyError) as error:
        return jsonify(ok=False, message=str(error) or '元記録の選択を確認してください。'), 400


def save_priority_confirmation(vehicle_record_id):
    from .models import Vehicle, ChecklistEvent, db
    user = _user(); vehicle = _vehicle(vehicle_record_id)
    if user.role not in {'admin', 'itc'}:
        abort(403)
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or len(request.get_data()) > 32000:
        abort(400)
    try:
        signed = _serializer().loads(body.get('token', ''), max_age=1800)
        if (not isinstance(signed, dict) or signed.get('version') != VERSION
                or signed.get('company_code') != vehicle.company_code or signed.get('vehicle_id') != vehicle.id
                or signed.get('actor_identity') != user.account_identity):
            raise ValueError('確認画面を開き直してください。')
        # Existing vehicle-row write locking works on SQLite and PostgreSQL. It
        # also advances the existing transactional input epoch, without a new
        # DB schema/trigger or changing vehicle attributes.
        count = Vehicle.query.filter_by(company_code=vehicle.company_code, id=vehicle.id, deleted=False).update(
            {Vehicle.id: Vehicle.id}, synchronize_session=False)
        if count != 1:
            raise ValueError('対象車両を確認できません。')
        db.session.expire_all()
        rows = _rows(vehicle); revision = rows[-1].id if rows else 0
        if (type(signed.get('revision')) is not int or signed['revision'] != revision
                or any(_object(row.detail_json).get('request_token') == signed.get('request_token') for row in rows)):
            raise ValueError('確認記録が更新されたか、同じ内容が送信済みです。再読み込みしてください。')
        entries = {e['event_id']: e for e in confirmation_statuses(vehicle)}
        action = signed.get('action')
        target = signed.get('event_id') if action == 'cancel' else signed.get('replace_event_id')
        if target is not None and (type(target) is not int or target not in entries or entries[target]['status'] == 'withdrawn'):
            raise ValueError('取消・訂正する記録が更新されています。')
        value = None
        if action == 'confirm':
            value = _checked_preview(vehicle, signed['kind'], signed['selection'], _day())
            expected = [s['key'] for s in value['statements']]
            statements = body.get('statements')
            if (not isinstance(statements, list) or len(statements) != len(expected)
                    or any(not isinstance(s, str) for s in statements) or set(statements) != set(expected)):
                raise ValueError('表示された事実確認をすべて確認してから登録してください。')
            if value['fingerprint'] != signed['fingerprint'] or fingerprint(value) != signed['preview_hash']:
                raise ValueError('元記録・原本または適用条件が更新されています。根拠を確認し直してください。')
        elif action != 'cancel' or target is None:
            raise ValueError('確認画面を開き直してください。')
        now = datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(timespec='seconds')
        actor = dict(user_id=user.id, identity=user.account_identity, username=user.username,
            name=f'{user.last_name or ""}{user.first_name or ""}' or user.username, role=user.role)
        def append(event_type, details):
            detail = dict(version=VERSION, company_code=vehicle.company_code, vehicle_id=vehicle.id,
                actor=actor, confirmed_at=now, request_token=signed['request_token'], **details)
            row = ChecklistEvent(company_code=vehicle.company_code, result_type=RESULT_TYPE, result_id=vehicle.id,
                event_type=event_type, actor_username=user.username, actor_name=actor['name'],
                created_at=now, detail_json=json.dumps(detail, ensure_ascii=False))
            db.session.add(row); db.session.flush()
            return row
        if target is not None:
            append(WITHDRAW, dict(withdraws_event_id=target, kind=entries[target]['kind']))
        if value is not None:
            saved = append(CONFIRM, {k: value[k] for k in ('kind', 'selection', 'fingerprint', 'subject', 'source_ids', 'sources')} |
                dict(statements=[s['key'] for s in value['statements']]))
        else:
            saved = None
        db.session.commit()
        return jsonify(ok=True, event_id=saved.id if saved else None, message=MESSAGE)
    except (BadSignature, ValueError, TypeError, KeyError) as error:
        db.session.rollback()
        return jsonify(ok=False, message=str(error) if isinstance(error, ValueError) and str(error) else '確認画面の有効期限が切れました。開き直してください。'), 409
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify(ok=False, message='保存が競合しました。最新の根拠確認を読み直してください。'), 409


def priority_certificate_original(vehicle_record_id, document_id):
    from io import BytesIO
    from flask import send_file
    from .priority_certificate_sources import read_certificate_confirmation_original
    _user(); vehicle = _vehicle(vehicle_record_id)
    try:
        value = read_certificate_confirmation_original(vehicle, document_id, as_of=_day())
    except ValueError:
        abort(404)
    return send_file(BytesIO(value['data']), mimetype=value['mimetype'],
        download_name=value['filename'], as_attachment=False, max_age=0)


def confirmation_input_state(vehicle, *, as_of=None):
    """Small versioned input stamp includes withdrawals and held source bindings."""
    entries = confirmation_statuses(vehicle, as_of=as_of)
    rows = _rows(vehicle)
    return {'version': VERSION, 'revision': rows[-1].id if rows else 0,
        'confirmations': [dict(event_id=e['event_id'], kind=e['kind'], status=e['status'],
            fingerprint=e['fingerprint'], current_fingerprint=(e.get('preview') or {}).get('fingerprint'),
            terminal=e.get('terminal')) for e in entries]}
