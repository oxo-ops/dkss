"""Synthetic CI only: loopback PG/HTTP and owned temporary SQLite; no egress."""
import os
from pathlib import Path
import sys

if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != 'oxo-ops/dkss':
    raise RuntimeError('ANALYSIS_RUNTIME_CI_GUARD_REQUIRES_OWNED_JOB')
ROOT = Path(os.environ['DKSS_VALIDATION_TMP']).resolve()
PORTS = {5432, 5019}


def guard(event, args):
    if event == 'socket.getaddrinfo':
        if args[0] not in {'127.0.0.1', 'localhost', '::1', None}:
            raise RuntimeError('ANALYSIS_RUNTIME_CI_EXTERNAL_DNS_FORBIDDEN')
    if event in {'socket.connect', 'socket.bind'}:
        address = args[1]
        if not (isinstance(address, tuple) and len(address) >= 2 and address[0] == '127.0.0.1' and address[1] in PORTS):
            raise RuntimeError('ANALYSIS_RUNTIME_CI_NON_LOOPBACK_SOCKET_FORBIDDEN')
    if event == 'sqlite3.connect':
        name = str(args[0])
        if name != ':memory:' and (name.startswith('file:') or not Path(name).resolve().is_relative_to(ROOT)):
            raise RuntimeError('ANALYSIS_RUNTIME_CI_EXTERNAL_SQLITE_FORBIDDEN')


sys.addaudithook(guard)
os.environ['ANALYSIS_RUNTIME_CI_GUARD_LOADED'] = '1'
