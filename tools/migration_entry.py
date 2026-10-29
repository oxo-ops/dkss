"""Approval-bound Q04 library entry. No CLI, credentials, job or recovery executor.

The supervisor supplies an Engine and a trusted evidence port. The port must
atomically claim an idle target/attempt, durably append events, reject overwrite
and NEVER auto-release a claimed target (even after FINAL). This also covers a
persisted FINAL whose storage ACK is lost. No resume/release API is provided.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Protocol

from sqlalchemy import event, text

from dkss_app.master_generations import KINDS
from tools.migration_adapters.q04_master_generations import apply


OPERATION = 'q04.master_generations.v1'
TABLES = tuple(KINDS.values())
_HEX = re.compile(r'[0-9a-f]{64}')
_REF = re.compile(r'[A-Za-z0-9_.:/-]{1,160}')


class ContractError(ValueError):
    """Only a fixed, non-secret code is allowed across this boundary."""


class TargetRejected(RuntimeError):
    pass


class EvidencePort(Protocol):
    def read(self, ref: str) -> dict: ...
    def claim(self, pending: dict) -> str:
        """Atomic durable PENDING; reject reused attempt or non-idle target."""
        ...
    def append(self, record: dict) -> str:
        """Durable append, idempotent identical event only; NEVER release a claim."""
        ...


def digest(value):
    """Digest JSON-compatible non-secret evidence; manifest uses its exact bytes."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode('utf-8')).hexdigest()


def _time(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed
    except (ValueError, TypeError, AttributeError):
        raise ContractError('INVALID_APPROVAL_TIME') from None


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError('DUPLICATE_MANIFEST_KEY')
        result[key] = value
    return result


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected.split()):
        raise ContractError('INVALID_MANIFEST_SHAPE')


def _ref(value):
    if not isinstance(value, str) or not _REF.fullmatch(value):
        raise ContractError('INVALID_EVIDENCE_REFERENCE')


