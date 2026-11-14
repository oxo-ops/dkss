"""Fresh-process file-CAS acceptance; only synthetic temporary data.

Run: python -I test_process_persistence.py
No network, live source, notification, database or installed dependency.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

def block_network(event, args):
    if event.startswith('socket.'):
        raise RuntimeError('NETWORK_FORBIDDEN_IN_SYNTHETIC_TEST')

sys.addaudithook(block_network)
import offline_monitor as m
from test_offline_monitor import collect, only, policy, NOW, LATER


def worker(mode, bundle_path, attempt_path, ready_path, go_path):
    store = m.SyntheticFileCASStore(bundle_path)
    identifier = only(store)[0]
    if mode == 'recover':
        m.recover_reserved(store, LATER)
    real_send = m.SyntheticTransport.send

    def observed_send(self, payload, now):
        # This is a fake-send witness, not real delivery evidence.
        if mode == 'crash_before_send':
            os._exit(73)
        fd = os.open(attempt_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'ab') as stream:
            stream.write(b'synthetic-attempt\n')
            stream.flush()
            os.fsync(stream.fileno())
        if mode == 'crash_after_send':
            os._exit(74)
        return real_send(self, payload, now)

    m.SyntheticTransport.send = observed_send
    if mode == 'race':
        real_read, first = store.read, [True]

        def synchronized_read():
            result = real_read()
            if first[0]:
                first[0] = False
                Path(ready_path).write_text('ready')
                deadline = time.monotonic() + 10
                while not Path(go_path).exists():
                    if time.monotonic() > deadline:
                        raise RuntimeError('TEST_BARRIER_TIMEOUT')
                    time.sleep(0.005)
            return result

        store.read = synchronized_read
    elif mode == 'crash_while_locked':
        def interrupted_replace(source, target):
            os._exit(75)
        m.os.replace = interrupted_replace

    try:
        result = m.send_one(store, m.SyntheticTransport(), identifier, LATER,
                            policy(send_enabled=True))
    except m.StoreConflict:
        result = 'conflict'
    print(json.dumps({'result': result, 'state': only(store)[1]['state']}))


class ProcessPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='q09-process-synthetic-')
        self.root = Path(self.temp.name)
        self.path = self.root / 'bundle.json'
        self.attempts = self.root / 'attempts'
        self.store = m.SyntheticFileCASStore(self.path)
        self.store.initialize()
        collect(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def start(self, mode, suffix=''):
        return subprocess.Popen(
            [sys.executable, '-I', str(Path(__file__).resolve()), '--worker', mode,
             str(self.path), str(self.attempts), str(self.root / ('ready'+suffix)),
             str(self.root / 'go')], env={}, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)

    def finish(self, process, expected=0):
        try:
            out, err = process.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            self.fail('TEST_CHILD_TIMEOUT')
        self.assertEqual(process.returncode, expected, err)
        self.assertEqual(err, '')
        return json.loads(out) if out else None

    def count(self):
        return len(self.attempts.read_bytes().splitlines()) if self.attempts.exists() else 0

    def test_fresh_process_preserves_accepted_and_suppresses_resend(self):
        self.assertEqual(self.finish(self.start('send')),
                         {'result': 'accepted', 'state': 'accepted'})
        self.assertEqual(self.finish(self.start('send')),
                         {'result': 'suppressed', 'state': 'accepted'})
        self.assertEqual(self.count(), 1)
        self.assertIsNone(only(self.store)[1]['arrival_proof'])
        self.assertIsNone(only(self.store)[1]['human_ack_proof'])

    def test_process_exit_after_reservation_before_fake_send_never_retries(self):
        self.finish(self.start('crash_before_send'), 73)
        self.assertEqual(only(self.store)[1]['state'], 'reserved')
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.finish(self.start('send'))['result'], 'suppressed')
        self.assertEqual(self.finish(self.start('recover')),
                         {'result': 'suppressed', 'state': 'uncertain'})
        self.assertEqual(self.count(), 0)

    def test_process_exit_after_fake_send_before_result_save_never_retries(self):
        self.finish(self.start('crash_after_send'), 74)
        self.assertEqual(only(self.store)[1]['state'], 'reserved')
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.finish(self.start('recover')),
                         {'result': 'suppressed', 'state': 'uncertain'})
        self.assertEqual(self.finish(self.start('send'))['result'], 'suppressed')
        self.assertEqual(self.count(), 1)

    def test_two_file_writer_processes_with_same_initial_revision_send_once(self):
        processes = [self.start('race', str(i)) for i in range(2)]
        try:
            deadline = time.monotonic() + 10
            while not all((self.root / ('ready'+str(i))).exists() for i in range(2)):
                if time.monotonic() > deadline:
                    self.fail('TEST_BARRIER_TIMEOUT')
                time.sleep(0.005)
            (self.root / 'go').write_text('go')
            results = [self.finish(p) for p in processes]
            # The loser can briefly hold the lock while rejecting its stale
            # reservation. The winner's result-write may then also conflict.
            # Both permitted schedules must retain one attempt and no rearm.
            outcomes = sorted(r['result'] for r in results)
            self.assertIn(outcomes, [['accepted', 'conflict'], ['conflict', 'conflict']])
            self.assertEqual(self.count(), 1)
            state = only(self.store)[1]['state']
            self.assertEqual(state, 'accepted' if 'accepted' in outcomes else 'reserved')
            self.assertEqual(self.finish(self.start('send'))['result'], 'suppressed')
            recovered = self.finish(self.start('recover'))
            self.assertEqual(recovered, {'result': 'suppressed',
                             'state': 'accepted' if state == 'accepted' else 'uncertain'})
            self.assertEqual(self.count(), 1)
        finally:
            for p in processes:
                if p.poll() is None:
                    p.kill()
                    p.communicate()

    def test_crash_while_locked_fails_closed_in_new_process_without_lock_theft(self):
        before = self.path.read_bytes()
        self.finish(self.start('crash_while_locked'), 75)
        lock = self.path.with_name(self.path.name + '.lock')
        self.assertTrue(lock.exists())
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.finish(self.start('send')),
                         {'result': 'conflict', 'state': 'unattempted'})
        self.assertTrue(lock.exists())
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.count(), 0)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--worker':
        worker(*sys.argv[2:])
    else:
        unittest.main(verbosity=2)
