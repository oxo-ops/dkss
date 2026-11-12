"""Loopback-only, synthetic SQLite fixture for Q04 browser acceptance.

This file never connects to a configured/production database. --preflight runs
one real HTTP login/CSRF/form smoke check without launching a browser.
"""
import argparse
import datetime
import hashlib
from html.parser import HTMLParser
from http.client import HTTPConnection
from http.cookies import SimpleCookie
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import smtplib
import socket
import sqlite3
import subprocess
import sys
import threading
from urllib.parse import urlencode
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--work-dir', required=True)
parser.add_argument('--source-root', default=str(Path(__file__).resolve().parents[1]))
parser.add_argument('--preflight', action='store_true')
args = parser.parse_args()
ROOT = Path(args.source_root).resolve()
RUN = Path(args.work_dir).resolve()
assert RUN != ROOT and not RUN.is_relative_to(ROOT / '.git')
assert not RUN.exists(), 'Refusing to reuse an existing fixture directory/database'
RUN.mkdir(parents=True)
DBPATH = RUN / 'synthetic.sqlite3'
assert not DBPATH.exists()
allowed_env = {'PATH', 'LANG', 'HOME', 'PYTHONDONTWRITEBYTECODE',
               'PYTHONNOUSERSITE', 'LC_CTYPE'}
assert set(os.environ) <= allowed_env, 'Run fixture with an empty inherited environment'
os.environ.clear()
os.environ.update({
    'PATH': '/usr/bin:/bin', 'HOME': str(RUN), 'LANG': 'C.UTF-8',
    'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1',
    'AWS_EC2_METADATA_DISABLED': 'true', 'DOCUMENT_IMPORT_WORKER_ENABLED': '0',
    'MFA_ENABLED': 'false', 'RENDER': '', 'RATELIMIT_STORAGE_URI': 'memory://',
})
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
allowed_port = None
allowed_thread = None
safety_events = []
mutations = []
phase = 'import'


def deny(label):
    def blocked(*_args, **_kwargs):
        safety_events.append(label)
        raise RuntimeError('Q04_SAFETY_BLOCK: ' + label)
    return blocked


subprocess.Popen = deny('subprocess')
os.system = deny('os.system')
for name in ('fork', 'forkpty', 'posix_spawn', 'posix_spawnp'):
    if hasattr(os, name):
        setattr(os, name, deny('os.' + name))
urllib.request.urlopen = deny('urllib.urlopen')
urllib.request.OpenerDirector.open = deny('urllib.opener.open')
smtplib.SMTP = deny('SMTP')
smtplib.SMTP_SSL = deny('SMTP_SSL')
original_start = threading.Thread.start


def start_thread(thread, *a, **kw):
    target = getattr(thread, 'function', None)
    limiter_timer = (isinstance(thread, threading.Timer)
        and getattr(target, '__module__', '') == 'limits.storage.memory'
        and getattr(target, '__qualname__', '') == 'MemoryStorage.__expire_events')
    if thread is not allowed_thread and not limiter_timer:
        return deny('background_thread')()
    return original_start(thread, *a, **kw)


threading.Thread.start = start_thread
original_getaddrinfo = socket.getaddrinfo


def getaddrinfo(host, port, *a, **kw):
    if host != '127.0.0.1':
        return deny('external_DNS')()
    return original_getaddrinfo(host, port, *a, **kw)


socket.getaddrinfo = getaddrinfo
# This fixture is IPv4-only. Prevent urllib3's import-time ::1 capability bind
# rather than allowing an additional listener or weakening the socket guard.
socket.has_ipv6 = False


def within_run(value):
    return Path(os.fsdecode(value)).resolve().is_relative_to(RUN)


def audit(event, values):
    if event == 'socket.connect':
        address = values[1]
        if not isinstance(address, tuple) or address[:2] != ('127.0.0.1', allowed_port):
            deny('external_socket_connect')()
    elif event == 'socket.bind':
        address = values[1]
        if not isinstance(address, tuple) or address[:2] != ('127.0.0.1', 0):
            deny('nonfixture_socket_bind')()
    elif event == 'socket.getaddrinfo' and values[0] != '127.0.0.1':
        deny('external_DNS_audit')()
    elif event == 'sqlite3.connect' and Path(str(values[0])).resolve() != DBPATH:
        deny('nonfixture_SQLite')()
    elif event in ('subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn', 'os.fork'):
        deny(event)()
    elif event == 'open' and isinstance(values[0], (str, bytes, os.PathLike)):
        path = Path(os.fsdecode(values[0])).resolve()
        if any(part in ('.aws', '.codex', '.env') for part in path.parts):
            deny('credential_file_read')()
        mode, flags = values[1], values[2]
        writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
            isinstance(flags, int) and flags & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if writing and not path.is_relative_to(RUN):
            deny('write_outside_fixture')()
    elif event in ('os.mkdir', 'os.remove', 'os.rmdir'):
        if not within_run(values[0]):
            deny('filesystem_change_outside_fixture')()
    elif event == 'os.rename':
        if not within_run(values[0]) or not within_run(values[1]):
            deny('rename_outside_fixture')()


