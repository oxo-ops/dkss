"""Read-only bridge from adopted manufacturer timing to response priority.

An opaque server offer binds the original rule, component and baseline records.
Current adoption, all same-vehicle history and mileage competitors are reread in
an independent clean session. AI prose and saved calculation flags are not input
facts. Manufacturer periodic rules never establish a legal or operation floor.
"""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import hashlib
import json
import re

from vehicle_priority_assessment import Candidate, Evidence, Reference, Scope, TimingFact, assess_priority
from vehicle_priority_inputs import display_target

VERSION = 'registered-adopted-timing-priority-v1'
PROOF_KEY = 'priority_timing_provenance'
MAX_HISTORY_ROWS = 5000
MAX_PERIODIC_ROWS = 100


class TimingReadLimit(ValueError):
    """A complete current snapshot cannot be formed within the read budget."""

RULE_KEYS = ('action', 'criteria', 'relation', 'cycle', 'model_codes', 'engine_codes',
             'conditions', 'source_page', 'source_quote')
VEHICLE_KEYS = ('manufacturer', 'model_code', 'engine_code', 'first_registration_date',
                'body_type', 'type', 'gross_vehicle_weight', 'max_payload')


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), default=str).encode()).hexdigest()


def _day(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) and len(value) == 10 else None
    except ValueError:
        return None


def _rule_key(knowledge_id, document_id, checksum, rule):
    identity = {'knowledge_id': knowledge_id, 'document_id': document_id,
        'document_checksum': checksum, 'rule': {key: rule[key] for key in RULE_KEYS}}
    # Exactly the identity serialization used by the existing adoption pipeline.
    return hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False,
        default=str).encode()).hexdigest()


def _proof(vehicle, knowledge, rule, timing, sources):
    adoption = rule.get('analysis_adoption') or {}
    evidence = knowledge.get('maintenance_rule_evidence') or {}
    if (knowledge.get('source_kind') != 'メーカー公式資料'
            or adoption.get('status') != 'adopted_for_analysis'
            or rule.get('adoption_assessment', {}).get('status') != 'eligible'
            or rule.get('vehicle_applicability', {}).get('status') != 'conditions_matched'
            or timing.get('calculation_permitted') is not True
            or rule.get('action') not in {'replace', 'inspect'}):
        return None
    checksum = adoption.get('document_checksum')
    sid = knowledge.get('source_id')
    if (not isinstance(checksum, str) or not re.fullmatch('[a-f0-9]{64}', checksum)
            or checksum != evidence.get('document_checksum')
            or adoption.get('knowledge_source_id') != sid
            or adoption.get('vehicle_source_id') != f'vehicle:{vehicle.id}'
            or not isinstance(sid, str) or not re.fullmatch(r'knowledge:[1-9][0-9]*', sid)):
        return None
    try:
        key = _rule_key(int(sid.split(':')[1]), adoption['document_id'], checksum, rule)
    except (KeyError, ValueError, TypeError):
        return None
    if adoption.get('rule_key') != key:
        return None
    prefix = 'part:' if rule['action'] == 'replace' else 'periodic:'
    ids = timing.get('source_ids')
    if not isinstance(ids, list) or any(not isinstance(v, str) for v in ids):
        return None
    baseline_ids = sorted(v for v in ids if v.startswith(prefix))
    if not baseline_ids or any(not isinstance(sources.get(v, {}).get('snapshot'), dict) for v in baseline_ids):
        return None
    baseline = {sid: sources[sid]['snapshot'] for sid in baseline_ids}
    # Snapshot hashes preserve replacement/inspection scope, original evidence,
    # item index, completion and record dates. Current elapsed values are separate.
    proof = {'version': VERSION, 'company_code': vehicle.company_code,
        'vehicle_id': vehicle.id, 'target': knowledge.get('part_name'),
        'action': rule['action'], 'knowledge_source_id': sid, 'rule_key': key,
        'document_checksum': checksum, 'source_url': adoption.get('source_url'),
        'rule_fingerprint': _hash({k: v for k, v in rule.items() if k not in {
            'analysis_adoption', 'timing_facts', 'adoption_assessment', 'vehicle_applicability'}}),
        'vehicle_fingerprint': _hash({k: getattr(vehicle, k, None) for k in VEHICLE_KEYS}),
        'baseline_fingerprint': _hash(baseline), 'baseline_source_ids': baseline_ids,
        'source_ids': sorted(set(ids))}
    if not isinstance(proof['target'], str) or not proof['target'].strip() or not proof['source_url']:
        return None
    proof['ref'] = 'timing:' + _hash(proof)
    return proof


