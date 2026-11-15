"""Offline synthetic v2 integration. No scheduler, real transport or Render IO.
One bundle holds original monitor, outbox and immutable collection history.
The v1 projection is an adapter, never a second file. POSIX cooperative writers.
"""
import copy
import os
from pathlib import Path
import tempfile
import offline_monitor as old
import collection_history as history

FORMAT = 'q09-synthetic-monitor-history-v2'


def migrate_snapshot(legacy):
    old.validate_bundle(legacy)
    result = {'format': FORMAT, 'monitor': copy.deepcopy(legacy),
              'prior_runs_without_history': legacy['ledger']['runs'], 'history': []}
    validate(result)
    return result


def validate(bundle):
    old.keys(bundle, {'format', 'monitor', 'prior_runs_without_history', 'history'})
    if bundle['format'] != FORMAT:
        old.reject()
    old.validate_bundle(bundle['monitor'])
    history.validate({'format': history.FORMAT, 'ledger': bundle['monitor']['ledger'],
                      'prior_runs_without_history': bundle['prior_runs_without_history'],
                      'history': bundle['history']}, old.RESOURCE)
    if len(old.encoded(bundle).encode()) > old.ledger.MAX_STATE:
        raise ValueError('STATE_CAPACITY')


def transition(previous, candidate):
    validate(previous)
    validate(candidate)
    old.validate_transition(previous['monitor'], candidate['monitor'])
    delta = candidate['monitor']['ledger']['runs'] - previous['monitor']['ledger']['runs']
    if (delta not in (0, 1) or
            candidate['prior_runs_without_history'] != previous['prior_runs_without_history'] or
            candidate['history'][:len(previous['history'])] != previous['history'] or
            len(candidate['history']) != len(previous['history']) + delta):
        old.reject()


class FileStore(old.SyntheticFileCASStore):
    def _check_parent(self):
        if os.name != 'posix':
            raise ValueError('POSIX_ONLY')
        super()._check_parent()

    def read(self):
        self._check_parent()
        try:
            bundle = old.ledger.private_file(self.path, old.ledger.MAX_STATE)
            validate(bundle)
            return bundle
        except Exception:
            raise old.StoreUncertain('STORE_UNREADABLE_OR_UNCERTAIN') from None

    def initialize(self):
        return self._commit(None, migrate_snapshot(old.new_bundle()), create=True)

    def compare_and_swap(self, expected, candidate):
        return self._commit(expected, candidate)

    def _commit(self, expected, candidate, create=False):
        self._check_parent()
        validate(candidate)
        lock = self.path.with_name(self.path.name + '.lock')
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            raise old.StoreConflict('STORE_LOCKED') from None
        os.close(fd)
        temporary = None
        try:
            if create:
                if os.path.lexists(self.path):
                    raise old.StoreConflict('STORE_ALREADY_EXISTS')
            else:
                previous = self.read()
                if old.digest(previous) != expected:
                    raise old.StoreConflict('STORE_CONFLICT')
                transition(previous, candidate)
            fd, temporary = tempfile.mkstemp(prefix='.q09-v2-', dir=self.path.parent)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(old.encoded(candidate).encode())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            temporary = None
            fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            return candidate['monitor']['revision']
        except old.StoreConflict:
            raise
        except Exception:
            raise old.StoreUncertain('STORE_OUTCOME_UNCERTAIN') from None
        finally:
            failed = False
            for path in (temporary, lock):
                if path is not None:
                    try:
                        os.unlink(path)
                    except Exception:
                        failed = True
            if failed:
                raise old.StoreUncertain('STORE_CLEANUP_UNCERTAIN') from None

    def migrate_from(self, source, *, writers_stopped=False):
        """Explicit operator-controlled offline migration. Retains v1 original.
        Caller must stop v1 writers permanently before using v2; no dual-write.
        Source lock excludes cooperative in-flight writers during snapshot.
        """
        if writers_stopped is not True:
            raise ValueError('OFFLINE_MIGRATION_REQUIRED')
        source = old.SyntheticFileCASStore(source)
        if source.path.resolve() == self.path.resolve():
            raise ValueError('DISTINCT_DESTINATION_REQUIRED')
        lock = source.path.with_name(source.path.name + '.lock')
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            raise old.StoreConflict('SOURCE_LOCKED') from None
        os.close(fd)
        try:
            return self._commit(None, migrate_snapshot(source.read()), create=True)
        finally:
            try:
                os.unlink(lock)
            except Exception:
                raise old.StoreUncertain('MIGRATION_CLEANUP_UNCERTAIN') from None


class Projection:
    """One operation-local v1 view. Whole v2 digest CAS prevents lost updates."""
    def __init__(self, store):
        self.store = store
        self.previous = store.read()
        validate(self.previous)

    def read(self):
        return copy.deepcopy(self.previous['monitor'])

    def compare_and_swap(self, expected_revision, candidate):
        if expected_revision != self.previous['monitor']['revision']:
            raise old.StoreConflict('STORE_CONFLICT')
        result = copy.deepcopy(self.previous)
        result['monitor'] = copy.deepcopy(candidate)
        delta = candidate['ledger']['runs'] - self.previous['monitor']['ledger']['runs']
        if delta == 1:
            result['history'].append(history.entry(candidate['ledger']['last_scan'], candidate['ledger']['runs']))
        transition(self.previous, result)
        revision = self.store.compare_and_swap(old.digest(self.previous), result)
        self.previous = result
        return revision


def collect_once(store, recorder, now, policy, scheduled=False):
    if type(recorder) is not old.SyntheticRecorder or type(policy) is not old.Policy or type(scheduled) is not bool:
        old.reject()
    adapter = Projection(store)
    # Not-due returns without consuming a fixture, even if history is full.
    if scheduled and not old.due(adapter.read(), now, policy):
        return store.read()
    if len(adapter.previous['history']) >= history.MAX_HISTORY:
        raise ValueError('COLLECTION_HISTORY_FULL')
    old.collect_once(adapter, recorder, now, policy, scheduled=scheduled)
    return store.read()
