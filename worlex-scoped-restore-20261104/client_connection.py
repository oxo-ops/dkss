"""Explicit verified TLS settings for the pure-Python PostgreSQL client.

No connection is made by this module. Never use pg8000's None/True TLS defaults:
those defaults do not provide the required CA and hostname verification.
"""
import re
import ssl
from pathlib import Path

CLIENT_DRIVER = 'postgresql+pg8000'
SOCKET_TIMEOUT_SECONDS = 130


def tls_context(cafile=None):
    if cafile is None:
        import certifi
        cafile = certifi.where()
    path = Path(cafile)
    if not path.is_file():
        raise ValueError('CLIENT_CA_FILE_MISSING')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_verify_locations(cafile=str(path))
    if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
        raise ValueError('CLIENT_VERIFIED_TLS_REQUIRED')
    return context


def connection_args(*, cafile=None, timeout=SOCKET_TIMEOUT_SECONDS,
                    application_name='worlex_scoped_restore', read_only=False):
    # This is a socket timeout, not only a TCP connect timeout. It must allow
    # the 120-second server statement limit to return its own cancellation.
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 5 <= timeout <= 150:
        raise ValueError('CLIENT_SOCKET_TIMEOUT_OUT_OF_BOUNDS')
    if not isinstance(application_name, str) or not re.fullmatch(r'worlex_[a-z0-9_]{1,48}', application_name):
        raise ValueError('CLIENT_APPLICATION_NAME_INVALID')
    if type(read_only) is not bool:
        raise ValueError('CLIENT_READ_ONLY_FLAG_INVALID')
    startup = {
        'search_path': 'pg_catalog,public',
        'statement_timeout': '120000',
        'lock_timeout': '10000',
        'idle_in_transaction_session_timeout': '180000',
        'transaction_timeout': '300000',
    }
    if read_only:
        startup['default_transaction_read_only'] = 'on'
    return {'ssl_context': tls_context(cafile), 'timeout': timeout,
            'application_name': application_name, 'startup_params': startup}


def sqlstate(error):
    """Return only the five-character server SQLSTATE, never raw diagnostics."""
    original = getattr(error, 'orig', error)
    args = getattr(original, 'args', ())
    value = args[0].get('C') if args and isinstance(args[0], dict) else None
    return value if isinstance(value, str) and re.fullmatch(r'[0-9A-Z]{5}', value) else None


def verify_tls_connection(connection, expected_host):
    """Check the actual pinned driver's socket; do not issue SQL or reconnect."""
    raw = connection.connection.driver_connection
    sock = getattr(raw, '_usock', None)
    if (connection.dialect.driver != 'pg8000' or type(raw).__module__ != 'pg8000.legacy'
            or not isinstance(sock, ssl.SSLSocket)
            or sock.context.verify_mode != ssl.CERT_REQUIRED or not sock.context.check_hostname
            or sock.server_hostname != expected_host or not sock.getpeercert()
            or sock.version() not in ('TLSv1.2', 'TLSv1.3')):
        raise ValueError('CLIENT_ACTUAL_TLS_NOT_VERIFIED')
    return {'tls_version': sock.version(), 'hostname_verified': True, 'certificate_verified': True}
