"""Pure, opt-in shadow bridge for host-verified adopted maintenance timing.

No source discovery, I/O, current-state inference, production integration, or legal
classification. The caller owns semantic proposal/event and reference review.
"""
from calendar import monthrange
from dataclasses import asdict, dataclass
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, localcontext, Context
import hashlib
import json
import math

from vehicle_priority_assessment import Evidence, Reference, Scope, TimingFact, InvalidInput


@dataclass(frozen=True)
class ReferenceBinding:
    reference_id: str
    document_checksum: str
    reference_hash: str


@dataclass(frozen=True)
class TimingBinding:
    scope: Scope
    event_id: str
    as_of: date
    snapshot_hash: str
    rule_key: str
    document_checksum: str
    reference_ids: tuple[str, ...]
    # Actual event evidence, NOT automatically relabelled historical baselines.
    event_source_ids: tuple[str, ...]
    origin_verified: bool = False
    event_binding_verified: bool = False
    reference_checked_on: date | None = None
    reference_bindings: tuple[ReferenceBinding, ...] = ()


@dataclass(frozen=True)
class TimingCondition:
    metric: str
    threshold: str
    unit: str
    baseline_on: date
    reference_on: date
    threshold_reached: bool
    due_on: date | None = None
    elapsed_quantity: str | None = None
    remaining_quantity: str | None = None
    excess_quantity: str | None = None
    # Calendar duration is a factual span, not a defined 90%-of-month policy.
    calendar_interval_days: int | None = None


@dataclass(frozen=True)
class TimingConditionGroup:
    relation: str
    as_of: date
    conditions: tuple[TimingCondition, ...]
    threshold_reached: bool
    calendar_threshold_on: date | None
    calendar_threshold_basis: str | None
    source_quote: str
    scoring_input_emitted: bool
    note: str = "登録された基準日での到達状態。実際の到達日や整備要否の推定ではありません。"


@dataclass(frozen=True)
class TimingBridgeResult:
    timings: tuple[TimingFact, ...]
    missing_conditions: tuple[str, ...]
    snapshot_hash: str
    provenance_source_ids: tuple[str, ...]
    rule_key: str
    relation: str
    mode: str = 'shadow'
    production_enabled: bool = False
    condition_group: TimingConditionGroup | None = None
    scope: Scope | None = None
    event_id: str | None = None
    as_of: date | None = None


def _typed(value):
    # Every node is tagged; an ordinary dictionary cannot impersonate Decimal.
    if value is None:
        return ['none']
    if type(value) is bool:
        return ['bool', value]
    if type(value) is str:
        return ['str', value]
    if type(value) is int:
        return ['int', str(value)]
    if type(value) in (float, Decimal):
        if not Decimal(str(value)).is_finite():
            raise ValueError('nonfinite snapshot number')
        return ['float' if type(value) is float else 'decimal', str(value)]
    if type(value) in (list, tuple):
        return ['list' if type(value) is list else 'tuple', [_typed(v) for v in value]]
    if type(value) is dict and all(type(k) is str for k in value):
        return ['dict', [[k, _typed(value[k])] for k in sorted(value)]]
    raise TypeError('unsupported snapshot value')


