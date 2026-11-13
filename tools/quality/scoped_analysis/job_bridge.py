"""Explicit one-state bridge; no CLI, worker enablement, or automatic invocation.

Caller supplies an already counted/approved exact normal-input request and a
transport. Counting may itself disclose data: it is not performed here. Approval
and correct provider count evidence remain operational prerequisites, not claims
that a Python object can attest. No scoped/partial comparison is publishable.
"""
import json
from .pilot import Trial, digest, SOL_STANDARD_30M
from .final_gate import RESPONSES_URL
from .http_candidate import COUNT_SOURCE


class ScopedJobBridge:
    def __init__(self, ledger, request, *, transport):
        if (len(ledger.policy.targets) != 1 or ledger.policy.max_calls != 1
                or ledger.policy.pricing_profile != SOL_STANDARD_30M
                or ledger.policy.endpoint != RESPONSES_URL
                or request.token_count_source != COUNT_SOURCE or not callable(transport)):
            raise ValueError('SINGLE_APPROVED_STANDARD_REQUEST_REQUIRED')
        Trial(ledger.policy).prepare(request, observed_target=request.target)
        self.ledger, self.request, self.transport = ledger, request, transport
        self.loaded = False
        self.started = False

    def validate_state(self, state):
        target = self.request.target
        if (state is None or state.company_code != target.company
                or state.vehicle_record_id != target.vehicle_id):
            raise ValueError('PILOT_STATE_SCOPE_MISMATCH')
        if self.started or self.ledger.receipts():
            raise ValueError('PILOT_ALREADY_ATTEMPTED_NO_RETRY')

    def load_input(self, vehicle):
        from dkss_app.analysis import get_vehicle_karte_analysis_job_data
        target = self.request.target
        if (vehicle.company_code, vehicle.id) != (target.company, target.vehicle_id):
            raise ValueError('PILOT_VEHICLE_SCOPE_MISMATCH')
        # Ordinary complete input, never pass comparison_vehicle_ids here.
        payload, sources = get_vehicle_karte_analysis_job_data(vehicle)
        detached = json.loads(json.dumps(payload, ensure_ascii=False, default=str, allow_nan=False))
        if ((payload.get('comparison') or {}).get('comparison_scope', {}).get('acceptance_limited')
                or digest(detached) != target.input_revision):
            raise ValueError('PILOT_NORMAL_INPUT_CHANGED')
        self.loaded = True
        return payload, sources

    def analyze(self, payload, on_progress=None):
        from vehicle_karte_analysis_ai import analyze_vehicle_karte_single_request
        if not self.loaded or self.started or self.ledger.receipts():
            raise ValueError('PILOT_NOT_LOADED_OR_ALREADY_ATTEMPTED')
        self.started = True
        return analyze_vehicle_karte_single_request(payload, model=self.ledger.policy.model,
            transport=self._send, on_progress=on_progress)

    def _send(self, body):
        raw = json.dumps(body, allow_nan=False)
        # Final builder output must match counted/approved bytes exactly.
        _, number = self.ledger.reserve_exact_body(self.request, raw,
                                                   observed_target=self.request.target)
        try:
            result = self.transport(RESPONSES_URL, raw.encode('utf-8'))
            if not isinstance(result, dict):
                raise ValueError('PILOT_RESPONSE_SHAPE')
        except BaseException:
            self.ledger.record_outcome(number, 'uncertain')
            # Never allow caller/provider exception payloads into normal job logs.
            raise RuntimeError('PILOT_TRANSPORT_UNCERTAIN') from None
        self.ledger.record_outcome(number, 'returned')
        return result
