"""DRAFT PostgreSQL durable ledger. No connection, DDL or send on import.

Migration is separate. Fixed trial ID is consumed before queue or count. No
resume/recreate API: any repeat start fails even when no request was sent.
"""
from contextlib import contextmanager
from dataclasses import asdict
from sqlalchemy import text
from tools.quality.scoped_analysis.ledger import Ledger
from tools.quality.scoped_analysis.count_transport import CountLedger, CountPolicy
from tools.quality.scoped_analysis.count_material import validate_material
from tools.quality.scoped_analysis.pilot import Trial, Policy, digest

TRIAL_ID = 'approved-388-HARUMICHI-644-count1-generation1'


class PostgresStore:
    def __init__(self, engine):
        if engine.dialect.name != 'postgresql':
            raise ValueError('POSTGRES_LEDGER_REQUIRED')
        self.engine = engine

    def sql(self, raw):
        # Non-PG branch is reachable only via the private disposable test seam.
        return text(raw if self.engine.dialect.name == 'postgresql' else raw.replace('public.', ''))

    @contextmanager
    def writing(self):
        with self.engine.begin() as db:
            if self.engine.dialect.name == 'postgresql':
                db.execute(text('SET LOCAL synchronous_commit = on'))
            yield db

    def start(self, *, approval_reference, pricing_reference):
        # One fixed trial identity, including all failure stages. No UPSERT.
        if not approval_reference or not pricing_reference:
            raise ValueError('EVIDENCE_REFERENCES_REQUIRED')
        with self.writing() as db:
            db.execute(self.sql('''INSERT INTO public.dkss_scoped_pilot_trial
                (trial_id,approval_hash,pricing_hash) VALUES (:t,:a,:p)'''),
                {'t':TRIAL_ID,'a':digest(approval_reference),'p':digest(pricing_reference)})

    def verify_unstarted(self, *, approval_reference, pricing_reference):
        """Read-only continuation gate, caller MUST hold canonical leadership.

        Existing marker is retained unchanged. Any phase/reservation forbids
        continuation, including uncertain/reserved attempts. No implicit resume.
        """
        with self.writing() as db:
            query = 'SELECT approval_hash,pricing_hash FROM public.dkss_scoped_pilot_trial WHERE trial_id=:t'
            if self.engine.dialect.name == 'postgresql':
                query += ' FOR UPDATE'
            rows = db.execute(self.sql(query), {'t':TRIAL_ID}).all()
            if len(rows) != 1 or tuple(rows[0]) != (digest(approval_reference),digest(pricing_reference)):
                raise ValueError('CONTINUATION_MARKER_MISMATCH')
            for suffix in ('phase','reservation'):
                n = db.execute(self.sql('SELECT count(*) FROM public.dkss_scoped_pilot_'+suffix+' WHERE trial_id=:t'), {'t':TRIAL_ID}).scalar_one()
                if n != 0:
                    raise ValueError('CONTINUATION_HAS_PHASE_OR_RESERVATION')

    def create_phase(self, phase, policy_hash):
        if phase not in ('count', 'generation'):
            raise ValueError('PHASE_REJECTED')
        with self.writing() as db:
            db.execute(self.sql('''INSERT INTO public.dkss_scoped_pilot_phase
                (trial_id,phase,policy_hash) VALUES (:t,:p,:h)'''),
                {'t':TRIAL_ID,'p':phase,'h':policy_hash})

    def reserve(self, phase, policy_hash, body_hash, amount):
        # Phase row lock serializes the check and INSERT on PostgreSQL. Unique
        # primary key also prevents duplicates after process/connection failure.
        with self.writing() as db:
            query = 'SELECT policy_hash FROM public.dkss_scoped_pilot_phase WHERE trial_id=:t AND phase=:p'
            if self.engine.dialect.name == 'postgresql':
                query += ' FOR UPDATE'
            stored = db.execute(self.sql(query), {'t':TRIAL_ID,'p':phase}).scalar_one()
            if stored != policy_hash:
                raise ValueError('POLICY_CHANGED')
            db.execute(self.sql('''INSERT INTO public.dkss_scoped_pilot_reservation
                (trial_id,phase,body_hash,amount,state) VALUES (:t,:p,:h,:a,'reserved')'''),
                {'t':TRIAL_ID,'p':phase,'h':body_hash,'a':amount})
            # Commit must return before any HTTP transport can be invoked.

    def outcome(self, phase, outcome, evidence=None):
        if outcome not in ('returned','uncertain'):
            raise ValueError('OUTCOME_REJECTED')
        evidence = evidence or {}
        with self.writing() as db:
            result = db.execute(self.sql('''UPDATE public.dkss_scoped_pilot_reservation
                SET state=:s,response_hash=:h,input_tokens=:n,request_id=:r,received_at=:d
                WHERE trial_id=:t AND phase=:p AND state='reserved' '''),
                {'s':outcome,'h':evidence.get('response_sha256'),'n':evidence.get('input_tokens'),
                 'r':evidence.get('request_id'),'d':evidence.get('received_at'),'t':TRIAL_ID,'p':phase})
            if result.rowcount != 1:
                raise ValueError('RESERVATION_NOT_OPEN')

    def receipts(self, phase):
        with self.engine.connect() as db:
            rows = db.execute(self.sql('''SELECT body_hash,amount,state FROM public.dkss_scoped_pilot_reservation
                WHERE trial_id=:t AND phase=:p'''), {'t':TRIAL_ID,'p':phase}).all()
            return [(1, *tuple(row)) for row in rows]


