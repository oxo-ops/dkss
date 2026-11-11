"""Pure contracts: every local socket construction is explicitly forbidden."""
import ast
from collections import Counter
import json
from email.message import Message
import hashlib
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from video_connected_browser import exact_invoice_download as module

HERE = Path(__file__).resolve().parent
HARNESS = HERE / 'video_connected_browser/acceptance.py'
BASELINE = json.loads((HERE / 'fixtures/invoice_preview_contract_baseline.json').read_text())
URL = module.ORIGIN + '/vehicle/karte/1/documents/00000000-0000-0000-0000-000000000001/source'
BODY = b'%PDF-1.4\nsynthetic-fixture-only\n'
HEADERS = [('Content-Type', 'application/pdf'), ('Content-Disposition', 'inline; filename=invoice.pdf'),
           ('Content-Length', str(len(BODY))), ('Cache-Control', 'private, no-store'),
           ('X-Content-Type-Options', 'nosniff')]


def request_headers(*pairs):
    headers = Message()
    headers['Host'] = '127.0.0.1:8765'
    for name, value in pairs:
        headers[name] = value
    return headers


def receiver(**changes):
    args = dict(url=URL, status=200, headers=HEADERS, body=BODY,
                expected_sha256=hashlib.sha256(BODY).hexdigest(), width=1440)
    args.update(changes)
    return module.ExactInvoiceDownload(**args)


def armed(value):
    value._armed = True
    value._deadline = module.time.monotonic() + 100
    return value


class FakeSocket:
    def __init__(self, address=module.ADDRESS):
        self.address = address
        self.closed = False
        self.shutdowns = []

    def fileno(self): return -1 if self.closed else 123
    def getsockname(self): return self.address
    def shutdown(self, how): self.shutdowns.append(how)
    def close(self): self.closed = True


class FakeServer:
    def __init__(self, address, handler, bind_and_activate):
        self.address, self.handler = address, handler
        self.bind_and_activate = bind_and_activate
        self.socket = FakeSocket()
        self.binds = self.activations = self.closes = 0

    def server_bind(self): self.binds += 1
    def server_activate(self): self.activations += 1
    def server_close(self): self.closes += 1; self.socket.close()


class FakeThread:
    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        self.ident = None
        self.alive = False
        self.join_timeouts = []
        self.canceled = False

    def start(self): self.ident = 1; self.alive = True
    def cancel(self): self.canceled = True
    def join(self, timeout): self.join_timeouts.append(timeout); self.alive = False
    def is_alive(self): return self.alive


