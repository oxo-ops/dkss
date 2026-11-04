"""Exact generic observer components exported for synthetic CI only.
No production target, initializer entry point or live credentials are included.
"""
import re
import time
from datetime import datetime, timezone
LIMIT = 64

def utc():
    return datetime.now(timezone.utc).isoformat()


def safe_settings(settings):
    """Only fixed enums and bounded decimal settings; never DSN/host/user/path."""
    if not isinstance(settings, dict):
        return {'available': False}
    out = {'available': True}
    value = settings.get('sslmode')
    if value in ('disable', 'allow', 'prefer', 'require', 'verify-ca', 'verify-full'):
        out['sslmode'] = value
    for key in ('connect_timeout', 'keepalives', 'keepalives_idle', 'keepalives_interval',
                'keepalives_count', 'tcp_user_timeout'):
        value = settings.get(key)
        if isinstance(value, (str, int)) and re.fullmatch(r'[0-9]{1,10}', str(value)):
            out[key] = int(value)
    out['sslrootcert_configured'] = bool(settings.get('sslrootcert'))
    options = settings.get('options')
    if isinstance(options, str):
        accepted = {}
        pattern = r'(?:^|\s)-c\s+(search_path=public|statement_timeout=[0-9]{1,10}|lock_timeout=[0-9]{1,10}|idle_in_transaction_session_timeout=[0-9]{1,10})(?=\s|$)'
        for match in re.finditer(pattern, options):
            key, value = match.group(1).split('=', 1)
            accepted[key] = value if key == 'search_path' else int(value)
        out['requested_options'] = accepted
        out['unrecognized_options_suppressed'] = bool(re.sub(pattern, '', options).strip())
    return out


def driver_versions():
    import psycopg2
    from psycopg2 import extensions
    version = re.match(r'^[0-9]+\.[0-9]+\.[0-9]+(?= |$)', psycopg2.__version__)
    result = {'psycopg2_version': version.group(0) if version else 'UNAVAILABLE',
              'wait_callback_installed': extensions.get_wait_callback() is not None}
    for key, getter in (('libpq_compile_version', lambda: psycopg2.__libpq_version__),
                        ('libpq_runtime_version', extensions.libpq_version)):
        try: value = getter()
        except Exception: value = None
        result[key] = value if type(value) is int and 0 < value < 10000000 else None
    return result


