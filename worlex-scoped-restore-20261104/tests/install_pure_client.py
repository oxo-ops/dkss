"""Install only hash-pinned pure client wheels in a disposable Actions interpreter."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / 'tests/windows-ci'
sys.path.insert(0, str(CI))
from build_windows_client import fetch, filtered_requirements
from verify_client_evidence import validate_pure_wheels


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != 'oxo-ops/dkss':
        raise SystemExit('DEDICATED_CI_ONLY')
    if len(sys.argv) != 2 or sys.argv[1] not in ('application', 'runner'):
        raise SystemExit('FIXED_CI_INSTALL_SCOPE_REQUIRED')
    lock = json.loads((CI / 'client-build-inputs.json').read_text())
    with tempfile.TemporaryDirectory(prefix='worlex-pure-install-', dir=os.environ['RUNNER_TEMP']) as temporary:
        work = Path(temporary); wheels = work / 'wheels'; wheels.mkdir()
        for entry in lock['pure_client']['packages']:
            fetch(entry, wheels / entry['filename'])
        validate_pure_wheels(lock['pure_client']['packages'], wheels)
        requirements = work / 'requirements.txt'
        requirements.write_text(filtered_requirements(ROOT.parent / 'requirements.txt')
                                if sys.argv[1] == 'application' else 'SQLAlchemy==2.0.50\n')
        env = dict(os.environ, PIP_CONFIG_FILE=os.devnull, PIP_INDEX_URL='https://pypi.org/simple',
                   PIP_NO_INPUT='1', PIP_DISABLE_PIP_VERSION_CHECK='1', PYTHONDONTWRITEBYTECODE='1')
        # Application pins are unchanged; only its psycopg2-binary pin is omitted.
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', str(requirements)],
                       env=env, check=True, timeout=600)
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-index', '--no-deps',
                        *map(str, sorted(wheels.glob('*.whl')))], env=env, check=True, timeout=120)
        subprocess.run([sys.executable, '-m', 'pip', 'check'], env=env, check=True, timeout=60)


if __name__ == '__main__':
    main()
