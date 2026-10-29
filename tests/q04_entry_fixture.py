"""Synthetic manifests and evidence port. Never bind this port to production."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from sqlalchemy import Column, Integer, MetaData, String, Table

from tools.migration_entry import OPERATION, TABLES, digest


class MemoryEvidence:
    """Test-only atomic-port model, including unresolved-target/replay rejection."""
    def __init__(self):
        self.records = {}
        self.events = []
        self.busy = {}
        self.attempts = set()
        self.fail_event = None

    def read(self, ref):
        return copy.deepcopy(self.records[ref])

    def claim(self, pending):
        if pending['target_ref'] in self.busy or pending['attempt_id'] in self.attempts:
            raise RuntimeError('Attempt or unresolved target already reserved')
        self.attempts.add(pending['attempt_id'])
        self.busy[pending['target_ref']] = pending['attempt_id']
        return self.append(pending)

    def append(self, record):
        if record['event_type'] == self.fail_event:
            raise OSError('Synthetic storage unavailable')
        event_id = (record['attempt_id'], record['event_type'])
        existing = next((e for e in self.events if (e['attempt_id'], e['event_type']) == event_id), None)
        if existing is not None:
            if existing != record:
                raise ValueError('Evidence overwrite refused')
        else:
            self.events.append(copy.deepcopy(record))
        # A persisted FINAL can lose its ACK. Releasing here would let a caller's
        # UNKNOWN result be bypassed with a new attempt. Only an external manual
        # review/new approval may make a target idle again; there is no API here.
        return 'synthetic/' + '/'.join(event_id)


def manifest_for(snapshot, attempt='synthetic-1'):
    root = Path(__file__).resolve().parents[1]
    names = {'entry_sha256': 'tools/migration_entry.py',
             'adapter_sha256': 'tools/migration_adapters/q04_master_generations.py',
             'core_sha256': 'dkss_app/master_generations.py'}
    release = {k: hashlib.sha256((root / v).read_bytes()).hexdigest() for k, v in names.items()}
    release['source_commit'] = '1' * 40  # synthetic approved source, not a live release
    return dict(format_version=1, example_only=False, operation=OPERATION,
        ledger={'name': '技術移行選定台帳', 'item': 'M07', 'title': 'Q04マスタ世代'},
        attempt_id=attempt, release=release,
        target=dict(ref='synthetic-target', provider_resource_ref='synthetic-primary',
                    secret_ref='synthetic-no-secret', scope='isolated-test', snapshot=snapshot),
        evidence={name: dict(ref='synthetic-' + name, sha256=digest({'synthetic': name}))
                  for name in ('T01', 'T02', 'T03', 'baseline', 'privileges', 'writer_stop',
                               'backup_restore', 'form_revocation', 'rollback_write_restrictions')},
        approval=dict(P1_ref='synthetic-P1-' + attempt,
            window_start_utc=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            window_end_utc=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()))


def approve(manifest, evidence):
    raw = json.dumps(manifest, ensure_ascii=False).encode('utf-8')
    for name, item in manifest['evidence'].items():
        evidence.records[item['ref']] = {'synthetic': name}
    approval = dict(approval_ref=manifest['approval']['P1_ref'], approver_ref='synthetic-reviewer',
        manifest_sha256=hashlib.sha256(raw).hexdigest(), target_ref=manifest['target']['ref'],
        source_commit=manifest['release']['source_commit'], decision='P1_APPROVED',
        valid_until_utc=manifest['approval']['window_end_utc'])
    evidence.records[approval['approval_ref']] = copy.deepcopy(approval)
    return raw, approval


def fake_snapshot():
    return dict(endpoint='127.0.0.1', port=5432, database='q04_entry_ci', session_user='synthetic',
        current_user='synthetic', primary=True, schema='q04_entry_synthetic', schema_oid=50000,
        original_search_path='pg_catalog', effective_schemas=['pg_catalog'], isolation='read committed',
        read_only=False, ssl_in_use=False, connection_parameters_sha256='2' * 64,
        tables={t: dict(oid=50001+i, relkind='r', definition_sha256='3' * 64,
                       privileges=[True]*4, indexes_valid=True) for i, t in enumerate(TABLES)})


def legacy_fixture(engine, schema):
    metadata = MetaData(schema=schema)
    for name in (*TABLES, 'csv_owner_control'):
        Table(name, metadata, Column('id', Integer, primary_key=True),
              Column('company_code', String(50)), Column('name', String(100)),
              Column('owner_identity', String(36)))
    metadata.create_all(engine)
    with engine.begin() as connection:
        for table in metadata.tables.values():
            connection.execute(table.insert(), [dict(id=1, company_code='A', name='A', owner_identity=None),
                dict(id=2, company_code='B', name='B', owner_identity='11111111-1111-4111-8111-111111111111')])
