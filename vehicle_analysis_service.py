"""Input construction, scheduling and job orchestration with explicit dependencies.

No application globals, Flask imports, model declarations or database startup.
"""
import calendar
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import json
from zoneinfo import ZoneInfo


def snapshot_hash(fingerprints):
    return hashlib.sha256(json.dumps(
        fingerprints, sort_keys=True, ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AnalysisComparisonSettings:
    registration_scope: str
    include_inactive: bool

    @classmethod
    def from_environ(cls, environ):
        scope = environ.get("VEHICLE_KARTE_AI_PEER_REGISTRATION", "auto").strip()
        inactive = environ.get("VEHICLE_KARTE_AI_PEER_INCLUDE_INACTIVE", "0").strip()
        if scope not in {"auto", "same_year", "all_years"}:
            raise ValueError("VEHICLE_KARTE_AI_PEER_REGISTRATION must be auto, same_year or all_years")
        if inactive not in {"0", "1"}:
            raise ValueError("VEHICLE_KARTE_AI_PEER_INCLUDE_INACTIVE must be 0 or 1")
        return cls(scope, inactive == "1")


class VehicleAnalysisInputService:
    def __init__(self, *, repository, build_summary, read_comparison, build_payload,
                 today, read_settings):
        self.repository = repository
        self.build_summary = build_summary
        self.read_comparison = read_comparison
        self.build_payload = build_payload
        self.today = today
        self.read_settings = read_settings

    def build(self, vehicle):
        today = self.today()
        start = today.replace(year=today.year - 2, day=min(
            today.day, calendar.monthrange(today.year - 2, today.month)[1],
        ))
        records = self.repository.load(vehicle, today)
        summary = self.build_summary(
            records.maintenance, records.operations, records.parts, records.defects,
            start.isoformat(), today.isoformat(), periodic_records=records.periodic,
        )
        settings = self.read_settings()
        comparison = self.read_comparison(
            vehicle, summary, registration_scope=settings.registration_scope,
            include_inactive=settings.include_inactive,
        )
        comparison["comparison_scope"]["condition_source"] = "automatic_analysis_configuration"
        return self.build_payload(
            vehicle, summary, comparison, records.maintenance, records.parts, records.defects,
        )


class VehicleAnalysisQueueService:
    """Change scheduling fields only; the caller still owns the outer commit."""

    def __init__(self, *, repository, utc_now, parse_result):
        self.repository = repository
        self.utc_now = utc_now
        self.parse_result = parse_result

    def queue(self, vehicle, payload):
        utc = ZoneInfo("UTC")
        now = self.utc_now()

        def aware(value):
            if value is None:
                return None
            return value.replace(tzinfo=utc) if value.tzinfo is None else value.astimezone(utc)

        state = self.repository.get_or_create(vehicle)
        fingerprints = payload["_fingerprints"]
        signature = snapshot_hash(fingerprints)
        old_result = self.parse_result(state.result_json)
        previous = old_result.get("fingerprints") or {}
        if not isinstance(previous, dict):
            previous = {}
        active = (state.status == "running" and aware(state.lease_expires_at) is not None
                  and aware(state.lease_expires_at) > now)
        if state.input_hash == signature and (state.status in {"pending", "error"} or active):
            return state

        important_changed = (previous.get("policy_version") != fingerprints["policy_version"]
                             or previous.get("important_hash") != fingerprints["important_hash"])
        routine_changed = previous.get("routine_hash") != fingerprints["routine_hash"]
        state.input_hash = signature
        if previous and not important_changed and not routine_changed:
            if not active:
                state.status = "completed"
                state.next_analysis_at = None
                state.last_error = None
                state.lease_token = None
                state.lease_expires_at = None
            return state
        if important_changed:
            due = now + timedelta(minutes=2)
            reason = "初回分析" if not previous else "整備・不具合・点検指摘などの変更"
        elif routine_changed:
            local = now.astimezone(ZoneInfo("Asia/Tokyo"))
            due = local.replace(hour=3, minute=0, second=0, microsecond=0)
            if due <= local:
                due += timedelta(days=1)
            due = due.astimezone(utc)
            reason = "走行距離・期限などの日次確認"
        else:
            due = now + timedelta(minutes=2)
            reason = "中断した分析の再実行"
        existing_due = aware(state.next_analysis_at)
        if state.status in {"pending", "running"} and existing_due:
            due = min(existing_due, due)
        state.next_analysis_at = due
        state.request_reason = reason
        if not active:
            state.status = "pending"
            state.lease_token = None
            state.lease_expires_at = None
        return state


class VehicleAnalysisJobService:
    def __init__(self, *, repository, load_input, analyze, utc_now, new_token,
                 input_context, logger, read_api_key):
        self.repository = repository
        self.load_input = load_input
        self.analyze = analyze
        self.utc_now = utc_now
        self.new_token = new_token
        self.input_context = input_context
        self.logger = logger
        self.read_api_key = read_api_key

    def run(self, state_id):
        now = self.utc_now()
        state = self.repository.get(state_id)
        if state is None:
            return False
        claimed_hash = state.input_hash
        token = self.new_token()
        if not self.repository.claim(state_id, claimed_hash, token, now):
            return False
        try:
            vehicle = self.repository.find_vehicle(state.company_code, state.vehicle_record_id)
            if vehicle is None:
                self.repository.skip(state_id, token)
                return True
            with self.input_context():
                payload, sources = self.load_input(vehicle)
            fingerprints = payload["_fingerprints"]
            signature = snapshot_hash(fingerprints)
            method = "ai" if fingerprints["has_important_history"] else "record_check"
            if method == "ai":
                def renew_analysis_lease():
                    self.repository.renew(state_id, token, self.utc_now())
                analysis = self.analyze(payload, on_progress=renew_analysis_lease)
            else:
                analysis = {
                    "overview": "AIの対応候補を作るための整備・不具合・点検指摘の履歴はありません。",
                    "recommendations": [],
                }
            finished = self.utc_now()
            bundle = {
                "analysis": analysis, "sources": sources, "coverage": payload["coverage"],
                "comparison": payload.get("comparison"), "fingerprints": fingerprints,
                "analysis_method": method,
                "generated_at": finished.astimezone(ZoneInfo("Asia/Tokyo")).strftime("%Y/%m/%d %H:%M"),
            }
            return self.repository.finish(
                state_id, token, claimed_hash=claimed_hash, snapshot_hash=signature,
                bundle=bundle, finished=finished, method=method,
            )
        except Exception as error:
            self.repository.rollback()
            code = f"{type(error).__name__}: {error}"
            key = self.read_api_key()
            if key:
                code = code.replace(key, "[REDACTED]")
            code = code[:500]
            self.logger.warning("車両自動分析に失敗しました: %s", code)
            self.repository.fail(state_id, token, code, self.utc_now() + timedelta(hours=1))
            return False


def analysis_input_projection(payload):
    records = payload.get("records", [])
    return {
        "fingerprints": payload["_fingerprints"],
        "comparison": payload.get("comparison"),
        "input_summary": {
            label: sum(
                str(row.get("source_id", "")).startswith(prefix) for row in records
            )
            for label, prefix in (
                ("daily_inspections", "inspection:"),
                ("periodic_inspections", "periodic:"),
                ("maintenance", "maintenance:"),
                ("parts", "part:"),
            )
        },
    }


class AnalysisReadProjectionService:
    def __init__(
        self,
        *,
        repository,
        load_projection,
        context_key,
        clock,
        load_legacy_projection=None
    ):
        self.repository = repository
        self.load_projection = load_projection
        self.context_key = context_key
        self.clock = clock
        self.load_legacy_projection = load_legacy_projection or load_projection

    def read(self, company, vehicle_id):
        key = self.context_key(self.clock())
        token = self.repository.token(company, self.clock())
        if token is None:
            return self.load_legacy_projection(), True
        cached = self.repository.get(company, vehicle_id, key, token, self.clock())
        if cached is not None:
            checked_at = self.clock()
            after = self.repository.token(company, checked_at)
            if (
                after is not None
                and token.revision == after.revision
                and key == self.context_key(checked_at)
                and token.observed_at <= checked_at < token.expires_at
            ):
                return cached, True
        projection = None
        for _ in range(2):
            before_time = self.clock()
            key = self.context_key(before_time)
            before = self.repository.token(company, before_time)
            if before is None:
                return self.load_legacy_projection(), True
            projection = self.load_projection()
            after_time = self.clock()
            after = self.repository.token(company, after_time)
            stable = (
                after is not None
                and before.revision == after.revision
                and key == self.context_key(after_time)
                and before_time <= after_time < before.expires_at
            )
            if stable:
                self.repository.put(company, vehicle_id, key, before, projection)
                return projection, True
        return projection, False
