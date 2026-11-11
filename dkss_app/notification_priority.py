"""Read-only links from an owned notification to the same saved proposal event.

Notification text, delivery, read state, workflow and ordering are untouched.
No AI input rebuild, network call or persistent cache is used here.
"""
from datetime import datetime
import re
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo

from flask import has_request_context, request, session, url_for

from vehicle_priority_inputs import display_target, fingerprint
from vehicle_priority_projection import InspectionSnapshot, inspection_provenance, priority_order_key


def _positive_id(value):
    return type(value) is int and 0 < value <= 2147483647


def _same_target(note, row, fragment):
    """The displayed target and stored event must identify the same inspection."""
    parsed = urlsplit(note.link or '')
    if (parsed.scheme or parsed.netloc or parsed.fragment != fragment
            or parsed.path.rstrip('/') != f'/vehicle/checklists/{row.checklist_id}'):
        return False
    try:
        pairs = parse_qsl(parsed.query, max_num_fields=20)
        for key, expected in (('vehicle_record_id', row.vehicle_record_id),
                              ('year', row.year), ('month', row.month), ('active_day', row.day)):
            values = [v for k, v in pairs if k == key]
            if (len(values) != 1 or not re.fullmatch(r'[0-9]{1,10}', values[0])
                    or int(values[0]) != int(expected)):
                return False
    except (TypeError, ValueError):
        return False
    return True


def _event_reference(note, row, proof, context):
    from . import models as m, notifications
    from .serialization import safe_json_dict
    if (not isinstance(proof, dict) or proof.get('version') != 'registered-inspection-priority-source-v1'
            or not _positive_id(proof.get('vehicle_id')) or not _positive_id(proof.get('record_id'))
            or proof.get('company_code') != row.company_code
            or proof.get('vehicle_id') != row.vehicle_record_id or proof.get('record_id') != row.id
            or proof.get('inspection_on') != f'{row.year}-{str(row.month).zfill(2)}-{str(row.day).zfill(2)}'):
        return None
    if context.get('action') == 'operation_result':
        if not _positive_id(context.get('event_id')) or not _same_target(note, row, 'vehicle-flow-judgment'):
            return None
        event = m.db.session.query(m.ChecklistEvent.detail_json).filter_by(
            id=context['event_id'], company_code=row.company_code, result_type='vehicle',
            result_id=row.id, event_type='運行判断').first()
        judgment = safe_json_dict(event.detail_json).get('judgment') if event else None
        instruction = proof.get('instruction')
        if (not isinstance(judgment, dict) or not isinstance(instruction, dict)
                or judgment.get('status') != '運行不可'
                or note.title != '車両の運行判断：運行不可'
                or fingerprint(judgment) != instruction.get('judgment_fingerprint')
                or instruction.get('input_ref') != f'inspection:{row.id}:instruction:{fingerprint(judgment)[:24]}'):
            return None
        return instruction.get('input_ref'), '既存の運行判断の確認'
    if context or not note.title.endswith('：再確認待ち'):
        return None
    match = re.fullmatch(r'vehicle-flow-defect-([1-9][0-9]{0,9})-([1-9][0-9]{0,9})',
                         urlsplit(note.link or '').fragment)
    if (not match or int(match[1]) != row.id or not _positive_id(int(match[2]))
            or not _same_target(note, row, match[0])
            or notifications.get_recheck_notification_state(note).get('workflow_status') != 'pending'):
        return None
    judgment = safe_json_dict(row.operation_judgment_json)
    defects = judgment.get('defects')
    matches = [d for d in defects if isinstance(d, dict) and type(d.get('defect_no')) is int
               and d['defect_no'] == int(match[2])] if isinstance(defects, list) else []
    if len(matches) != 1 or matches[0].get('status') != '再確認待ち':
        return None
    repair = matches[0].get('repair')
    if (not isinstance(repair, dict) or not note.created_at
            or (repair.get('notification_created_at') or repair.get('recorded_at')) != note.created_at):
        return None
    # Legacy repair notices have second-resolution timestamps, not an event ID.
    # Do not choose a version when two owned notices share that binding.
    duplicates = m.db.session.query(m.Notification.id).filter_by(company_code=note.company_code,
        owner_identity=note.owner_identity, title=note.title, link=note.link,
        created_at=note.created_at).limit(2).all()
    if len(duplicates) != 1:
        return None
    current = inspection_provenance(InspectionSnapshot(row.company_code, row.vehicle_record_id,
        row.id, f'{row.year}-{str(row.month).zfill(2)}-{str(row.day).zfill(2)}', row.status,
        row.checklist_snapshot_json, row.answers_json, row.operation_judgment_json,
        datetime.now(ZoneInfo('Asia/Tokyo')).date()))
    def selected(value):
        events = value.get('events') if isinstance(value, dict) else None
        return [e for e in events if isinstance(e, dict) and type(e.get('defect_no')) is int
                and e['defect_no'] == int(match[2])] if isinstance(events, list) else []
    original, latest = selected(proof), selected(current)
    identity = ('defect_no', 'item_no', 'item_code', 'item_content', 'item_definition_fingerprint',
                'reported_at', 'answer_fingerprint', 'input_ref')
    if (len(original) != 1 or len(latest) != 1
            or any(original[0].get(k) != latest[0].get(k) for k in identity)):
        return None
    return original[0].get('input_ref'), display_target(original[0].get('item_content'))