def _approved(raw, approval, evidence):
    if not isinstance(raw, bytes) or len(raw) > 131072:
        raise ContractError('MANIFEST_BYTES_REQUIRED')
    try:
        m = json.loads(raw, object_pairs_hook=_unique)
        _keys(m, 'format_version example_only operation ledger attempt_id release target evidence approval')
        if type(m['format_version']) is not int or m['format_version'] != 1 or m['example_only'] is not False or m['operation'] != OPERATION:
            raise ContractError('UNAPPROVED_MANIFEST_KIND')
        if m['ledger'] != {'name': '技術移行選定台帳', 'item': 'M07', 'title': 'Q04マスタ世代'}:
            raise ContractError('WRONG_LEDGER')
        _ref(m['attempt_id'])
        _keys(m['release'], 'source_commit entry_sha256 adapter_sha256 core_sha256')
        if not re.fullmatch(r'[0-9a-f]{40}', m['release']['source_commit']):
            raise ContractError('FULL_SOURCE_COMMIT_REQUIRED')
        from pathlib import Path
        expected = {
            'entry_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'adapter_sha256': hashlib.sha256(Path(__file__).with_name('migration_adapters')
                                            .joinpath('q04_master_generations.py').read_bytes()).hexdigest(),
            'core_sha256': hashlib.sha256(Path(__file__).resolve().parents[1]
                                         .joinpath('dkss_app/master_generations.py').read_bytes()).hexdigest()}
        if any(m['release'][k] != v for k, v in expected.items()):
            raise ContractError('EXECUTABLE_DIGEST_MISMATCH')
        _keys(m['target'], 'ref provider_resource_ref secret_ref scope snapshot')
        for key in ('ref', 'provider_resource_ref', 'secret_ref'):
            _ref(m['target'][key])
        target = m['target']['snapshot']
        _keys(target, 'endpoint port database session_user current_user primary schema schema_oid '
                      'original_search_path effective_schemas isolation read_only ssl_in_use '
                      'connection_parameters_sha256 tables')
        if (type(target['port']) is not int or not 0 < target['port'] < 65536
                or type(target['schema_oid']) is not int or target['schema_oid'] <= 0
                or any(not isinstance(target[k], str) or not target[k]
                       for k in ('endpoint', 'database', 'session_user', 'current_user', 'original_search_path'))):
            raise ContractError('INVALID_TARGET_IDENTITY')
        if (not isinstance(target['schema'], str) or not target['schema']
                or target['schema'].startswith('pg_') or target['schema'] == 'information_schema'):
            raise ContractError('EXPLICIT_BUSINESS_SCHEMA_REQUIRED')
        if (target['primary'] is not True or target['read_only'] is not False
                or target['isolation'] != 'read committed'):
            raise ContractError('WRITABLE_READ_COMMITTED_PRIMARY_REQUIRED')
        if not _HEX.fullmatch(target['connection_parameters_sha256']):
            raise ContractError('CONNECTION_PROFILE_REQUIRED')
        if set(target['tables']) != set(TABLES):
            raise ContractError('EXACT_FIVE_TABLES_REQUIRED')
        for table in target['tables'].values():
            _keys(table, 'oid relkind definition_sha256 privileges indexes_valid')
            if (type(table['oid']) is not int or table['oid'] <= 0 or table['relkind'] != 'r'
                    or not _HEX.fullmatch(table['definition_sha256'])
                    or table['privileges'] != [True, True, True, True]
                    or table['indexes_valid'] is not True):
                raise ContractError('UNEXPECTED_STORAGE_OR_PRIVILEGES')
        scope = m['target']['scope']
        if scope == 'isolated-test':
            if (target['endpoint'] not in {'127.0.0.1', '::1', 'localhost'}
                    or not target['database'].startswith('q04_entry_')
                    or not target['schema'].startswith('q04_entry_')):
                raise ContractError('ISOLATED_TARGET_REQUIRED')
        elif scope != 'production-approved' or target['ssl_in_use'] is not True:
            raise ContractError('VERIFIED_TLS_REQUIRED')
        _keys(m['evidence'], 'T01 T02 T03 baseline privileges writer_stop backup_restore form_revocation rollback_write_restrictions')
        for item in m['evidence'].values():
            _keys(item, 'ref sha256')
            _ref(item['ref'])
            if not _HEX.fullmatch(item['sha256']) or digest(evidence.read(item['ref'])) != item['sha256']:
                raise ContractError('EVIDENCE_DIGEST_MISMATCH')
        _keys(m['approval'], 'P1_ref window_start_utc window_end_utc')
        _keys(approval, 'approval_ref approver_ref manifest_sha256 target_ref source_commit valid_until_utc decision')
        _ref(approval['approver_ref'])
        _ref(approval['approval_ref'])
        if (approval['decision'] != 'P1_APPROVED' or approval['approval_ref'] != m['approval']['P1_ref']
                or evidence.read(approval['approval_ref']) != approval
                or approval['manifest_sha256'] != hashlib.sha256(raw).hexdigest()
                or approval['target_ref'] != m['target']['ref']
                or approval['source_commit'] != m['release']['source_commit']):
            raise ContractError('APPROVAL_MISMATCH')
        now = datetime.now(timezone.utc)
        if not (_time(m['approval']['window_start_utc']) <= now
                < min(_time(m['approval']['window_end_utc']), _time(approval['valid_until_utc']))):
            raise ContractError('APPROVAL_EXPIRED_OR_NOT_STARTED')
        return m
    except ContractError:
        raise
    except Exception:
        raise ContractError('MANIFEST_OR_EVIDENCE_INVALID') from None


