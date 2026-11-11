"""One-shot, bounded loopback response for a synthetic native-download test.

This is not an application server. Only start it in the authorized CI browser
experiment. Construction and policy tests do not open sockets. It has no Flask,
database, filesystem lookup, HTTP client, proxy, or outbound connection.
"""
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import re
import socket
from socketserver import TCPServer
import threading
import time
from urllib.parse import urlsplit

ADDRESS = ('127.0.0.1', 8765)
ORIGIN = 'http://127.0.0.1:8765'
MAX_LIFETIME_SECONDS = 15.0
CONNECTION_TIMEOUT_SECONDS = 2.0
JOIN_TIMEOUT_SECONDS = 3.0


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class _Server(HTTPServer):
    address_family = socket.AF_INET
    allow_reuse_address = True
    allow_reuse_port = False

    def server_bind(self):
        # HTTPServer normally resolves getfqdn here. No DNS is needed or used.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = ADDRESS

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(CONNECTION_TIMEOUT_SECONDS)
        if not self.owner._track(connection):
            raise OSError('Invoice receiver already disarmed')
        return connection, address

    def close_request(self, request):
        try:
            super().close_request(request)
        finally:
            self.owner._untrack(request)

    def handle_error(self, request, client_address):
        self.owner._error('handler_exception')


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def __getattr__(self, name):
        if name.startswith('do_'):
            return self._dispatch
        raise AttributeError(name)

    def log_message(self, format, *args):
        pass  # No cookies, arbitrary headers, or response bodies in logs.

    def log_error(self, format, *args):
        self.server.owner._error('request_parse_or_timeout')

    def send_error(self, code, message=None, explain=None):
        self.server.owner._reject_parse(getattr(self, 'command', None),
            getattr(self, 'path', None), self.client_address[0])
        self.send_response_only(403)
        self.end_headers()
        self.close_connection = True

    def _dispatch(self):
        owner = self.server.owner
        transfer = owner._admit(self.command, self.path, self.headers, self.client_address[0])
        self.close_connection = True
        if transfer is None:
            self.send_response_only(403)
            self.end_headers()
            return
        try:
            # Preserve the real Flask response status, every header, and bytes.
            # HTTP/1.0 and close_connection only bound the transport lifetime.
            self.send_response_only(owner.status)
            for key, value in owner.headers:
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(owner.body)
            self.wfile.flush()
            owner._written(transfer)
        except Exception as error:
            owner._error('response_write_' + type(error).__name__)
            raise


