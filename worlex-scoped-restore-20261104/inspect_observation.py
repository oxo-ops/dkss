"""Bounded, local-only observations. Never reads SQL, parameters or error text.

Instrumentation wraps existing operations once, forwarding their exact arguments
and return values. No event issues SQL. The canonical restore plan is untouched.
"""
import contextlib
import datetime
import functools
import json
import os
from pathlib import Path
import re
import struct
import sys
import time
import uuid

TYPES = frozenset(('OtherError Stop Exception RuntimeError ValueError TypeError '
    'OSError TimeoutError ConnectionError ConnectionResetError BrokenPipeError '
    'PermissionError FileNotFoundError SSLError SSLCertVerificationError '
    'InterfaceError DatabaseError OperationalError IntegrityError InternalError '
    'ProgrammingError DataError NotSupportedError DBAPIError StatementError '
    'InvalidRequestError PendingRollbackError ResourceClosedError KeyboardInterrupt '
    'SystemExit').split())
PHASES = frozenset(('startup source_render dbapi_connect tls_handshake '
    'sqlalchemy_initialize tls_verify transaction_setup validate_schema typed_payload '
    'prepare_deferred_push check_empty_and_itc snapshot sequence_states identity '
    'plan transaction_end connection_close engine_dispose output_write '
    'collision_flush cleanup rollback close commit cursor_close').split())
OPERATIONS = frozenset(('phase cursor_execute cursor_executemany cursor_fetchone '
    'cursor_fetchmany cursor_fetchall cursor_iterate cleanup').split())
DIAGNOSTIC_OPERATIONS = {
    'create_directory': 'snapshot_directory',
    'open_snapshot': 'pending_snapshot',
    'write_snapshot': 'pending_snapshot',
    'fsync_snapshot': 'pending_snapshot',
    'close_snapshot': 'pending_snapshot',
    'replace_snapshot': 'current_snapshot',
}
ACTIVE = None
LAST = None


def _attribute(error, name):
    try:return getattr(error, name, None)
    except BaseException:return None


def safe_error(error):
    """Bounded breadth-first graph; only explicitly allowed attributes are read."""
    nodes, pending, seen = [], [(error, None, None)], set()
    while pending and len(nodes) < 8:
        current, parent, link = pending.pop(0)
        if not isinstance(current, BaseException) or id(current) in seen:
            continue
        seen.add(id(current))
        name = type(current).__name__
        node = {'type': name if name in TYPES else 'OtherError', 'parent': parent, 'link': link}
        # pg8000 server fields are a dictionary in args[0]. No other fields survive.
        args = BaseException.args.__get__(current, type(current))
        code = args[0].get('C') if type(args) is tuple and args and type(args[0]) is dict else None
        if type(code) is str and re.fullmatch('[A-Z0-9]{5}', code):
            node['sqlstate'] = code
        for field in ('errno', 'winerror'):
            value = _attribute(current, field)
            if type(value) is int and -2147483648 <= value <= 2147483647:
                node[field] = value
        index = len(nodes)
        nodes.append(node)
        for edge in ('orig', '__cause__', '__context__'):
            value = _attribute(current, edge)
            if isinstance(value, BaseException):
                pending.append((value, index, edge))
    return nodes


def _integer(value, low=0, high=2**63-1):
    return type(value) is int and low <= value <= high