def attach_timing_priority_inputs(vehicle, payload, sources):
    """Offer only existing adopted/calculable rules during ordinary generation.

    Mutates this generation's payload/sources only. No DB, persisted result,
    proposal identity, or human operation decision is changed here.
    """
    from .analysis import calculate_adopted_maintenance_rule_timing
    for knowledge in payload.get('maintenance_knowledge', []):
        offers, proofs = [], []
        for rule in knowledge.get('maintenance_rule_evidence', {}).get('rules', []):
            timing = calculate_adopted_maintenance_rule_timing(rule, knowledge.get('part_name'),
                payload.get('preventive_facts'), payload.get('summary'))
            proof = _proof(vehicle, knowledge, rule, timing, sources)
            if proof is None:
                continue
            offers.append({'ref': proof['ref'], 'kind': 'adopted_timing',
                'source_ids': proof['source_ids'], 'target': proof['target'],
                'display_target': display_target(proof['target'])})
            proofs.append(proof)
        knowledge['priority_inputs'] = offers
        sid = knowledge.get('source_id')
        if sid in sources and proofs:
            sources[sid][PROOF_KEY] = proofs


def _current_inputs(vehicle, knowledge_ids, as_of):
    """Read all scoped timing facts, not only originally cited records.

    Must run in the fresh app context created by the public batch adapter.
    Reuses the ordinary fact builders without AI, peers, cache, or notifications.
    """
    from flask import current_app
    from . import analysis as a, knowledge as k, models as m
    from .vehicle_operations import get_vehicle_canonical_operations
    from vehicle_analysis_repository import VehicleAnalysisInputRepository
    scope = {'company_code': vehicle.company_code, 'vehicle_record_id': vehicle.id}
    models = (m.VehicleMaintenanceRecord, m.VehicleOperationRecord, m.VehiclePartReplacement,
              m.VehiclePatrol, m.VehiclePeriodicInspectionRecord, m.VehicleDrivingReportRecord)
    counts = {model: model.query.filter_by(**scope).count() for model in models}
    if sum(counts.values()) > MAX_HISTORY_ROWS or counts[m.VehiclePeriodicInspectionRecord] > MAX_PERIODIC_ROWS:
        raise TimingReadLimit('現在履歴の読取上限を超えたためメーカー時期の算定を保留しています。部分履歴では計算しません')
    repository = VehicleAnalysisInputRepository(maintenance=m.VehicleMaintenanceRecord,
        operations=m.VehicleOperationRecord, parts=m.VehiclePartReplacement, defects=m.VehiclePatrol,
        periodic=m.VehiclePeriodicInspectionRecord, canonical_operations=get_vehicle_canonical_operations)
    rows = repository.load(vehicle, as_of)
    if (sum(len(getattr(rows, key)) for key in ('maintenance','operations','parts','defects','periodic'))
            > MAX_HISTORY_ROWS or len(rows.periodic) > MAX_PERIODIC_ROWS):
        raise TimingReadLimit('現在履歴の読取上限を超えたためメーカー時期の算定を保留しています。部分履歴では計算しません')
    summary = a.build_vehicle_karte_analysis_summary(rows.maintenance, rows.operations, rows.parts,
        rows.defects, as_of.isoformat(), as_of.isoformat(), periodic_records=rows.periodic)
    maintenance, parts, _ = a.filter_vehicle_maintenance_factual_history(rows.maintenance, rows.parts)
    parents = {row.id: row for row in maintenance}
    linked = m.VehiclePartReplacementSource.query.filter_by(company_code=vehicle.company_code).filter(
        m.VehiclePartReplacementSource.maintenance_record_id.in_(parents)).all() if parents else []
    linked = {row.replacement_id: row for row in linked}
    records, sources = [], {}
    for part in parts:
        parent = parents.get(part.maintenance_record_id)
        if parent is None or (_day(part.replacement_date) and _day(part.replacement_date) > as_of):
            continue
        record = {'source_id': f'part:{part.id}', 'date': part.replacement_date or None,
            'replacement_document_evidence': a.build_vehicle_part_document_evidence(part, parent, linked.get(part.id)),
            'type': '部品交換', 'content': str(part.part_name or '').strip()[:400],
            'part_number': str(part.part_number or '').strip()[:400], 'mileage': part.mileage,
            'quantity': part.quantity, 'notes': str(part.notes or '').strip()[:400],
            'status': str(parent.status or '').strip()[:400], 'completion_date': parent.completion_date}
        # Ordinary generation turns malformed dates into missing, never a date.
        record['date'] = record['date'] if _day(record['date']) else None
        records.append(record); sources[record['source_id']] = {'snapshot': record}
    for row in rows.periodic:
        if a.periodic_inspection_synthetic_evidence(row) or (_day(row.inspection_date) and _day(row.inspection_date) > as_of):
            continue
        draft = m.VehicleDocumentImportDraft.query.filter_by(id=row.source_draft_id,
            company_code=vehicle.company_code, document_type='inspection').first()
        details = a.build_periodic_inspection_ai_details(row, draft)
        record = {'source_id': f'periodic:{row.id}', 'date': row.inspection_date if _day(row.inspection_date) else None,
            **details, 'type': '定期点検', 'category': str(row.inspection_type or '').strip()[:400],
            'content': str(row.content or '').strip()[:2000],
            'notes': str(a._dkss_serialization.safe_json_dict(row.details_json).get('notes') or '').strip()[:2000],
            'mileage': row.mileage, 'completion_date': row.completion_date,
            'next_inspection_date': row.next_inspection_date}
        records.append(record); sources[record['source_id']] = {'snapshot': record}
    facts = a.build_vehicle_karte_preventive_facts(vehicle, summary, records)
    reader = current_app.extensions.get('maintenance_knowledge_import', {}).get('get_vehicle_scopes')
    if reader is None:
        return {'summary': summary, 'preventive_facts': facts, 'maintenance_knowledge': []}, sources
    known = m.VehicleMaintenanceKnowledge.query.filter_by(company_code=vehicle.company_code).filter(
        m.VehicleMaintenanceKnowledge.id.in_(knowledge_ids)).all()
    _scopes, evidence_by_id = reader(known, include_rule_evidence=True)
    aliases = {'トラック': 'truck', '大型トラック': 'truck', '中型トラック': 'truck', '小型トラック': 'truck',
        'トラクタ': 'truck', 'トラクター': 'truck', 'バス': 'bus'}
    categories = {aliases[v] for v in (vehicle.body_type, vehicle.type) if v in aliases}
    category = next(iter(categories)) if len(categories) == 1 else None
    knowledge = []
    for row in known:
        evidence = deepcopy(evidence_by_id.get(row.id, {}))
        for rule in evidence.get('rules', []):
            assessed = k.assess_public_maintenance_rule_adoption(vehicle, row, evidence, rule, vehicle_category=category)
            rule['adoption_assessment'] = {'status': assessed['status'], 'reason': assessed['reason']}
            rule['vehicle_applicability'] = k.evaluate_vehicle_maintenance_rule(vehicle, rule,
                document_checksum=evidence.get('document_checksum'), vehicle_category=category)
            if assessed['status'] != 'eligible':
                rule['analysis_adoption'] = {'status': 'held'}
                continue
            rule['analysis_adoption'] = {'status': 'adopted_for_analysis',
                'knowledge_source_id': f'knowledge:{row.id}', 'vehicle_source_id': f'vehicle:{vehicle.id}',
                'document_id': assessed['document_id'], 'document_checksum': assessed['document_checksum'],
                'source_url': assessed['source_url'], 'rule_key': _rule_key(row.id,
                    assessed['document_id'], assessed['document_checksum'], rule)}
            rule['timing_facts'] = a.calculate_adopted_maintenance_rule_timing(rule, row.part_name, facts, summary)
        item = {'source_id': f'knowledge:{row.id}', 'part_name': row.part_name,
            'source_kind': row.source_kind, 'manufacturer': row.manufacturer, 'provider': row.provider,
            'title': row.title, 'maintenance_rule_evidence': evidence}
        knowledge.append(item); sources[item['source_id']] = {'snapshot': item}
    sources[f'vehicle:{vehicle.id}'] = {}
    payload = {'summary': summary, 'preventive_facts': facts, 'maintenance_knowledge': knowledge}
    attach_timing_priority_inputs(vehicle, payload, sources)
    return payload, sources