def snapshot_target(connection, schema):
    """Read only: fixed target/shape, not a diagnostic or manifest approver."""
    if connection.dialect.name != 'postgresql' or connection.dialect.driver != 'psycopg2':
        raise TargetRejected('POSTGRES_PSYCOPG2_REQUIRED')
    driver = connection.connection.driver_connection
    if driver.autocommit:
        raise TargetRejected('EXPLICIT_TRANSACTION_REQUIRED')
    params = driver.get_dsn_parameters()
    profile = {k: v for k, v in params.items() if k not in {'password', 'sslpassword', 'passfile'}}
    row = connection.execute(text("""SELECT pg_catalog.current_database(), session_user, current_user,
        NOT pg_catalog.pg_is_in_recovery(), pg_catalog.current_setting('search_path'),
        pg_catalog.current_schemas(true), pg_catalog.current_setting('transaction_isolation'),
        pg_catalog.current_setting('transaction_read_only') = 'on',
        COALESCE((SELECT ssl FROM pg_catalog.pg_stat_ssl WHERE pid=pg_catalog.pg_backend_pid()), false)""")).one()
    schema_oid = connection.scalar(text('SELECT oid FROM pg_catalog.pg_namespace WHERE nspname=:s'), {'s': schema})
    if schema_oid is None:
        raise TargetRejected('SCHEMA_MISSING')
    tables = {}
    for name in TABLES:
        r = connection.execute(text("""SELECT c.oid, c.relkind, c.relrowsecurity, c.relforcerowsecurity,
            pg_catalog.has_schema_privilege(n.oid,'USAGE'),
            pg_catalog.has_table_privilege(c.oid,'SELECT'), pg_catalog.has_table_privilege(c.oid,'UPDATE'),
            pg_catalog.pg_has_role(current_user,c.relowner,'USAGE'), c.relowner, c.relacl::text
            FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=:s AND c.relname=:t"""), {'s': schema, 't': name}).one_or_none()
        if r is None:
            raise TargetRejected('MASTER_TABLE_MISSING')
        columns = connection.execute(text("""SELECT a.attnum, a.attname,
            pg_catalog.format_type(a.atttypid,a.atttypmod), a.attnotnull, a.attidentity, a.attgenerated,
            a.attcollation, pg_catalog.pg_get_expr(d.adbin,d.adrelid)
            FROM pg_catalog.pg_attribute a LEFT JOIN pg_catalog.pg_attrdef d
            ON d.adrelid=a.attrelid AND d.adnum=a.attnum
            WHERE a.attrelid=:oid AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum"""), {'oid': r[0]}).all()
        indexes = connection.execute(text("""SELECT pg_catalog.pg_get_indexdef(indexrelid), indisvalid, indisready
            FROM pg_catalog.pg_index WHERE indrelid=:oid ORDER BY indexrelid"""), {'oid': r[0]}).all()
        constraints = connection.execute(text("""SELECT conname, contype, convalidated,
            pg_catalog.pg_get_constraintdef(oid) FROM pg_catalog.pg_constraint
            WHERE conrelid=:oid ORDER BY conname"""), {'oid': r[0]}).all()
        extras = connection.execute(text("""SELECT
            EXISTS(SELECT 1 FROM pg_catalog.pg_trigger WHERE tgrelid=:oid AND NOT tgisinternal),
            EXISTS(SELECT 1 FROM pg_catalog.pg_rewrite WHERE ev_class=:oid),
            EXISTS(SELECT 1 FROM pg_catalog.pg_inherits WHERE inhrelid=:oid OR inhparent=:oid)"""), {'oid': r[0]}).one()
        tables[name] = dict(oid=r[0], relkind=r[1], privileges=list(r[4:8]),
            indexes_valid=all(i[1] and i[2] for i in indexes),
            definition_sha256=digest([list(r[2:4]), list(r[8:]), [list(c) for c in columns],
                                      [list(i) for i in indexes], [list(c) for c in constraints], list(extras)]))
    return dict(endpoint=params.get('host', ''), port=int(params.get('port', 5432)), database=row[0],
        session_user=row[1], current_user=row[2], primary=row[3], schema=schema, schema_oid=schema_oid,
        original_search_path=row[4], effective_schemas=list(row[5]), isolation=row[6], read_only=row[7],
        ssl_in_use=row[8], connection_parameters_sha256=digest(profile), tables=tables)