def validate_observation(value):
    """Strict producer/launcher contract. Invalid input fails closed, never copied."""
    def require(ok):
        if not ok:
            raise ValueError('OBSERVATION_SCHEMA_INVALID')
    require(type(value) is dict and set(value) == {'version', 'nonce', 'application_name',
        'backend_pid', 'tls_completed', 'startup_completed', 'server_clock',
        'effective_timeouts', 'events', 'primary', 'cleanup', 'dropped_events',
        'inspection_completed', 'diagnostic_persistence'})
    require(type(value['version']) is int and value['version'] == 2)
    require(type(value['nonce']) is str and re.fullmatch('[a-f0-9]{32}', value['nonce']) is not None)
    require(value['application_name'] == 'worlex_inspect_' + value['nonce'])
    require(value['backend_pid'] is None or _integer(value['backend_pid'], 1, 2147483647))
    require(all(value[k] is None or value[k] is True for k in ('tls_completed','startup_completed')))
    require(value['server_clock'] is None and value['effective_timeouts'] is None)
    require(_integer(value['dropped_events']))
    def event(e):
        require(type(e) is dict and set(e) == {'phase','operation','ordinal','state','utc','elapsed_ms','duration_ms'})
        require(type(e['phase']) is str and e['phase'] in PHASES)
        require(type(e['operation']) is str and e['operation'] in OPERATIONS)
        require(_integer(e['ordinal']) and _integer(e['elapsed_ms']) and _integer(e['duration_ms']))
        require(e['state'] in ('start','ok','error') and type(e['state']) is str)
        require(type(e['utc']) is str and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z', e['utc']) is not None)
    def failure(f):
        require(type(f) is dict and set(f) == {'event','errors'})
        event(f['event'])
        require(type(f['errors']) is list and 1 <= len(f['errors']) <= 8)
        for i, n in enumerate(f['errors']):
            require(type(n) is dict and {'type','parent','link'} <= set(n) <= {'type','parent','link','sqlstate','errno','winerror'})
            require(type(n['type']) is str and n['type'] in TYPES)
            require((i == 0 and n['parent'] is None and n['link'] is None) or
                    (i > 0 and _integer(n['parent'], 0, i-1) and n['link'] in ('orig','__cause__','__context__')))
            if 'sqlstate' in n:
                require(type(n['sqlstate']) is str and re.fullmatch('[A-Z0-9]{5}', n['sqlstate']) is not None)
            for k in ('errno','winerror'):
                if k in n: require(_integer(n[k], -2147483648, 2147483647))
    require(type(value['events']) is list and len(value['events']) <= 64)
    for e in value['events']: event(e)
    if value['primary'] is not None: failure(value['primary'])
    require(type(value['cleanup']) is list and len(value['cleanup']) <= 8)
    for f in value['cleanup']: failure(f)
    require(type(value['inspection_completed']) is bool)
    persistence = value['diagnostic_persistence']
    require(type(persistence) is dict and set(persistence) == {'complete', 'warning'})
    require(type(persistence['complete']) is bool)
    warning = persistence['warning']
    require(persistence['complete'] is (warning is None))
    if warning is not None:
        require(type(warning) is dict and {'code', 'operation', 'target', 'event'} <= set(warning)
                <= {'code', 'operation', 'target', 'event', 'errno', 'winerror'})
        require(type(warning['code']) is str and warning['code'] in
                ('DIAGNOSTIC_IO_DISABLED', 'DIAGNOSTIC_SHORT_WRITE'))
        require(type(warning['operation']) is str and warning['operation'] in DIAGNOSTIC_OPERATIONS)
        require(warning['target'] == DIAGNOSTIC_OPERATIONS[warning['operation']])
        require(warning['code'] != 'DIAGNOSTIC_SHORT_WRITE' or
                warning['operation'] == 'write_snapshot' and set(warning) == {'code','operation','target','event'})
        event(warning['event'])
        for k in ('errno', 'winerror'):
            if k in warning: require(_integer(warning[k], -2147483648, 2147483647))
    # Serialize only after exact shape and primitive type validation.
    return json.loads(json.dumps(value, separators=(',', ':')))


class Observation:
    def __init__(self, directory):
        self.started = time.monotonic_ns()
        self.phase = 'startup'
        self.ordinal = 0
        self.failures = []
        nonce = uuid.uuid4().hex
        self.value = dict(version=2, nonce=nonce, application_name='worlex_inspect_'+nonce,
            backend_pid=None, tls_completed=None, startup_completed=None,
            server_clock=None, effective_timeouts=None, events=[], primary=None,
            cleanup=[], dropped_events=0, inspection_completed=False,
            diagnostic_persistence={'complete': True, 'warning': None})
        # A nonce directory is always new; never reopen an earlier attempt.
        self.directory = Path(directory) / ('inspect-observation-' + nonce)
        try:
            self.directory.mkdir(mode=0o700)
        except FileExistsError:
            # A duplicate nonce or occupied path is an integrity failure, not
            # optional diagnostic unavailability. Never reuse its contents.
            raise
        except OSError as error:
            self._diagnostic_failure('create_directory', error)
        self.persist()

    def _diagnostic_failure(self, operation, error=None):
        if not self.value['diagnostic_persistence']['complete']:
            return
        # No arbitrary exception graph, text, filename, URL or locals here.
        # A startup failure has no event yet; its context is a safe start event.
        context = (dict(self.value['events'][-1]) if self.value['events'] else
                   self.event('startup', 'phase', 0, 'start', self.started))
        warning = dict(code='DIAGNOSTIC_IO_DISABLED' if error is not None else 'DIAGNOSTIC_SHORT_WRITE',
                       operation=operation, target=DIAGNOSTIC_OPERATIONS[operation], event=context)
        if error is not None:
            for field in ('errno', 'winerror'):
                value = _attribute(error, field)
                if _integer(value, -2147483648, 2147483647): warning[field] = value
        self.value['diagnostic_persistence'] = {'complete': False, 'warning': warning}

    def _io(self, operation, function, *args):
        # Called only for observer-owned filesystem operations. Schema checks,
        # serialization and all operational callbacks stay outside this catch.
        try:
            return True, function(*args)
        except OSError as error:
            self._diagnostic_failure(operation, error)
            return False, None

    def persist(self):
        # Validate even after degradation; programming/schema failures still stop.
        data = json.dumps(validate_observation(self.value), separators=(',', ':')).encode()
        if not self.value['diagnostic_persistence']['complete']:
            return
        temporary = self.directory / 'next.json'
        ok, fd = self._io('open_snapshot', os.open, temporary,
                          os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        if not ok: return
        # Unbuffered I/O prevents a close after failed write/fsync from flushing
        # again. Close the already-owned descriptor once; never reopen or delete.
        try:
            ok, count = self._io('write_snapshot', os.write, fd, data)
            if not ok: return
            if count != len(data):
                self._diagnostic_failure('write_snapshot')
                return
            ok, _ = self._io('fsync_snapshot', os.fsync, fd)
            if not ok: return
        finally:
            closed, _ = self._io('close_snapshot', os.close, fd)
        if not closed or not self.value['diagnostic_persistence']['complete']: return
        self._io('replace_snapshot', os.replace, temporary, self.directory / 'observation.json')

    def event(self, phase, operation, ordinal, state, start):
        now = time.monotonic_ns()
        item = dict(phase=phase, operation=operation, ordinal=ordinal, state=state,
            utc=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z'),
            elapsed_ms=(now-self.started)//1000000, duration_ms=(now-start)//1000000)
        self.value['events'].append(item)
        if len(self.value['events']) > 64:
            self.value['events'].pop(0); self.value['dropped_events'] += 1
        return item

    @contextlib.contextmanager
    def scope(self, phase=None, operation='phase', *, cleanup=False, ordinal=None, preserve_error=False):
        previous = self.phase
        preserve_error = preserve_error or (cleanup and sys.exc_info()[1] is not None)
        phase = phase or previous
        self.phase = phase
        start = time.monotonic_ns()
        ordinal = (0 if cleanup else self.ordinal) if ordinal is None else ordinal
        self.event(phase, operation, ordinal, 'start', start)
        persistence_error = None
        try:
            self.persist()
        except Exception as error:
            if not cleanup:
                self.phase = previous
                raise
            # Failed logging must NEVER skip rollback, close or dispose.
            persistence_error = error
        try:
            yield
        except BaseException as error:
            if isinstance(error, StopIteration) and operation == 'cursor_iterate':
                self.event(phase, operation, ordinal, 'ok', start)
                self.persist()
                raise
            e = self.event(phase, operation, ordinal, 'error', start)
            self.capture(error, e, cleanup=cleanup, persist=False)
            try: self.persist()
            except Exception: pass  # Preserve the operation's original exception.
            raise
        else:
            self.event(phase, operation, ordinal, 'ok', start)
            if persistence_error is not None and not preserve_error: raise persistence_error
            try:self.persist()
            except Exception:
                if not preserve_error:raise
        finally:
            self.phase = previous

    def capture(self, error, event=None, *, cleanup=False, persist=True):
        e = event or self.event(self.phase, 'phase', self.ordinal, 'error', time.monotonic_ns())
        if not any(error is prior for prior in self.failures):
            if len(self.failures) < 32:self.failures.append(error)
            record = {'event':e, 'errors':safe_error(error)}
            if cleanup:
                if len(self.value['cleanup']) < 8: self.value['cleanup'].append(record)
            elif self.value['primary'] is None:
                self.value['primary'] = record
        if persist:
            # Capture is called while an original failure is already in flight.
            try:self.persist()
            except Exception:pass

    def call(self, phase, function, *args, **kwargs):
        with self.scope(phase): return function(*args, **kwargs)

    def connect(self, engine):
        connection = None
        try:
            with self.scope('sqlalchemy_initialize'):
                connection = engine.connect()
                return connection
        except BaseException:
            # An observation write can fail after successful engine.connect().
            # SQLAlchemy cannot own a connection that was not returned to caller.
            if connection is not None:
                try:
                    with self.scope('connection_close', cleanup=True, preserve_error=True):
                        connection.close()
                except BaseException: pass
            raise

    def wrap_context(self, context, exit_phase):
        observation = self
        class Context:
            def __enter__(self):
                with observation.scope(): return context.__enter__()
            def __exit__(self, *args):
                with observation.scope(exit_phase, cleanup=True, preserve_error=args[1] is not None):
                    return context.__exit__(*args)
        return Context()

    def install(self, engine, connect_args):
        """Instrument engine-local methods; leave SSL and driver classes unchanged."""
        connect = engine.dialect.connect
        def observed_connect(*args, **kwargs):
            raw = None
            try:
                with self.scope('dbapi_connect'):
                    raw = connect(*args, **kwargs)
                    self.value['startup_completed'] = True
                    # Pinned pg8000 1.31.6 stores exactly 8 network-order bytes.
                    if type(raw).__module__ == 'pg8000.legacy':
                        key = getattr(raw, '_backend_key_data', None)
                        if type(key) is bytes and len(key) == 8:
                            pid = struct.unpack('!i', key[:4])[0]
                            if 1 <= pid <= 2147483647: self.value['backend_pid'] = pid
                    self.wrap_raw(raw)
                    return raw
            except BaseException:
                if raw is not None:
                    try: raw.close()
                    except BaseException: pass
                raise
        engine.dialect.connect = observed_connect
        initialize = engine.dialect.initialize
        engine.dialect.initialize = lambda *a, **kw: self.call('sqlalchemy_initialize', initialize, *a, **kw)

    def wrap_raw(self, raw):
        cursor = raw.cursor
        def observed_cursor(*args, **kwargs):
            return Cursor(cursor(*args, **kwargs), self)
        raw.cursor = observed_cursor
        for name in ('rollback', 'commit', 'close'):
            original = getattr(raw, name)
            def wrapped(*args, _original=original, _name=name, **kwargs):
                with self.scope(_name, 'cleanup', cleanup=True, ordinal=0):
                    return _original(*args, **kwargs)
            setattr(raw, name, wrapped)


class Cursor:
    def __init__(self, raw, observation):
        object.__setattr__(self, '_raw', raw)
        object.__setattr__(self, '_observation', observation)
        object.__setattr__(self, '_ordinal', 0)
        object.__setattr__(self, '_category', observation.phase)
    def __getattr__(self, name): return getattr(self._raw, name)
    def __setattr__(self, name, value): setattr(self._raw, name, value)
    def _call(self, name, *args, **kwargs):
        obs = self._observation
        if name in ('execute','executemany'):
            obs.ordinal += 1
            object.__setattr__(self, '_ordinal', obs.ordinal)
            object.__setattr__(self, '_category', obs.phase)
        with obs.scope(self._category, 'cursor_'+name, ordinal=self._ordinal):
            result = getattr(self._raw, name)(*args, **kwargs)
            return self if result is self._raw else result
    def execute(self, *a, **kw): return self._call('execute', *a, **kw)
    def executemany(self, *a, **kw): return self._call('executemany', *a, **kw)
    def fetchone(self, *a, **kw): return self._call('fetchone', *a, **kw)
    def fetchmany(self, *a, **kw): return self._call('fetchmany', *a, **kw)
    def fetchall(self, *a, **kw): return self._call('fetchall', *a, **kw)
    def close(self):
        with self._observation.scope('cursor_close', 'cleanup', cleanup=True, ordinal=0):
            return self._raw.close()
    def __iter__(self):
        iter(self._raw)
        return self
    def __next__(self):
        with self._observation.scope(self._category, 'cursor_iterate', ordinal=self._ordinal):
            return next(self._raw)
    def __enter__(self):
        result = self._raw.__enter__()
        return self if result is self._raw else result
    def __exit__(self, *args):
        with self._observation.scope('cursor_close', 'cleanup', cleanup=True,
                                     ordinal=0, preserve_error=args[1] is not None):
            return self._raw.__exit__(*args)


def phase(name):
    """Fixed call-site phase; no SQL classification or parsing."""
    def decorate(function):
        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            if ACTIVE is None: return function(*args, **kwargs)
            with ACTIVE.scope(name): return function(*args, **kwargs)
        return wrapped
    return decorate


def output_fields():
    return {} if LAST is None else {'observation':validate_observation(LAST.value)}


def launcher_observation(parsed):
    """Reviewed adapter: merge into the launcher's existing typed safe output."""
    if type(parsed) is not dict or 'observation' not in parsed: return {}
    return {'observation':validate_observation(parsed['observation'])}
