"""Offline, single-owner pilot guard. No DB, sockets, application import or AI client.

An approved production adapter is deliberately not provided. Cost limits apply to
supplied token bounds/rates, not to an unverified provider invoice.
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def positive_int(value):
    return type(value) is int and value > 0


def sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


@dataclass(frozen=True)
class Target:
    company: str
    vehicle_id: int
    input_revision: str

    def __post_init__(self):
        if not isinstance(self.company, str) or not self.company.strip() or not positive_int(self.vehicle_id) or not sha(self.input_revision):
            raise ValueError('INVALID_TARGET')


@dataclass(frozen=True)
class Policy:
    targets: tuple
    model: str
    max_calls: int
    max_output_tokens: int
    max_request_bytes: int
    budget_microusd: int
    input_usd_per_million: str
    output_usd_per_million: str
    rate_source: str
    rate_as_of: str

    def __post_init__(self):
        if (type(self.targets) is not tuple or not 1 <= len(self.targets) <= 5
                or any(not isinstance(t, Target) for t in self.targets)
                or len({(t.company, t.vehicle_id) for t in self.targets}) != len(self.targets)
                or not isinstance(self.model, str) or not self.model.strip()
                or any(not positive_int(n) for n in (self.max_calls, self.max_output_tokens,
                    self.max_request_bytes, self.budget_microusd))
                or not self.rate_source or not self.rate_as_of):
            raise ValueError('INVALID_POLICY')
        for price in (self.input_usd_per_million, self.output_usd_per_million):
            if not isinstance(price, str):
                raise ValueError('INVALID_RATE')
            value = Decimal(price)
            if not value.is_finite() or value <= 0:
                raise ValueError('INVALID_RATE')


@dataclass(frozen=True)
class Request:
    target: Target
    body_json: str
    body_sha256: str
    input_token_upper_bound: int
    token_count_source: str


def estimate_microusd(policy, input_tokens, output_tokens):
    """USD per million tokens × tokens = microUSD. Round upwards once per call.

    All input tokens are priced uncached. Output bound must include all billed
    output/reasoning tokens. Unknown counts must not be replaced by char counts.
    """
    if not positive_int(input_tokens) or not positive_int(output_tokens):
        raise ValueError('TOKEN_BOUND_REQUIRED')
    return int((Decimal(policy.input_usd_per_million) * input_tokens +
                Decimal(policy.output_usd_per_million) * output_tokens).to_integral_value(rounding=ROUND_CEILING))


class Trial:
    """Finite in-memory trial only. Not thread/process-safe or restart durable.

    A production adapter must reserve durably before transmission; this object
    must never be recreated to retry an uncertain send. Only the synthetic harness
    below invokes callbacks in this implementation.
    """
    def __init__(self, policy):
        self.policy = policy
        self.used = 0
        self.receipts = []
        self.seen = set()
        self.stopped = False

    def prepare(self, request, *, observed_target):
        p = self.policy
        if self.stopped:
            raise ValueError('TRIAL_STOPPED')
        if request.target not in p.targets or observed_target != request.target:
            raise ValueError('SCOPE_OR_REVISION_MISMATCH')
        if not isinstance(request.body_json, str):
            raise ValueError('INVALID_REQUEST')
        raw = request.body_json.encode()
        if len(raw) > p.max_request_bytes or hashlib.sha256(raw).hexdigest() != request.body_sha256:
            raise ValueError('REQUEST_CHANGED_OR_OVERSIZE')
        body = json.loads(raw)
        # This tool supports only the current text-only analysis transport shape.
        allowed = {'model', 'instructions', 'input', 'text', 'reasoning', 'max_output_tokens', 'store'}
        if (not isinstance(body, dict) or set(body) != allowed or body['model'] != p.model
                or body['store'] is not False or body['reasoning'] != {'effort': 'low'}
                or not isinstance(body['input'], str) or not isinstance(body['instructions'], str)
                or not isinstance(body['text'], dict)):
            raise ValueError('UNAPPROVED_REQUEST_SHAPE')
        limit = body['max_output_tokens']
        if not positive_int(limit) or limit > p.max_output_tokens:
            raise ValueError('OUTPUT_LIMIT_EXCEEDED')
        if not isinstance(request.token_count_source, str) or not request.token_count_source.strip():
            raise ValueError('TOKEN_BOUND_REQUIRED')
        amount = estimate_microusd(p, request.input_token_upper_bound, limit)
        key = (request.target, request.body_sha256)
        if key in self.seen:
            raise ValueError('REPLAY_FORBIDDEN')
        if len(self.receipts) >= p.max_calls or self.used + amount > p.budget_microusd:
            raise ValueError('BUDGET_OR_CALL_LIMIT')
        self.seen.add(key)
        self.used += amount
        receipt = {'number': len(self.receipts) + 1, 'request_sha256': request.body_sha256,
            'reserved_microusd': amount, 'status': 'reserved'}
        self.receipts.append(receipt)
        return body, receipt

    def synthetic_call(self, request, *, observed_target, transport):
        """Only fixture data + injected fake transport; never a production API entry."""
        if any(not t.company.startswith('SYNTHETIC_') for t in self.policy.targets):
            raise ValueError('SYNTHETIC_ONLY')
        body, receipt = self.prepare(request, observed_target=observed_target)
        try:
            result = transport(body)
        except BaseException:
            receipt['status'] = 'uncertain'
            self.stopped = True
            raise
        receipt['status'] = 'returned'
        return result