sys.addaudithook(audit)
import boto3
import botocore.session
import pywebpush
from sqlalchemy import event
from sqlalchemy.engine import Engine

boto3.client = deny('boto3.client')
boto3.resource = deny('boto3.resource')
boto3.Session = deny('boto3.Session')
botocore.session.Session.create_client = deny('botocore.create_client')
pywebpush.webpush = deny('webpush')


@event.listens_for(Engine, 'do_connect')
def guard_database(dialect, _record, cargs, _cparams):
    if dialect.name != 'sqlite' or not cargs or Path(str(cargs[0])).resolve() != DBPATH:
        deny('nonfixture_SQLAlchemy')()


@event.listens_for(Engine, 'before_cursor_execute')
def log_sql(_conn, _cursor, statement, _parameters, _context, _many):
    operation = statement.lstrip().split(None, 1)[0].upper() if statement.strip() else ''
    if operation in ('ATTACH', 'DETACH'):
        deny('SQLite_attach')()
    if operation in ('INSERT', 'UPDATE', 'DELETE'):
        mutations.append({'phase': phase, 'sql': statement})


from flask import jsonify, request
from dkss_app import create_app, models as m
from dkss_app.extensions import db
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server, WSGIRequestHandler

app = create_app({
    'SECRET_KEY': 'q04-browser-synthetic-only-not-a-real-secret',
    'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(DBPATH),
    'TESTING': True, 'WTF_CSRF_ENABLED': True, 'MFA_ENABLED': False,
    'RATELIMIT_ENABLED': False, 'RATELIMIT_STORAGE_URI': 'memory://',
    'UPLOAD_FOLDER': str(RUN / 'uploads'),
})
phase = 'initial_fixture_only'
with app.app_context():
    db.create_all()
    for company in ('Q04-OWN', 'Q04-FOREIGN'):
        db.session.add(m.Company(company_code=company, company_name='Synthetic ' + company,
                                 vehicle_limit=20, active=True))
        db.session.add(m.User(company_code=company, username='synthetic-admin', role='admin',
            last_name='Synthetic', first_name='Admin', office='',
            password=generate_password_hash('Synthetic-only-pass-918!'),
            password_changed_at=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        for suffix in ('A', 'B'):
            db.session.add(m.Office(company_code=company, name='Synthetic Office ' + suffix))
            db.session.add(m.VehicleType(company_code=company, name='Synthetic Type ' + suffix))
        if company == 'Q04-FOREIGN':
            db.session.add(m.Office(company_code=company, name='Foreign Office Only'))
            db.session.add(m.VehicleType(company_code=company, name='Foreign Type Only'))
        db.session.add(m.Vehicle(company_code=company,
            chassis_number=company + '-NO-REAL-VEHICLE', plate_area='架空', plate_class='100',
            plate_kana='あ', plate_number='00-01', model_code='', engine_code='',
            first_registration_date='', manufacturer='Synthetic Maker', body_type='',
            gross_vehicle_weight=1000, max_payload=100, type='Synthetic Type A',
            office='Synthetic Office A', inspection_expiry=''))
    db.session.commit()
    own_id = m.Vehicle.query.filter_by(company_code='Q04-OWN').one().id
    foreign_id = m.Vehicle.query.filter_by(company_code='Q04-FOREIGN').one().id
    db.session.add(m.VehicleMaintenanceRecord(company_code='Q04-FOREIGN',
        vehicle_record_id=foreign_id, entry_date='2026-01-01',
        content='Synthetic history sentinel',
        invoice_details_json='{"schema_version":1,"sentinel":"unchanged-foreign-history"}'))
    db.session.commit()


def safe_value(key, value):
    if any(part in key for part in ('password', 'code_hash', 'pending_email',
                                    'mfa_', 'email_change_code')):
        return '[omitted synthetic authentication field]'
    if isinstance(value, bytes):
        return {'length': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


def snapshot():
    with app.app_context():
        db.session.remove()
        return {table.name: [{k: safe_value(k, v) for k, v in row.items()}
            for row in db.session.execute(table.select().order_by(*table.primary_key.columns)).mappings()]
            for table in db.metadata.sorted_tables}


@app.before_request
def fixture_request_guard():
    global phase
    phase = request.method + ' ' + request.path
    if request.path == '/master/vehicles/certificate/extract':
        deny('real_certificate_extraction')()


@app.route('/__fixture/snapshot')
def fixture_snapshot():
    return jsonify(snapshot())


@app.route('/__fixture/safety')
def fixture_safety():
    return jsonify(events=safety_events, sql=mutations)


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *_args, **_kwargs):
        pass


class Form(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.values, self.select = {}, None
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        a = dict(attributes)
        if tag == 'input' and a.get('name') and a.get('type') not in ('submit', 'file'):
            self.values[a['name']] = a.get('value', '')
        elif tag == 'select':
            self.select = a.get('name')
        elif tag == 'option' and self.select and 'selected' in a:
            self.values[self.select] = a.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'select':
            self.select = None


def preflight():
    cookies = SimpleCookie()
    steps = []

    def http(method, target, form=None):
        body = urlencode(form) if form is not None else None
        headers = {'Accept': 'application/json'}
        if form is not None:
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        if cookies:
            headers['Cookie'] = '; '.join(k + '=' + v.value for k, v in cookies.items())
        connection = HTTPConnection('127.0.0.1', allowed_port, timeout=10)
        connection.request(method, target, body, headers)
        response = connection.getresponse()
        text = response.read().decode('utf-8')
        for name, value in response.getheaders():
            if name.lower() == 'set-cookie':
                cookies.load(value)
        steps.append({'method': method, 'path': target, 'status': response.status})
        connection.close()
        return response.status, text

    status, html = http('GET', '/login')
    assert status == 200
    login = Form(html).values
    assert login.get('csrf_token')
    login.update(company_code='Q04-OWN', username='synthetic-admin',
                 password='Synthetic-only-pass-918!')
    assert http('POST', '/login', login)[0] == 302
    target = f'/master/vehicles/{own_id}/edit'
    status, html = http('GET', target)
    assert status == 200 and 'Foreign Office Only' not in html and 'Foreign Type Only' not in html
    form = Form(html).values
    assert form.get('csrf_token') and form.get('vehicle_master_selection')
    assert form['office'] == 'Synthetic Office A' and form['type'] == 'Synthetic Type A'
    before = snapshot()
    missing_csrf = dict(form)
    missing_csrf.pop('csrf_token')
    assert http('POST', target, missing_csrf)[0] == 400
    status, confirmation = http('POST', target, form)
    assert status == 200 and '車両の変更内容確認' in confirmation
    assert Form(confirmation).values.get('vehicle_master_selection')
    assert before == snapshot(), 'Preflight confirm/rejected CSRF changed the database'
    result = {'status': 'failed' if safety_events else 'passed', 'transport': 'real loopback TCP, no browser',
        'database': 'new synthetic SQLite only', 'csrf_missing_status': 400,
        'confirm_status': 200, 'database_unchanged': True, 'safety_events': safety_events,
        'steps': steps}
    (RUN / 'preflight.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('Q04_HTTP_PREFLIGHT ' + json.dumps(result), flush=True)
    assert not safety_events, safety_events


server = make_server('127.0.0.1', 0, app, threaded=False, request_handler=QuietHandler)
allowed_port = server.server_port
manifest = {'port': allowed_port, 'base': f'http://127.0.0.1:{allowed_port}',
    'run': str(RUN), 'own_id': own_id, 'foreign_id': foreign_id,
    'csrf_enabled': True, 'database': 'new synthetic SQLite only',
    'requirements': {line.split('==')[0]: importlib.metadata.version(line.split('==')[0])
                     for line in (ROOT / 'requirements.txt').read_text().splitlines() if '==' in line}}
(RUN / 'initial-snapshot.json').write_text(json.dumps(snapshot(), indent=2, ensure_ascii=False), encoding='utf-8')
(RUN / 'ready.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print('BROWSER_READY ' + json.dumps(manifest), flush=True)


def terminate(_signum, _frame):
    raise SystemExit(0)


signal.signal(signal.SIGTERM, terminate)
try:
    if args.preflight:
        allowed_thread = threading.Thread(target=server.serve_forever,
                                          name='q04-preflight-loopback', daemon=True)
        allowed_thread.start()
        try:
            preflight()
        finally:
            server.shutdown()
            allowed_thread.join(5)
    else:
        server.serve_forever()
finally:
    server.server_close()
    (RUN / 'safety-sql.json').write_text(json.dumps({'events': safety_events, 'sql': mutations}, indent=2), encoding='utf-8')
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
