"""Synthetic-only final wire boundary. This is NOT a live HTTP transport.

A callback receives the exact immutable envelope that was checked and reserved.
Injected token counters are test seams, not evidence of provider token billing.
No headers, credentials, redirects, retries, network client or live enable switch.
"""
from dataclasses import dataclass
from .pilot import SOL_STANDARD_30M, positive_int

RESPONSES_URL = 'https://api.openai.com/v1/responses'


@dataclass(frozen=True)
class Envelope:
    url: str
    body: bytes


def synthetic_final_call(ledger, approved_request, envelope, *, observed_target,
                         count_input_tokens, transport):
    """Recheck final bytes/count, reserve durably, then invoke one fake transport.

    Model, service tier, output cap, hash, scope and budget are validated by the
    existing ledger gate against these same bytes. The counter must count the
    final serialized body, not an earlier prompt. No reservation on rejection.
    """
    if type(envelope) is not Envelope:
        raise ValueError('INVALID_FINAL_ENVELOPE')
    if any(not t.company.startswith('SYNTHETIC_') for t in ledger.policy.targets):
        raise ValueError('SYNTHETIC_ONLY')
    if (ledger.policy.pricing_profile != SOL_STANDARD_30M
            or envelope.url != RESPONSES_URL
            or ledger.policy.endpoint != envelope.url):
        raise ValueError('FINAL_ENDPOINT_OR_PROFILE_UNVERIFIED')
    if type(envelope.body) is not bytes or envelope.body != approved_request.body_json.encode('utf-8'):
        raise ValueError('APPROVED_TRANSPORT_BODY_CHANGED')
    count, source = count_input_tokens(envelope.body, ledger.policy.model)
    if not positive_int(count):
        raise ValueError('INVALID_FINAL_INPUT_TOKEN_COUNT')
    if source != approved_request.token_count_source or not isinstance(source, str) or not source.strip():
        raise ValueError('FINAL_TOKEN_COUNT_SOURCE_CHANGED')
    if count > approved_request.input_token_upper_bound:
        raise ValueError('FINAL_TOKEN_BOUND_EXCEEDED')
    _, number = ledger.reserve_exact_body(
        approved_request, envelope.body.decode('utf-8'), observed_target=observed_target)
    try:
        result = transport(envelope)
    except BaseException:
        ledger.record_outcome(number, 'uncertain')
        raise
    ledger.record_outcome(number, 'returned')
    return result
