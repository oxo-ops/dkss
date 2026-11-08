"""CI-only, message-free evidence for the disposable owned PostgreSQL server.

Never copy raw log text. Unrecognized/partial records are discarded. This module
has no database, process, network, retry, or acceptance-gate implementation.
"""
from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

OWNER = 'WORLEX_WINDOWS_CLIENT_SYNTHETIC_ONLY'
MAX_BYTES = 2097152
MAX_LINES = 8192
MAX_EVENTS = 128
MAX_OUTPUT = 65536
PREFIX = "log_line_prefix = 'WORLEX_CI|%m|%c|%p|%d|%e|'\n"
_RECORD = re.compile(r'^WORLEX_CI\|(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} UTC)\|([0-9a-f]{1,16}\.[0-9a-f]{1,16})\|([0-9]{1,10})\|([^|]{0,64})\|([0-9A-Z]{5})\|(LOG|FATAL|ERROR|WARNING|PANIC):  (.*)$')
_EVENTS = (
    ('server_starting', 'starting PostgreSQL '),
    ('shutdown_in_progress', 'shutting down'),
    ('authentication_timeout', 'canceling authentication due to timeout'),
    ('ssl_eof', 'could not accept SSL connection: EOF detected'),
    ('ssl_accept_failed', 'could not accept SSL connection:'),
    ('connection_reset', 'could not receive data from client: Connection reset by peer'),
    ('connection_accept_failed', 'could not accept new connection:'),
    ('connection_limit', 'sorry, too many clients already'),
    ('memory_exhausted', 'out of memory'),
    ('process_start_failed', 'could not fork new process for connection:'),
    ('process_start_failed', 'could not start server process:'),
    ('ready', 'database system is ready to accept connections'),
    ('shutdown_requested', 'received fast shutdown request'),
    ('shutdown_complete', 'database system is shut down'),
    ('connection_received', 'connection received:'),
    ('connection_authenticated', 'connection authenticated:'),
    ('connection_authorized', 'connection authorized:'),
    ('disconnection', 'disconnection:'),
    ('connection_lost', 'could not receive data from client:'),
    ('connection_write_failed', 'could not send data to client:'),
    ('connection_terminated', 'terminating connection due to administrator command'),
    ('authentication_failed', 'password authentication failed for user'),
    ('startup_failed', 'could not bind IPv4 address'),
)


def exception_label(exc):
    if exc is None:
        return None
    # Never serialize an arbitrary application exception name or message.
    allowed = {'RuntimeError', 'ValueError', 'OSError', 'PermissionError',
               'FileNotFoundError', 'TimeoutExpired', 'CalledProcessError',
               'KeyboardInterrupt', 'SystemExit'}
    name = type(exc).__name__
    return name if name in allowed else 'OtherError'


def collect_owned_events(work, runner_root):
    work, runner_root = Path(work), Path(runner_root)
    _evidence_directory(work)  # Also reject symlink/reparse ancestors.
    resolved = work.resolve(strict=True)
    if work.is_symlink() or not resolved.is_relative_to(runner_root.resolve(strict=True)) or resolved == runner_root.resolve():
        raise ValueError('OWNED_SCOPE_REQUIRED')
    marker = work / 'OWNER'
    _ordinary_path(marker)
    with marker.open('rb') as source:
        if source.read(len(OWNER) + 1) != OWNER.encode('ascii'):
            raise ValueError('OWNED_MARKER_REQUIRED')
    log = work / 'server.log'
    result = {'schema_version': 1, 'synthetic_only': True, 'status': 'missing',
              'events': [], 'truncated': False, 'partial_tail_discarded': False,
              'unknown_event_count': 0, 'unparsed_line_count': 0,
              'bytes_omitted': 0, 'lines_omitted': 0, 'events_omitted': 0}
    if not os.path.lexists(log):
        return result
    _ordinary_path(log)
    if log.resolve().parent != resolved:
        raise ValueError('OWNED_REGULAR_LOG_REQUIRED')
    with log.open('rb') as source:
        size = source.seek(0, 2)
        start = max(0, size - MAX_BYTES)
        source.seek(start)
        raw = source.read(MAX_BYTES)
    result['truncated'] = bool(start)
    result['bytes_omitted'] = start
    if start:
        raw = raw.partition(b'\n')[2]  # Never parse the partial first record.
    result['partial_tail_discarded'] = bool(raw and not raw.endswith(b'\n'))
    lines = raw.split(b'\n')[:-1]  # A concurrent partial write is never evidence.
    result['truncated'] |= len(lines) > MAX_LINES
    result['lines_omitted'] = max(0, len(lines) - MAX_LINES)
    for line in lines[-MAX_LINES:]:
        match = _RECORD.fullmatch(line.rstrip(b'\r').decode('ascii', errors='replace'))
        if not match:
            result['unparsed_line_count'] += 1
            continue
        stamp, session, pid, database, sqlstate, severity, message = match.groups()
        try:
            datetime.strptime(stamp, '%Y-%m-%d %H:%M:%S.%f UTC')
        except ValueError:
            result['unparsed_line_count'] += 1
            continue
        category = next((kind for kind, prefix in _EVENTS if message.startswith(prefix)), None)
        if category is None:
            # Only fixed SQLSTATE categories, never arbitrary codes or messages.
            category = {'57P01': 'administrator_shutdown', '57P02': 'crash_shutdown',
                        '57P03': 'server_not_ready', '53300': 'connection_limit',
                        '28P01': 'authentication_failed', '08006': 'connection_failure',
                        '53200': 'memory_exhausted', '53100': 'disk_full',
                        '53400': 'configuration_limit'}.get(sqlstate)
        if category is None:
            result['unknown_event_count'] += 1
            if severity in ('ERROR', 'FATAL', 'PANIC'):
                category = 'unknown_error'
        if category:
            result['events'].append({'timestamp': stamp, 'session': session, 'pid': int(pid), 'severity': severity,
                                     'sqlstate': sqlstate if sqlstate in ('00000', '57P01', '57P02', '57P03', '53300', '28P01', '08006', '53200', '53100', '53400') else 'unclassified',
                                     'database': database if database in ('postgres', 'dkss_restore_ci') or re.fullmatch(r'restore_owned_[0-9a-f]{32}', database) else 'unattributed',
                                     'category': category})
    result['truncated'] |= len(result['events']) > MAX_EVENTS
    result['events_omitted'] = max(0, len(result['events']) - MAX_EVENTS)
    # Preserve rare failures over connection chatter, within the same hard cap.
    routine = {'server_starting', 'ready', 'connection_received',
               'connection_authenticated', 'connection_authorized', 'disconnection',
               'shutdown_requested', 'shutdown_in_progress', 'shutdown_complete'}
    important = [i for i, event in enumerate(result['events'])
                 if event['severity'] in ('ERROR', 'FATAL', 'PANIC') or event['category'] not in routine]
    selected = set(important[-MAX_EVENTS:])
    for i in range(len(result['events']) - 1, -1, -1):
        if len(selected) >= MAX_EVENTS:
            break
        selected.add(i)
    result['events'] = [event for i, event in enumerate(result['events']) if i in selected]
    result['status'] = 'collected'
    return result