def _hash(value):
    return hashlib.sha256(json.dumps(_typed(value), ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def timing_snapshot_hash(rule, timing):
    return _hash({'rule': rule, 'timing': timing})


def reference_snapshot_hash(reference):
    if not isinstance(reference, Reference):
        raise TypeError('Reference required')
    return _hash(asdict(reference))


def _number(value):
    if type(value) not in (int, float, Decimal):
        raise ValueError('invalid number')
    n = Decimal(str(value))
    if (not n.is_finite() or n < 0 or n > Decimal('1000000000000')
            or n.as_tuple().exponent < -6):
        raise ValueError('number outside supported exact arithmetic bounds')
    return n


def _native(value):
    n = _number(value)
    result = int(n) if n == n.to_integral_value() else float(n)
    if not math.isfinite(result) or Decimal(str(result)) != n:
        raise ValueError('numeric precision cannot be preserved')
    return result


def _day(value):
    if not isinstance(value, str):
        raise ValueError('date missing')
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        raise ValueError('date not canonical')
    return result


def _ratio(elapsed, interval):
    e, i = _number(elapsed), _number(interval)
    if i <= 0:
        raise ValueError('invalid interval')
    en, inn = _native(e), _native(i)
    # Scorer uses native 0.9 multiplication. Reject rather than move a boundary.
    with localcontext() as context:
        context.prec = max(28, len(i.as_tuple().digits) + 2)
        near = Decimal('0.9') * i
    if (en >= inn) != (e >= i) or (en >= 0.9 * inn) != (e >= near):
        raise ValueError('numeric scoring boundary cannot be preserved')
    return en, inn


def bridge_adopted_timing(rule, timing, binding, evidence, references):
    # Bounds below need at most 20 significant digits; never inherit caller precision.
    with localcontext(Context(prec=40)):
        return _bridge_adopted_timing(rule, timing, binding, evidence, references)


def _bridge_adopted_timing(rule, timing, binding, evidence, references):
    """Return facts only for verified single / wholly calculable OR snapshots.

    Invalid identity/provenance raises InvalidInput. Unsupported/incomplete timing
    returns no facts and a missing condition; no priority label is invented here.
    """
    if (not isinstance(binding, TimingBinding) or not isinstance(binding.scope, Scope)
            or not isinstance(binding.scope.company_code, str) or not binding.scope.company_code.strip()
            or not isinstance(binding.scope.target, str) or not binding.scope.target.strip()
            or type(binding.scope.vehicle_id) is not int or binding.scope.vehicle_id <= 0
            or not isinstance(binding.event_id, str) or not binding.event_id.strip()
            or type(binding.as_of) is not date or not isinstance(rule, dict)
            or not isinstance(timing, dict) or not isinstance(evidence, Mapping)
            or not isinstance(references, Mapping)):
        raise InvalidInput('invalid timing binding')
    try:
        digest = timing_snapshot_hash(rule, timing)
    except (ValueError, TypeError, RecursionError):
        raise InvalidInput('invalid timing snapshot') from None
    adoption = rule.get('analysis_adoption')
    applicability = rule.get('vehicle_applicability')
    if (digest != binding.snapshot_hash or not isinstance(adoption, dict)
            or adoption.get('status') != 'adopted_for_analysis'
            or not isinstance(binding.rule_key, str) or not binding.rule_key.strip() or adoption.get('rule_key') != binding.rule_key
            or not isinstance(binding.document_checksum, str) or not binding.document_checksum.strip()
            or adoption.get('document_checksum') != binding.document_checksum
            or type(adoption.get('document_id')) is not int or adoption['document_id'] <= 0
            or not isinstance(applicability, dict) or applicability.get('status') != 'conditions_matched'
            or binding.origin_verified is not True or binding.event_binding_verified is not True
            or type(binding.reference_checked_on) is not date
            or binding.reference_checked_on != binding.as_of):
        raise InvalidInput('adoption, applicability, origin or snapshot binding not verified')
    sources = timing.get('source_ids')
    action = rule.get('action')
    kind = {'replace': 'replacement', 'inspect': 'inspection'}.get(action) if isinstance(action, str) else None
    prefix = 'part:' if action == 'replace' else 'periodic:'
    if (kind is None or not isinstance(rule.get('cycle'), str) or rule.get('cycle') not in {'repeat', 'all'}
            or not isinstance(sources, list) or not sources
            or any(not isinstance(s, str) or not s for s in sources)
            or not any(s.startswith(prefix) for s in sources)
            or not isinstance(adoption.get('knowledge_source_id'), str)
            or not adoption['knowledge_source_id'].startswith('knowledge:')
            or adoption.get('knowledge_source_id') not in sources
            or adoption.get('vehicle_source_id') != f'vehicle:{binding.scope.vehicle_id}'
            or adoption.get('vehicle_source_id') not in sources
            or timing.get('scope') != f'registered_{kind}_and_reading_dates'):
        raise InvalidInput('timing provenance not bound')
    if (type(binding.event_source_ids) is not tuple or not binding.event_source_ids
            or type(binding.reference_ids) is not tuple or not binding.reference_ids
            or any(not isinstance(s, str) or not s.strip() for s in binding.event_source_ids + binding.reference_ids)
            or len(set(binding.reference_ids)) != len(binding.reference_ids)):
        raise InvalidInput('explicit event evidence and references required')
    for sid in binding.event_source_ids:
        item = evidence.get(sid)
        if (not isinstance(item, Evidence) or item.source_id != sid or item.scope != binding.scope
                or item.event_id != binding.event_id or item.verified is not True
                or type(item.observed_on) is not date or item.observed_on > binding.as_of
                or item.kind != 'record' or not isinstance(item.status, str) or item.status not in {'current', 'open'}
                or not isinstance(item.excerpt, str) or not item.excerpt.strip()):
            raise InvalidInput('event evidence not verified')
    if (type(binding.reference_bindings) is not tuple
            or any(not isinstance(v, ReferenceBinding) or not isinstance(v.reference_id, str)
                   or not isinstance(v.document_checksum, str) or not isinstance(v.reference_hash, str)
                   for v in binding.reference_bindings)
            or len(binding.reference_bindings) != len(binding.reference_ids)
            or {v.reference_id for v in binding.reference_bindings} != set(binding.reference_ids)):
        raise InvalidInput('exact reference version bindings required')
    reference_bindings = {v.reference_id: v for v in binding.reference_bindings}
    for rid in binding.reference_ids:
        ref = references.get(rid)
        if (not isinstance(ref, Reference) or ref.reference_id != rid
                or ref.verified is not True or ref.applicable is not True
                or type(ref.immediate_action) is not bool
                or ref.authority != 'manufacturer'
                or not all(isinstance(v, str) and v.strip() for v in
                           (ref.url, ref.issuer, ref.title, ref.version, ref.quote))
                or ref.url != adoption.get('source_url')
                or ref.quote != rule.get('source_quote')):
            raise InvalidInput('adopted manufacturer reference not verified')
        rb = reference_bindings[rid]
        try:
            exact_reference_hash = reference_snapshot_hash(ref)
        except (ValueError, TypeError, RecursionError):
            raise InvalidInput('invalid reference snapshot') from None
        if rb.document_checksum != binding.document_checksum or rb.reference_hash != exact_reference_hash:
            raise InvalidInput('reference version does not match bound document checksum')
    relation = rule.get('relation')
    provenance = tuple(sorted(set(sources)))
    def result(facts=(), missing=(), group=None):
        return TimingBridgeResult(tuple(facts), tuple(missing), digest, provenance,
                                  binding.rule_key, relation, condition_group=group, scope=binding.scope,
                                  event_id=binding.event_id, as_of=binding.as_of)
    criteria, rows = rule.get('criteria'), timing.get('criteria')
    if (not isinstance(relation, str) or not isinstance(criteria, list) or not 1 <= len(criteria) <= 4
            or (relation != 'single' if len(criteria) == 1 else relation not in {'any', 'all'})):
        raise InvalidInput('invalid criteria relation')
    if (timing.get('calculation_permitted') is not True
            or not isinstance(timing.get('status'), str)
            or timing.get('status') not in {'threshold_reached', 'not_reached_at_reference_dates'}
            or not isinstance(rows, list) or len(rows) != len(criteria)):
        return result(missing=('全条件の期限計算・起算・適用条件を確認要',))
    facts, conditions, metrics, baselines = [], [], set(), set()
    try:
        reached = []
        for criterion, row in zip(criteria, rows):
            if not isinstance(criterion, dict) or not isinstance(row, dict):
                raise ValueError('criterion/result must be mappings')
            metric = criterion['metric']
            threshold = _number(criterion['value'])
            if (not isinstance(metric, str) or metric in metrics or metric not in {'distance_km', 'period_days', 'period_months'}
                    or threshold <= 0 or row.get('metric') != metric
                    or _number(row.get('threshold')) != threshold
                    or row.get('calculation_permitted') is not True):
                raise ValueError('criterion mismatch')
            metrics.add(metric)
            baseline, reference = _day(row['baseline_date']), _day(row['reference_date'])
            baselines.add(baseline)
            if not baseline <= reference <= binding.as_of:
                raise ValueError('date order')
            if kind == 'inspection' and (row.get('baseline_kind') != 'inspection'
                    or type(row.get('inspection_item_index')) is not int
                    or row['inspection_item_index'] < 0):
                raise ValueError('inspection origin missing')
            kwargs, condition_values = {}, {}
            if metric == 'distance_km':
                elapsed = _number(row['elapsed_km'])
                origin, current = _number(row[f'{kind}_mileage']), _number(row['recorded_mileage'])
                if current < origin or current - origin != elapsed:
                    raise ValueError('meter mismatch')
                if (_number(row['remaining_km']) != max(Decimal(0), threshold - elapsed)
                        or _number(row['excess_km']) != max(Decimal(0), elapsed - threshold)):
                    raise ValueError('distance result mismatch')
                if relation != 'all':
                    e, interval = _ratio(elapsed, threshold)
                    kwargs.update(elapsed=e, interval=interval, elapsed_unit='km', interval_unit='km')
                is_reached = elapsed >= threshold
                condition_values.update(elapsed_quantity=str(elapsed),
                    remaining_quantity=str(max(Decimal(0), threshold - elapsed)),
                    excess_quantity=str(max(Decimal(0), elapsed - threshold)))
            else:
                if threshold != threshold.to_integral_value() or reference != binding.as_of:
                    raise ValueError('calendar period mismatch')
                amount = int(threshold)
                if metric == 'period_days':
                    due = baseline + timedelta(days=amount)
                    if relation != 'all':
                        e, interval = _ratio((reference - baseline).days, amount)
                        kwargs.update(elapsed=e, interval=interval, elapsed_unit='days', interval_unit='days')
                else:
                    total = baseline.month - 1 + amount
                    year, month = baseline.year + total // 12, total % 12 + 1
                    due = baseline.replace(year=year, month=month,
                        day=min(baseline.day, monthrange(year, month)[1]))
                if (any(type(row.get(k)) is not int for k in ('elapsed_days', 'remaining_days', 'overdue_days'))
                        or _day(row['due_date']) != due or row['elapsed_days'] != (reference - baseline).days
                        or row['remaining_days'] != max(0, (due - reference).days)
                        or row['overdue_days'] != max(0, (reference - due).days)):
                    raise ValueError('calendar result mismatch')
                kwargs['due_on'] = due
                is_reached = reference >= due
                condition_values.update(due_on=due, elapsed_quantity=str((reference - baseline).days),
                    remaining_quantity=str(max(0, (due - reference).days)),
                    excess_quantity=str(max(0, (reference - due).days)),
                    calendar_interval_days=(due - baseline).days)
            if row.get('status') != ('reached' if is_reached else 'not_reached_at_reference'):
                raise ValueError('status mismatch')
            reached.append(is_reached)
            conditions.append(TimingCondition(metric, str(threshold),
                {'distance_km':'km', 'period_days':'days', 'period_months':'calendar_months'}[metric],
                baseline, reference, is_reached, **condition_values))
            if relation != 'all':
                facts.append(TimingFact(binding.event_source_ids, binding.reference_ids,
                    calculation_permitted=True, calculation_verified=True, origin_verified=True,
                    combination_verified=True, legal_deadline=False, **kwargs))
        group_reached = all(reached) if relation == 'all' else any(reached)
        if len(baselines) != 1 or (timing['status'] == 'threshold_reached') != group_reached:
            raise ValueError('aggregate result mismatch')
    except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError):
        return result(missing=('期限計算・単位・起算・数値精度又は条件の一致を確認要',))
    missing = ('月間隔の90％判定は未対応です。確認済み期限日だけを使用します。',) if 'period_months' in metrics else ()
    calendar_only = all(condition.due_on is not None for condition in conditions)
    threshold_on, date_basis = None, None
    if calendar_only:
        dates = [condition.due_on for condition in conditions]
        threshold_on = max(dates) if relation == 'all' else min(dates)
        date_basis = {'all':'all_calendar_conditions_latest', 'any':'any_calendar_condition_earliest',
                      'single':'single_calendar_condition'}[relation]
    note = '登録された基準日での到達状態。実際の到達日や整備要否の推定ではありません。'
    if not calendar_only:
        note += '距離条件の到達日を推定しないため、条件全体の暦上の到達日は算出しません。'
    group = TimingConditionGroup(relation, binding.as_of, tuple(conditions), group_reached,
                                 threshold_on, date_basis, rule['source_quote'], relation != 'all', note)
    if relation == 'all':
        missing = ('AND条件全体の接近・採点方法は未定義です。検証済み条件を別表示し、期限点を加算しません。',) + missing
        return result(missing=missing, group=group)
    return result(facts, missing, group)


def timing_condition_payload(result):
    """JSON-ready factual display seam, kept separate from priority scoring.

    Does not read raw unverified rows, register a route, generate markup, or save
    anything. A caller must retain the complete original snapshot as well.
    This is an internal serializer, not validation of a request-supplied dataclass.
    """
    if not isinstance(result, TimingBridgeResult):
        raise InvalidInput('validated timing bridge result required')
    group = result.condition_group
    payload = {'version':'timing-condition-view-v1', 'mode':'shadow', 'production_enabled':False,
               'rule_key':result.rule_key, 'relation':result.relation,
               'scope':asdict(result.scope) if result.scope else None, 'event_id':result.event_id,
               'as_of':result.as_of.isoformat() if result.as_of else None,
               'snapshot_hash':result.snapshot_hash, 'source_ids':list(result.provenance_source_ids),
               'missing_conditions':list(result.missing_conditions), 'scoring_input_emitted':False,
               'status':'calculation_unavailable', 'condition_group':None}
    if group is not None:
        # Each source quotation is data for a textContent/escaped-text renderer,
        # never HTML. Calendar units and countdown units remain distinct.
        values = asdict(group)
        values['as_of'] = group.as_of.isoformat()
        values['calendar_threshold_on'] = group.calendar_threshold_on.isoformat() if group.calendar_threshold_on else None
        values['conditions'] = [
            {**asdict(condition), 'baseline_on':condition.baseline_on.isoformat(),
             'reference_on':condition.reference_on.isoformat(),
             'due_on':condition.due_on.isoformat() if condition.due_on else None,
             'quantity_unit':'km' if condition.metric == 'distance_km' else 'days'}
            for condition in group.conditions]
        payload.update(status='verified_condition_facts', condition_group=values,
                       scoring_input_emitted=group.scoring_input_emitted)
    return payload
