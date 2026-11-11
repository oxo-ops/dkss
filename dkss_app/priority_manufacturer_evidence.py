"""Bind adopted manufacturer originals to explicitly selected observation records.

This is a read-only evidence reader, not a priority consumer. It rereads original
bytes, source quotes, current adoption and exact inspection provenance. Neither
matching models, quoted urgency words, AI review nor selecting two records proves
that the manufacturer's immediate condition occurred on this vehicle. The absent
condition/action confirmation remains explicit. Only the separately verified
common confirmation workflow may use the fact mapper to request the core floor.
"""
from copy import deepcopy
from datetime import date, datetime
import hashlib
import re
from zoneinfo import ZoneInfo
from urllib.parse import urlencode

from vehicle_priority_inputs import fingerprint
from .priority_observations import REF as OBSERVATION_REF, read_inspection_observation_sources
from .priority_timing import RULE_KEYS, VEHICLE_KEYS, _rule_key

VERSION = 'registered-manufacturer-observation-evidence-v1'
MAX_SELECTIONS = 20
MAX_RULES = 100
MAX_DOCUMENT_BYTES = 32 * 1024 * 1024
MAX_TOTAL_DOCUMENT_BYTES = 64 * 1024 * 1024
KNOWLEDGE_REF = re.compile(r'knowledge:([1-9][0-9]{0,9})\Z')
SHA256 = re.compile(r'[a-f0-9]{64}\Z')
MISSING_CONFIRMATION = (
    'メーカー原文の発動条件とこの現車観測の対応、および原文が求める即時対応を確認要。'
    '引用・数値・型式の一致やAIの意味確認だけでは高60下限を適用しません'
)


class EvidenceUnavailable(ValueError):
    """The complete selected source bundle cannot be verified."""


def _selections(values):
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= MAX_SELECTIONS:
        raise EvidenceUnavailable('メーカー原本と元観測の組を個別に指定してください')
    result, seen = [], set()
    for value in values:
        required = {'knowledge_source_id', 'rule_key', 'observation_input_ref'}
        if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - {'expected_fingerprint'}:
            raise EvidenceUnavailable('メーカー原本と元観測の明示参照を確認要')
        knowledge = value['knowledge_source_id']
        match = KNOWLEDGE_REF.fullmatch(knowledge) if isinstance(knowledge, str) else None
        observation = value['observation_input_ref']
        observed = OBSERVATION_REF.fullmatch(observation) if isinstance(observation, str) else None
        key = value['rule_key']
        expected = value.get('expected_fingerprint')
        if (not match or int(match[1]) > 2147483647 or not observed
                or max(int(observed[1]), int(observed[2])) > 2147483647
                or not isinstance(key, str) or not SHA256.fullmatch(key)
                or ('expected_fingerprint' in value and (not isinstance(expected, str) or not SHA256.fullmatch(expected)))):
            raise EvidenceUnavailable('メーカー原本・規則・元観測の参照形式を確認要')
        identity = (knowledge, key, observation)
        if identity in seen:
            raise EvidenceUnavailable('同じメーカー原本と元観測の組が重複しています')
        seen.add(identity)
        result.append({**value, 'knowledge_id': int(match[1])})
    return result


