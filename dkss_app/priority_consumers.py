"""Shared response-only identities, counts and periodic-source preservation.

No database writes, model calls, new workflow, or operation decisions. A saved
proposal's original source proof is never reconstructed from today's records.
"""
from copy import deepcopy
from datetime import datetime
import json
from zoneinfo import ZoneInfo

from vehicle_priority_projection import project_priority

PERIODIC_PROOF_KEY = 'priority_source_proof'
PERIODIC_PROOF_VERSION = 'periodic-proposal-priority-sources-v1'


def identify_priority_proposals(analysis):
    """Use the existing feedback identity algorithm on untouched saved items."""
    from .analysis_feedback import vehicle_analysis_proposal_ids
    output = deepcopy(analysis) if isinstance(analysis, dict) else {}
    items = output.get('recommendations')
    if not isinstance(items, list):
        return output
    for item in items:
        if isinstance(item, dict):
            key, revision = vehicle_analysis_proposal_ids(item)
            item['proposal_id'], item['proposal_revision'] = key, revision
    return output


def priority_counts(analysis):
    """Counts describe displayed proposals, not faults, vehicles or safety."""
    counts = {'高': 0, '中': 0, '低': 0}
    invalid = 0
    items = analysis.get('recommendations') if isinstance(analysis, dict) else None
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            invalid += 1
            continue
        assessment = item.get('priority_assessment')
        label = assessment.get('label') if isinstance(assessment, dict) else None
        if label in counts:
            counts[label] += 1
        else:
            invalid += 1
    return {'labels': counts, 'invalid_count': invalid,
            'proposal_count': sum(counts.values()) + invalid}


def capture_periodic_priority_sources(company_code, vehicle_id, sources):
    """Capture server sources at generation, separately from model output."""
    if not company_code or type(vehicle_id) is not int or vehicle_id <= 0 or not isinstance(sources, dict):
        raise ValueError('trusted periodic priority source scope required')
    return {'version': PERIODIC_PROOF_VERSION, 'company_code': company_code,
            'vehicle_id': vehicle_id,
            # Match the normal analysis cache: Decimal/date snapshots are
            # stored as strings before crossing the background-job boundary.
            'sources': json.loads(json.dumps(sources, ensure_ascii=False, default=str))}


def bind_periodic_priority_sources(result, proof):
    """New generation only. Legacy stored JSON is never migrated or rewritten."""
    output = deepcopy(result)
    if isinstance(output, dict):
        output.pop(PERIODIC_PROOF_KEY, None)  # Model output can never supply server proof.
        if isinstance(proof, dict):
            output[PERIODIC_PROOF_KEY] = deepcopy(proof)
    return output


def project_periodic_priorities(result, vehicle, current_evidence, *, as_of=None, is_current=True):
    """Return (response, source links), preserving saved labels when unbound."""
    from .priority_projection import project_registered_priorities
    as_of = as_of or datetime.now(ZoneInfo('Asia/Tokyo')).date()
    output = deepcopy(result) if isinstance(result, dict) else {}
    proof = output.pop(PERIODIC_PROOF_KEY, None)
    identified = identify_priority_proposals(output)
    valid = (isinstance(proof, dict) and proof.get('version') == PERIODIC_PROOF_VERSION
             and proof.get('company_code') == vehicle.company_code
             and proof.get('vehicle_id') == vehicle.id and isinstance(proof.get('sources'), dict))
    if valid:
        sources = proof['sources']
        projected = project_registered_priorities(identified, vehicle, sources, as_of=as_of, is_current=is_current)
    else:
        # Render existing links if available, but never use them as the missing
        # original generation proof or bind old output to a newly-created event.
        sources = deepcopy(current_evidence) if isinstance(current_evidence, dict) else {}
        projected = project_priority(identified, {}, [], company_code=vehicle.company_code,
            vehicle_id=vehicle.id, as_of=as_of, is_current=True,
            unavailable_reason='この保存提案には生成時の根拠証明がないため、保存された区分を無点数で表示します')
    if is_current is False:
        # Apply exact withdrawal/resolution first, but do not turn the remaining
        # previous result into a fresh score while a replacement is pending.
        retained = {(item.get('proposal_id'), item.get('proposal_revision')): item
                    for item in projected.get('recommendations', []) if isinstance(item, dict)}
        held = deepcopy(identified)
        held['recommendations'] = [item for item in identified.get('recommendations', [])
            if isinstance(item, dict) and (item.get('proposal_id'), item.get('proposal_revision')) in retained]
        preserved = project_priority(held, sources, [], company_code=vehicle.company_code,
            vehicle_id=vehicle.id, as_of=as_of, is_current=False,
            unavailable_reason='分析の更新が完了していないため、前回の保存区分を無点数で表示します')
        if valid:
            from .priority_confirmed_projection import saved_confirmed_priority_history
            for item in preserved.get('recommendations', []):
                if not isinstance(item, dict):
                    continue
                original = retained.get((item.get('proposal_id'), item.get('proposal_revision')), {})
                assessment = original.get('priority_assessment') or {}
                history = assessment.get('historical_confirmation_details')
                if not isinstance(history, list):
                    # A still-active confirmation may have only current details
                    # in the first projection. Read its saved snapshot instead
                    # of relabelling today's preview as historical evidence.
                    history = saved_confirmed_priority_history(item, sources, vehicle)
                if history:
                    item['priority_assessment']['historical_confirmation_details'] = deepcopy(history)
        if 'priority_resolved_proposals' in projected:
            preserved['priority_resolved_proposals'] = projected['priority_resolved_proposals']
        projected = preserved
    projected['priority_summary'] = priority_counts(projected)
    return projected, sources
