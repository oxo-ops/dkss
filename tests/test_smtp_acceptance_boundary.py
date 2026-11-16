"""Exact production-function isolation; no app import, network, credentials or email."""
import ast
import os
import smtplib
import ssl
import unittest
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]

def functions(path, names, ns):
    tree = ast.parse((SOURCE / 'dkss_app' / path).read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in nodes} == set(names)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, 'exec'), ns)
    return SimpleNamespace(**{n: ns[n] for n in names})

class Acceptance(unittest.TestCase):
    def probe(self, kind, scenario, opt_in=True, sender='sender@example.invalid'):
        calls, logs = [], []
        messages = []
        self.messages = messages
        class SMTP(smtplib.SMTP):
            def __init__(self, host, port, timeout):
                calls.append('connect')
                assert host == 'smtp.example.invalid' and port == 587 and timeout == 20
                if scenario == 'connect': raise TimeoutError('synthetic')
            def starttls(self, *, context):
                calls.append('tls')
                assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
                if scenario == 'tls': raise ssl.SSLCertVerificationError('synthetic')
            def login(self, username, password):
                calls.append('login')
                if scenario == 'login': raise smtplib.SMTPAuthenticationError(535, b'synthetic')
            def send_message(self, message):
                calls.append('send')
                messages.append(message)
                if scenario == 'data_timeout': raise TimeoutError('synthetic uncertain DATA')
                if scenario == 'refused': raise smtplib.SMTPRecipientsRefused({'recipient@example.invalid': (550, b'synthetic')})
                return {'recipient@example.invalid': (550, b'synthetic')} if scenario == 'refusal_return' else {}
            def docmd(self, command, args=''):
                assert command == 'QUIT'
                calls.append('quit')
                if scenario == 'quit_timeout': raise TimeoutError('synthetic')
                if scenario == 'quit_bad_status': return 500, b'synthetic'
                if scenario == 'quit_disconnect': raise smtplib.SMTPServerDisconnected('synthetic')
                return 221, b'bye'
            def close(self): calls.append('closed')
        ns = dict(ssl=ssl, _dkss_common=SimpleNamespace(os=os, smtplib=SimpleNamespace(SMTP=SMTP), EmailMessage=EmailMessage, parseaddr=parseaddr), _dkss_runtime=SimpleNamespace(app=SimpleNamespace(logger=None)), log_email_delivery_failure=lambda logger, **kw: logs.append(kw['stage']))
        auth = functions('auth.py', ['is_valid_email_address','set_email_origin_headers','send_email_change_code_email','send_mfa_code_email'], ns)
        delivery = functions('notifications_delivery.py', ['send_email_notification'], dict(ns, _dkss_auth=auth, build_absolute_app_url=lambda link: ''))
        ns['_dkss_notifications_delivery'] = delivery
        user = SimpleNamespace(email_address='recipient@example.invalid', email_notify_enabled=opt_in)
        with patch.dict(os.environ, {'SMTP_HOST':'smtp.example.invalid','SMTP_PORT':'587','SMTP_USERNAME':'synthetic','SMTP_PASSWORD':'synthetic','SMTP_FROM':sender}, clear=True), patch('socket.create_connection', side_effect=AssertionError('network forbidden')):
            if kind == 'change': result = auth.send_email_change_code_email(user.email_address, '000000')
            elif kind == 'mfa': result = auth.send_mfa_code_email(user, '000000')
            else: result = delivery.send_email_notification(user, 'notice', 'synthetic')
        self.assertLessEqual(calls.count('send'), 1)
        return result, calls, logs

    def test_transaction_boundaries(self):
        for kind in ('notification','mfa','change'):
            for scenario in ('ok','quit_timeout','quit_bad_status','quit_disconnect','connect','tls','login','data_timeout','refused','refusal_return'):
                with self.subTest(kind=kind, scenario=scenario):
                    result, calls, logs = self.probe(kind, scenario)
                    self.assertEqual(result, scenario in ('ok','quit_timeout','quit_bad_status','quit_disconnect'))
                    if scenario in ('connect','tls','login'): self.assertNotIn('send', calls)
                    if scenario.startswith('quit_') or scenario in ('data_timeout','refused','refusal_return'): self.assertIn('closed', calls)

    def test_invalid_origin_domain_never_opens_transport(self):
        for kind in ('notification', 'mfa', 'change'):
            result, calls, logs = self.probe(kind, 'ok', sender='sender@example..invalid')
            self.assertFalse(result)
            self.assertEqual(calls, [])
            self.assertEqual(logs, [])

    def test_header_domain_normalization_and_safe_rejection(self):
        auth = functions('auth.py', ['set_email_origin_headers'], {})
        for sender, domain in (
            ('sender@EXAMPLE.invalid  ', 'example.invalid'),
            ('sender@例え.invalid', 'xn--r8jz45g.invalid'),
        ):
            with self.subTest(sender=sender):
                message = EmailMessage()
                self.assertTrue(auth.set_email_origin_headers(message, sender))
                self.assertTrue(str(message['Message-ID']).endswith('@' + domain + '>'))
                self.assertFalse(message['Message-ID'].defects)
        for sender in ('sender@example..invalid', 'sender@-bad.invalid',
                       'sender@bad_.invalid', 'sender@example.invalid\r\nX-Test: yes',
                       'sender@' + 'x' * 64 + '.invalid', 'missing-at'):
            with self.subTest(sender=sender):
                message = EmailMessage()
                self.assertFalse(auth.set_email_origin_headers(message, sender))
                self.assertNotIn('Date', message)
                self.assertNotIn('Message-ID', message)

    def test_origin_headers_for_all_mail_purposes(self):
        identifiers = set()
        for kind in ('notification', 'mfa', 'change'):
            for _ in range(2):
                with self.subTest(kind=kind):
                    self.assertTrue(self.probe(kind, 'ok')[0])
                    message, = self.messages
                    self.assertEqual(len(message.get_all('Date')), 1)
                    self.assertEqual(len(message.get_all('Message-ID')), 1)
                    date = parsedate_to_datetime(str(message['Date']))
                    self.assertIsNotNone(date.tzinfo)
                    identifier = str(message['Message-ID'])
                    self.assertRegex(identifier, r'^<[0-9a-f]{32}@example\.invalid>$')
                    self.assertNotIn(identifier, identifiers)
                    identifiers.add(identifier)
                    self.assertEqual(str(message['To']), 'recipient@example.invalid')
                    self.assertEqual(str(message['From']), 'sender@example.invalid')
                    self.assertNotIn('recipient', identifier)
                    self.assertNotIn('synthetic', identifier)
                    # Serialization must retain both headers without defects.
                    from email import policy
                    from email.parser import BytesParser
                    parsed = BytesParser(policy=policy.default).parsebytes(message.as_bytes())
                    self.assertEqual(str(parsed['Message-ID']), identifier)
                    self.assertFalse(parsed['Message-ID'].defects)
                    self.assertFalse(parsed['Date'].defects)

    def test_opt_in_preserved(self):
        result, calls, _ = self.probe('notification', 'ok', opt_in=False)
        self.assertFalse(result); self.assertEqual(calls, [])
        result, calls, _ = self.probe('mfa', 'ok', opt_in=False)
        self.assertTrue(result); self.assertEqual(calls.count('send'), 1)

if __name__ == '__main__': unittest.main(verbosity=2)