def _verify_original(original, checksum, rule):
    from maintenance_knowledge_import import verify_maintenance_rule_sources
    if not isinstance(original, bytes) or hashlib.sha256(original).hexdigest() != checksum:
        raise EvidenceUnavailable('メーカー原本の保存bytesと版checksumが一致しません')
    semantic = rule.get('semantic_review')
    entries = semantic.get('evidence') if isinstance(semantic, dict) else None
    if not isinstance(entries, list) or not 1 <= len(entries) <= 3:
        raise EvidenceUnavailable('メーカー規則の意味確認に用いた原文を確認要')
    packets = [{'page': rule['source_page'], 'quote': rule['source_quote'],
        'maintenance_rules': [{key: rule[key] for key in RULE_KEYS}]}]
    for entry in entries:
        if (not isinstance(entry, dict) or type(entry.get('source_page')) is not int
                or not isinstance(entry.get('source_quote'), str) or not entry['source_quote'].strip()
                or len(entry['source_quote']) > 2000):
            raise EvidenceUnavailable('メーカー規則の意味確認原文・ページが保存されていません')
        packets.append({'page': entry['source_page'], 'quote': entry['source_quote']})
    verified = verify_maintenance_rule_sources(original, packets)
    if any(value['source_verification']['status'] != 'quote_matched' for value in verified):
        raise EvidenceUnavailable('メーカー規則または意味確認の引用を保存原本で再照合できません')
    if verified[0]['maintenance_rules'][0]['numeric_evidence']['status'] != 'tokens_present':
        raise EvidenceUnavailable('採用済みメーカー規則の数値・単位を保存原本で再照合できません')
    return {'document_checksum': checksum, 'source': verified[0]['source_verification'],
        'numeric_evidence': verified[0]['maintenance_rules'][0]['numeric_evidence'],
        'semantic_sources': [value['source_verification'] for value in verified[1:]]}