class StatementTrace:
    def __init__(self, engine, metadata, allowed, result):
        from sqlalchemy import event
        self.result = result
        self.state = {'schema': 1, 'scope': 'SQLAlchemy cursor events only; dialect direct cursor calls may be absent',
                      'trace_started_at_utc': utc(), 'recent_operations': [], 'counters': {},
                      'failed_operation': None, 'trace_incomplete': False,
                      'raw_SQL_saved': False, 'parameters_saved': False,
                      'additional_SQL_executed': False, 'automatic_retry': False,
                      'server_settings_queried': False,
                      'requested_connection_settings': safe_settings(dict(engine.url.query)),
                      'driver_versions': driver_versions(),
                      'physical_connection_count': 0, 'cached_connection_observations': []}
        result['statement_trace'] = self.state
        self.objects = {}
        self.refs = []
        self.active = {}
        self.sequence = 0
        self.origin = time.monotonic_ns()
        # Names come only from the pinned offline manifest AND matching metadata identity.
        for table in metadata.tables.values():
            for index in table.indexes:
                pair = (index.name, table.name)
                if pair in allowed:
                    self.objects[id(index)] = ('CREATE_INDEX', pair[0], pair[1])
                    self.objects[id(table)] = ('CREATE_TABLE', None, pair[1])
                    self.refs.extend((index, table))
        self.listeners = []
        try:
            for name, callback in [('connect', self.connect), ('before_cursor_execute', self.before),
                                   ('after_cursor_execute', self.after), ('handle_error', self.error)]:
                wrapped = self.protect(callback)
                self.listeners.append((engine, name, wrapped))
                event.listen(engine, name, wrapped)
        except BaseException:
            self.close()
            raise

    def close(self):
        from sqlalchemy import event
        for engine, name, callback in reversed(self.listeners):
            try:
                if event.contains(engine, name, callback):
                    event.remove(engine, name, callback)
            except BaseException:
                self.state['trace_incomplete'] = True
        self.listeners.clear()
        self.active.clear()

    def protect(self, callback):
        def observer(*args, **kwargs):
            try:
                callback(*args, **kwargs)
            except Exception:
                self.state['trace_incomplete'] = True
            # handle_error must return None, never replace/suppress original exception.
            return None
        return observer

    def connect(self, dbapi_connection, connection_record):
        # Count physical connection observation before optional cached getters.
        self.state['physical_connection_count'] += 1
        # psycopg2 cached protocol metadata: no query, cursor, or connection attempt.
        try:
            pid = dbapi_connection.get_backend_pid()
        except Exception:
            pid = None
        connection_record.info['safe_trace_backend_pid'] = pid if type(pid) is int and pid > 0 else None
        try:
            settings = safe_settings(dbapi_connection.get_dsn_parameters())
        except Exception:
            settings = {'available': False}
        async_value = getattr(dbapi_connection, 'async_', None)
        async_mode = bool(async_value) if type(async_value) in (bool, int) and async_value in (0, 1) else None
        self.state['cached_connection_observations'].append({
            'observed_at_utc': utc(), 'backend_pid': connection_record.info['safe_trace_backend_pid'],
            'dbapi_async_mode': async_mode,
            'source': 'DBAPI cached connection parameters; not server SHOW/current_setting',
            'cached_connection_parameters': settings})
        del self.state['cached_connection_observations'][:-8]

    def classify(self, context):
        from sqlalchemy.schema import CreateIndex, CreateTable
        from sqlalchemy.sql import Select, Insert, Update, Delete
        compiled = getattr(context, 'compiled', None)
        statement = getattr(compiled, 'statement', None)
        if isinstance(statement, (CreateIndex, CreateTable)):
            element = statement.element
            known = self.objects.get(id(element))
            if known and any(element is ref for ref in self.refs):
                if isinstance(statement, CreateIndex) and (element.name, element.table.name) == (known[1], known[2]):
                    return known
                if isinstance(statement, CreateTable) and element.name == known[2]:
                    return known
            return ('UNRECOGNIZED_DDL_TARGET', None, None)
        for typ, label in ((Select, 'SELECT'), (Insert, 'INSERT'), (Update, 'UPDATE'), (Delete, 'DELETE')):
            if isinstance(statement, typ): return (label, None, None)
        return ('OTHER_COMPILED_SQL' if compiled is not None else 'DRIVER_SQL', None, None)

    def before(self, connection, cursor, statement, parameters, context, executemany):
        family, index, table = self.classify(context)
        self.sequence += 1
        now = time.monotonic_ns()
        item = {'sequence': self.sequence, 'family': family,
                'index': index, 'table': table,
                'started_at_utc': utc(), 'started_monotonic_ns': now,
                'since_trace_start_ns': now - self.origin,
                'backend_pid': connection.info.get('safe_trace_backend_pid'),
                'status': 'STARTED'}
        self.state['counters'][family] = self.state['counters'].get(family, 0) + 1
        self.state['recent_operations'].append(item)
        del self.state['recent_operations'][:-LIMIT]
        self.active[id(context)] = (context, item)
        if len(self.active) > LIMIT:
            self.active.pop(next(iter(self.active)))
            self.state['trace_incomplete'] = True

    def finish(self, context, status):
        pair = self.active.pop(id(context), None)
        if pair is None or pair[0] is not context:
            return None
        item = pair[1]
        now = time.monotonic_ns()
        item.update(status=status, finished_at_utc=utc(), finished_monotonic_ns=now,
                    duration_ns=max(0, now - item['started_monotonic_ns']),
                    duration_ms=max(0, now - item['started_monotonic_ns']) / 1000000)
        return item

    def after(self, connection, cursor, statement, parameters, context, executemany):
        self.finish(context, 'COMPLETED')

    def error(self, exception_context):
        item = self.finish(exception_context.execution_context, 'FAILED')
        if self.state['failed_operation'] is None:
            # Freeze first failure so rollback/teardown cannot replace the index target.
            failed = dict(item) if item is not None else {
                'family': 'NO_MATCHING_CURSOR_EVENT', 'index': None, 'table': None,
                'observed_at_utc': utc(), 'backend_pid': None, 'status': 'FAILED'}
            failed['dialect_reports_disconnect'] = exception_context.is_disconnect is True
            self.state['failed_operation'] = failed
