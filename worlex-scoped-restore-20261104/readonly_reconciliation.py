"""Sealed read-only sequence batching and secret-free, mandatory observation.

This companion is not the restore runner. Its separate byte identity must be
bound in the successor's evidence alongside the immutable legacy runner/plan.
It is never imported by the production execute CLI. No retries or writes to DB.
"""
from __future__ import annotations
import contextlib
import datetime
import hashlib
import json
import logging
import re
import struct
import time
import types
from pathlib import Path

LEGACY_CORE_SHA256 = 'fd22c4f29b566a0403da17d9b524ad8d6091a417d4ab9f2ca3788991eb2ba446'
CONTRACT = 'worlex_readonly_batch_observation_v1'
MAX_BRANCHES = 16
MAX_SQL_BYTES = 32768
MAX_REQUESTED = 256
MAX_EVENTS = 256
_ACTIVE = False
PHASES = frozenset(('connect', 'session_before', 'data', 'session_after', 'rollback',
    'close', 'dispose', 'plan', 'verify_restore', 'reader_mode', 'sequence_metadata',
    'sequence_ownership', 'sequence_values', 'complete', 'outside'))
ERROR_TYPES = frozenset(('Stop', 'ReadOnlyStop', 'ClientStop', 'InterfaceError',
    'OperationalError', 'DatabaseError', 'TimeoutError', 'OSError', 'PermissionError',
    'KeyboardInterrupt', 'ValueError', 'RuntimeError', 'ProgrammingError', 'InternalError',
    'DataError', 'IntegrityError', 'InvalidRequestError', 'PendingRollbackError',
    'SSLError', 'SSLEOFError', 'ConnectionResetError', 'BrokenPipeError'))
# Only documented codes useful to this read-only workflow, not arbitrary five
# characters supplied by exceptions. No message, detail, hint, SQL or params.
SQLSTATES = frozenset(('08000', '08001', '08003', '08004', '08006', '08007', '08P01',
    '25006', '25P02', '25P03', '25P04', '40001', '40P01', '42501', '42P01',
    '42703', '53300', '53400', '57014', '57P01', '57P02', '57P03', '57P05', '58030'))

class ReadOnlyStop(RuntimeError): pass

def require(condition, code):
    if not condition: raise ReadOnlyStop(code)

def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

def _safe_attribute(value, key, default=None):
    try: return getattr(value, key, default)
    except BaseException: return default


def safe_error(error):
    """Bounded traversal of actual exception links; no formatting of any error."""
    name = type(error).__name__
    state = None
    pending = [error]; seen = set()
    for current in pending:
        if id(current) in seen: continue
        seen.add(id(current))
        args = _safe_attribute(current, 'args', ())
        candidates = [_safe_attribute(current, 'sqlstate'), _safe_attribute(current, 'pgcode')]
        if type(args) is tuple and args and type(args[0]) is dict:
            candidates.append(args[0].get('C'))
        for candidate in candidates:
            if type(candidate) is str and candidate in SQLSTATES:
                state = candidate; break
        if state is not None: break
        for key in ('orig', '__cause__', '__context__'):
            child = _safe_attribute(current, key)
            if isinstance(child, BaseException) and id(child) not in seen and len(pending) < 6:
                pending.append(child)
    return {'error_type': name if name in ERROR_TYPES else 'OtherError', 'sqlstate': state}