class ExactInvoiceDownload:
    def __init__(self, url, status, headers, body, expected_sha256, *, width):
        parsed = urlsplit(url)
        if (f'{parsed.scheme}://{parsed.netloc}' != ORIGIN or parsed.query or parsed.fragment
                or not re.fullmatch(r'/vehicle/karte/[1-9][0-9]*/documents/'
                    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/source', parsed.path)):
            raise AssertionError('Exact fixture original URL required')
        self.url, self.path = url, parsed.path
        self.status = status
        self.headers = tuple((str(key), str(value)) for key, value in headers)
        self.body = bytes(body)
        by_name = {}
        for key, value in self.headers:
            if '\r' in key + value or '\n' in key + value:
                raise AssertionError('Invalid fixture response header')
            by_name.setdefault(key.lower(), []).append(value)
        if (status != 200 or by_name.get('content-type') != ['application/pdf']
                or len(by_name.get('content-disposition', [])) != 1
                or not by_name['content-disposition'][0].startswith('inline;')
                or by_name.get('content-length') != [str(len(self.body))]
                or 'transfer-encoding' in by_name or 'location' in by_name
                or hashlib.sha256(self.body).hexdigest() != expected_sha256):
            raise AssertionError('Unchanged exact original PDF response required')
        self.report = dict(width=width, source_url=url, status=status,
            content_type=by_name['content-type'][0],
            content_disposition=by_name['content-disposition'][0],
            source_sha256=expected_sha256, byte_length=len(self.body),
            response_headers_sha256=hashlib.sha256(json.dumps(self.headers,
                ensure_ascii=True, separators=(',', ':')).encode()).hexdigest(),
            max_lifetime_seconds=MAX_LIFETIME_SECONDS,
            connection_timeout_seconds=CONNECTION_TIMEOUT_SECONDS,
            accepted=[], rejected=[], errors=[], expired=False,
            cleanup_complete=False, bound_address=None,
            transport='one_shot_immutable_fixture_response_only')
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._active = set()
        self._server = self._thread = self._timer = None
        self._deadline = None
        self._armed = False

    def _error(self, reason):
        with self._lock:
            self.report['errors'].append(reason)

    def _track(self, connection):
        with self._lock:
            if self._stop.is_set():
                connection.close()
                return False
            self._active.add(connection)
            return True

    def _untrack(self, connection):
        with self._lock:
            self._active.discard(connection)

    def _reject_parse(self, method, path, peer):
        with self._lock:
            self.report['rejected'].append(dict(method=method, path=path, peer=peer,
                reason='malformed_request', at=utc_now()))

    def _admit(self, method, path, headers, peer):
        hosts = headers.get_all('Host', [])
        lengths = headers.get_all('Content-Length', [])
        with self._lock:
            reason = None
            if not self._armed or self._stop.is_set(): reason = 'not_armed'
            elif self._deadline is None or time.monotonic() >= self._deadline: reason = 'deadline'
            elif peer != ADDRESS[0]: reason = 'peer'
            elif method != 'GET': reason = 'method'
            elif path != self.path: reason = 'path'
            elif hosts != ['127.0.0.1:8765']: reason = 'host'
            elif lengths not in ([], ['0']) or headers.get_all('Transfer-Encoding', []): reason = 'body'
            elif self.report['accepted']: reason = 'one_shot_exhausted'
            entry = dict(method=method, path=path, host=hosts[0] if len(hosts) == 1 else None,
                         peer=peer, at=utc_now())
            if reason:
                entry['reason'] = reason
                self.report['rejected'].append(entry)
                return None
            entry.update(status=self.status, byte_length=len(self.body),
                source_sha256=self.report['source_sha256'], write_complete=False)
            self.report['accepted'].append(entry)
            return entry

    def _written(self, transfer):
        with self._lock:
            transfer.update(write_complete=True, finished_utc=utc_now())

    def _interrupt_io(self):
        with self._lock:
            connections = tuple(self._active)
        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            finally:
                connection.close()
        if self._server is not None:
            self._server.server_close()

    def _expire(self):
        with self._lock:
            if self._stop.is_set():
                return
            self.report['expired'] = True
            self._armed = False
            self._stop.set()
        self._interrupt_io()

    def _serve(self):
        try:
            while not self._stop.is_set():
                if time.monotonic() >= self._deadline:
                    self._expire()
                    break
                try:
                    self._server.handle_request()
                except (OSError, ValueError):
                    if not self._stop.is_set():
                        raise
        except Exception as error:
            self._error('listener_' + type(error).__name__)
            self._stop.set()
        finally:
            self._server.server_close()

    def start(self):
        if self._server is not None or self._stop.is_set():
            raise AssertionError('Receiver cannot be restarted')
        try:
            self._server = _Server(ADDRESS, _Handler, bind_and_activate=False)
            self._server.owner = self
            self._server.timeout = 0.1
            self._server.server_bind()
            if self._server.socket.getsockname() != ADDRESS:
                raise AssertionError('Receiver bound outside the exact loopback endpoint')
            self._server.server_activate()
            self.report['bound_address'] = list(self._server.socket.getsockname())
            self.report['armed_utc'] = utc_now()
            self._deadline = time.monotonic() + MAX_LIFETIME_SECONDS
            self._armed = True
            self._thread = threading.Thread(target=self._serve, name='invoice-fixture-response', daemon=True)
            self._timer = threading.Timer(MAX_LIFETIME_SECONDS, self._expire)
            self._timer.daemon = True
            self._timer.start()
            self._thread.start()
            return self
        except Exception:
            self.close()
            raise

    def close(self):
        with self._lock:
            self._armed = False
            self._stop.set()
        if self._timer is not None:
            self._timer.cancel()
        self._interrupt_io()
        for thread in (self._thread, self._timer):
            if thread is not None and thread.ident is not None:
                thread.join(JOIN_TIMEOUT_SECONDS)
        threads_done = all(thread is None or not thread.is_alive() for thread in (self._thread, self._timer))
        socket_closed = self._server is None or self._server.socket.fileno() == -1
        with self._lock:
            connections_closed = all(connection.fileno() == -1 for connection in self._active)
            self.report['cleanup_complete'] = threads_done and socket_closed and connections_closed
            self.report['disarmed_utc'] = utc_now()
        if not self.report['cleanup_complete']:
            raise AssertionError('Invoice receiver cleanup incomplete')

    def assert_complete(self):
        if (len(self.report['accepted']) != 1 or not self.report['accepted'][0]['write_complete']
                or self.report['rejected'] or self.report['errors'] or self.report['expired']
                or not self.report['cleanup_complete'] or self.report['bound_address'] != list(ADDRESS)):
            raise AssertionError('Exactly one complete, confined native HTTP transfer required')

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