@dataclass
class _Trace:
    connection: object = None
    driver: object = None
    commit_entered: bool = False
    rollback_entered: bool = False
    phase: str = 'BEFORE_CONNECT'
    refs: list = field(default_factory=list)
    rejected_fields: list = field(default_factory=list)

    def attach(self, connection):
        self.connection = connection
        self.driver = connection.connection.driver_connection
        event.listen(connection, 'commit', lambda c: setattr(self, 'commit_entered', True))
        event.listen(connection, 'rollback', lambda c: setattr(self, 'rollback_entered', True))

    def rollback_confirmed(self):
        # SQLAlchemy's rollback event is BEFORE the DBAPI call: it alone is not proof.
        try:
            return (not self.commit_entered and self.rollback_entered and not self.driver.closed
                    and self.driver.get_transaction_status() == 0)  # psycopg2 IDLE
        except Exception:
            return False


def _different_fields(expected, actual, prefix=''):
    fields = []
    for key, value in expected.items():
        name = prefix + key
        if isinstance(value, dict) and isinstance(actual.get(key), dict):
            fields.extend(_different_fields(value, actual[key], name + '.'))
        elif value != actual.get(key):
            fields.append(name)
    return fields


def execute_q04(*, engine, manifest, approval, evidence):
    """One attempt only. An unavailable evidence port is a hard, closed failure."""
    m = _approved(manifest, approval, evidence)
    if engine.dialect.name != 'postgresql' or engine.dialect.driver != 'psycopg2':
        raise ContractError('POSTGRES_PSYCOPG2_REQUIRED')
    if engine.echo or engine.pool.echo:
        raise ContractError('SQL_LOGGING_MUST_BE_DISABLED')
    trace = _Trace()
    base = dict(attempt_id=m['attempt_id'], manifest_sha256=hashlib.sha256(manifest).hexdigest(),
                target_ref=m['target']['ref'], operation=OPERATION)

    def record(kind, **values):
        receipt = evidence.append(dict(base, event_type=kind, **values))
        _ref(receipt)
        return receipt

    result = dict(base, status='OUTCOME_UNKNOWN', commit_state='NOT_ATTEMPTED',
                  failure_code=None, sqlstate=None, report=None, evidence_refs=trace.refs,
                  last_guard_phase=trace.phase, rejected_fields=[])
    try:
        receipt = evidence.claim(dict(base, event_type='PENDING'))
        _ref(receipt)
        trace.refs.append(receipt)
    except Exception:
        result['failure_code'] = 'ATTEMPT_CLAIM_FAILED'
        return result

    def guard(connection, phase):
        if phase == 'CONNECTED':
            if trace.connection is not None:
                raise TargetRejected('GUARD_CONNECTION_OR_PHASE_MISMATCH')
            trace.attach(connection)
        elif phase != 'LOCKED' or trace.phase != 'CONNECTED' or connection is not trace.connection:
            raise TargetRejected('GUARD_CONNECTION_OR_PHASE_MISMATCH')
        connection.exec_driver_sql("SET LOCAL statement_timeout='15s'")
        # Expiry can occur while waiting for all five locks; never rely on entry-time only.
        _approved(manifest, approval, evidence)
        actual = snapshot_target(connection, m['target']['snapshot']['schema'])
        if actual != m['target']['snapshot']:
            trace.rejected_fields = _different_fields(m['target']['snapshot'], actual)
            raise TargetRejected('TARGET_CHANGED')
        if m['target']['scope'] == 'production-approved':
            if trace.driver.get_dsn_parameters().get('sslmode') != 'verify-full':
                raise TargetRejected('VERIFIED_TLS_REQUIRED')
        if phase == 'CONNECTED':
            key = int.from_bytes(hashlib.sha256((base['target_ref'] + ':' + OPERATION).encode()).digest()[:8], 'big', signed=True)
            if not connection.scalar(text('SELECT pg_catalog.pg_try_advisory_xact_lock(:key)'), {'key': key}):
                raise TargetRejected('TARGET_BUSY')
        else:
            held = set(connection.scalars(text("""SELECT relation FROM pg_catalog.pg_locks
                WHERE pid=pg_catalog.pg_backend_pid() AND locktype='relation'
                AND mode='AccessExclusiveLock' AND granted""")))
            if not {t['oid'] for t in actual['tables'].values()}.issubset(held):
                raise TargetRejected('FIVE_LOCKS_REQUIRED')
        trace.refs.append(record(phase + '_OK', target_fingerprint=digest(actual)))
        trace.phase = phase

    try:
        report = apply(engine=engine, schema=m['target']['snapshot']['schema'], target_guard=guard)
        result.update(report=report, commit_state='ACKNOWLEDGED',
                      status='ALREADY_APPLIED' if all(not r['added_column'] and r['assigned'] == 0
                                                    for r in report.values()) else 'APPLIED')
    except Exception as error:
        original = getattr(error, 'orig', None)
        sqlstate = getattr(original, 'pgcode', None)
        result['sqlstate'] = sqlstate if isinstance(sqlstate, str) and re.fullmatch('[0-9A-Z]{5}', sqlstate) else None
        if trace.rollback_confirmed():
            result.update(status='REJECTED' if isinstance(error, (TargetRejected, ContractError))
                          else 'ABORTED_CONFIRMED', commit_state='NOT_COMMITTED', failure_code='PRECOMMIT_ROLLBACK_CONFIRMED')
        else:
            result.update(commit_state='UNKNOWN' if trace.commit_entered else 'NOT_CONFIRMED',
                          failure_code='COMMIT_OR_CLEANUP_NOT_CONFIRMED')
    result['last_guard_phase'] = trace.phase
    result['rejected_fields'] = trace.rejected_fields
    try:
        trace.refs.append(record('FINAL', status=result['status'], commit_state=result['commit_state'],
                                 failure_code=result['failure_code'], sqlstate=result['sqlstate'],
                                 rejected_fields=result['rejected_fields'], report=result['report']))
    except Exception:
        result.update(status='OUTCOME_UNKNOWN', failure_code='FINAL_RECORD_FAILED')
    return result


