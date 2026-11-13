"""Offline count material only. No DB, credentials, HTTP or approval inference.

A provider-shaped response passed here is untrusted supplied evidence, not proof
of a real provider request. Operations must retain authenticated response evidence
and separately authorize both count disclosure and generation.
"""
from dataclasses import dataclass, field
import hashlib
import json

from .http_candidate import COUNT_SOURCE, COUNT_PATH
from .pilot import Target, digest, positive_int


def _hash(raw):
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class CountMaterial:
    target: Target
    model: str
    generation_json: str = field(repr=False)
    generation_sha256: str
    count_json: str = field(repr=False)
    count_sha256: str
    endpoint: str = 'https://api.openai.com' + COUNT_PATH


def prepare_count_material(payload, *, target, model):
    """Build complete ordinary one-call body; reject restricted peer cohorts.

    Caller must supply the authorized complete ordinary payload, not an invented
    target-only subset. No source is loaded and no network request is made here.
    """
    from vehicle_karte_analysis_ai import prepare_vehicle_karte_analysis_request
    detached = json.loads(json.dumps(payload, ensure_ascii=False, default=str, allow_nan=False))
    if (not isinstance(target, Target) or digest(detached) != target.input_revision
            or (payload.get('comparison') or {}).get('comparison_scope', {}).get('acceptance_limited')):
        raise ValueError('COUNT_INPUT_SCOPE_OR_REVISION_MISMATCH')
    if model != 'gpt-6.1-sol':
        raise ValueError('COUNT_MODEL_UNSUPPORTED')
    body = prepare_vehicle_karte_analysis_request(payload, model=model)
    body['service_tier'] = 'default'
    raw = json.dumps(body, allow_nan=False)  # identical to ScopedJobBridge._send
    count = json.dumps({k: body[k] for k in ('model', 'instructions', 'input', 'text', 'reasoning')}, allow_nan=False)
    return CountMaterial(target, model, raw, _hash(raw), count, _hash(count))


def validate_material(material, *, observed_generation_sha256, observed_count_sha256):
    """Validate immutable count/generation linkage without inventing a token count."""
    raw, count_raw = material.generation_json, material.count_json
    body = json.loads(raw)
    expected_count = json.dumps({k: body[k] for k in ('model', 'instructions', 'input', 'text', 'reasoning')}, allow_nan=False)
    if (material.endpoint != 'https://api.openai.com' + COUNT_PATH
            or material.model != body['model'] or body['service_tier'] != 'default'
            or _hash(raw) != material.generation_sha256
            or _hash(count_raw) != material.count_sha256 or count_raw != expected_count
            or observed_generation_sha256 != material.generation_sha256
            or observed_count_sha256 != material.count_sha256):
        raise ValueError('COUNT_EVIDENCE_BINDING_MISMATCH')


def bind_supplied_count(material, response, *, observed_generation_sha256, observed_count_sha256):
    """Return non-secret evidence metadata, NOT an approval or live-ready Request.

    Both hashes must identify the actual bytes associated with the supplied
    response. An operator must independently establish provenance; hashes alone
    cannot authenticate a fabricated response or confer spending permission.
    """
    validate_material(material, observed_generation_sha256=observed_generation_sha256,
                      observed_count_sha256=observed_count_sha256)
    if (not isinstance(response, dict) or response.get('object') != 'response.input_tokens'
            or not positive_int(response.get('input_tokens'))):
        raise ValueError('COUNT_RESPONSE_INVALID')
    return dict(generation_sha256=material.generation_sha256, count_sha256=material.count_sha256,
                input_revision=material.target.input_revision, model=material.model,
                input_tokens=response['input_tokens'], count_source=COUNT_SOURCE,
                provider_provenance_verified=False, generation_authorized=False)