def _ordinary_path(path, *, directory=False):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
        raise ValueError('EVIDENCE_LINK_REJECTED')
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise ValueError('EVIDENCE_PATH_TYPE_REJECTED')
    if not directory and info.st_nlink != 1:
        raise ValueError('EVIDENCE_MULTIPLE_LINKS_REJECTED')
    return info


def _evidence_directory(evidence):
    directory = Path(evidence).absolute()
    for parent in (*reversed(directory.parents), directory):
        _ordinary_path(parent, directory=True)
    return directory


def _persist(evidence, name, value):
    if name not in ('owned-server-before-teardown.json', 'owned-server-after-teardown.json',
                    'owned-server-lifecycle.json'):
        raise ValueError('EVIDENCE_NAME_REJECTED')
    data = json.dumps(value, sort_keys=True, indent=2).encode('utf-8')
    if len(data) > MAX_OUTPUT:
        raise ValueError('EVIDENCE_BOUND_EXCEEDED')
    directory = _evidence_directory(evidence)
    target = directory / name
    if os.path.lexists(target):
        _ordinary_path(target)
    # mkstemp uses exclusive creation, never follows an existing temp symlink.
    # Write through the returned descriptor, then atomically publish only the
    # complete file. No predictable .json.tmp path is opened or overwritten.
    descriptor, temporary_name = tempfile.mkstemp(prefix='.owned-server-', suffix='.tmp', dir=directory)
    temporary = Path(temporary_name)
    identity = os.fstat(descriptor)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            descriptor = None
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        _evidence_directory(directory)
        current = _ordinary_path(temporary)
        if (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
            raise ValueError('EVIDENCE_TEMP_CHANGED')
        if os.path.lexists(target):
            _ordinary_path(target)
        temporary.replace(target)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        # Do not remove a substituted path we did not create.
        try:
            current = temporary.lstat()
            if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                temporary.unlink()
        except FileNotFoundError:
            pass


def _fallback():
    try:
        print('OWNED_SERVER_DIAGNOSTICS_INCOMPLETE', file=sys.stderr)
    except BaseException:
        pass


@contextmanager
def owned_server_lifecycle(work, runner_root, evidence, *, start, cleanup, secrets_cleanup,
                           collector=collect_owned_events, writer=_persist):
    """Run callbacks once, preserving the original failure over all teardown errors."""
    primary = cleanup_error = secret_error = None
    incomplete = False
    stages = {}

    def persist(name, value):
        nonlocal incomplete
        try:
            writer(evidence, name, value)
        except BaseException:
            incomplete = True
            _fallback()

    def snapshot(stage):
        nonlocal incomplete
        try:
            value = collector(work, runner_root)
            if value['status'] != 'collected' or any(value.get(key, False) for key in (
                    'truncated', 'partial_tail_discarded', 'bytes_omitted',
                    'lines_omitted', 'events_omitted')):
                incomplete = True
        except BaseException as exc:
            incomplete = True
            value = {'schema_version': 1, 'status': 'collection_failed',
                     'exception_class': exception_label(exc), 'events': []}
        stages[stage] = value['status']
        persist('owned-server-' + stage + '.json', value)

    try:
        start()
        yield
    except BaseException as exc:
        primary = exc
        raise
    finally:
        snapshot('before-teardown')
        try:
            cleanup()
        except BaseException as exc:
            cleanup_error = exc
        finally:
            try:
                secrets_cleanup()
            except BaseException as exc:
                secret_error = exc
        snapshot('after-teardown')
        persist('owned-server-lifecycle.json', {
            'schema_version': 1, 'primary_exception_class': exception_label(primary),
            'cleanup_exception_class': exception_label(cleanup_error),
            'secrets_cleanup_exception_class': exception_label(secret_error),
            'collection_incomplete': incomplete, 'stages': stages})
        if incomplete:
            _fallback()
        if primary is None:
            if cleanup_error is not None:
                raise cleanup_error
            if secret_error is not None:
                raise secret_error