class PureContracts(unittest.TestCase):
    def setUp(self):
        self.no_socket = patch.object(module.socket, 'socket', side_effect=AssertionError('No local sockets'))
        self.no_socket.start()
        self.addCleanup(self.no_socket.stop)

    def handler(self, value, *, method='GET', path=None, headers=None):
        handler = object.__new__(module._Handler)
        handler.server = SimpleNamespace(owner=value)
        handler.command, handler.path = method, path or value.path
        handler.headers = headers or request_headers()
        handler.client_address = ('127.0.0.1', 12345)
        handler.wfile = BytesIO()
        handler.statuses, handler.response_headers = [], []
        handler.send_response_only = lambda status: handler.statuses.append(status)
        handler.send_header = lambda key, value: handler.response_headers.append((key, value))
        handler.end_headers = lambda: None
        return handler

    def test_construction_copies_immutable_response_without_socket(self):
        headers, body = list(HEADERS), bytearray(BODY)
        value = receiver(headers=headers, body=body)
        headers.append(('Location', 'https://example.com')); body[:] = b'changed'
        self.assertEqual(value.headers, tuple(HEADERS)); self.assertEqual(value.body, BODY)
        self.assertIsNone(value._server)

    def test_rejects_other_origins_queries_fragments_and_non_source_paths(self):
        for url in (URL.replace('127.0.0.1', 'localhost'), URL.replace(':8765', ':8766'),
                    URL.replace('http:', 'https:'), URL + '?download=1', URL + '#x',
                    URL.replace('/karte/1/', '/karte/../'), module.ORIGIN + '/etc/passwd'):
            with self.subTest(url=url), self.assertRaises(AssertionError): receiver(url=url)

    def test_rejects_changed_status_body_hash_disposition_mime_and_length(self):
        bad_headers = []
        for name, replacement in (('Content-Type', 'text/html'), ('Content-Disposition', 'attachment; filename=invoice.pdf'),
                                  ('Content-Length', '0')):
            bad_headers.append([(key, replacement if key == name else value) for key, value in HEADERS])
        for values in ({'status': 302}, {'body': BODY + b'X'}, {'expected_sha256': '0' * 64},
                       *({'headers': headers} for headers in bad_headers),
                       {'headers': HEADERS + [('Transfer-Encoding', 'chunked')]},
                       {'headers': HEADERS + [('Location', URL)]},
                       {'headers': HEADERS + [('X-Bad', 'a\r\nb')]}):
            with self.subTest(values=values), self.assertRaises(AssertionError): receiver(**values)

    def test_unarmed_expired_and_stopped_requests_are_rejected(self):
        for mode in ('unarmed', 'expired', 'stopped'):
            value = receiver()
            if mode != 'unarmed': armed(value)
            if mode == 'expired': value._deadline = 0
            if mode == 'stopped': value._stop.set()
            self.assertIsNone(value._admit('GET', value.path, request_headers(), '127.0.0.1'))
            self.assertEqual(len(value.report['rejected']), 1)

    def test_one_exact_request_only(self):
        value = armed(receiver())
        accepted = value._admit('GET', value.path, request_headers(), '127.0.0.1')
        self.assertIsNotNone(accepted)
        self.assertIsNone(value._admit('GET', value.path, request_headers(), '127.0.0.1'))
        self.assertEqual(value.report['rejected'][0]['reason'], 'one_shot_exhausted')

    def test_rejects_method_path_host_peer_and_advertised_body(self):
        invalid = [('POST', URL.split(':8765')[1], request_headers(), '127.0.0.1'),
                   ('HEAD', URL.split(':8765')[1], request_headers(), '127.0.0.1'),
                   ('GET', '/other', request_headers(), '127.0.0.1'),
                   ('GET', URL.split(':8765')[1], Message(), '127.0.0.1'),
                   ('GET', URL.split(':8765')[1], request_headers(('Host', '127.0.0.1:8765')), '127.0.0.1'),
                   ('GET', URL.split(':8765')[1], request_headers(), '127.0.0.2'),
                   ('GET', URL.split(':8765')[1], request_headers(('Content-Length', '1')), '127.0.0.1'),
                   ('GET', URL.split(':8765')[1], request_headers(('Transfer-Encoding', 'chunked')), '127.0.0.1')]
        for values in invalid:
            value = armed(receiver())
            self.assertIsNone(value._admit(*values)); self.assertFalse(value.report['accepted'])

    def test_dispatch_writes_exact_status_every_original_header_and_body(self):
        value = armed(receiver()); handler = self.handler(value)
        handler._dispatch()
        self.assertEqual(handler.statuses, [200])
        self.assertEqual(handler.response_headers, HEADERS)
        self.assertEqual(handler.wfile.getvalue(), BODY)
        self.assertTrue(handler.close_connection)
        self.assertTrue(value.report['accepted'][0]['write_complete'])

    def test_dispatch_denial_serves_no_original_bytes(self):
        value = armed(receiver()); handler = self.handler(value, path='/other')
        handler._dispatch()
        self.assertEqual(handler.statuses, [403]); self.assertEqual(handler.wfile.getvalue(), b'')
        self.assertFalse(value.report['accepted'])

    def test_unknown_method_and_malformed_requests_are_recorded(self):
        value = armed(receiver()); handler = self.handler(value, method='UNKNOWN')
        handler.do_UNKNOWN()
        self.assertEqual(value.report['rejected'][0]['reason'], 'method')
        handler.send_error(400)
        self.assertEqual(value.report['rejected'][-1]['reason'], 'malformed_request')

    def test_write_timeout_remains_fatal_and_not_complete(self):
        value = armed(receiver()); handler = self.handler(value)
        handler.wfile = SimpleNamespace(write=lambda body: (_ for _ in ()).throw(TimeoutError()), flush=lambda: None)
        with self.assertRaises(TimeoutError): handler._dispatch()
        self.assertFalse(value.report['accepted'][0]['write_complete'])
        self.assertIn('response_write_TimeoutError', value.report['errors'])

    def test_expiry_disarms_and_closes_listener_and_active_connections(self):
        value = armed(receiver()); value._server = FakeServer(module.ADDRESS, module._Handler, False)
        connection = FakeSocket(); value._track(connection)
        value._expire()
        self.assertTrue(value.report['expired']); self.assertTrue(value._stop.is_set())
        self.assertFalse(value._armed); self.assertTrue(connection.closed)
        self.assertTrue(value._server.socket.closed)
        late = FakeSocket(); self.assertFalse(value._track(late)); self.assertTrue(late.closed)

    def test_accepted_connection_receives_finite_read_write_timeout(self):
        value = receiver()
        server = object.__new__(module._Server)
        server.owner = value
        connection = FakeSocket()
        connection.timeouts = []
        connection.settimeout = connection.timeouts.append
        with patch.object(module.HTTPServer, 'get_request', return_value=(connection, ('127.0.0.1', 12345))):
            result = server.get_request()
        self.assertIs(result[0], connection)
        self.assertEqual(connection.timeouts, [2.0])
        self.assertIn(connection, value._active)
        server.close_request(connection)
        self.assertTrue(connection.closed); self.assertNotIn(connection, value._active)

    def test_start_uses_fixed_address_and_finite_watchdog_without_local_socket(self):
        value = receiver()
        with patch.object(module, '_Server', FakeServer), patch.object(module.threading, 'Thread', FakeThread), \
                patch.object(module.threading, 'Timer', FakeThread):
            value.start()
            self.assertEqual(value._server.address, ('127.0.0.1', 8765))
            self.assertFalse(value._server.bind_and_activate)
            self.assertEqual(value._server.binds, 1); self.assertEqual(value._server.activations, 1)
            self.assertEqual(value._timer.args, (15.0, value._expire))
            self.assertEqual(value._server.timeout, 0.1)
            value.close()
        self.assertTrue(value.report['cleanup_complete'])
        self.assertTrue(value._timer.canceled)
        self.assertEqual(value._thread.join_timeouts, [3.0])
        self.assertEqual(value._timer.join_timeouts, [3.0])

    def test_occupied_port_stops_without_fallback(self):
        value = receiver()
        class Occupied(FakeServer):
            def server_bind(self): self.binds += 1; raise OSError('Address already in use')
        with patch.object(module, '_Server', Occupied), self.assertRaises(OSError): value.start()
        self.assertEqual(value._server.binds, 1)
        self.assertEqual(value._server.activations, 0)
        self.assertTrue(value._server.socket.closed)
        self.assertTrue(value.report['cleanup_complete'])

    def test_wrong_bound_address_stops_before_listen(self):
        value = receiver()
        class WrongAddress(FakeServer):
            def server_bind(self): self.socket.address = ('0.0.0.0', 8765)
        with patch.object(module, '_Server', WrongAddress), self.assertRaises(AssertionError): value.start()
        self.assertEqual(value._server.activations, 0); self.assertTrue(value._server.socket.closed)

    def test_exception_in_download_body_always_closes_context(self):
        value = receiver()
        with patch.object(module, '_Server', FakeServer), patch.object(module.threading, 'Thread', FakeThread), \
                patch.object(module.threading, 'Timer', FakeThread):
            with self.assertRaisesRegex(AssertionError, 'canceled'):
                with value: raise AssertionError('canceled')
        self.assertTrue(value.report['cleanup_complete'])

    def test_unfinished_thread_fails_cleanup_after_finite_join(self):
        value = receiver(); value._thread = FakeThread(); value._thread.start()
        value._thread.join = lambda timeout: value._thread.join_timeouts.append(timeout)
        with self.assertRaises(AssertionError): value.close()
        self.assertEqual(value._thread.join_timeouts, [3.0]); self.assertFalse(value.report['cleanup_complete'])

    def test_deadline_loop_expires_even_without_timer_callback(self):
        value = armed(receiver()); value._deadline = 15.0
        value._server = FakeServer(module.ADDRESS, module._Handler, False)
        value._server.handle_request = lambda: None
        with patch.object(module.time, 'monotonic', side_effect=[0.0, 16.0]): value._serve()
        self.assertTrue(value.report['expired']); self.assertTrue(value._server.socket.closed)

    def test_pass_requires_one_complete_transfer_cleanup_and_no_faults(self):
        for bad in ('none', 'incomplete', 'rejected', 'errors', 'expired', 'cleanup', 'address'):
            value = armed(receiver())
            transfer = value._admit('GET', value.path, request_headers(), '127.0.0.1')
            value._written(transfer)
            value.report.update(cleanup_complete=True, bound_address=list(module.ADDRESS))
            if bad == 'none': value.report['accepted'] = []
            elif bad == 'incomplete': transfer['write_complete'] = False
            elif bad in ('rejected', 'errors'): value.report[bad].append('fault')
            elif bad == 'expired': value.report['expired'] = True
            elif bad == 'cleanup': value.report['cleanup_complete'] = False
            elif bad == 'address': value.report['bound_address'] = ['0.0.0.0', 8765]
            with self.subTest(bad=bad), self.assertRaises(AssertionError): value.assert_complete()
        value = armed(receiver()); transfer = value._admit('GET', value.path, request_headers(), '127.0.0.1')
        value._written(transfer); value.report.update(cleanup_complete=True, bound_address=list(module.ADDRESS))
        value.assert_complete()


