"""Single-machine durable reservations for a finite pilot; no network or app DB.

One explicit local file per approved trial. Never recreate a missing ledger on
resume. SQLite FULL synchronous + IMMEDIATE transactions precede any callback.
Not an API idempotency guarantee, shared-drive/multi-host ledger or invoice cap.
"""
from contextlib import closing
from dataclasses import asdict
import os
from pathlib import Path
import sqlite3
from .pilot import Trial, digest


class Ledger:
    def __init__(self, path, policy):
        self.path = Path(path).resolve()
        self.policy = policy
        self.policy_hash = digest(asdict(policy))
        if not self.path.is_file():
            raise ValueError('LEDGER_MISSING_DO_NOT_RECREATE')
        stat=self.path.stat()
        self.identity=(stat.st_dev,stat.st_ino)
        with self._connect() as db:
            row = db.execute('SELECT policy_hash FROM pilot').fetchone()
            if row != (self.policy_hash,):
                raise ValueError('LEDGER_POLICY_MISMATCH')

    def _connect(self):
        # mode=rw forbids implicit creation on resume after file loss.
        stat=self.path.stat()
        if (stat.st_dev,stat.st_ino) != self.identity:
            raise ValueError('LEDGER_FILE_REPLACED')
        db = sqlite3.connect(self.path.as_uri()+'?mode=rw', uri=True, timeout=5)
        stat=self.path.stat()
        if (stat.st_dev,stat.st_ino) != self.identity:
            db.close()
            raise ValueError('LEDGER_FILE_REPLACED')
        db.execute('PRAGMA synchronous=FULL')
        db.execute('PRAGMA busy_timeout=5000')
        return closing(db)

    @classmethod
    def create(cls, path, policy):
        path = Path(path).resolve()
        # Only local POSIX storage currently validated, not Windows/network FS.
        if os.name != 'posix':
            raise ValueError('LEDGER_PLATFORM_NOT_VALIDATED')
        fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        os.close(fd)
        with closing(sqlite3.connect(str(path))) as db:
            db.execute('PRAGMA synchronous=FULL')
            db.executescript('''
                CREATE TABLE pilot(policy_hash TEXT NOT NULL);
                CREATE TABLE reservation(
                    id INTEGER PRIMARY KEY,
                    request_key TEXT NOT NULL UNIQUE,
                    body_hash TEXT NOT NULL,
                    amount INTEGER NOT NULL CHECK(amount>0),
                    state TEXT NOT NULL CHECK(state IN ('reserved','returned','uncertain')));
            ''')
            db.execute('INSERT INTO pilot VALUES (?)',(digest(asdict(policy)),))
            db.commit()
        directory = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
        return cls(path, policy)

    def reserve(self, request, *, observed_target):
        # Reuse all existing request/model/scope/token/rate validations.
        body, proposed = Trial(self.policy).prepare(request, observed_target=observed_target)
        amount = proposed['reserved_microusd']
        key = digest({'target':asdict(request.target),'body':request.body_sha256})
        with self._connect() as db:
            try:
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT policy_hash FROM pilot').fetchone() != (self.policy_hash,):
                    raise ValueError('LEDGER_POLICY_MISMATCH')
                if db.execute("SELECT 1 FROM reservation WHERE state IN ('reserved','uncertain') LIMIT 1").fetchone():
                    raise ValueError('UNRESOLVED_RESERVATION_NO_RETRY')
                if db.execute('SELECT 1 FROM reservation WHERE request_key=?',(key,)).fetchone():
                    raise ValueError('REPLAY_FORBIDDEN')
                calls, used = db.execute('SELECT count(*), coalesce(sum(amount),0) FROM reservation').fetchone()
                if calls >= self.policy.max_calls or used+amount > self.policy.budget_microusd:
                    raise ValueError('BUDGET_OR_CALL_LIMIT')
                cursor=db.execute("INSERT INTO reservation(request_key,body_hash,amount,state) VALUES (?,?,?,'reserved')",
                                  (key,request.body_sha256,amount))
                number=cursor.lastrowid
                db.commit()  # Only after this returns may a caller transmit.
            except BaseException:
                db.rollback()
                raise
        return body, number

    def reserve_exact_body(self, approved_request, actual_body_json, *, observed_target):
        """Guard the approved serialized transport, not a caller's rebuilt guess."""
        if actual_body_json != approved_request.body_json:
            raise ValueError('APPROVED_TRANSPORT_BODY_CHANGED')
        return self.reserve(approved_request, observed_target=observed_target)

    def record_outcome(self, number, outcome):
        if outcome not in ('returned','uncertain'):
            raise ValueError('INVALID_LEDGER_OUTCOME')
        with self._connect() as db:
            try:
                db.execute('BEGIN IMMEDIATE')
                if db.execute("UPDATE reservation SET state=? WHERE id=? AND state='reserved'",
                              (outcome,number)).rowcount != 1:
                    raise ValueError('RESERVATION_NOT_OPEN')
                db.commit()
            except BaseException:
                db.rollback(); raise

    def receipts(self):
        with self._connect() as db:
            return db.execute('SELECT id,body_hash,amount,state FROM reservation ORDER BY id').fetchall()

    def synthetic_call(self, request, *, observed_target, transport):
        if any(not t.company.startswith('SYNTHETIC_') for t in self.policy.targets):
            raise ValueError('SYNTHETIC_ONLY')
        body, number = self.reserve(request, observed_target=observed_target)
        try:
            result=transport(body)
        except BaseException:
            self.record_outcome(number,'uncertain')
            raise
        self.record_outcome(number,'returned')
        return result
