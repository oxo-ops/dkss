"""Offline bridge to the application's real request builder; never sends/saves.

The caller must obtain payload and observed identity from an authorized scoped
reader. This module cannot attest that an arbitrary supplied dictionary came
from that reader. Revision is the full payload digest, NOT queue fingerprints.
"""
import hashlib
import json
from vehicle_karte_analysis_ai import prepare_vehicle_karte_analysis_request
from .pilot import Request, digest


def prepare_scoped_request(policy, target, payload, *, observed_company,
                           observed_vehicle_id, count_input_tokens):
    # Scope/version checks precede prompt generation and token counting.
    if (target not in policy.targets
            or (observed_company, observed_vehicle_id) != (target.company, target.vehicle_id)
            or digest(payload) != target.input_revision):
        raise ValueError('SCOPED_INPUT_CHANGED')
    body = prepare_vehicle_karte_analysis_request(payload, model=policy.model)
    raw = json.dumps(body, allow_nan=False)  # Exact serializer used by normal HTTP transport.
    if len(raw.encode()) > policy.max_request_bytes:
        raise ValueError('REQUEST_OVERSIZE')
    # A local, model-correct counter must cover instructions, schema and protocol;
    # unknown counts fail in Trial.prepare. No network tokenizer is supplied.
    count, source = count_input_tokens(raw, policy.model)
    return Request(target, raw, hashlib.sha256(raw.encode()).hexdigest(), count, source)
