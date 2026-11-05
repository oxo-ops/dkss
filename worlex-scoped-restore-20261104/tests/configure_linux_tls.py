"""Enable verified TLS only on this workflow's fresh PostgreSQL 18 service.

This is CI setup, not a database repair or production configuration utility.
It accepts no arguments, contacts only the local Docker daemon and loopback,
and never creates, resets, drops, or truncates a database. Private key material
stays in RUNNER_TEMP and the disposable container, outside artifact paths.
"""

import datetime
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import ssl
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit


DATABASE = 'dkss_restore_ci'
USERNAME = 'restore_ci'
PASSWORD = 'restore-disposable-synthetic-only'
MARKER = 'WORLEX_RESTORE_SYNTHETIC_ONLY'
PGDATA = '/var/lib/postgresql/18/docker'
DOCKER = ['docker', '--host', 'unix:///var/run/docker.sock']
HBA = (
    '# Dedicated ephemeral synthetic CI service only.\n'
    'local all restore_ci trust\n'
    'local all all reject\n'
    'hostnossl all all all reject\n'
    # Published loopback connections arrive from the Docker bridge address.
    # This role is fixed, and every TCP connection requires TLS and SCRAM.
    'hostssl all restore_ci all scram-sha-256\n'
    'hostssl all all all reject\n'
)
DATABASE_FACTS_SQL = """
SELECT json_build_object(
    'database', current_database(), 'username', current_user,
    'owner', pg_get_userbyid(d.datdba),
    'marker', shobj_description(d.oid, 'pg_database'),
    'is_superuser', current_setting('is_superuser'),
    'server_version_num', current_setting('server_version_num'),
    'data_directory', current_setting('data_directory'),
    'hba_file', current_setting('hba_file'),
    'recovery', pg_is_in_recovery(),
    'extra_databases', (SELECT count(*) FROM pg_database
        WHERE datname NOT IN ('dkss_restore_ci','postgres','template0','template1')),
    'user_relations', (SELECT count(*) FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'),
    'user_functions', (SELECT count(*) FROM pg_proc p
        JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'),
    'extra_schemas', (SELECT count(*) FROM pg_namespace
        WHERE nspname !~ '^pg_' AND nspname NOT IN ('public','information_schema'))
) FROM pg_database d WHERE d.datname=current_database()
"""


class SetupError(RuntimeError):
    """Only fixed, nonsecret diagnostic codes may be reported by this script."""


def require(condition, code):
    if not condition:
        raise SetupError(code)


def validate_environment(environment):
    require(sys.platform == 'linux' and environment.get('GITHUB_ACTIONS') == 'true'
            and environment.get('GITHUB_REPOSITORY') == 'oxo-ops/dkss',
            'DEDICATED_LINUX_CI_ONLY')
    container = environment.get('POSTGRES_SERVICE_CONTAINER', '')
    require(re.fullmatch(r'[0-9a-f]{64}', container) is not None,
            'WORKFLOW_SERVICE_CONTAINER_ID_REQUIRED')
    try:
        url = urlsplit(environment.get('WORLEX_TEST_POSTGRES_URL', ''))
        port = url.port
        valid = (url.scheme == 'postgresql+pg8000' and url.hostname == '127.0.0.1'
                 and url.username == USERNAME and url.password == PASSWORD
                 and url.path == '/' + DATABASE and not url.query and not url.fragment
                 and type(port) is int and 1 <= port <= 65535)
    except ValueError:
        valid = False
    require(valid, 'FIXED_SYNTHETIC_LOOPBACK_URL_REQUIRED')
    temp_value = environment.get('RUNNER_TEMP', '')
    env_value = environment.get('GITHUB_ENV', '')
    workspace_value = environment.get('GITHUB_WORKSPACE', '')
    require(all((temp_value, env_value, workspace_value)), 'RUNNER_PATHS_REQUIRED')
    require(not any(c in temp_value + env_value for c in '\r\n\x00'),
            'RUNNER_PATHS_INVALID')
    runner_temp = Path(temp_value).resolve(strict=True)
    github_env = Path(env_value).resolve(strict=True)
    workspace = Path(workspace_value).resolve(strict=True)
    require(runner_temp.is_dir() and runner_temp != Path('/')
            and not runner_temp.is_relative_to(workspace)
            and github_env.is_file() and github_env.is_relative_to(runner_temp),
            'ISOLATED_RUNNER_TEMP_REQUIRED')
    return container, port, runner_temp, github_env


def run(arguments):
    # --host overrides Docker context/host settings. Do not inherit credential,
    # libpq, client TLS, or Docker environment variables, or log subprocess output.
    result = subprocess.run(
        [*DOCKER, *arguments], check=False, capture_output=True, text=True,
        timeout=30, env={'PATH': os.defpath, 'LANG': 'C.UTF-8'},
    )
    require(result.returncode == 0, 'OWNED_SERVICE_COMMAND_FAILED')
    return result.stdout.strip()