def _read(vehicle, selections, as_of):
    from flask import current_app
    from sqlalchemy import func
    from . import knowledge as k
    from .models import db, VehicleMaintenanceKnowledge as Knowledge, VehicleChecklistResult as Inspection
    from .maintenance_knowledge_import_models import get_models
    Document, _ = get_models(db)
    reader = current_app.extensions.get('maintenance_knowledge_import', {}).get('get_vehicle_scopes')
    if reader is None:
        raise EvidenceUnavailable('メーカー原本・採用の既存readerを利用できません')
    ids = {value['knowledge_id'] for value in selections}
    rows = Knowledge.query.filter_by(company_code=vehicle.company_code).filter(Knowledge.id.in_(ids)).all()
    if len(rows) != len(ids):
        raise EvidenceUnavailable('同じ会社の指定メーカー原本を確認できません')
    _, evidences = reader(rows, include_rule_evidence=True)
    if sum(len(value.get('rules', [])) for value in evidences.values()) > MAX_RULES:
        raise EvidenceUnavailable('メーカー規則の読取上限を超えるため部分資料では照合しません')
    aliases = {'トラック': 'truck', '大型トラック': 'truck', '中型トラック': 'truck', '小型トラック': 'truck',
        'トラクタ': 'truck', 'トラクター': 'truck', 'バス': 'bus'}
    categories = {aliases[value] for value in (vehicle.body_type, vehicle.type) if value in aliases}
    category = next(iter(categories)) if len(categories) == 1 else None
    rows = {row.id: row for row in rows}
    originals, used_bytes, manufacturers = {}, 0, {}
    for selection in selections:
        identity = (selection['knowledge_id'], selection['rule_key'])
        if identity in manufacturers:
            continue
        row = rows[selection['knowledge_id']]
        evidence = evidences.get(row.id, {})
        document_id, checksum = evidence.get('document_id'), evidence.get('document_checksum')
        if not isinstance(checksum, str) or not SHA256.fullmatch(checksum):
            raise EvidenceUnavailable('メーカー原本の版を確認できません')
        matches = [rule for rule in evidence.get('rules', []) if _rule_key(row.id, document_id, checksum, rule) == selection['rule_key']]
        if len(matches) != 1:
            raise EvidenceUnavailable('指定メーカー規則と採用された原文の一意な対応を確認できません')
        rule = matches[0]
        adoption = k.assess_public_maintenance_rule_adoption(vehicle, row, evidence, rule, vehicle_category=category)
        if adoption['status'] != 'eligible' or not row.valid_from or row.valid_from > as_of.isoformat():
            raise EvidenceUnavailable('メーカー原本の現在版・採用・対象車両への適用条件を確認できません')
        if document_id not in originals:
            size = db.session.query(func.length(Document.original_data)).filter_by(
                company_code=vehicle.company_code, id=document_id, checksum=checksum).scalar()
            if type(size) is not int or not 1 <= size <= MAX_DOCUMENT_BYTES or used_bytes + size > MAX_TOTAL_DOCUMENT_BYTES:
                raise EvidenceUnavailable('メーカー原本が欠落したか読取上限を超えるため照合しません')
            raw = db.session.query(Document.original_data).filter_by(
                company_code=vehicle.company_code, id=document_id, checksum=checksum).scalar()
            if not isinstance(raw, bytes) or len(raw) != size:
                raise EvidenceUnavailable('メーカー原本の保存内容を確認できません')
            originals[document_id] = raw
            used_bytes += size
        verification = _verify_original(originals[document_id], checksum, rule)
        manufacturers[identity] = {
            'knowledge_source_id': selection['knowledge_source_id'], 'rule_key': selection['rule_key'],
            'document_id': document_id, 'document_checksum': checksum, 'source_url': adoption['source_url'],
            'knowledge': {key: getattr(row, key) for key in ('title', 'part_name', 'manufacturer', 'model_code',
                'conditions', 'guidance', 'source_kind', 'source_reference', 'provider', 'status',
                'valid_from', 'valid_until', 'confirmed_by', 'confirmed_at')},
            'rule': deepcopy(rule), 'adoption': deepcopy(adoption), 'original_verification': verification}
    refs = list(dict.fromkeys(value['observation_input_ref'] for value in selections))
    observation_result = read_inspection_observation_sources(vehicle, refs, as_of=as_of)
    observations = {value['input_ref']: value for value in observation_result['observations']}
    if len(observations) != len(refs):
        raise EvidenceUnavailable('指定した同じ会社・車両の元観測をすべて照合できません')
    link_rows = db.session.query(Inspection.id, Inspection.checklist_id, Inspection.year, Inspection.month,
        Inspection.day).filter(Inspection.company_code == vehicle.company_code,
        Inspection.vehicle_record_id == vehicle.id,
        Inspection.id.in_({value['record_id'] for value in observations.values()})).all()
    observation_links = {f'inspection:{row.id}': f'/vehicle/checklists/{row.checklist_id}?' + urlencode({
        'vehicle_record_id': vehicle.id, 'year': row.year, 'month': row.month, 'active_day': row.day}) for row in link_rows}
    vehicle_facts = {key: getattr(vehicle, key, None) for key in VEHICLE_KEYS}
    bundles = []
    for selection in selections:
        observation = observations[selection['observation_input_ref']]
        manufacturer = manufacturers[(selection['knowledge_id'], selection['rule_key'])]
        source = {'version': VERSION, 'company_code': vehicle.company_code, 'vehicle_id': vehicle.id,
            'vehicle_facts': vehicle_facts, 'manufacturer': manufacturer, 'observation': observation,
            'source_links': {observation['source_id']: observation_links[observation['source_id']],
                manufacturer['knowledge_source_id']: '/vehicle/knowledge-documents/' + manufacturer['document_id'] + '/source'}}
        digest = fingerprint(source)
        if selection.get('expected_fingerprint') is not None and selection['expected_fingerprint'] != digest:
            raise EvidenceUnavailable('メーカー原本・採用・車両条件・元観測の版が変わったため再確認してください')
        bundles.append({**deepcopy(source), 'fingerprint': digest, 'evidence_ref': 'manufacturer-evidence:' + digest,
            'condition_match_verified': False, 'immediate_action_verified': False,
            'missing_conditions': [MISSING_CONFIRMATION]})
    return bundles