def _assessment(item, proof, knowledge, rule, summary, as_of, is_current, sources):
    timing = rule['timing_facts']
    relation = rule.get('relation')
    criteria = timing.get('criteria', [])
    if not criteria or relation not in {'single', 'any', 'all'}:
        return None, 'メーカー基準の条件結合と計算対象を確認要'
    scope = Scope(proof['company_code'], proof['vehicle_id'], proof['target'])
    event = proof['ref']
    source_ids = list(proof['source_ids'])
    if any(row.get('metric') == 'distance_km' for row in criteria):
        source_ids += [row['source_id'] for row in summary.get('mileage_reference', {}).get('sources', [])
            if isinstance(row, dict) and isinstance(row.get('source_id'), str)]
    source_ids = tuple(sorted(set(source_ids)))
    rid = 'manufacturer:' + proof['rule_key']
    references = {rid: Reference(rid, proof['source_url'], knowledge.get('manufacturer') or knowledge.get('provider') or '',
        knowledge.get('title') or '', proof['document_checksum'], rule['source_quote'], 'manufacturer', True, True)}
    baseline = min((_day(row.get('baseline_date')) for row in criteria if _day(row.get('baseline_date'))), default=None)
    if baseline is None or baseline > as_of:
        return None, 'メーカー時期基準の起算記録を確認要'
    measured_on = _day(summary.get('current_mileage_date'))
    evidence = {}
    for sid in source_ids:
        observed = _day(sources.get(sid, {}).get('snapshot', {}).get('date'))
        if sid in proof['baseline_source_ids'] and observed is None:
            return None, '起算出典の記録日を確認要'
        if sid.startswith('operation:'):
            observed = measured_on
        # Rule/vehicle IDs describe the dated baseline's applicability, not a
        # claim that a physical observation happened at the current read time.
        observed = observed or baseline
        evidence[sid] = Evidence(sid, scope, observed, event,
            f'採用済み{rule["action"]}基準の起算・適用・記録距離: {sid}', True)
    results, missing = [], []
    for criterion in criteria:
        metric = criterion.get('metric')
        if criterion.get('calculation_permitted') is not True:
            missing.append(f'{metric}: {criterion.get("reason") or "計算条件不足"}')
            continue
        kwargs = {}
        if metric == 'distance_km':
            elapsed, interval = criterion.get('elapsed_km'), criterion.get('threshold')
            if not isinstance(elapsed, (int, float, Decimal)) or not isinstance(interval, (int, float, Decimal)):
                missing.append('走行距離の数値・単位を確認要'); continue
            kwargs = dict(elapsed=float(elapsed), interval=float(interval), elapsed_unit='km', interval_unit='km')
        elif metric in {'period_days', 'period_months'}:
            due, origin = _day(criterion.get('due_date')), _day(criterion.get('baseline_date'))
            if due is None or origin is None or due <= origin:
                missing.append('起算日と暦上の期限を確認要'); continue
            kwargs = dict(due_on=due)
            if metric == 'period_months':
                # Calendar arithmetic supplies an actual due date, but the
                # approved policy does not define a fractional-month 90% rule.
                if (due-as_of).days > 30:
                    missing.append('period_months: 暦月90%の定義は未確定。期限まで30日超のため保存版を保持します')
                    continue
            else:
                kwargs.update(elapsed=(as_of-origin).days, interval=(due-origin).days,
                              elapsed_unit='days', interval_unit='days')
        else:
            missing.append(f'{metric}: 対応時期への接続条件を確認要'); continue
        fact = TimingFact(source_ids, (rid,), True, True, True, True, **kwargs)
        candidate = Candidate(item['proposal_id'], scope, event, timings=(fact,),
            missing_conditions=('登録記録に基づく対応時期です。現在の異常や安全性を判定していません',),
            input_is_current=is_current)
        result = assess_priority(candidate, evidence, references, as_of=as_of)
        if result['factors'][1]['points'] is not None:
            results.append(result)
    if not results or (missing and not (relation == 'any' and any(r['effective_score'] == 35 for r in results))):
        return None, 'メーカー時期基準の不足条件: ' + '、'.join(missing or ['計算可能な条件なし'])
    if relation == 'all' and any(r['factors'][1]['points'] != 35 for r in results):
        return None, 'AND条件は全条件到達のみ接続済みです。到達前の接近度の結合規則は未確定のため保存版を保持します'
    chosen = max(results, key=lambda r: r['factors'][1]['points'])
    chosen['missing_conditions'] = sorted(set(chosen['missing_conditions'] + missing))
    chosen['timing_relation'] = relation
    chosen['timing_criteria'] = deepcopy(criteria)
    chosen['timing_rule_key'] = proof['rule_key']
    chosen['timing_reference'] = {'url': proof['source_url'], 'issuer': references[rid].issuer,
        'title': references[rid].title, 'version': proof['document_checksum'],
        'source_page': rule.get('source_page'), 'quote': rule['source_quote'],
        'authority': 'manufacturer', 'action': rule['action']}
    chosen['timing_origin_on'] = baseline.isoformat()
    chosen['factors'][1]['rule_ids'] = [proof['rule_key']]
    chosen['factors'][1]['combination'] = relation
    # A distance limb has no predicted calendar date. AND does not become due
    # merely because the period limb has reached its calendar date.
    deadlines = sorted(row['due_date'] for row in criteria if _day(row.get('due_date')))
    chosen['earliest_due_on'] = ((max if relation == 'all' else min)(deadlines) if deadlines else None)
    if relation == 'all' and any(row.get('metric') == 'distance_km' for row in criteria):
        chosen['earliest_due_on'] = None
    chosen['evaluation_fingerprint'] = _hash({'assessment': chosen['evaluation_fingerprint'],
        'criteria': criteria, 'relation': relation, 'sources': source_ids})
    return chosen, None


