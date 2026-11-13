"""Explicit, durable one-count path. No credentials lookup, CLI or automatic run.

Creation requires an operator-supplied authorization record; strings cannot prove
user consent. Fixed local ledger must never be recreated to retry. No generation.
"""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import http.client
import json
import ssl

from .count_material import bind_supplied_count, validate_material
from .ledger import Ledger
from .pilot import digest, positive_int, sha

COUNT_URL = 'https://api.openai.com/v1/responses/input_tokens'


@dataclass(frozen=True)
class CountPolicy:
    generation_sha256: str
    count_sha256: str
    target_hash: str
    model: str
    approval_reference: str
    reserved_count_microusd: int
    pricing_evidence_reference: str

    def __post_init__(self):
        if (not all(sha(x) for x in (self.generation_sha256,self.count_sha256,self.target_hash))
                or self.model != 'gpt-6.1-sol' or not isinstance(self.approval_reference,str)
                or not self.approval_reference.strip()
                or not isinstance(self.pricing_evidence_reference,str) or not self.pricing_evidence_reference.strip()
                or not positive_int(self.reserved_count_microusd)):
            raise ValueError('COUNT_AUTHORIZATION_AND_PRICING_REQUIRED')


class CountLedger(Ledger):
    @classmethod
    def create(cls, path, policy):
        if not isinstance(policy, CountPolicy):
            raise ValueError('COUNT_POLICY_REQUIRED')
        ledger = super().create(path, policy)
        with ledger._connect() as db:
            db.execute('CREATE TABLE count_evidence(response_hash TEXT NOT NULL, input_tokens INTEGER NOT NULL, request_id TEXT NOT NULL, received_at TEXT NOT NULL)')
            db.commit()
        return ledger

    def reserve_count(self, material):
        p = self.policy
        # Full immutable body linkage is checked without pretending a count exists.
        validate_material(material,
            observed_generation_sha256=p.generation_sha256, observed_count_sha256=p.count_sha256)
        if digest(asdict(material.target)) != p.target_hash or material.model != p.model:
            raise ValueError('COUNT_SCOPE_MISMATCH')
        with self._connect() as db:
            try:
                db.execute('BEGIN IMMEDIATE')
                db.execute('SELECT response_hash FROM count_evidence LIMIT 0')
                if db.execute('SELECT policy_hash FROM pilot').fetchone() != (self.policy_hash,):
                    raise ValueError('COUNT_POLICY_CHANGED')
                if db.execute('SELECT 1 FROM reservation LIMIT 1').fetchone():
                    raise ValueError('COUNT_ALREADY_ATTEMPTED_NO_RETRY')
                db.execute("INSERT INTO reservation(request_key,body_hash,amount,state) VALUES (?,?,?,'reserved')",
                    (p.generation_sha256,p.count_sha256,p.reserved_count_microusd))
                db.commit()
            except BaseException:
                db.rollback(); raise

    def record_count(self, evidence):
        with self._connect() as db:
            try:
                db.execute('BEGIN IMMEDIATE')
                if db.execute("UPDATE reservation SET state='returned' WHERE id=1 AND state='reserved'").rowcount != 1:
                    raise ValueError('COUNT_RESERVATION_NOT_OPEN')
                db.execute('INSERT INTO count_evidence VALUES (?,?,?,?)',
                    (evidence['response_sha256'],evidence['input_tokens'],evidence['request_id'],evidence['received_at']))
                db.commit()
            except BaseException:
                db.rollback(); raise


class CountHTTPS:
    def __init__(self, api_key, *, connection_factory=http.client.HTTPSConnection):
        if (not isinstance(api_key,str) or not api_key.strip() or any(c in api_key for c in '\r\n')
                or not callable(connection_factory)):
            raise ValueError('COUNT_CREDENTIAL_REQUIRED')
        self._key, self._factory, self._started = api_key, connection_factory, False

    def run(self, ledger, material):
        if not isinstance(ledger,CountLedger) or material.endpoint != COUNT_URL:
            raise ValueError('COUNT_ENDPOINT_OR_LEDGER_REJECTED')
        if self._started:
            raise ValueError('COUNT_NO_TRANSPORT_RETRY')
        self._started = True
        key, self._key = self._key, None
        connection = None
        reserved = False
        try:
            ledger.reserve_count(material)  # Commit before any connection or send.
            reserved = True
            connection = self._factory('api.openai.com',timeout=120,context=ssl.create_default_context())
            connection.request('POST','/v1/responses/input_tokens',body=material.count_json.encode(),
                headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError('COUNT_HTTP_REJECTED')
            raw = response.read(65537)
            if len(raw)>65536:
                raise ValueError('COUNT_RESPONSE_TOO_LARGE')
            evidence = bind_supplied_count(material,json.loads(raw),
                observed_generation_sha256=ledger.policy.generation_sha256,
                observed_count_sha256=ledger.policy.count_sha256)
            request_id = response.getheader('x-request-id')
            if (not isinstance(request_id,str) or not 1<=len(request_id)<=128
                    or not all(c.isascii() and (c.isalnum() or c in '_-') for c in request_id)):
                raise ValueError('COUNT_REQUEST_ID_REQUIRED')
            evidence.update(response_sha256=hashlib.sha256(raw).hexdigest(),request_id=request_id,
                            received_at=datetime.now(timezone.utc).isoformat(),transport_received=True)
            ledger.record_count(evidence)
            return evidence  # No body/key; generation authorization remains false.
        except BaseException:
            if reserved:
                try: ledger.record_outcome(1,'uncertain')
                except BaseException: pass  # Existing reserved/returned still blocks replay.
            raise RuntimeError('COUNT_ATTEMPT_FAILED_NO_RETRY') from None
        finally:
            key = None
            if connection is not None:
                try: connection.close()
                except Exception: pass
