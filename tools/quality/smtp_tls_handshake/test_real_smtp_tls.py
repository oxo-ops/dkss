"""Isolated exact-function contract probe, loopback only, synthetic mail only.
Not a full-app test or real-provider/inbox acceptance. No app/DB import.
"""
import ast, logging, os, smtplib, socket, ssl, subprocess, tempfile, threading, unittest
from pathlib import Path
from types import SimpleNamespace
from email.message import EmailMessage
from email.utils import parseaddr
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]

def load_functions(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in nodes} == set(names)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return SimpleNamespace(**{n: namespace[n] for n in names})

class SMTPFixture:
    def __init__(self, cert, key):
        self.commands, self.messages, self.errors = [], 0, []
        self.sock = socket.socket(); self.sock.settimeout(5)
        self.sock.bind(('127.0.0.1', 0)); self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(cert, key)
        self.thread = threading.Thread(target=self.run, daemon=True)
    def __enter__(self):
        self.thread.start(); return self
    def run(self):
        conn = None
        try:
            conn, _ = self.sock.accept(); conn.settimeout(5)
            conn.sendall(b'220 fixture ESMTP\r\n')
            stream = conn.makefile('rb')
            while True:
                line = stream.readline(16384)
                if not line: break
                verb = line.split(b' ', 1)[0].strip().upper()
                self.commands.append(verb)
                if verb == b'EHLO':
                    conn.sendall(b'250-fixture\r\n250-STARTTLS\r\n250 AUTH PLAIN\r\n')
                elif verb == b'STARTTLS':
                    conn.sendall(b'220 Ready\r\n'); stream.close()
                    conn = self.context.wrap_socket(conn, server_side=True)
                    stream = conn.makefile('rb')
                elif verb == b'AUTH': conn.sendall(b'235 OK\r\n')
                elif verb in (b'MAIL', b'RCPT'): conn.sendall(b'250 OK\r\n')
                elif verb == b'DATA':
                    conn.sendall(b'354 End with dot\r\n')
                    while True:
                        line = stream.readline(16384)
                        if not line: raise RuntimeError('incomplete synthetic data')
                        if line == b'.\r\n': break
                    self.messages += 1; conn.sendall(b'250 OK\r\n')
                elif verb == b'QUIT':
                    conn.sendall(b'221 Bye\r\n'); break
                else: raise RuntimeError('unexpected synthetic command')
        except ssl.SSLError:
            self.errors.append('tls_rejected')
        except Exception as e:
            self.errors.append(type(e).__name__)
        finally:
            if conn: conn.close()
            self.sock.close()
    def __exit__(self, *args):
        self.thread.join(7)
        assert not self.thread.is_alive(), 'fixture did not finish'

class RealTLSContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.base = Path(cls.temp.name)
        (cls.base/'empty').mkdir()
        for name, san in [('valid', 'IP:127.0.0.1'), ('wronghost', 'DNS:wrong.example.invalid')]:
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes',
                '-keyout', str(cls.base/(name+'.key')), '-out', str(cls.base/(name+'.crt')),
                '-days','1','-subj','/CN=synthetic-only', '-addext','subjectAltName='+san],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()
    def probe(self, purpose, scenario):
        certname = 'wronghost' if scenario == 'hostname_mismatch' else 'valid'
        trusted = 'wronghost' if scenario == 'untrusted' else certname
        failures = []
        common = SimpleNamespace(os=os, smtplib=smtplib, EmailMessage=EmailMessage, parseaddr=parseaddr)
        def log_failure(logger, *, purpose, stage, error):
            failures.append((stage, type(error).__name__, getattr(error, 'verify_code', None)))
        namespace = dict(ssl=ssl, _dkss_common=common,
            _dkss_runtime=SimpleNamespace(app=SimpleNamespace(logger=logging.getLogger('test'))),
            log_email_delivery_failure=log_failure)
        auth = load_functions('dkss_app/auth.py', ['is_valid_email_address','send_email_change_code_email','send_mfa_code_email'], namespace)
        delivery_namespace = dict(namespace, _dkss_auth=auth, build_absolute_app_url=lambda link: '')
        delivery = load_functions('dkss_app/notifications_delivery.py', ['send_email_notification'], delivery_namespace)
        namespace['_dkss_notifications_delivery'] = delivery
        user = SimpleNamespace(email_address='recipient@example.invalid', email_notify_enabled=True)
        original_connect = socket.socket.connect
        def guarded_connect(sock, address):
            if address != ('127.0.0.1', fixture.port): raise AssertionError('non-fixture connection forbidden')
            return original_connect(sock, address)
        with SMTPFixture(self.base/(certname+'.crt'), self.base/(certname+'.key')) as fixture:
            env = {'SMTP_HOST':'127.0.0.1','SMTP_PORT':str(fixture.port),
                'SMTP_USERNAME':'synthetic@example.invalid','SMTP_PASSWORD':'synthetic-not-a-credential',
                'SSL_CERT_FILE':str(self.base/(trusted+'.crt')), 'SSL_CERT_DIR':str(self.base/'empty')}
            def numeric_resolution(host, port, family=0, socktype=0, proto=0, flags=0):
                if host != '127.0.0.1' or port != fixture.port:
                    raise AssertionError('non-fixture resolution forbidden')
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', fixture.port))]
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(socket.socket, 'connect', guarded_connect), \
                    patch.object(socket, 'getfqdn', return_value='synthetic.invalid'), \
                    patch.object(socket, 'getaddrinfo', numeric_resolution), \
                    patch.object(socket, 'gethostbyaddr', side_effect=AssertionError('DNS forbidden')), \
                    patch.object(socket, 'gethostbyname', side_effect=AssertionError('DNS forbidden')):
                if purpose == 'notification': result = delivery.send_email_notification(user,'Synthetic','Synthetic')
                elif purpose == 'mfa': result = auth.send_mfa_code_email(user,'000000')
                else: result = auth.send_email_change_code_email('new@example.invalid','000000')
        if scenario == 'valid':
            self.assertTrue(result); self.assertEqual(failures, [])
            self.assertEqual(fixture.messages, 1); self.assertEqual(fixture.commands.count(b'AUTH'), 1)
            self.assertEqual(fixture.errors, [])
        else:
            self.assertFalse(result)
            self.assertEqual(failures, [('starttls','SSLCertVerificationError', 18 if scenario == 'untrusted' else 64)])
            self.assertEqual(fixture.messages, 0)
            for verb in (b'AUTH',b'MAIL',b'RCPT',b'DATA'): self.assertNotIn(verb,fixture.commands)
            self.assertEqual(fixture.errors, ['tls_rejected'])
        self.assertEqual(fixture.commands.count(b'STARTTLS'), 1)

for purpose in ('notification','mfa','email_change'):
    for scenario in ('valid','untrusted','hostname_mismatch'):
        setattr(RealTLSContract,'test_'+purpose+'_'+scenario,
                lambda self,p=purpose,s=scenario: self.probe(p,s))

if __name__ == '__main__': unittest.main(verbosity=2)