class Observation:
    """All checkpoints use caller's exclusive durable writer, never best-effort IO.

    Event callbacks only collect in memory. Phase boundaries synchronously persist
    the counters. Pool logger records never call getMessage or format traceback.
    An IO error while a primary is propagating is recorded separately in memory,
    and final persistence remains mandatory. It cannot authorize a clean result.
    """
    def __init__(self, journal, application):
        require(type(application) is str and re.fullmatch(r'worlex_reconcile_[a-f0-9]{12}', application),
                'OBSERVATION_APPLICATION_INVALID')
        self.journal = journal; self.application = application
        self.started = utc_now(); self.clock = time.monotonic()
        self.phase = 'outside'; self.pid = None; self.events = []
        self.primary = None; self.cleanup = []; self.failed_io = False
        self.attempted = 0; self.succeeded = 0; self.batches = 0; self.sequences = 0
        self.installed = False; self.finished = False

    def capture(self, error, *, cleanup=False, operation=None):
        value = {'phase': self.phase, **safe_error(error)}
        if cleanup:
            require(operation in ('rollback', 'close', 'dispose', 'pool_termination', 'journal', 'observer_remove'),
                    'OBSERVATION_CLEANUP_INVALID')
            value['operation'] = operation
            require(len(self.cleanup) < 32, 'OBSERVATION_CLEANUP_LIMIT')
            self.cleanup.append(value)
        elif self.primary is None:
            self.primary = value

    def checkpoint(self, event_name):
        require(not self.failed_io, 'OBSERVATION_JOURNAL_FAILED_NO_RETRY')
        require(not self.finished and event_name in ('start', 'end', 'failed', 'bound', 'complete'),
                'OBSERVATION_EVENT_INVALID')
        require(len(self.events) < MAX_EVENTS, 'OBSERVATION_EVENT_LIMIT')
        value = {'version': 1, 'index': len(self.events)+1, 'event': event_name,
            'phase': self.phase, 'utc': utc_now(), 'elapsed_ms': int((time.monotonic()-self.clock)*1000),
            'backend_pid': self.pid, 'queries_attempted': self.attempted,
            'queries_succeeded': self.succeeded, 'sequence_batches': self.batches,
            'sequences_read': self.sequences, 'primary': self.primary,
            'cleanup': list(self.cleanup)}
        try:
            self.journal('observation-%04d' % value['index'], value)
        except BaseException:
            self.failed_io = True
            raise
        self.events.append(value)

    @contextlib.contextmanager
    def scope(self, phase, *, cleanup=False):
        require(phase in PHASES and phase != 'outside', 'OBSERVATION_PHASE_INVALID')
        if cleanup: require(phase in ('rollback', 'close', 'dispose'), 'OBSERVATION_CLEANUP_INVALID')
        previous = self.phase; self.phase = phase
        try:
            start_error = None
            try: self.checkpoint('start')
            except BaseException as error:
                if not cleanup:
                    self.capture(error)
                    raise
                self.capture(error, cleanup=True, operation='journal')
                start_error = error
            try:
                yield
            except BaseException as error:
                self.capture(error, cleanup=cleanup, operation=phase if cleanup else None)
                try: self.checkpoint('failed')
                except BaseException as io_error:
                    self.capture(io_error, cleanup=True, operation='journal')
                raise
            else:
                if start_error is not None: raise start_error
                self.checkpoint('end')
        finally:
            self.phase = previous

    def bind_connection(self, connection):
        raw = connection.connection.driver_connection
        require(type(raw).__module__ == 'pg8000.legacy', 'OBSERVATION_CLIENT_INVALID')
        key = getattr(raw, '_backend_key_data', None)
        require(type(key) is bytes and len(key) == 8, 'OBSERVATION_PID_UNAVAILABLE')
        pid = struct.unpack('!i', key[:4])[0]
        require(1 <= pid <= 2147483647, 'OBSERVATION_PID_INVALID')
        require(self.pid in (None, pid), 'OBSERVATION_PID_CHANGED')
        self.pid = pid
        self.checkpoint('bound')

    @contextlib.contextmanager
    def install(self, engine):
        from sqlalchemy import event
        require(not self.installed and not self.finished, 'OBSERVATION_ALREADY_INSTALLED')
        require(type(engine.pool).__name__ == 'NullPool' and engine.echo is False
                and engine.pool.logging_name is None,
                'OBSERVATION_NULLPOOL_NO_ECHO_REQUIRED')
        self.installed = True
        owner = self
        def before(*args): self.attempted += 1
        def after(*args): self.succeeded += 1
        def error(context):
            cleanup = self.phase in ('rollback', 'close', 'dispose')
            self.capture(context.original_exception, cleanup=cleanup,
                         operation=self.phase if cleanup else None)
        class PoolHandler(logging.Handler):
            def emit(self, record):
                # A fixed category for every pool error. Unknown/missing exc_info
                # also stops; record.msg and record.args are never evaluated.
                original = record.exc_info[1] if type(record.exc_info) is tuple and len(record.exc_info)==3 and isinstance(record.exc_info[1], BaseException) else ReadOnlyStop()
                owner.capture(original, cleanup=True, operation='pool_termination')
        logger = logging.getLogger('sqlalchemy.pool.impl.NullPool')
        old_handlers, old_level, old_propagate, old_disabled = logger.handlers[:], logger.level, logger.propagate, logger.disabled
        handler = PoolHandler(logging.ERROR)
        logger.handlers = [handler]; logger.setLevel(logging.ERROR); logger.propagate = False; logger.disabled = False
        registered = []
        try:
            for name, callback in (('before_cursor_execute', before), ('after_cursor_execute', after), ('handle_error', error)):
                event.listen(engine, name, callback); registered.append((name, callback))
            yield self
        finally:
            try:
                for name, callback in reversed(registered):
                    try: event.remove(engine, name, callback)
                    except BaseException as error: self.capture(error, cleanup=True, operation='observer_remove')
            finally:
                logger.handlers = old_handlers; logger.setLevel(old_level)
                logger.propagate = old_propagate; logger.disabled = old_disabled
                self.installed = False

    def require_clean(self):
        require(self.primary is None and not self.cleanup and not self.failed_io,
                'READONLY_OBSERVATION_UNRESOLVED')

    def finish(self):
        require(not self.installed and not self.finished, 'OBSERVATION_FINISH_ORDER_INVALID')
        self.phase = 'complete'
        self.checkpoint('complete')
        value = {'version': 1, 'contract': CONTRACT, 'application': self.application,
            'started_utc': self.started, 'ended_utc': utc_now(), 'backend_pid': self.pid,
            'events': list(self.events), 'primary': self.primary, 'cleanup': list(self.cleanup),
            'journal_failed': self.failed_io, 'clean': self.primary is None and not self.cleanup and not self.failed_io}
        try: self.journal('readonly-observation', value)
        except BaseException:
            self.failed_io = True
            raise
        self.finished = True
        return value


