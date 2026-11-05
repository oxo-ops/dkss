"""No-network tests for strict TLS and bounded pure-client connection options."""
import ssl
import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
import client_connection as client

class ConnectionTests(unittest.TestCase):
    def test_tls_context_requires_ca_and_hostname(self):
        context=client.tls_context()
        self.assertIsInstance(context,ssl.SSLContext)
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
        self.assertGreaterEqual(context.minimum_version,ssl.TLSVersion.TLSv1_2)
        self.assertGreater(context.cert_store_stats()['x509_ca'],0)
    def test_invalid_ca_does_not_fallback(self):
        with self.assertRaisesRegex(ValueError,'CA_FILE_MISSING'):client.tls_context('/no/such/ca-file')
    def test_read_only_is_connection_startup_setting(self):
        args=client.connection_args(read_only=True)
        self.assertEqual(args['startup_params']['default_transaction_read_only'],'on')
        self.assertEqual(args['startup_params']['search_path'],'pg_catalog,public')
        self.assertEqual(args['startup_params']['statement_timeout'],'120000')
        self.assertEqual(args['startup_params']['transaction_timeout'],'300000')
        self.assertEqual(args['timeout'],130)
        self.assertNotIn('sslmode',args)
    def test_execute_has_no_readonly_override_or_plaintext_flag(self):
        args=client.connection_args()
        self.assertNotIn('default_transaction_read_only',args['startup_params'])
        self.assertIsInstance(args['ssl_context'],ssl.SSLContext)
        self.assertNotIn('options',args)
        sock=MagicMock(spec=ssl.SSLSocket);sock.context=args['ssl_context'];sock.server_hostname='synthetic.invalid'
        sock.getpeercert.return_value={'synthetic':True};sock.version.return_value='TLSv1.3'
        raw=type('Connection',(),{'__module__':'pg8000.legacy'})();raw._usock=sock
        connection=SimpleNamespace(dialect=SimpleNamespace(driver='pg8000'),connection=SimpleNamespace(driver_connection=raw))
        self.assertTrue(client.verify_tls_connection(connection,'synthetic.invalid')['hostname_verified'])
        for host in ('wrong.invalid',''):
            with self.subTest(host=host),self.assertRaisesRegex(ValueError,'ACTUAL_TLS_NOT_VERIFIED'):
                client.verify_tls_connection(connection,host)
        raw._usock=object()
        with self.assertRaises(ValueError):client.verify_tls_connection(connection,'synthetic.invalid')
    def test_timeout_and_application_overrides_fail_closed(self):
        for value in (True,None,0,151,float('inf'),float('nan'),'130'):
            with self.subTest(value=value),self.assertRaises(ValueError):client.connection_args(timeout=value)
        for value in ('bad','worlex_ABC','worlex_a -c secret','worlex_a\nsecret'):
            with self.subTest(value=value),self.assertRaises(ValueError):client.connection_args(application_name=value)
        with self.assertRaises(ValueError):client.connection_args(read_only=1)
    def test_safe_sqlstate_never_returns_detail_or_secret(self):
        err=Exception({'C':'23505','D':'SECRET','M':'SECRET'})
        self.assertEqual(client.sqlstate(err),'23505')
        outer=Exception();outer.orig=err
        self.assertEqual(client.sqlstate(outer),'23505')
        for value in ('SECRET','secret','23505 SECRET',12345,None):
            self.assertIsNone(client.sqlstate(Exception({'C':value,'M':'SECRET'})))
        self.assertIsNone(client.sqlstate(Exception('SECRET')))
        self.assertIsNone(client.sqlstate(Exception()))

if __name__=='__main__':unittest.main(verbosity=2)
