"""Actual Linux entry points; fresh SQLite only and no non-loopback connections."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request


@unittest.skipUnless(sys.platform.startswith('linux'), 'Actual Gunicorn requires Linux')
class LinuxRuntimeTests(unittest.TestCase):
    def test_gunicorn_and_explicit_ocr_start_and_stop_without_external_services(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='q09-linux-new-') as temporary:
            folder = Path(temporary)
            # Every child, including Gunicorn workers, loads the same network guard.
            (folder / 'sitecustomize.py').write_text('''
import sys
def guard(event, args):
    if event == 'socket.connect':
        address = args[1]
        if not isinstance(address, tuple) or address[0] not in {'127.0.0.1', '::1'}:
            raise RuntimeError('Q09_NON_LOOPBACK_CONNECTION_BLOCKED')
sys.addaudithook(guard)
''', encoding='utf-8')
            env = {key: value for key, value in os.environ.items()
                   if key in {'PATH', 'LANG', 'LC_ALL', 'SYSTEMROOT', 'WINDIR'}}
            env.update(SECRET_KEY=os.urandom(32).hex(), ITC_INITIAL_PASSWORD=os.urandom(24).hex(),
                DATABASE_URL='sqlite:///' + str(folder / 'new.db'), RENDER='',
                RATELIMIT_STORAGE_URI='memory://', AWS_EC2_METADATA_DISABLED='true',
                S3_BUCKET_NAME='', OPENAI_API_KEY='', SMTP_HOST='', VAPID_PRIVATE_KEY='',
                VAPID_PUBLIC_KEY='', MFA_ENABLED='false', WEB_CONCURRENCY='1', WEB_THREADS='4',
                PYTHONPATH=os.pathsep.join([str(folder), str(root)]), PYTHONUNBUFFERED='1')
            # Confirm the guard is loaded; the denied connect never leaves this process.
            guard_check = subprocess.run([sys.executable, '-c',
                "import socket; socket.socket().connect(('192.0.2.1',9))"],
                env=env, cwd=root, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(guard_check.returncode, 0)
            self.assertIn('Q09_NON_LOOPBACK_CONNECTION_BLOCKED', guard_check.stderr)
            initialized = subprocess.run([sys.executable, '-m', 'flask', '--app', 'app', 'init-db'],
                env=env, cwd=root, capture_output=True, text=True, timeout=45)
            self.assertEqual(initialized.returncode, 0, 'New SQLite bootstrap failed; raw output withheld')
            self.assertIn('DATABASE_INITIALIZED', initialized.stdout)
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]

            def launch_and_stop(command, logname, expected_markers, ready):
                log = folder / logname
                with log.open('w', encoding='utf-8') as output:
                    process = subprocess.Popen(command, env=env, cwd=root,
                        stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
                    try:
                        deadline = time.monotonic() + 25
                        while time.monotonic() < deadline:
                            self.assertIsNone(process.poll(), 'Runtime exited before readiness')
                            contents = log.read_text(encoding='utf-8')
                            if all(marker in contents for marker in expected_markers) and ready():
                                break
                            time.sleep(0.1)
                        else:
                            self.fail('Runtime did not reach readiness; raw output withheld')
                        process.send_signal(signal.SIGTERM)
                        self.assertEqual(process.wait(timeout=15), 0, 'Normal SIGTERM stop must succeed')
                    finally:
                        if process.poll() is None:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait(timeout=5)
                contents = log.read_text(encoding='utf-8')
                self.assertNotIn('Q09_NON_LOOPBACK_CONNECTION_BLOCKED', contents)
                self.assertNotIn('Traceback (most recent call last)', contents)
                self.assertNotIn(env['SECRET_KEY'], contents)
                self.assertNotIn(env['ITC_INITIAL_PASSWORD'], contents)

            def web_ready():
                try:
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    with opener.open(f'http://127.0.0.1:{port}/login', timeout=1) as response:
                        return response.status == 200 and b'<form' in response.read()
                except OSError:
                    return False

            launch_and_stop([sys.executable, '-m', 'gunicorn', '-c', 'gunicorn.conf.py',
                '--bind', f'127.0.0.1:{port}', 'app:app'], 'web.log',
                ['Using worker: gthread', 'OCR_WORKER_STARTED', 'OCR_WORKER_HEARTBEAT'], web_ready)
            # Explicit CLI intentionally runs even when embedded startup is disabled.
            env['DOCUMENT_IMPORT_WORKER_ENABLED'] = '0'
            launch_and_stop([sys.executable, '-m', 'flask', '--app', 'app', 'document-import-worker'],
                'ocr.log', ['OCR_WORKER_STARTED', 'OCR_WORKER_HEARTBEAT'], lambda: True)
            print('Q09_LINUX_RUNTIME_OK ' + json.dumps(dict(
                gunicorn='gthread/1/4', login_http=200, embedded_ocr=True,
                explicit_ocr=True, sigterm_exit_codes=[0, 0], non_loopback_blocked=True,
                fresh_sqlite_only=True)))