def reconcile_q04(*, attempt, readback_ref, evidence):
    """Compare supervisor-approved readback only. Never reconnect, retry or unlock."""
    if attempt.get('status') != 'OUTCOME_UNKNOWN':
        raise ContractError('UNKNOWN_ATTEMPT_REQUIRED')
    _ref(readback_ref)
    try:
        readback = evidence.read(readback_ref)
        if (readback['target_ref'] != attempt['target_ref']
                or readback['manifest_sha256'] != attempt['manifest_sha256']
                or readback['target_verified'] is not True or not readback['reviewer_ref']):
            raise ContractError('READBACK_TARGET_MISMATCH')
        storage = readback['storage_state']
        commit = readback['attempt_commit']
        if storage not in {'PRESTATE_MATCH', 'APPLIED_STATE_MATCH', 'INCONSISTENT', 'UNKNOWN'}:
            raise ContractError('INVALID_READBACK_STATE')
        if commit not in {'CONFIRMED', 'NOT_COMMITTED_CONFIRMED', 'UNKNOWN'}:
            raise ContractError('INVALID_COMMIT_STATE')
        if commit != 'UNKNOWN' and not readback.get('transaction_evidence_ref'):
            raise ContractError('TRANSACTION_EVIDENCE_REQUIRED')
        if commit != 'UNKNOWN':
            proof = evidence.read(readback['transaction_evidence_ref'])
            if any(proof.get(k) != attempt[k] for k in ('attempt_id', 'target_ref', 'manifest_sha256')) or proof.get('attempt_commit') != commit:
                raise ContractError('TRANSACTION_EVIDENCE_MISMATCH')
        result = dict(storage_state=storage, attempt_commit=commit, resume_allowed=False)
        receipt = evidence.append(dict(attempt_id=attempt['attempt_id'], target_ref=attempt['target_ref'],
            event_type='RECONCILIATION_' + digest(readback), readback_ref=readback_ref, **result))
        _ref(receipt)
        return result
    except ContractError:
        raise
    except Exception:
        raise ContractError('READBACK_UNAVAILABLE') from None