class StaticContracts(unittest.TestCase):
    def test_reviewed_bridge_and_unknown_failure_policy_remain_strict(self):
        text = HARNESS.read_text(); tree = ast.parse(text)
        bridge = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'bridge')
        self.assertEqual(hashlib.sha256(ast.dump(bridge).encode()).hexdigest(),
                         BASELINE['function_ast_sha256']['bridge'])
        # The classifier's same-Request removal and equal-valued unknown failure
        # rejection are exercised by test_invoice_preview_acceptance, rather
        # than pinning the obsolete pre-classifier failure callback.
        self.assertIn("and not report['failed_requests']", text)
        for value in (text, (HERE / 'video_connected_browser/exact_invoice_download.py').read_text()):
            for forbidden in ('route.continue_', 'route.fallback', 'socket.connect(', '.connect_ex(', 'urlopen(',
                              'requests.get(', 'Fetch.enable', 'Network.enable', 'SO_REUSEPORT'):
                self.assertNotIn(forbidden, value)

    def test_all_51_baseline_assertions_and_frozen_guards_remain(self):
        tree = ast.parse(HARNESS.read_text())
        actual = Counter(hashlib.sha256(ast.dump(n.args[0]).encode()).hexdigest()
            for n in ast.walk(tree) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == 'require')
        expected = Counter(BASELINE['require_condition_hash_counts'])
        self.assertEqual(sum(expected.values()), 51)
        self.assertFalse(expected - actual)
        native = (HERE / 'video_connected_browser/native_pdf_navigation.py').read_bytes()
        self.assertEqual(hashlib.sha1(f'blob {len(native)}\0'.encode() + native).hexdigest(),
                         '4573aa6f07666f1d4e508b7352cc4cd42df0a323')
        guard = HERE / 'history_presentation_browser/guard/sitecustomize.py'
        self.assertIn('if event == "socket.connect":', guard.read_text())
        self.assertIn('BROWSER_ACCEPTANCE_EXISTING_DATABASE_FORBIDDEN', guard.read_text())

    def test_ci_passes_receiver_flag_only_to_invoice_and_keeps_isolation(self):
        workflow = (HERE.parent / '.github/workflows/common-priority-browser.yml').read_text()
        self.assertIn('for scenario in normal instruction recheck invoice periodic_instruction periodic_timing confirmation_manufacturer confirmation_legal confirmation_progression; do', workflow)
        self.assertEqual(workflow.count('extra_args+=(--native-invoice-download-http)'), 1)
        self.assertIn('extra_args=()\n            if [[ "$scenario" == invoice ]]; then\n              extra_args+=(--native-invoice-download-http)\n            fi', workflow)
        self.assertIn('--case "$scenario" --run-browser --chromium "$chromium" "${extra_args[@]}"', workflow)
        wrapper = (HERE / 'video_connected_browser/run-isolated.sh').read_text()
        for required in ('exec env -i', 'history_presentation_browser/guard', "DATABASE_URL='sqlite:///:memory:'", 'DKSS_VALIDATION_TMP="$RUN/tmp"'):
            self.assertIn(required, wrapper)

    def test_only_explicit_invoice_browser_flag_can_arm_experiment(self):
        text = HARNESS.read_text()
        self.assertIn("parser.add_argument('--native-invoice-download-http', action='store_true')", text)
        self.assertIn("args.run_browser and args.case == 'invoice'", text)
        self.assertIn("require(args.native_invoice_download_http,", text)
        self.assertIn('with receiver:', text); self.assertIn('receiver.assert_complete()', text)
        self.assertIn("require(download_failure is None,", text)
        self.assertIn("'Original download changed'", text)
        self.assertEqual(module._Server.address_family, module.socket.AF_INET)
        self.assertFalse(module._Server.allow_reuse_port)
        self.assertEqual(module.CONNECTION_TIMEOUT_SECONDS, 2.0)
        self.assertEqual(module.MAX_LIFETIME_SECONDS, 15.0)


if __name__ == '__main__':
    unittest.main()