def _same_transaction(connection, transaction):
    require(connection.in_transaction() and connection.get_transaction() is transaction and transaction.is_active,
            'READONLY_TRANSACTION_CHANGED')


def _original_function(core, source):
    original = core.sequence_states
    require(type(original) is types.FunctionType and type(getattr(original, '__wrapped__', None)) is types.FunctionType,
            'LEGACY_SEQUENCE_FUNCTION_CHANGED')
    underlying = original.__wrapped__
    expected = next(c for c in compile(source, core.__file__, 'exec', dont_inherit=True).co_consts
                    if isinstance(c, types.CodeType) and c.co_name == 'sequence_states')
    # Compile at source line numbers, preserve annotations' future semantics.
    # Code equality includes constants/names and bytecode, not just a function name.
    require(underlying.__code__ == expected and underlying.__globals__ is core.__dict__
            and original.__globals__ is core.observation.__dict__
            and original.__code__ == core.observation.phase('sequence_states')(underlying).__code__
            and tuple(cell.cell_contents for cell in original.__closure__) == (underlying, 'sequence_states'),
            'LEGACY_SEQUENCE_FUNCTION_CHANGED')
    return original


@contextlib.contextmanager
def reader(core, connection, *, expected_core_sha256, expected_module_sha256, observer):
    """Activate only within one verified read-only transaction, always restore.

    The legacy file and private plan stay unmodified. The successor independently
    binds this module hash. Runtime substitution is explicit, scoped and tested.
    """
    global _ACTIVE
    require(not _ACTIVE, 'READONLY_READER_ALREADY_ACTIVE')
    require(expected_core_sha256 == LEGACY_CORE_SHA256, 'LEGACY_CORE_PIN_INVALID')
    path = Path(core.__file__)
    require(path.is_file() and not path.is_symlink(), 'LEGACY_CORE_FILE_INVALID')
    source = path.read_bytes()
    require(hashlib.sha256(source).hexdigest() == expected_core_sha256, 'LEGACY_CORE_SOURCE_CHANGED')
    require(type(expected_module_sha256) is str and re.fullmatch('[0-9a-f]{64}', expected_module_sha256)
            and hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == expected_module_sha256,
            'READONLY_MODULE_SOURCE_CHANGED')
    original = _original_function(core, source)
    transaction = connection.get_transaction()
    _same_transaction(connection, transaction)
    with observer.scope('reader_mode'):
        modes = tuple(connection.exec_driver_sql("SELECT current_setting('transaction_read_only'),current_setting('transaction_isolation'),current_setting('application_name')").one())
        require(modes == ('on', 'repeatable read', observer.application), 'READONLY_TRANSACTION_MODE_REQUIRED')
    _same_transaction(connection, transaction)
    def replacement(actual_connection, tables, lock=False):
        require(lock is False, 'READONLY_SEQUENCE_LOCK_FORBIDDEN')
        require(actual_connection is connection, 'READONLY_CONNECTION_CHANGED')
        return sequence_states(connection, tables, transaction, observer, core.q)
    _ACTIVE = True; core.sequence_states = replacement
    try:
        yield
        require(core.sequence_states is replacement, 'READONLY_READER_CHANGED')
        _same_transaction(connection, transaction)
    finally:
        core.sequence_states = original
        _ACTIVE = False


