"""Shared response-only identities, counts and periodic-source preservation.

No database writes, model calls, new workflow, or operation decisions. A saved
proposal's original source proof is never reconstructed from today's records.
"""
from copy import deepcopy
from datetime import datetime
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
            'vehicle_id': vehicle_id, 'sources': deepcopy(sources)}


def bind_periodic_priority_sources(result, proof):
    """New generation only. Legacy stored JSON is never migrated or rewritten."""
    output = deepcopy(result)
    if isinstance(output, dict):
        output.pop(PERIODIC_PROOF_KEY, None)  # Model output can never supply server proof.
        if isinstance(proof, dict):
            output[PERIODIC_PROOF_KEY] = deepcopy(proof)
    return output


def project_periodic_priorities(result, vehicle, current_evidence, *, as_of=None):
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
        projected = project_registered_priorities(identified, vehicle, sources, as_of=as_of, is_current=True)
    else:
        # Render existing links if available, but never use them as the missing
        # original generation proof or bind old output to a newly-created event.
        sources = deepcopy(current_evidence) if isinstance(current_evidence, dict) else {}
        projected = project_priority(identified, {}, [], company_code=vehicle.company_code,
            vehicle_id=vehicle.id, as_of=as_of, is_current=True,
            unavailable_reason='この保存提案には生成時の根拠証明がないため、保存された区分を無点数で表示します')
    projected['priority_summary'] = priority_counts(projected)
    return projected, sources
