"""Test process boundary: private SQLite and optional explicit Q08 loopback PG."""
import os
from pathlib import Path
import sys

ROOT = Path(os.environ['DKSS_VALIDATION_TMP']).resolve()
PG = bool(os.environ.get('Q08_POSTGRES_TEST_URL'))
GUARDED_INDEPENDENT_AUDIT = 'private-sqlite-q08-loopback-v1'


def audit(event, args):
    if event in {'socket.bind', 'socket.listen'}:
        raise RuntimeError('INDEPENDENT_LISTENER_FORBIDDEN')
    if event == 'socket.connect':
        address = args[1]
        if not (PG and isinstance(address, tuple) and len(address) >= 2
                and address[0] in {'127.0.0.1', '::1'} and address[1] == 5432):
            raise RuntimeError('INDEPENDENT_EXTERNAL_TRANSPORT_FORBIDDEN')
    if event == 'socket.getaddrinfo':
        if not (PG and args[0] in {'127.0.0.1', 'localhost', '::1'} and args[1] in {5432, '5432'}):
            raise RuntimeError('INDEPENDENT_EXTERNAL_DNS_FORBIDDEN')
    if event == 'sqlite3.connect':
        value = str(args[0])
        if value != ':memory:' and (value.startswith('file:') or not Path(value).resolve().is_relative_to(ROOT)):
            raise RuntimeError('INDEPENDENT_PRIVATE_SQLITE_REQUIRED')


sys.addaudithook(audit)