def project_registered_timing_priorities(analysis, vehicle, sources, *, as_of, is_current=None):
    """Return {original array index: (assessment or None, missing reason or None)}."""
    from flask import current_app
    from sqlalchemy.exc import SQLAlchemyError
    from .models import db, Vehicle
    selected = {index: item for index, item in enumerate((analysis or {}).get('recommendations', []))
        if isinstance(item, dict) and isinstance(item.get('priority_input_ref'), str)
        and item['priority_input_ref'].startswith('timing:')}
    if not selected:
        return {}
    blocked = lambda reason: {index: (None, reason) for index in selected}
    if db.session.new or db.session.dirty or db.session.deleted:
        return blocked('未保存変更があるためメーカー時期基準の現在照合を保留しています')
    if type(as_of) is not date:
        return blocked('メーカー時期基準の取得基準日を確認要')
    saved = {}
    for sid, source in sources.items() if isinstance(sources, dict) else []:
        if not isinstance(source, dict):
            continue
        proofs = source.get(PROOF_KEY, [])
        for proof in proofs if isinstance(proofs, list) else []:
            if isinstance(proof, dict) and proof.get('knowledge_source_id') == sid and isinstance(proof.get('ref'), str):
                saved.setdefault(proof['ref'], []).append(proof)
    needed, output = {}, {}
    for index, item in selected.items():
        matches = saved.get(item['priority_input_ref'], [])
        if len(matches) != 1:
            output[index] = (None, '元のメーカー規則・起算事象の明示参照を確認要'); continue
        proof = matches[0]
        if (proof.get('company_code') != vehicle.company_code or proof.get('vehicle_id') != vehicle.id
                or display_target(proof.get('target')) != item.get('target') or not item.get('proposal_id')
                or not item.get('proposal_revision') or not isinstance(item.get('source_ids'), list)
                or any(not isinstance(value, str) for value in item['source_ids'])
                or sorted(item['source_ids']) != proof.get('source_ids')):
            output[index] = (None, '元提案と会社・車両・部位・出典の対応を確認要'); continue
        original_knowledge = sources[proof['knowledge_source_id']].get('snapshot')
        original_evidence = original_knowledge.get('maintenance_rule_evidence') if isinstance(original_knowledge, dict) else None
        original_rules = original_evidence.get('rules') if isinstance(original_evidence, dict) else None
        matched_rules = [rule for rule in original_rules if isinstance(rule, dict)
            and isinstance(rule.get('analysis_adoption'), dict)
            and rule['analysis_adoption'].get('rule_key') == proof.get('rule_key')] if isinstance(original_rules, list) else []
        if (len(matched_rules) != 1 or original_knowledge.get('part_name') != proof.get('target')
                or original_knowledge.get('source_kind') != 'メーカー公式資料'
                or original_evidence.get('document_checksum') != proof.get('document_checksum')
                or _hash({k: v for k, v in matched_rules[0].items() if k not in {
                    'analysis_adoption', 'timing_facts', 'adoption_assessment', 'vehicle_applicability'}})
                    != proof.get('rule_fingerprint')):
            output[index] = (None, '元のメーカー規則の保存原文と証明が一致しません'); continue
        baseline_ids = proof.get('baseline_source_ids')
        if not isinstance(baseline_ids, list) or any(not isinstance(sid, str) for sid in baseline_ids):
            output[index] = (None, '元の起算出典の一覧を確認要'); continue
        original_baselines = {sid: sources[sid].get('snapshot')
            for sid in baseline_ids if isinstance(sources.get(sid), dict)}
        if not original_baselines or _hash(original_baselines) != proof.get('baseline_fingerprint'):
            output[index] = (None, '元の起算記録の保存原文と証明が一致しません'); continue
        needed[index] = proof
    if not needed:
        return output
    if len(needed) > 100:
        return {**output, **{index: (None, 'メーカー時期対象の読取上限を超えています') for index in needed}}
    company, vehicle_id = vehicle.company_code, vehicle.id
    try:
        # A fresh context owns a separate identity map and transaction, leaving
        # the caller's loaded rows and existing transaction untouched.
        with current_app._get_current_object().app_context():
            with db.session.no_autoflush:
                fresh = Vehicle.query.filter_by(company_code=company, id=vehicle_id, deleted=False).first()
                if fresh is None:
                    return {**output, **{index: (None, '会社・車両の現在登録を確認要') for index in needed}}
                ids = {int(proof['knowledge_source_id'].split(':')[1]) for proof in needed.values()}
                payload, current = _current_inputs(fresh, ids, as_of)
                for index, proof in needed.items():
                    current_proofs = current.get(proof['knowledge_source_id'], {}).get(PROOF_KEY, [])
                    if proof not in current_proofs:
                        output[index] = (None, 'メーカー資料版・適用条件・同一部位の最新起算事象が変わったか確認できません。保存版を保持します'); continue
                    knowledge = current[proof['knowledge_source_id']]['snapshot']
                    rules = [rule for rule in knowledge['maintenance_rule_evidence']['rules']
                        if rule.get('analysis_adoption', {}).get('rule_key') == proof['rule_key']]
                    if len(rules) != 1:
                        output[index] = (None, '適用規則の一意な対応を確認要'); continue
                    output[index] = _assessment(selected[index], proof, knowledge, rules[0],
                        payload['summary'], as_of, is_current, current)
    except TimingReadLimit as error:
        output.update({index: (None, str(error)) for index in needed})
    except (SQLAlchemyError, KeyError, ValueError, TypeError, AttributeError, OverflowError):
        output.update({index: (None, 'メーカー時期基準の現在登録と原本条件を読み取れません') for index in needed})
    return output
