"""Generate the application/schema contract from ORM metadata without opening a DB."""
import argparse
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def render():
    from sqlalchemy.engine import Engine
    from dkss_app import create_app
    from dkss_app.contracts import application_contract
    from dkss_app.extensions import db
    with patch.dict(os.environ, {'RENDER': '', 'S3_BUCKET_NAME': '',
        'AWS_EC2_METADATA_DISABLED': 'true', 'RATELIMIT_STORAGE_URI': 'memory://'}), patch.object(
        Engine, 'connect', side_effect=AssertionError('Contract export opened a database')
    ):
        app = create_app({'SECRET_KEY': 'contract-export-only',
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:', 'TESTING': True,
            'WTF_CSRF_ENABLED': False, 'S3_BUCKET_NAME': '', 'RATELIMIT_ENABLED': True})
        return json.dumps(application_contract(app, db), ensure_ascii=False, indent=2) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, nargs='?')
    args = parser.parse_args()
    result = render()
    if args.output:
        args.output.write_text(result, encoding='utf-8')
    else:
        print(result, end='')


if __name__ == '__main__':
    main()