def psql(container, sql):
    return run(['exec', '--user', 'postgres', container, 'psql', '--no-psqlrc',
                '--no-password', '--host', '/var/run/postgresql',
                '--username', USERNAME, '--dbname', DATABASE,
                '--set', 'ON_ERROR_STOP=1', '--tuples-only', '--no-align',
                '--command', sql])


def validate_container(container, port, inspected):
    require(isinstance(inspected, list) and len(inspected) == 1,
            'SERVICE_INSPECTION_INVALID')
    service = inspected[0]
    require(service.get('Id') == container and service.get('State', {}).get('Running') is True
            and service.get('Config', {}).get('Image') == 'postgres:18',
            'EXPECTED_POSTGRES_SERVICE_REQUIRED')
    entries = service.get('Config', {}).get('Env', [])
    require(isinstance(entries, list), 'SERVICE_ENVIRONMENT_INVALID')
    env = dict(entry.split('=', 1) for entry in entries if '=' in entry)
    require(env.get('POSTGRES_DB') == DATABASE and env.get('POSTGRES_USER') == USERNAME
            and env.get('POSTGRES_PASSWORD') == PASSWORD
            and env.get('POSTGRES_INITDB_ARGS') == '--auth-host=scram-sha-256'
            and env.get('PGDATA') == PGDATA,
            'FIXED_SYNTHETIC_SERVICE_REQUIRED')
    require(not any(key in env for key in ('POSTGRES_HOST_AUTH_METHOD',
                'POSTGRES_PASSWORD_FILE', 'POSTGRES_USER_FILE', 'POSTGRES_DB_FILE')),
            'SERVICE_AUTH_OVERRIDE_FORBIDDEN')
    bindings = service.get('NetworkSettings', {}).get('Ports', {}).get('5432/tcp') or []
    require(any(item.get('HostPort') == str(port)
                and item.get('HostIp') in ('0.0.0.0', '127.0.0.1') for item in bindings),
            'SERVICE_PUBLISHED_LOOPBACK_PORT_MISMATCH')


def validate_database(facts):
    require(facts.get('database') == DATABASE and facts.get('username') == USERNAME
            and facts.get('owner') == USERNAME and facts.get('is_superuser') == 'on'
            and facts.get('recovery') is False and facts.get('marker') is None,
            'FRESH_OWNED_MARKER_DATABASE_REQUIRED')
    require(180000 <= int(facts.get('server_version_num', 0)) < 190000,
            'POSTGRES_18_REQUIRED')
    require(all(facts.get(key) == 0 for key in
                ('extra_databases', 'user_relations', 'user_functions', 'extra_schemas')),
            'EMPTY_SYNTHETIC_SERVICE_REQUIRED')
    hba = PurePosixPath(facts.get('hba_file', ''))
    require(facts.get('data_directory') == PGDATA and str(hba) == PGDATA + '/pg_hba.conf',
            'EXPECTED_SERVICE_CONFIGURATION_PATH_REQUIRED')
    return str(hba)


