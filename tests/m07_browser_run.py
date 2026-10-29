"""Run browser acceptance against new SQLite only; never inherit service settings."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def main():
    destination = Path(sys.argv[1]).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='m07-browser-'))
    guard = root / 'guard'
    guard.mkdir()
    (guard / 'sitecustomize.py').write_text('''
import sys
from pathlib import Path
ROOT = Path(''' + repr(str(root)) + ''').resolve()
def guard(event, args):
    if event in {'socket.connect','socket.sendto'}:
        address = args[1]
        if not isinstance(address, tuple) or address[0] not in {'127.0.0.1','::1'}:
            raise RuntimeError('M07_EXTERNAL_NETWORK_BLOCKED')
    if event == 'socket.getaddrinfo' and args[0] not in {'127.0.0.1','::1',None}:
        raise RuntimeError('M07_EXTERNAL_DNS_BLOCKED')
sys.addaudithook(guard)
from sqlalchemy.engine import Engine
original = Engine.connect
def connect(self, *args, **kwargs):
    if self.url.get_backend_name() != 'sqlite':
        raise RuntimeError('M07_NON_SQLITE_DATABASE_BLOCKED')
    path = self.url.database
    if path and path != ':memory:' and not Path(path).resolve().is_relative_to(ROOT):
        raise RuntimeError('M07_EXISTING_DATABASE_BLOCKED')
    return original(self, *args, **kwargs)
Engine.connect = connect
''', encoding='utf-8')
    repo = Path(__file__).resolve().parents[1]
    env = {k: v for k, v in os.environ.items() if k.upper() in {
        'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'USERPROFILE',
        'APPDATA', 'LOCALAPPDATA', 'HOME', 'NODE_PATH', 'Q10_BROWSER_EXECUTABLE'}}
    env.update(TEMP=str(root), TMP=str(root), PYTHONUTF8='1', PYTHONUNBUFFERED='1',
        PYTHONPATH=os.pathsep.join([str(guard), str(repo), str(repo / 'tests')]),
        AWS_EC2_METADATA_DISABLED='true', DOCUMENT_IMPORT_WORKER_ENABLED='0',
        S3_BUCKET_NAME='', OPENAI_API_KEY='', SMTP_HOST='', VAPID_PRIVATE_KEY='',
        VAPID_PUBLIC_KEY='', RENDER='')
    records = []
    for mode in ['normal', 'legacy']:
        folder = destination / mode
        folder.mkdir(exist_ok=True)
        ready = root / (mode + '.json')
        with (folder / 'server.txt').open('w', encoding='utf-8') as log:
            server = subprocess.Popen([sys.executable, 'tests/m07_browser_server.py', str(ready), mode],
                cwd=repo, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                for _ in range(300):
                    if ready.exists():
                        break
                    if server.poll() is not None:
                        raise RuntimeError('Synthetic M07 fixture exited; see server.txt')
                    time.sleep(.1)
                else:
                    raise RuntimeError('Synthetic M07 fixture did not become ready')
                with (folder / 'node.txt').open('w', encoding='utf-8') as node_log:
                    result = subprocess.run(['node', 'tests/m07_browser_acceptance.cjs', str(ready), str(folder)],
                        cwd=repo, env=env, stdout=node_log, stderr=subprocess.STDOUT, timeout=120)
                records.append(dict(mode=mode, exit=result.returncode,
                    results=json.loads((folder / 'browser-results.json').read_text(encoding='utf-8'))))
            finally:
                ready.with_suffix('.stop').touch()
                server.wait(20)
                if server.returncode != 0:
                    raise RuntimeError('Synthetic M07 fixture cleanup failed')
    (destination / 'acceptance.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps([dict(mode=r['mode'], exit=r['exit'], passed=r['results']['passed'],
                           failed=r['results']['failed']) for r in records]))
    return int(any(r['exit'] for r in records))


if __name__ == '__main__':
    raise SystemExit(main())