def read_manufacturer_priority_evidence(vehicle, selections, *, as_of=None):
    """Read selected adopted originals and observations, without semantic joining.

    A selection contains knowledge_source_id, rule_key and observation_input_ref.
    Optional expected_fingerprint rejects changed evidence instead of rebinding a
    saved selection. The result is not an AI offer, Fact, score or confirmation.
    A normal screen still needs an explicit, authenticated condition/action link.
    No confirmed link is inferred from old prose or backfilled into existing rows.
    """
    from flask import current_app
    from sqlalchemy.exc import SQLAlchemyError
    from .models import db, Vehicle
    today = datetime.now(ZoneInfo('Asia/Tokyo')).date()
    as_of = today if as_of is None else as_of
    company, vehicle_id = vehicle.company_code, vehicle.id
    output = {'version': VERSION, 'company_code': company, 'vehicle_id': vehicle_id,
        'bundles': [], 'missing_conditions': []}
    try:
        selections = _selections(selections)
        if type(as_of) is not date or as_of > today:
            raise EvidenceUnavailable('メーカー原本と観測の取得基準日を確認要')
        if db.session.new or db.session.dirty or db.session.deleted:
            raise EvidenceUnavailable('未保存変更があるためメーカー原本と元観測の照合を保留しています')
        # Independent identity map/transaction; never refresh or flush caller rows.
        with current_app._get_current_object().app_context():
            with db.session.no_autoflush:
                fresh = Vehicle.query.filter_by(company_code=company, id=vehicle_id, deleted=False).first()
                if fresh is None:
                    raise EvidenceUnavailable('会社・車両の現在登録を確認できません')
                output['bundles'] = _read(fresh, selections, as_of)
    except EvidenceUnavailable as error:
        output['missing_conditions'] = [str(error)]
    except (SQLAlchemyError, KeyError, ValueError, TypeError, AttributeError, OverflowError):
        output['missing_conditions'] = ['メーカー原本・採用・元観測の保存内容を読み取れません']
    return output


STATEMENTS = (
    ('actual_observation_confirmed', '選択した記録は架空・取込テスト用ではなく、実際の現車観測であることを確認しました'),
    ('vehicle_scope_confirmed', '原文の対象機器・型式・仕様・例外条件が、この車両と選択した観測対象に適用することを確認しました'),
    ('condition_match_confirmed', '引用した発動条件が、選択した現車観測で現在成立していることを確認しました'),
    ('immediate_action_confirmed', '引用した対応を、その条件下でメーカーが即時に求めていることを確認しました'),
)
MAX_KNOWLEDGE_OPTIONS = 100


def manufacturer_confirmation_options(vehicle, observation_input_ref, *, as_of=None):
    """Offer current adopted originals for a user-selected observation, not facts.

    No textual/target matching selects a rule for the user. If the bounded set is
    incomplete, no partial set masquerades as an exhaustive manufacturer search.
    """
    from flask import current_app
    from sqlalchemy.exc import SQLAlchemyError
    from .models import db, Vehicle, VehicleMaintenanceKnowledge as Knowledge
    from .knowledge import assess_public_maintenance_rule_adoption
    output = {'version': VERSION, 'company_code': vehicle.company_code, 'vehicle_id': vehicle.id,
        'bundles': [], 'missing_conditions': []}
    as_of = datetime.now(ZoneInfo('Asia/Tokyo')).date() if as_of is None else as_of
    try:
        if (type(as_of) is not date or not isinstance(observation_input_ref, str)
                or not OBSERVATION_REF.fullmatch(observation_input_ref)):
            raise EvidenceUnavailable('確認対象の元観測を選択してください')
        if db.session.new or db.session.dirty or db.session.deleted:
            raise EvidenceUnavailable('未保存変更があるためメーカー原本の候補照合を保留しています')
        company, vehicle_id = vehicle.company_code, vehicle.id
        with current_app._get_current_object().app_context():
            with db.session.no_autoflush:
                fresh = Vehicle.query.filter_by(company_code=company, id=vehicle_id, deleted=False).first()
                if fresh is None:
                    raise EvidenceUnavailable('会社・車両の現在登録を確認できません')
                rows = Knowledge.query.filter_by(company_code=company, source_kind='メーカー公式資料').filter(
                    Knowledge.status.in_({'draft', 'active'})).order_by(Knowledge.id).limit(MAX_KNOWLEDGE_OPTIONS + 1).all()
                if len(rows) > MAX_KNOWLEDGE_OPTIONS:
                    raise EvidenceUnavailable('メーカー資料の候補が読取上限を超えています')
                reader = current_app.extensions.get('maintenance_knowledge_import', {}).get('get_vehicle_scopes')
                if reader is None:
                    raise EvidenceUnavailable('メーカー原本・採用の既存readerを利用できません')
                _, evidences = reader(rows, include_rule_evidence=True)
                aliases = {'トラック': 'truck', '大型トラック': 'truck', '中型トラック': 'truck', '小型トラック': 'truck',
                    'トラクタ': 'truck', 'トラクター': 'truck', 'バス': 'bus'}
                categories = {aliases[value] for value in (fresh.body_type, fresh.type) if value in aliases}
                category = next(iter(categories)) if len(categories) == 1 else None
                selections = []
                for row in rows:
                    evidence = evidences.get(row.id, {})
                    for rule in evidence.get('rules', []):
                        adoption = assess_public_maintenance_rule_adoption(fresh, row, evidence, rule, vehicle_category=category)
                        if adoption['status'] != 'eligible':
                            continue
                        selections.append({'knowledge_source_id': f'knowledge:{row.id}',
                            'rule_key': _rule_key(row.id, evidence['document_id'], evidence['document_checksum'], rule),
                            'observation_input_ref': observation_input_ref})
                if not selections:
                    raise EvidenceUnavailable('この車両に採用可能なメーカー原本の規則を確認できません。即時対応は推定しません')
                if len(selections) > MAX_SELECTIONS:
                    raise EvidenceUnavailable('確認できるメーカー規則の候補数を超えています')
                return read_manufacturer_priority_evidence(fresh, selections, as_of=as_of)
    except EvidenceUnavailable as error:
        output['missing_conditions'] = [str(error)]
    except (SQLAlchemyError, KeyError, ValueError, TypeError, AttributeError, OverflowError):
        output['missing_conditions'] = ['メーカー原本・採用の候補を読み取れません']
    return output