def sequence_states(connection, tables, transaction, observer, quote):
    """Same legacy state dictionary, stricter unknown-result rejection, no ALTER.

    Catalog/ownership statements are the legacy SQL. Only value reads use bounded
    UNION ALL. Every returned ordinal/type is checked before any state is returned.
    No results are reused across calls, connections or transactions.
    """
    from sqlalchemy import Integer, text
    _same_transaction(connection, transaction)
    requested = [(name, col) for name, table in sorted(tables.items()) for col in table.primary_key]
    require(len(requested) <= MAX_REQUESTED, 'SEQUENCE_REQUEST_LIMIT')
    if not requested: return {}
    params = {}; values = []
    for i, (name, col) in enumerate(requested):
        values.append('(CAST(:i%d AS integer),CAST(:t%d AS text),CAST(:c%d AS text))' % (i,i,i))
        params.update({'i%d'%i:i, 't%d'%i:'public.'+quote(name), 'c%d'%i:col.name})
    with observer.scope('sequence_metadata'):
        metadata = connection.execute(text("WITH requested(ord,table_name,column_name) AS (VALUES "+','.join(values)+"), resolved AS (SELECT ord,pg_get_serial_sequence(table_name,column_name) AS seq FROM requested) SELECT r.ord,r.seq,n.nspname,c.relname,c.oid,c.relowner,c.relacl::text,c.relpersistence,c.reloptions,c.reltablespace,c.relfilenode,s.seqtypid,s.seqstart,s.seqincrement,s.seqmin,s.seqmax,s.seqcache,s.seqcycle FROM resolved r LEFT JOIN pg_class c ON c.oid=CAST(r.seq AS regclass) LEFT JOIN pg_sequence s ON s.seqrelid=c.oid LEFT JOIN pg_namespace n ON n.oid=c.relnamespace ORDER BY r.ord"), params).all()
        _same_transaction(connection, transaction)
        require(type(metadata) in (list,tuple) and len(metadata)==len(requested)
                and all(hasattr(row,'__len__') and len(row)==18 and type(row[0]) is int for row in metadata)
                and [row[0] for row in metadata]==list(range(len(requested))), 'SEQUENCE_METADATA_SHAPE_CHANGED')
    meta_by = {}; ownership_by = {}; owned = []; params = {}; sequence_ids = set()
    for row in metadata:
        i, seq, *meta = row
        name, col = requested[i]
        if seq is None:
            require(all(v is None for v in meta), 'SEQUENCE_METADATA_UNKNOWN')
            require(not (col.name=='id' and isinstance(col.type,Integer)), 'OWNED_ID_SEQUENCE_MISSING')
            continue
        require(type(seq) is str and seq and meta[0]=='public' and type(meta[1]) is str, 'SEQUENCE_METADATA_UNKNOWN')
        quote(meta[0]); quote(meta[1])
        require(seq == 'public.'+meta[1], 'SEQUENCE_METADATA_UNKNOWN')
        require(all(type(meta[k]) is int for k in (2,3,7,8,9,10,11,12,13,14))
                and (meta[4] is None or type(meta[4]) is str)
                and type(meta[5]) is str and meta[5] in ('p','u','t')
                and (meta[6] is None or type(meta[6]) is list and all(type(v) is str for v in meta[6]))
                and type(meta[15]) is bool and meta[2]>0 and meta[3]>0
                and meta[9] in (20,21,23) and meta[10]>=1 and meta[13]>=meta[10]
                and meta[7]>=0 and meta[8]>=0, 'SEQUENCE_METADATA_UNKNOWN')
        require(meta[2] not in sequence_ids, 'SEQUENCE_METADATA_DUPLICATE')
        sequence_ids.add(meta[2])
        meta_by[i] = (seq, meta); ownership_by[i] = []
        owned.append('(CAST(:i%d AS integer),CAST(:s%d AS regclass))' % (i,i))
        params.update({'i%d'%i:i, 's%d'%i:seq})
    if owned:
        _same_transaction(connection, transaction)
        with observer.scope('sequence_ownership'):
            rows = connection.execute(text("WITH requested(ord,seq) AS (VALUES "+','.join(owned)+") SELECT r.ord,d.refobjid,d.refobjsubid,d.deptype FROM requested r JOIN pg_depend d ON d.objid=r.seq WHERE d.classid='pg_class'::regclass AND d.refclassid='pg_class'::regclass AND d.deptype IN ('a','i') ORDER BY r.ord,d.refobjid,d.refobjsubid,d.deptype"), params).all()
            require(type(rows) in (list,tuple), 'SEQUENCE_OWNERSHIP_SHAPE_CHANGED')
            for row in rows:
                require(hasattr(row,'__len__') and len(row)==4 and all(type(row[k]) is int for k in (0,1,2))
                        and row[0] in ownership_by and row[1]>0 and row[2]>0 and type(row[3]) is str and row[3] in ('a','i'),
                        'SEQUENCE_OWNERSHIP_SHAPE_CHANGED')
                ownership_by[row[0]].append(list(row[1:]))
            _same_transaction(connection, transaction)
    pending = []
    for i, (seq, meta) in meta_by.items():
        require(meta[11]==1 and meta[12]==1 and meta[14]==1 and meta[15] is False
                and len(ownership_by[i])==1, 'UNSUPPORTED_SEQUENCE')
        qualified = quote(meta[0])+'.'+quote(meta[1])
        pending.append((i, qualified))
    states = {}; values_by = {}
    for offset in range(0, len(pending), MAX_BRANCHES):
        batch = pending[offset:offset+MAX_BRANCHES]
        statement = ' UNION ALL '.join('SELECT '+str(i)+'::integer AS sequence_ordinal,last_value,is_called,log_cnt FROM '+qualified for i,qualified in batch)
        require(len(statement.encode('utf-8')) <= MAX_SQL_BYTES, 'SEQUENCE_SQL_BUDGET_EXCEEDED')
        _same_transaction(connection, transaction)
        with observer.scope('sequence_values'):
            rows = connection.exec_driver_sql(statement).all()
            _same_transaction(connection, transaction)
            expected = {i for i,_ in batch}; result = {}
            require(type(rows) in (list,tuple) and len(rows)==len(batch), 'SEQUENCE_VALUES_SHAPE_CHANGED')
            for row in rows:
                require(hasattr(row,'__len__') and len(row)==4 and type(row[0]) is int
                        and row[0] in expected and row[0] not in result and type(row[1]) is int
                        and type(row[2]) is bool and type(row[3]) is int and row[3]>=0,
                        'SEQUENCE_VALUES_SHAPE_CHANGED')
                require(1<=row[1]<=meta_by[row[0]][1][13], 'SEQUENCE_VALUE_RANGE_CHANGED')
                result[row[0]] = tuple(row[1:])
            require(set(result)==expected, 'SEQUENCE_VALUES_SHAPE_CHANGED')
            values_by.update(result); observer.batches += 1; observer.sequences += len(result)
    require(set(values_by)==set(meta_by), 'SEQUENCE_VALUES_INCOMPLETE')
    _same_transaction(connection, transaction)
    for i, (name, col) in enumerate(requested):
        if i not in meta_by: continue
        _, meta = meta_by[i]
        schema,sn,oid,owner,acl,persistence,options,tablespace,filenode,type_oid,start,inc,mn,mx,cache,cycle = meta
        last,called,log_cnt = values_by[i]
        states[(name,col.name)] = {'qualified':quote(schema)+'.'+quote(sn), 'last':last,
            'called':called,'next':last+1 if called else last,'max':mx,
            'catalog':{'schema':schema,'name':sn,'oid':oid,'owner':owner,'acl':acl,
                'type_oid':type_oid,'start':start,'increment':inc,'min':mn,'max':mx,
                'cache':cache,'cycle':cycle,'ownership':ownership_by[i]}}
        if name=='push_subscription':
            states[(name,col.name)]['log_cnt'] = log_cnt
            states[(name,col.name)]['catalog'].update(persistence=persistence,options=options,tablespace=tablespace,filenode=filenode)
    return states