def generate_certificates(directory):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'WORLEX ephemeral synthetic CI CA')])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - datetime.timedelta(minutes=5))
          .not_valid_after(now + datetime.timedelta(days=1))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                         key_encipherment=False, data_encipherment=False, key_agreement=False,
                         key_cert_sign=True, crl_sign=True, encipher_only=False,
                         decipher_only=False), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
          .sign(ca_key, hashes.SHA256()))
    server = (x509.CertificateBuilder()
              .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')]))
              .issuer_name(ca_name).public_key(server_key.public_key())
              .serial_number(x509.random_serial_number())
              .not_valid_before(now - datetime.timedelta(minutes=5))
              .not_valid_after(now + datetime.timedelta(days=1))
              .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
              .add_extension(x509.SubjectAlternativeName([
                  x509.DNSName('localhost'), x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),
                  critical=False)
              .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
              .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                             key_encipherment=True, data_encipherment=False, key_agreement=False,
                             key_cert_sign=False, crl_sign=False, encipher_only=False,
                             decipher_only=False), critical=True)
              .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                             critical=False)
              .sign(ca_key, hashes.SHA256()))
    ca_file, cert_file, key_file = (directory / name for name in ('ca.pem', 'server.crt', 'server.key'))
    ca_file.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_file.write_bytes(server.public_bytes(serialization.Encoding.PEM))
    # The CA signing key is never written to disk. Create the server key with
    # restrictive permissions from the first write, not a later chmod.
    descriptor = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as handle:
        handle.write(server_key.private_bytes(serialization.Encoding.PEM,
                     serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return ca_file, cert_file, key_file


def assert_tls_session(connection):
    sock = getattr(connection, '_usock', None)
    require(type(connection).__module__ == 'pg8000.legacy'
            and isinstance(sock, ssl.SSLSocket)
            and sock.context.verify_mode == ssl.CERT_REQUIRED and sock.context.check_hostname
            and sock.server_hostname == '127.0.0.1' and bool(sock.getpeercert())
            and sock.version() in ('TLSv1.2', 'TLSv1.3'),
            'PG8000_VERIFIED_TLS_SOCKET_REQUIRED')
    cursor = connection.cursor()
    try:
        cursor.execute('SHOW ssl')
        row = cursor.fetchone()
        require(row is not None and tuple(row) == ('on',), 'POSTGRES_SSL_REQUIRED')
        cursor.execute('SELECT ssl, version FROM pg_stat_ssl WHERE pid=pg_backend_pid()')
        row = cursor.fetchone()
        require(row is not None and row[0] is True and row[1] == sock.version(),
                'POSTGRES_TLS_SESSION_PROOF_REQUIRED')
    finally:
        cursor.close()


def prove_tls(port, ca_file):
    import pg8000

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_verify_locations(cafile=str(ca_file))
    connection = pg8000.connect(host='127.0.0.1', port=port, database=DATABASE,
                                user=USERNAME, password=PASSWORD, ssl_context=context,
                                timeout=10, application_name='worlex_linux_tls_setup',
                                startup_params={'statement_timeout': '10000'})
    try:
        assert_tls_session(connection)
    finally:
        connection.close()


def configure(environment):
    container, port, runner_temp, github_env = validate_environment(environment)
    validate_container(container, port, json.loads(run(['inspect', container])))
    hba_file = validate_database(json.loads(psql(container, DATABASE_FACTS_SQL)))
    directory = Path(tempfile.mkdtemp(prefix='worlex-linux-tls-', dir=runner_temp))
    ca_file, cert_file, key_file = generate_certificates(directory)
    hba_source = directory / 'pg_hba.conf'
    hba_source.write_text(HBA, encoding='ascii')
    destination = '/tmp/' + directory.name
    run(['exec', '--user', '0', container, 'install', '-d', '-m', '700',
         '-o', 'postgres', '-g', 'postgres', destination])
    for source, target in ((cert_file, destination + '/server.crt'),
                           (key_file, destination + '/server.key'), (hba_source, hba_file)):
        run(['cp', str(source), container + ':' + target])
        run(['exec', '--user', '0', container, 'chown', 'postgres:postgres', target])
        run(['exec', '--user', '0', container, 'chmod', '600', target])
    for setting, value in (('ssl_cert_file', destination + '/server.crt'),
                           ('ssl_key_file', destination + '/server.key'),
                           ('ssl_min_protocol_version', 'TLSv1.2'), ('ssl', 'on')):
        # Both names and values are fixed or generated internally, never SQL inputs.
        psql(container, "ALTER SYSTEM SET " + setting + " = '" + value + "'")
    require(psql(container, 'SELECT pg_reload_conf()') == 't', 'SERVICE_TLS_RELOAD_FAILED')
    deadline = time.monotonic() + 10
    while True:
        settings = json.loads(psql(container, "SELECT json_build_object('ssl', current_setting('ssl'),"
            "'cert', current_setting('ssl_cert_file'), 'key', current_setting('ssl_key_file'),"
            "'minimum', current_setting('ssl_min_protocol_version'))"))
        if settings == {'ssl': 'on', 'cert': destination + '/server.crt',
                        'key': destination + '/server.key', 'minimum': 'TLSv1.2'}:
            break
        require(time.monotonic() < deadline, 'SERVICE_TLS_RELOAD_NOT_APPLIED')
        time.sleep(0.2)
    # hostssl rules are reported as errors while SSL is disabled. Keep this
    # guard after the reload is confirmed, before any client proof or marker.
    require(psql(container, 'SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL') == '0',
            'SYNTHETIC_TLS_HBA_INVALID')
    prove_tls(port, ca_file)
    # Recheck emptiness immediately before writing the only database marker.
    validate_database(json.loads(psql(container, DATABASE_FACTS_SQL)))
    psql(container, "COMMENT ON DATABASE dkss_restore_ci IS '" + MARKER + "'")
    require(psql(container, "SELECT shobj_description(oid,'pg_database') FROM pg_database "
                 "WHERE datname=current_database()") == MARKER, 'SERVICE_MARKER_NOT_VERIFIED')
    with github_env.open('a', encoding='utf-8') as handle:
        handle.write('WORLEX_TEST_CA_FILE=' + str(ca_file) + '\n')
    print('Verified pg8000 TLS is ready on the owned synthetic PostgreSQL 18 service.')


if __name__ == '__main__':
    try:
        require(len(sys.argv) == 1, 'THIS_CI_SETUP_ACCEPTS_NO_ARGUMENTS')
        configure(os.environ)
    except SetupError as error:
        raise SystemExit(str(error)) from None
    except Exception:
        # Exceptions may contain subprocess diagnostics or connection details.
        raise SystemExit('LINUX_CI_TLS_SETUP_FAILED') from None
