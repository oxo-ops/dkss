"""Non-production HTTP integration candidate. No CLI, credentials or app hook.

Only synthetic targets and the literal synthetic credential are accepted. Tests
replace HTTPSConnection; never invoke against a real service. Count is an extra
HTTP disclosure, not an offline tokenizer or a generation budget reservation.
"""
import hashlib
import json
import ssl
from .final_gate import Envelope, RESPONSES_URL, synthetic_final_call
from .pilot import Trial, positive_int, SOL_STANDARD_30M

COUNT_SOURCE = 'responses-input-tokens-v1-2026-11-12'
COUNT_PATH = '/v1/responses/input_tokens'
RESPONSE_LIMIT = 2 * 1024 * 1024


class SyntheticHTTPTrial:
    """One owner / one count + one generation, no retry or redirect handling."""
    def __init__(self, ledger, approved_request, *, observed_target, connection_factory):
        if (len(ledger.policy.targets) != 1 or ledger.policy.max_calls != 1
                or not observed_target.company.startswith('SYNTHETIC_')):
            raise ValueError('SYNTHETIC_SINGLE_TARGET_ONLY')
        Trial(ledger.policy).prepare(approved_request, observed_target=observed_target)
        if (ledger.policy.endpoint != RESPONSES_URL
                or ledger.policy.pricing_profile != SOL_STANDARD_30M):
            raise ValueError('ENDPOINT_REJECTED')
        if approved_request.token_count_source != COUNT_SOURCE:
            raise ValueError('COUNT_SOURCE_REJECTED')
        self.ledger, self.request, self.target = ledger, approved_request, observed_target
        self.connection_factory = connection_factory
        self.started = False


    def run(self):
        if self.started or self.ledger.receipts():
            raise ValueError('PILOT_ALREADY_ATTEMPTED_NO_RETRY')
        self.started = True  # Includes failed count: no implicit retry in this owner.
        request = self.request
        Trial(self.ledger.policy).prepare(request, observed_target=self.target)
        if request.token_count_source != COUNT_SOURCE:
            raise ValueError('COUNT_SOURCE_REJECTED')
        body = json.loads(request.body_json)
        # Official count API supports these input-affecting fields, including
        # instructions/schema; output cap/store/tier do not add input content.
        count_body = {key: body[key] for key in
                      ('model', 'instructions', 'input', 'text', 'reasoning')}
        counted = post_json_synthetic(COUNT_PATH, json.dumps(count_body).encode(),
                                      connection_factory=self.connection_factory)
        count = counted.get('input_tokens')
        if counted.get('object') != 'response.input_tokens' or not positive_int(count):
            raise ValueError('INVALID_PROVIDER_COUNT')
        raw = request.body_json.encode()
        bound_hash = hashlib.sha256(raw).hexdigest()
        def counter(final_raw, model):
            if hashlib.sha256(final_raw).hexdigest() != bound_hash or model != body['model']:
                raise ValueError('COUNTED_BODY_CHANGED')
            return count, COUNT_SOURCE
        return synthetic_final_call(self.ledger, request, Envelope(RESPONSES_URL, raw),
            observed_target=self.target, count_input_tokens=counter,
            transport=lambda envelope: post_json_synthetic('/v1/responses', envelope.body,
                connection_factory=self.connection_factory))


def post_json_synthetic(path, raw, *, connection_factory):
    if path not in (COUNT_PATH, '/v1/responses'):
        raise ValueError('ENDPOINT_REJECTED')
    # The helper never follows Location or automatically retries a request.
    # Only an explicit injected mock connection is used; no default network client.
    # No proxy/environment/credential lookup. Default TLS verification stays on.
    if not callable(connection_factory):
        raise ValueError('MOCK_CONNECTION_FACTORY_REQUIRED')
    connection = connection_factory('api.openai.com', timeout=120,
                                            context=ssl.create_default_context())
    try:
        connection.request('POST', path, body=raw, headers={
            'Authorization': 'Bearer synthetic-only',
            'Content-Type': 'application/json'})
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError('PILOT_HTTP_STATUS_' + str(response.status))
        data = response.read(RESPONSE_LIMIT + 1)
        if len(data) > RESPONSE_LIMIT:
            raise ValueError('PILOT_RESPONSE_TOO_LARGE')
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError('PILOT_RESPONSE_SHAPE')
        return result
    finally:
        connection.close()