def _strict_json(raw):
    require(type(raw) is bytes and 0 < len(raw) <= 262144, 'OBSERVATION_FILE_INVALID')
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, 'OBSERVATION_DUPLICATE_KEY')
            value[key] = item
        return value
    def bad_constant(unused): raise ReadOnlyStop('OBSERVATION_NONFINITE')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_constant)


def validate_observation_bundle(files, *, expected_application):
    """Validate complete *clean* companion proof before existing adapter eligibility.

    The caller binds exact core/module/helper/plan/release hashes in its separate
    readonly-binding.json. This function accepts only observation files, no base
    adapter proof files. Callback-added `utc` on the final summary is permitted
    only as the one required journal timestamp, never arbitrary extra fields.
    """
    require(type(files) is dict and 'readonly-observation.json' in files,
            'OBSERVATION_BUNDLE_INVALID')
    final = _strict_json(files['readonly-observation.json'])
    required = {'version','contract','application','started_utc','ended_utc','backend_pid',
                'events','primary','cleanup','journal_failed','clean'}
    require(type(final) is dict and set(final) in (required, required|{'utc'})
            and type(final['version']) is int and final['version']==1 and final['contract']==CONTRACT
            and final['application']==expected_application
            and type(expected_application) is str and re.fullmatch(r'worlex_reconcile_[a-f0-9]{12}', expected_application)
            and final['primary'] is None and final['cleanup']==[] and final['journal_failed'] is False
            and final['clean'] is True and type(final['backend_pid']) is int
            and 1<=final['backend_pid']<=2147483647,
            'OBSERVATION_TERMINAL_NOT_CLEAN')
    def timestamp(value):
        require(type(value) is str and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z', value),
                'OBSERVATION_TIMESTAMP_INVALID')
        return datetime.datetime.fromisoformat(value.replace('Z','+00:00'))
    start, end = timestamp(final['started_utc']), timestamp(final['ended_utc'])
    require(start<=end, 'OBSERVATION_TIME_REVERSED')
    if 'utc' in final: require(timestamp(final['utc'])>=end, 'OBSERVATION_TIME_REVERSED')
    events = final['events']
    require(type(events) is list and 1<=len(events)<=MAX_EVENTS, 'OBSERVATION_EVENTS_INVALID')
    expected_files = {'readonly-observation.json'}|{'observation-%04d.json'%i for i in range(1,len(events)+1)}
    require(set(files)==expected_files, 'OBSERVATION_FILE_SET_INVALID')
    keys = {'version','index','event','phase','utc','elapsed_ms','backend_pid','queries_attempted',
            'queries_succeeded','sequence_batches','sequences_read','primary','cleanup'}
    previous_time = start; counters = [0]*5; pid = None; stack = []; bound = 0
    completed_phases = []; top_phases = []; children = {}; saw_values = False
    for i, item in enumerate(events, 1):
        require(type(item) is dict and set(item)==keys and type(item['version']) is int and item['version']==1
                and type(item['index']) is int and item['index']==i
                and item == _strict_json(files['observation-%04d.json'%i])
                and item['phase'] in PHASES and item['event'] in ('start','end','bound','complete')
                and item['primary'] is None and item['cleanup']==[], 'OBSERVATION_EVENT_INVALID')
        current_time = timestamp(item['utc'])
        require(previous_time<=current_time<=end, 'OBSERVATION_TIME_REVERSED')
        previous_time = current_time
        values = [item[k] for k in ('elapsed_ms','queries_attempted','queries_succeeded','sequence_batches','sequences_read')]
        require(all(type(v) is int and 0<=v<=10000000 and v>=p for v,p in zip(values,counters))
                and values[2]<=values[1] and values[4]<=values[3]*MAX_BRANCHES,
                'OBSERVATION_COUNTER_INVALID')
        counters = values
        if item['backend_pid'] is not None:
            require(type(item['backend_pid']) is int and item['backend_pid']==final['backend_pid'], 'OBSERVATION_PID_CHANGED')
            pid = item['backend_pid']
        else: require(pid is None, 'OBSERVATION_PID_CHANGED')
        kind, phase = item['event'], item['phase']
        if kind=='start':
            require(phase not in ('complete','outside'), 'OBSERVATION_PHASE_INVALID')
            if not stack: top_phases.append(phase)
            else:
                children.setdefault(stack[-1], []).append(phase)
                require((stack[-1]=='data' and phase in ('reader_mode','plan','verify_restore'))
                        or (stack[-1] in ('plan','verify_restore') and phase in ('sequence_metadata','sequence_ownership','sequence_values')),
                        'OBSERVATION_PHASE_ORDER_INVALID')
            stack.append(phase)
        elif kind=='end':
            require(stack and stack.pop()==phase, 'OBSERVATION_PHASE_ORDER_INVALID')
            completed_phases.append(phase)
            if phase=='sequence_values': saw_values = True
        elif kind=='bound':
            bound += 1
            require(bound==1 and pid is not None and phase=='connect' and stack==['connect'], 'OBSERVATION_PID_BINDING_INVALID')
        else:
            require(i==len(events) and phase=='complete' and not stack, 'OBSERVATION_COMPLETION_INVALID')
    require(events[-1]['event']=='complete' and bound==1 and pid==final['backend_pid']
            and saw_values and counters[3]>0 and counters[4]>0 and counters[1]==counters[2],
            'OBSERVATION_COMPLETION_INVALID')
    branch = 'plan' if 'plan' in completed_phases else 'verify_restore'
    require(children.get('data')==['reader_mode',branch]
            and children.get(branch,[])[:2]==['sequence_metadata','sequence_ownership']
            and children.get(branch,[])[2:] and set(children[branch][2:])=={'sequence_values'},
            'OBSERVATION_PHASE_ORDER_INVALID')
    require(top_phases==['connect','session_before','rollback','data','rollback','session_after','rollback','close','dispose'],
            'OBSERVATION_PHASE_ORDER_INVALID')
    require(all(completed_phases.count(p)==1 for p in ('connect','session_before','data','session_after','close','dispose','reader_mode','sequence_metadata','sequence_ownership'))
            and completed_phases.count('rollback')==3
            and completed_phases.count('plan')+completed_phases.count('verify_restore')==1,
            'OBSERVATION_REQUIRED_PHASE_MISSING')
    return final