def _preview(bundle, selection):
    """Pure exact-range normalization; never interprets words as immediate facts."""
    observation = bundle['observation']
    if observation['registered_status'] not in {'対応待ち', '整備中'}:
        raise EvidenceUnavailable('この元観測は現在の未解消指摘ではありません。解消や再確認待ちを現在条件へ読み替えません')
    rule = bundle['manufacturer']['rule']
    passages = [{'source_page': rule['source_page'], 'source_quote': rule['source_quote']},
        *[{key: entry[key] for key in ('source_page', 'source_quote')} for entry in rule['semantic_review']['evidence']]]
    selected_quotes = {}
    for name in ('condition_quote', 'action_quote'):
        value = selection.get(name)
        if not isinstance(value, str) or not value.strip() or len(value) > 2000:
            raise EvidenceUnavailable('発動条件と即時対応の原文範囲をそれぞれ指定してください')
        value = value.strip()
        matches = [entry for entry in passages if value in entry['source_quote']]
        if not matches:
            raise EvidenceUnavailable('指定した発動条件または即時対応が、照合済み原文の範囲に含まれていません')
        selected_quotes[name] = {'quote': value, 'source_pages': sorted(set(entry['source_page'] for entry in matches))}
    selection = {key: selection[key] for key in ('knowledge_source_id', 'rule_key', 'observation_input_ref')}
    selection.update({key: value['quote'] for key, value in selected_quotes.items()})
    source_ids = [observation['source_id'], bundle['manufacturer']['knowledge_source_id']]
    source_links = deepcopy(bundle['source_links'])
    original_url = source_links[bundle['manufacturer']['knowledge_source_id']]
    answer = observation['reported_answer']
    vehicle_facts = bundle['vehicle_facts']
    manufacturer = bundle['manufacturer']
    display_sources = [
        {'label': '発動条件として選択した原文（p.' + ','.join(map(str, selected_quotes['condition_quote']['source_pages'])) + '）', 'text': selected_quotes['condition_quote']['quote'], 'url': original_url},
        {'label': '即時対応として選択した原文（p.' + ','.join(map(str, selected_quotes['action_quote']['source_pages'])) + '）', 'text': selected_quotes['action_quote']['quote'], 'url': original_url},
        {'label': '原文と対象車両の条件', 'text': '資料: ' + str(manufacturer['knowledge']['title'])
            + '\n資料の対象部位: ' + str(manufacturer['knowledge']['part_name'])
            + '\n登録メーカー: ' + str(vehicle_facts.get('manufacturer') or '（未登録）')
            + '\n登録型式: ' + str(vehicle_facts.get('model_code') or '（未登録）')
            + '\nエンジン型式: ' + str(vehicle_facts.get('engine_code') or '（未登録）')
            + '\n規則に残された条件: ' + rule['conditions'], 'url': original_url},
        {'label': '対象の元観測', 'text': observation['target'] + '\n記録日時: ' + observation['reported_at']
            + '\n登録状態: ' + str(observation['registered_status']) + '\n回答: ' + str(answer.get('value', ''))
            + '\nコメント: ' + str(answer.get('comment') or '（記載なし）'), 'url': source_links[observation['source_id']]},
    ]
    for transition in observation['transitions'][-2:]:
        display_sources.append({'label': '整備の原記録' if transition['kind'] == 'repair' else '再確認の原記録',
            'text': transition['performed_at'] + '\n' + transition['note'], 'url': source_links[observation['source_id']]})
    result = {'kind': 'manufacturer_immediate', 'selection': selection, 'subject': observation['target'],
        'source_ids': source_ids, 'source_links': source_links, 'display_sources': display_sources, 'sources': {'bundle': deepcopy(bundle), 'selected_quotes': selected_quotes},
        'statements': [{'key': key, 'label': label} for key, label in STATEMENTS]}
    result['fingerprint'] = fingerprint(result)
    return result