def _saved_projection(vehicle):
    from . import models as m
    from .analysis_feedback import latest_vehicle_analysis_feedback
    from .priority_consumers import identify_priority_proposals
    from .priority_projection import project_registered_priorities
    from .serialization import safe_json_dict
    cache = request.environ.setdefault('dkss.notification_priority_projections', {})
    key = (vehicle.company_code, vehicle.id)
    if key not in cache:
        state = m.db.session.query(m.VehicleKarteAnalysis.result_json).filter_by(
            company_code=vehicle.company_code, vehicle_record_id=vehicle.id).first()
        bundle = safe_json_dict(state.result_json) if state else {}
        analysis, sources = bundle.get('analysis'), bundle.get('sources')
        proposals = analysis.get('recommendations') if isinstance(analysis, dict) else None
        if (not isinstance(proposals, list) or len(proposals) > 1000 or not isinstance(sources, dict)
                or any(not isinstance(p, dict) or not isinstance(p.get('source_ids', []), list)
                       for p in proposals)):
            cache[key] = ({}, {}, {})
        else:
            projected = project_registered_priorities(identify_priority_proposals(analysis), vehicle, sources)
            feedback = {r.proposal_key: (r.proposal_revision, r.status)
                        for r in latest_vehicle_analysis_feedback(vehicle.company_code, vehicle.id)}
            cache[key] = (projected, sources, feedback)
    return cache[key]


def related_notification_priority(notification):
    """Same owner/company/vehicle/event/reference only; unsupported history is absent."""
    from . import models as m, notifications
    from .account_identity import owns_notification, notification_owner_clause
    from .serialization import safe_json_dict
    from sqlalchemy.exc import SQLAlchemyError
    if (not has_request_context() or not owns_notification(notification)
            or not _positive_id(notification.id) or m.db.session.new
            or m.db.session.dirty or m.db.session.deleted):
        return None
    hint = safe_json_dict(notification.workflow_context_json)
    if ((hint and hint.get('action') != 'operation_result')
            or (not hint and not str(notification.title or '').endswith('：再確認待ち'))):
        return None
    try:
        with m.db.session.no_autoflush:
            n = m.Notification
            values = m.db.session.query(n.id, n.company_code, n.owner_identity, n.target_username,
                n.title, n.message, n.link, n.created_at, n.workflow_context_json).filter(
                    n.id == notification.id, n.company_code == session.get('company_code'),
                    notification_owner_clause(), n.deleted_at.is_(None)).first()
            if values is None:
                return None
            note = SimpleNamespace(**values._mapping)
            context = safe_json_dict(note.workflow_context_json)
            if context and context.get('action') != 'operation_result':
                return None
            if not context and not note.title.endswith('：再確認待ち'):
                return None
            result_type, result_id = notifications.get_notification_result_reference(note)
            if result_type != 'vehicle' or not _positive_id(result_id):
                return None
            r = m.VehicleChecklistResult
            row = m.db.session.query(r.id, r.company_code, r.vehicle_record_id, r.checklist_id,
                r.year, r.month, r.day, r.status, r.checklist_snapshot_json, r.answers_json,
                r.operation_judgment_json).filter_by(id=result_id, company_code=note.company_code).first()
            if row is None:
                return None
            vehicle = m.db.session.query(m.Vehicle.id, m.Vehicle.company_code, m.Vehicle.gross_vehicle_weight).filter_by(
                company_code=note.company_code, id=row.vehicle_record_id, deleted=False).first()
            if vehicle is None:
                return None
            projected, sources, feedback = _saved_projection(vehicle)
            sid = f'inspection:{result_id}'
            source = sources.get(sid)
            binding = _event_reference(note, row, source.get('priority_provenance') if isinstance(source, dict) else None, context)
            if binding is None:
                return None
            ref, target = binding
            if not isinstance(ref, str) or not ref or not target:
                return None
            items = []
            for proposal in sorted(projected.get('recommendations', []), key=priority_order_key):
                if (proposal.get('priority_input_ref') != ref or proposal.get('target') != target
                        or sid not in proposal.get('source_ids', [])
                        or {s for s in proposal.get('source_ids', []) if isinstance(s, str) and s.startswith('inspection:')} != {sid}
                        or proposal.get('category') != '整備・点検'):
                    continue
                assessment = proposal.get('priority_assessment') or {}
                label = assessment.get('label')
                if label not in ('高', '中', '低'):
                    continue
                key, revision = proposal['proposal_id'], proposal['proposal_revision']
                if feedback.get(key) in ((revision, 'completed'), (revision, 'dismissed')):
                    continue
                score = assessment.get('effective_score')
                score = score if type(score) is int else None
                items.append(dict(proposal_id=key, proposal_revision=revision, label=label, score=score,
                    badge=label + (f' · {score}点' if score is not None else '（保存区分・根拠を確認）'),
                    subject=assessment.get('subject_label') or proposal.get('target') or '',
                    missing_conditions=assessment.get('missing_conditions', []),
                    url=url_for('vehicle_karte_analysis', vehicle_record_id=vehicle.id) + '#proposal=' + key))
            if not items:
                return None
            return dict(items=items[:5], count=len(items),
                summary='関連する確認・対応優先度：' + '、'.join(x['badge'] for x in items[:3])
                        + (f' ほか{len(items) - 3}件' if len(items) > 3 else ''),
                note='同じ事象に結び付いた保存提案を現在の登録根拠で表示しています。通知時点の点数ではありません。点数・区分は試行値で、運行可否は人が判断します。低は安全確認済みではありません。')
    except (SQLAlchemyError, TypeError, ValueError, KeyError, AttributeError):
        # No retry, rollback or fallback score; saved notification fields are untouched.
        return None
