"""Synthetic delivery contracts: real functions, mocked transport and no database."""
import io
import json
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, call, patch

from pywebpush import WebPushException
from dkss_app import auth, notifications_delivery as delivery

CANARY = 'SYNTHETIC_PRIVATE_CANARY'


class Capture(logging.StreamHandler):
    def __init__(self):
        self.output = io.StringIO()
        super().__init__(self.output)
        self.records = []

    def emit(self, record):
        self.records.append(record)
        super().emit(record)


class NotificationDeliveryLoggingTests(unittest.TestCase):
    def setUp(self):
        self.capture = Capture()
        self.logger = logging.Logger('synthetic-delivery', logging.DEBUG)
        self.logger.addHandler(self.capture)
        self.smtp = MagicMock()
        self.server = self.smtp.return_value.__enter__.return_value
        self.webpush = Mock()
        self.db = MagicMock()
        self.models = SimpleNamespace(PushSubscription=MagicMock(), Notification=MagicMock())
        self.subscription = SimpleNamespace(endpoint='https://push.example.invalid/'+CANARY,
            auth=CANARY+'-auth', p256dh=CANARY+'-key')
        self.models.PushSubscription.query.filter_by.return_value.all.return_value = [self.subscription]
        self.models.Notification.query.filter.return_value.count.return_value = 3
        self.env = {'SMTP_HOST':'smtp.example.invalid', 'SMTP_PORT':'587',
                    'SMTP_USERNAME':'sender@example.invalid', 'SMTP_PASSWORD':CANARY,
                    'SMTP_FROM':'sender@example.invalid'}
        self.common = SimpleNamespace(os=SimpleNamespace(environ=self.env), json=json,
            smtplib=SimpleNamespace(SMTP=self.smtp), EmailMessage=EmailMessage,
            parseaddr=parseaddr, db=self.db, webpush=self.webpush, WebPushException=WebPushException)
        self.app = SimpleNamespace(logger=self.logger, config={
            'VAPID_PRIVATE_KEY':CANARY, 'VAPID_PUBLIC_KEY':'synthetic-public',
            'VAPID_SUBJECT':'mailto:sender@example.invalid'})
        self.user = SimpleNamespace(email_notify_enabled=True,
            email_address='recipient@example.invalid', company_code='SYNTHETIC',
            account_identity='synthetic-identity')
        for module in (delivery, auth):
            self.enterContext(patch.object(module, '_dkss_common', self.common))
            self.enterContext(patch.object(module, '_dkss_runtime', SimpleNamespace(app=self.app)))
        self.enterContext(patch.object(delivery, '_dkss_models', self.models))
        self.url = self.enterContext(patch.object(delivery, 'build_absolute_app_url', return_value='https://app.example.invalid/notifications'))

    def assert_log(self, expected, level=logging.ERROR):
        self.assertEqual(len(self.capture.records), 1)
        record = self.capture.records[0]
        self.assertEqual(record.getMessage(), expected)
        self.assertEqual(record.levelno, level)
        self.assertIsNone(record.exc_info)
        self.assertIsNone(record.stack_info)
        self.assertNotIn(CANARY, repr(record.__dict__))
        self.assertNotIn('recipient@example.invalid', self.capture.output.getvalue())
        self.assertNotIn('Traceback', self.capture.output.getvalue())

    def email(self):
        return delivery.send_email_notification(self.user, 'Synthetic title', CANARY, '/notifications')

    def assert_verified_tls(self):
        self.server.starttls.assert_called_once()
        context = self.server.starttls.call_args.kwargs['context']
        self.assertIsInstance(context, ssl.SSLContext)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_certificate_verification_failure_stops_all_mail_paths_before_auth(self):
        paths = [self.email,
                 lambda: auth.send_mfa_code_email(self.user, '123456'),
                 lambda: auth.send_email_change_code_email('new@example.invalid', '456789')]
        for send in paths:
            with self.subTest(send=send):
                self.smtp.reset_mock()
                self.capture.records.clear()
                self.server.starttls.side_effect = ssl.SSLCertVerificationError(CANARY)
                self.assertFalse(send())
                self.assert_verified_tls()
                self.server.login.assert_not_called()
                self.server.send_message.assert_not_called()
                self.smtp.assert_called_once()
                self.assertNotIn(CANARY, self.capture.output.getvalue())
                self.assertEqual(len(self.capture.records), 1)
                self.assertIn('stage=starttls error_type=tls', self.capture.records[0].getMessage())

    def test_smtp_authentication_error_logs_no_credentials_or_response(self):
        self.server.login.side_effect = smtplib.SMTPAuthenticationError(535, CANARY.encode())
        self.assertFalse(self.email())
        self.assert_log('EMAIL_DELIVERY_FAILED purpose=notification stage=authenticate error_type=authentication')
        self.smtp.assert_called_once_with('smtp.example.invalid', 587, timeout=20)
        self.assert_verified_tls()
        self.server.login.assert_called_once_with('sender@example.invalid', CANARY)
        self.server.send_message.assert_not_called()

    def test_smtp_recipient_refusal_logs_no_recipient_or_message(self):
        self.server.send_message.side_effect = smtplib.SMTPRecipientsRefused({'recipient@example.invalid': (550, CANARY)})
        self.assertFalse(self.email())
        self.assert_log('EMAIL_DELIVERY_FAILED purpose=notification stage=send error_type=recipient_refused')
        self.server.send_message.assert_called_once()

    def test_smtp_connection_failure_logs_no_host_or_exception(self):
        self.smtp.side_effect = OSError(CANARY)
        self.assertFalse(self.email())
        self.assert_log('EMAIL_DELIVERY_FAILED purpose=notification stage=connect error_type=connection')
        self.smtp.assert_called_once()

    def test_smtp_tls_failure_does_not_send_or_downgrade(self):
        self.server.starttls.side_effect = ssl.SSLError(CANARY)
        self.assertFalse(self.email())
        self.assert_log('EMAIL_DELIVERY_FAILED purpose=notification stage=starttls error_type=tls')
        self.server.login.assert_not_called()
        self.server.send_message.assert_not_called()
        self.smtp.assert_called_once()

    def test_smtp_close_failure_remains_false_without_retry(self):
        self.smtp.return_value.__exit__.side_effect = smtplib.SMTPServerDisconnected(CANARY)
        self.assertFalse(self.email())
        self.assert_log('EMAIL_DELIVERY_FAILED purpose=notification stage=close error_type=connection')
        self.server.send_message.assert_called_once()
        self.smtp.assert_called_once()

    def test_arbitrary_error_class_name_and_string_are_not_logged(self):
        error_type = type(CANARY, (Exception,), {})
        self.server.send_message.side_effect = error_type(CANARY)
        self.assertFalse(self.email())
        self.assert_log('EMAIL_DELIVERY_FAILED purpose=notification stage=send error_type=unexpected')

    def test_email_success_preserves_tls_login_body_and_one_send(self):
        self.assertTrue(self.email())
        self.assertEqual(self.server.method_calls, [call.starttls(context=self.server.starttls.call_args.kwargs["context"]), call.login('sender@example.invalid', CANARY), call.send_message(self.server.send_message.call_args.args[0])])
        self.assert_verified_tls()
        email = self.server.send_message.call_args.args[0]
        self.assertEqual(email['To'], 'recipient@example.invalid')
        self.assertEqual(email['Subject'], 'Synthetic title')
        self.assertIn(CANARY, email.get_content())
        self.assertIn('https://app.example.invalid/notifications', email.get_content())
        self.assertEqual(self.capture.records, [])

    def test_email_no_username_preserves_no_authentication_behavior(self):
        self.env['SMTP_USERNAME'] = ''
        self.assertTrue(self.email())
        self.server.starttls.assert_called_once()
        self.server.login.assert_not_called()
        self.server.send_message.assert_called_once()
        self.assertEqual(self.capture.records, [])

    def test_email_invalid_inputs_and_opt_out_remain_noops(self):
        cases = [(None, 't', 'm'), (self.user, '', 'm'),
                 (self.user, 'bad\nsubject', 'm'), (self.user, 't', 'x'*10001)]
        for user, title, message in cases:
            with self.subTest(title=title):
                self.assertFalse(delivery.send_email_notification(user, title, message))
        self.user.email_notify_enabled = False
        self.assertFalse(self.email())
        self.smtp.assert_not_called()
        self.assertEqual(self.capture.records, [])

    def test_mfa_still_bypasses_notification_opt_out(self):
        self.user.email_notify_enabled = False
        self.assertTrue(auth.send_mfa_code_email(self.user, '123456'))
        self.assertEqual(self.server.send_message.call_args.args[0]['Subject'], 'ログイン認証コード')
        self.assertIn('123456', self.server.send_message.call_args.args[0].get_content())
        self.assertEqual(self.capture.records, [])

    def test_mfa_send_failure_logs_neither_code_nor_exception(self):
        self.server.send_message.side_effect = smtplib.SMTPDataError(554, (CANARY+' 123456').encode())
        self.assertFalse(auth.send_mfa_code_email(self.user, '123456'))
        self.assert_log('EMAIL_DELIVERY_FAILED purpose=notification stage=send error_type=data_rejected')
        self.assertNotIn('123456', self.capture.output.getvalue())

    def test_email_change_failure_logs_no_code_or_new_address(self):
        self.server.send_message.side_effect = smtplib.SMTPDataError(554, (CANARY+' 456789').encode())
        self.assertFalse(auth.send_email_change_code_email('new@example.invalid', '456789'))
        self.assert_log('EMAIL_DELIVERY_FAILED purpose=email_change stage=send error_type=data_rejected')
        self.assertNotIn('456789', self.capture.output.getvalue())
        self.assertNotIn('new@example.invalid', self.capture.output.getvalue())

    def test_email_change_success_preserves_message_and_tls(self):
        self.assertTrue(auth.send_email_change_code_email('new@example.invalid', '456789'))
        self.assert_verified_tls()
        email = self.server.send_message.call_args.args[0]
        self.assertEqual(email['To'], 'new@example.invalid')
        self.assertIn('456789', email.get_content())
        self.server.starttls.assert_called_once()
        self.server.login.assert_called_once()
        self.server.send_message.assert_called_once()
        self.assertEqual(self.capture.records, [])

    def test_email_change_invalid_address_still_noop(self):
        self.assertFalse(auth.send_email_change_code_email('bad\naddress', '456789'))
        self.smtp.assert_not_called()
        self.assertEqual(self.capture.records, [])

    def test_push_failure_keeps_active_subscription_and_no_payload_in_logs(self):
        self.webpush.side_effect = WebPushException(CANARY, response=SimpleNamespace(status_code=503, text=CANARY))
        self.assertFalse(delivery.send_web_push_notification(self.user, CANARY, CANARY))
        self.assert_log('WEB_PUSH_SEND_FAILED error_type=provider', logging.WARNING)
        self.db.session.delete.assert_not_called()
        self.db.session.commit.assert_not_called()
        self.webpush.assert_called_once()

    def test_push_404_and_410_still_delete_only_the_failed_subscription(self):
        for status in (404, 410):
            with self.subTest(status=status):
                self.capture.records.clear()
                self.db.reset_mock()
                self.webpush.reset_mock()
                self.webpush.side_effect = WebPushException(CANARY, response=SimpleNamespace(status_code=status, text=CANARY))
                self.assertFalse(delivery.send_web_push_notification(self.user, CANARY, CANARY))
                self.assert_log('WEB_PUSH_SEND_FAILED error_type=provider', logging.WARNING)
                self.db.session.delete.assert_called_once_with(self.subscription)
                self.db.session.commit.assert_called_once_with()
                self.webpush.assert_called_once()

    def test_unexpected_push_failure_logs_no_traceback_and_continues(self):
        other = SimpleNamespace(endpoint='https://push.example.invalid/second', auth='synthetic', p256dh='synthetic')
        self.models.PushSubscription.query.filter_by.return_value.all.return_value.append(other)
        self.webpush.side_effect = [RuntimeError(CANARY), None]
        self.assertTrue(delivery.send_web_push_notification(self.user, 't', 'm'))
        self.assert_log('WEB_PUSH_SEND_FAILED error_type=unexpected')
        self.assertEqual(self.webpush.call_count, 2)
        self.db.session.delete.assert_not_called()
        self.db.session.commit.assert_not_called()

    def test_push_success_preserves_owner_filter_payload_keys_and_timeouts(self):
        self.assertTrue(delivery.send_web_push_notification(self.user, 't', 'm', '/notifications'))
        self.models.PushSubscription.query.filter_by.assert_called_once_with(company_code='SYNTHETIC', owner_identity='synthetic-identity')
        kwargs = self.webpush.call_args.kwargs
        self.assertEqual(kwargs['subscription_info'], {'endpoint':self.subscription.endpoint,
            'keys':{'p256dh':self.subscription.p256dh, 'auth':self.subscription.auth}})
        self.assertEqual(kwargs['vapid_private_key'], CANARY)
        self.assertEqual((kwargs['ttl'], kwargs['timeout']), (300, 20))
        self.assertEqual(json.loads(kwargs['data'])['unread_count'], 3)
        self.assertEqual(self.capture.records, [])

    def test_push_without_user_identity_subscription_or_configuration_stays_noop(self):
        self.assertFalse(delivery.send_web_push_notification(None, 't', 'm'))
        self.user.account_identity = ''
        self.assertFalse(delivery.send_web_push_notification(self.user, 't', 'm'))
        self.user.account_identity = 'synthetic-identity'
        self.models.PushSubscription.query.filter_by.return_value.all.return_value = []
        self.assertFalse(delivery.send_web_push_notification(self.user, 't', 'm'))
        self.app.config['VAPID_PRIVATE_KEY'] = ''
        with patch('sys.stdout', io.StringIO()):
            self.assertFalse(delivery.send_web_push_notification(self.user, 't', 'm'))
        self.webpush.assert_not_called()
        self.assertEqual(self.capture.records, [])

    def test_push_database_cleanup_error_still_propagates_without_retry(self):
        self.webpush.side_effect = WebPushException(CANARY, response=SimpleNamespace(status_code=410, text=CANARY))
        error = RuntimeError('synthetic cleanup error')
        self.db.session.commit.side_effect = error
        with self.assertRaises(RuntimeError) as raised:
            delivery.send_web_push_notification(self.user, 't', 'm')
        self.assertIs(raised.exception, error)
        self.webpush.assert_called_once()
        self.db.session.commit.assert_called_once()
        self.assert_log('WEB_PUSH_SEND_FAILED error_type=provider', logging.WARNING)


    def test_email_change_all_failure_stages_are_fixed_and_never_retried(self):
        targets = [('connect', self.smtp), ('starttls', self.server.starttls),
                   ('authenticate', self.server.login), ('send', self.server.send_message),
                   ('close', self.smtp.return_value.__exit__)]
        for stage, target in targets:
            with self.subTest(stage=stage):
                self.capture.records.clear()
                self.smtp.reset_mock()
                target.side_effect = RuntimeError(CANARY)
                self.assertFalse(auth.send_email_change_code_email('new@example.invalid', '456789'))
                self.assert_log(f'EMAIL_DELIVERY_FAILED purpose=email_change stage={stage} error_type=unexpected')
                self.smtp.assert_called_once()
                target.side_effect = None

    def test_known_smtp_failure_categories_are_allowlisted(self):
        from dkss_app.delivery_failure_logging import log_email_delivery_failure
        errors = [(smtplib.SMTPAuthenticationError(535, CANARY), 'authentication'),
                  (smtplib.SMTPRecipientsRefused({CANARY:(550,CANARY)}), 'recipient_refused'),
                  (smtplib.SMTPSenderRefused(550, CANARY, CANARY), 'sender_refused'),
                  (smtplib.SMTPDataError(554, CANARY), 'data_rejected'),
                  (ssl.SSLError(CANARY), 'tls'),
                  (smtplib.SMTPServerDisconnected(CANARY), 'connection'),
                  (smtplib.SMTPConnectError(421, CANARY), 'smtp'),
                  (smtplib.SMTPNotSupportedError(CANARY), 'smtp'),
                  (TimeoutError(CANARY), 'connection'), (ValueError(CANARY), 'unexpected')]
        for error, category in errors:
            with self.subTest(category=category):
                self.capture.records.clear()
                log_email_delivery_failure(self.logger, purpose='notification', stage='send', error=error)
                self.assert_log(f'EMAIL_DELIVERY_FAILED purpose=notification stage=send error_type={category}')

    def test_logger_rejects_unknown_metadata_and_string_subclasses(self):
        from dkss_app.delivery_failure_logging import log_email_delivery_failure
        class UntrustedString(str):
            def __eq__(self, other):
                return True
        for value in (CANARY, None, UntrustedString(CANARY)):
            self.capture.records.clear()
            log_email_delivery_failure(self.logger, purpose=value, stage=value, error=RuntimeError(CANARY))
            self.assert_log('EMAIL_DELIVERY_FAILED purpose=unknown stage=unknown error_type=unexpected')

    def test_exception_string_and_repr_are_not_evaluated(self):
        class UnprintableError(Exception):
            def __str__(self):
                raise AssertionError('exception string must not be evaluated')
            def __repr__(self):
                raise AssertionError('exception repr must not be evaluated')
        self.server.send_message.side_effect = UnprintableError()
        self.assertFalse(self.email())
        self.assert_log('EMAIL_DELIVERY_FAILED purpose=notification stage=send error_type=unexpected')
        self.capture.records.clear()
        self.webpush.side_effect = UnprintableError()
        self.assertFalse(delivery.send_web_push_notification(self.user, 't', 'm'))
        self.assert_log('WEB_PUSH_SEND_FAILED error_type=unexpected')

    def test_push_provider_response_body_is_never_evaluated_for_logging(self):
        class ProviderResponse:
            status_code = 429
            @property
            def text(self):
                raise AssertionError('provider response body must not be evaluated')
        self.webpush.side_effect = WebPushException(CANARY, response=ProviderResponse())
        self.assertFalse(delivery.send_web_push_notification(self.user, 't', 'm'))
        self.assert_log('WEB_PUSH_SEND_FAILED error_type=provider', logging.WARNING)
        self.db.session.delete.assert_not_called()
        self.db.session.commit.assert_not_called()


    def test_push_provider_failure_without_response_is_safe_and_keeps_subscription(self):
        self.webpush.side_effect = WebPushException(CANARY, response=None)
        self.assertFalse(delivery.send_web_push_notification(self.user, 't', 'm'))
        self.assert_log('WEB_PUSH_SEND_FAILED error_type=provider', logging.WARNING)
        self.db.session.delete.assert_not_called()
        self.db.session.commit.assert_not_called()
        self.webpush.assert_called_once()

    def test_push_provider_failure_does_not_block_later_subscription_success(self):
        other = SimpleNamespace(endpoint='https://push.example.invalid/second', auth='synthetic', p256dh='synthetic')
        self.models.PushSubscription.query.filter_by.return_value.all.return_value.append(other)
        self.webpush.side_effect = [WebPushException(CANARY, response=None), None]
        self.assertTrue(delivery.send_web_push_notification(self.user, 't', 'm'))
        self.assert_log('WEB_PUSH_SEND_FAILED error_type=provider', logging.WARNING)
        self.assertEqual(self.webpush.call_count, 2)
        self.assertEqual(self.webpush.call_args.kwargs['subscription_info']['endpoint'], other.endpoint)
        self.db.session.delete.assert_not_called()
        self.db.session.commit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