def preview_manufacturer_confirmation(vehicle, selection, *, as_of=None):
    """Current source preview for the common authenticated confirmation workflow.

    Raises ValueError with a displayable reason on incomplete/changed input. This
    preview does not mean any statement was confirmed. Common storage owns actor,
    source-version concurrency, four affirmative statements, withdrawal and audit.
    """
    required = {'knowledge_source_id', 'rule_key', 'observation_input_ref', 'condition_quote', 'action_quote'}
    if not isinstance(selection, dict) or not required <= selection.keys() or selection.keys() - required - {'expected_fingerprint'}:
        raise EvidenceUnavailable('メーカー原本・元観測・原文範囲の選択を確認要')
    query = {key: value for key, value in selection.items() if key not in {'condition_quote', 'action_quote'}}
    result = read_manufacturer_priority_evidence(vehicle, [query], as_of=as_of)
    if len(result['bundles']) != 1:
        raise EvidenceUnavailable('、'.join(result['missing_conditions']) or 'メーカー原本と元観測を照合できません')
    return _preview(result['bundles'][0], selection)


def manufacturer_confirmation_inputs(preview, *, event_id, confirmed_on):
    """Map a CURRENT common-workflow-verified confirmation, never posted JSON.

    The caller MUST first use active_priority_confirmations, which validates all
    statements, authenticated actor, audit/version chain, withdrawal, original
    sources and current preview fingerprint. An unchecked preview is not consent.
    The event's confirmation time is audit evidence, not a new symptom timestamp.
    """
    from vehicle_priority_assessment import Scope, Evidence, Reference, Fact
    if type(event_id) is not int or event_id <= 0 or type(confirmed_on) is not date:
        raise EvidenceUnavailable('確認監査の本人識別・日時を確認要')
    if not isinstance(preview, dict) or preview.get('kind') != 'manufacturer_immediate':
        raise EvidenceUnavailable('メーカー即時条件の確認対象を確認要')
    bundle = preview['sources']['bundle']
    if _preview(bundle, preview['selection']) != preview:
        raise EvidenceUnavailable('メーカー即時条件の確認原文と保存版が一致しません')
    observation, manufacturer = bundle['observation'], bundle['manufacturer']
    observed_on = datetime.fromisoformat(observation['reported_at']).date()
    if observed_on > confirmed_on:
        raise EvidenceUnavailable('観測より前の確認日時を現車条件の証明にしません')
    scope = Scope(bundle['company_code'], bundle['vehicle_id'], observation['target'])
    subject_event = f"{observation['source_id']}:defect:{observation['defect_no']}"
    audit_id = f'priority_confirmation:{event_id}'
    reference_id = 'manufacturer:' + manufacturer['rule_key']
    condition = preview['selection']['condition_quote']
    action = preview['selection']['action_quote']
    knowledge = manufacturer['knowledge']
    evidence = {
        observation['source_id']: Evidence(observation['source_id'], scope, observed_on, subject_event,
            '選択された現車観測: ' + observation['target'], True, 'record', 'open'),
        audit_id: Evidence(audit_id, scope, confirmed_on, subject_event,
            '人が確認したメーカー条件: ' + condition + '\n即時要求対応: ' + action, True, 'record', 'current')}
    reference = Reference(reference_id, manufacturer['source_url'], knowledge['manufacturer'] or knowledge['provider'],
        knowledge['title'], manufacturer['document_checksum'], condition + '\n' + action, 'manufacturer', True, True, True)
    return {'scope': scope, 'event_id': subject_event,
        'facts': (Fact('manufacturer_immediate_condition', (observation['source_id'], audit_id), True, (reference_id,)),),
        'evidence': evidence, 'references': {reference_id: reference},
        'missing_conditions': ('メーカー即時条件の任意確認に基づく対応優先度です。運行可否は判定していません',),
        'manufacturer_reference': {'url': reference.url, 'issuer': reference.issuer, 'title': reference.title,
            'version': reference.version, 'condition_quote': condition, 'action_quote': action,
            'selected_quotes': deepcopy(preview['sources']['selected_quotes']), 'confirmation_event_id': event_id}}