class PostgresGenerationLedger(Ledger):
    def __init__(self, store, policy):
        if (not isinstance(store,PostgresStore) or not isinstance(policy,Policy)
                or policy.max_calls != 1 or len(policy.targets) != 1
                or policy.targets[0].company != 'HARUMICHI' or policy.targets[0].vehicle_id != 644
                or policy.budget_microusd != 250000):
            raise ValueError('FIXED_TRIAL_POLICY_REQUIRED')
        self.store, self.policy = store, policy
        self.policy_hash = digest(asdict(policy))
        store.create_phase('generation', self.policy_hash)

    def reserve(self, request, *, observed_target):
        body, receipt = Trial(self.policy).prepare(request, observed_target=observed_target)
        self.store.reserve('generation',self.policy_hash,request.body_sha256,receipt['reserved_microusd'])
        return body, 1

    def record_outcome(self, number, outcome):
        if number != 1:
            raise ValueError('SINGLE_RESERVATION_ONLY')
        self.store.outcome('generation',outcome)

    def receipts(self):
        return self.store.receipts('generation')


class PostgresCountLedger(CountLedger):
    def __init__(self, store, policy):
        if not isinstance(store,PostgresStore) or not isinstance(policy,CountPolicy) or policy.reserved_count_microusd != 1:
            raise ValueError('FIXED_COUNT_POLICY_REQUIRED')
        self.store, self.policy = store, policy
        self.policy_hash = digest(asdict(policy))
        store.create_phase('count', self.policy_hash)

    def reserve_count(self, material):
        p = self.policy
        validate_material(material, observed_generation_sha256=p.generation_sha256,
                          observed_count_sha256=p.count_sha256)
        if (digest(asdict(material.target)) != p.target_hash or material.model != p.model
                or material.target.company != 'HARUMICHI' or material.target.vehicle_id != 644):
            raise ValueError('COUNT_SCOPE_MISMATCH')
        self.store.reserve('count',self.policy_hash,p.count_sha256,p.reserved_count_microusd)

    def record_count(self, evidence):
        self.store.outcome('count','returned',evidence)

    def record_outcome(self, number, outcome):
        if number != 1:
            raise ValueError('SINGLE_RESERVATION_ONLY')
        self.store.outcome('count',outcome)

    def receipts(self):
        return self.store.receipts('count')