def manufacturer_confirmation_terminal(vehicle, saved_preview_or_selection, *, as_of=None):
    """Only an exact, authentically repaired/rechecked original can be suppressed.

    The common adapter owns saved confirmation identity and company scope. This
    reader does not turn missing sources, changed manufacturer text, guessed
    resolution, or a bare status into withdrawal. Manufacturer withdrawal is not
    required to recognize a true resolution of the selected inspection event.
    """
    from flask import current_app
    from sqlalchemy.exc import SQLAlchemyError
    from .models import db, Vehicle
    try:
        today = datetime.now(ZoneInfo('Asia/Tokyo')).date()
        as_of = today if as_of is None else as_of
        if type(as_of) is not date or as_of > today:
            return None
        if not isinstance(saved_preview_or_selection, dict):
            return None
        selection = saved_preview_or_selection.get('selection', saved_preview_or_selection)
        if not isinstance(selection, dict):
            return None
        query = {key: selection[key] for key in ('knowledge_source_id', 'rule_key', 'observation_input_ref')}
        _selections([query])
        if db.session.new or db.session.dirty or db.session.deleted:
            return None
        company, vehicle_id = vehicle.company_code, vehicle.id
        saved_sources = saved_preview_or_selection.get('sources', {})
        saved_bundle = saved_sources.get('bundle') if isinstance(saved_sources, dict) else None
        if saved_bundle is not None and (not isinstance(saved_bundle, dict)
                or saved_bundle.get('company_code') != company or saved_bundle.get('vehicle_id') != vehicle_id
                or saved_bundle.get('observation', {}).get('input_ref') != query['observation_input_ref']):
            return None
        with current_app._get_current_object().app_context():
            with db.session.no_autoflush:
                fresh = Vehicle.query.filter_by(company_code=company, id=vehicle_id, deleted=False).first()
                if fresh is None:
                    return None
                result = read_inspection_observation_sources(fresh, [query['observation_input_ref']], as_of=as_of)
                if (len(result['observations']) != 1
                        or result['observations'][0]['resolved_after_repair_and_recheck'] is not True):
                    return None
                return {'status': 'resolved', 'reason': '元観測の整備後・異常なし再確認を原版連鎖で確認',
                    'sources': result}
    except (SQLAlchemyError, KeyError, ValueError, TypeError, AttributeError, OverflowError):
        return None
