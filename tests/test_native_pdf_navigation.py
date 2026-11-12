import hashlib
import unittest
from types import SimpleNamespace

from video_connected_browser.native_pdf_navigation import NativePdfNavigation, NATIVE_ASSETS, PDF_EXTENSION, PDF_VIEWER

ORIGIN = 'http://127.0.0.1:8765'
SOURCE = ORIGIN + '/vehicle/karte/1/documents/synthetic/source'
BODY = b'%PDF-1.4\nsynthetic test bytes\n%%EOF'
DIGEST = hashlib.sha256(BODY).hexdigest()


class Request:
    def __init__(self, url, frame, *, method='GET', resource_type='document', navigation=False):
        self.url, self.frame, self.method = url, frame, method
        self.resource_type, self.navigation = resource_type, navigation
        self.failure = 'net::ERR_FAILED'

    def is_navigation_request(self):
        return self.navigation


class Route:
    def __init__(self, request):
        self.request = request
        self.actions = []

    def abort(self):
        self.actions.append('abort')


class PdfContracts(unittest.TestCase):
    def setUp(self):
        self.report = {}
        self.pdf = NativePdfNavigation(self.report, ORIGIN)
        self.page = SimpleNamespace(url=SOURCE)
        self.main = SimpleNamespace(page=self.page, url=SOURCE, parent_frame=None)
        self.page.main_frame = self.main
        self.viewer = SimpleNamespace(page=self.page, url=PDF_VIEWER, parent_frame=self.main)
        self.navigation = Request(SOURCE, self.main, navigation=True)
        self.pdf.begin(self.page, SOURCE, DIGEST)
        self.pdf.observe_response(self.navigation, 200, {'Content-Type': 'application/pdf'}, BODY)

    def asset(self, url):
        resource, kind = NATIVE_ASSETS[url]
        return Request(url, self.main if kind == 'embedder' else self.viewer, resource_type=resource)

    def test_exact_five_native_assets_only_abort_with_evidence(self):
        for url in NATIVE_ASSETS:
            with self.subTest(url=url):
                route = Route(self.asset(url))
                self.assertTrue(self.pdf.abort_if_native(route))
                self.assertEqual(route.actions, ['abort'])
                entry = self.report['blocked_native_pdf_viewer_resources'][-1]
                self.assertEqual(entry['url'], url)
                self.assertEqual(entry['source_sha256'], DIGEST)
                self.assertEqual(entry['action'], 'abort')
                self.assertTrue(self.pdf.record_request_failed(route.request))
        self.assertEqual(len(self.report['failed_native_pdf_viewer_requests']), 5)

    def test_scheme_credentials_port_path_query_fragment_spoofs_fail_closed(self):
        urls = []
        for url in NATIVE_ASSETS:
            scheme, rest = url.split('://', 1)
            host, path = rest.split('/', 1)
            urls.extend([
                'http://' + rest, 'https://' + rest, 'file://' + rest,
                'chrome-untrusted://' + rest, 'data:text/plain,' + url,
                scheme + '://user@' + rest, scheme + '://user:pass@' + rest,
                scheme + '://' + host + ':80/' + path,
                scheme + '://' + host + '.evil/' + path,
                scheme + '://' + host + '/' + path + '/extra',
                url + '?extra=1', url + '#extra', url.replace('.js', '%2Ejs') + '?',
            ])
        urls.extend([PDF_EXTENSION + '/index.html', PDF_EXTENSION + '/unexpected.js',
                     'chrome://resources/js/load_time_data.js'])
        for url in urls:
            with self.subTest(url=url):
                self.assertIsNone(self.pdf.classify_blocked(Request(url, self.viewer, resource_type='script')))

    def test_methods_navigation_and_wrong_resource_types_fail_closed(self):
        for url in NATIVE_ASSETS:
            for method in ('POST', 'PUT', 'DELETE', 'HEAD'):
                request = self.asset(url); request.method = method
                self.assertIsNone(self.pdf.classify_blocked(request))
            for resource in ('fetch', 'xhr', 'document', 'image'):
                request = self.asset(url); request.resource_type = resource
                self.assertIsNone(self.pdf.classify_blocked(request))
            request = self.asset(url); request.navigation = True
            self.assertIsNone(self.pdf.classify_blocked(request))

    def test_wrong_frame_page_parent_or_uncommitted_source_fail_closed(self):
        url = PDF_EXTENSION + '/main.js'
        request = self.asset(url)
        for frame in (self.main,
                SimpleNamespace(page=object(), url=PDF_VIEWER, parent_frame=self.main),
                SimpleNamespace(page=self.page, url='about:blank', parent_frame=self.main),
                SimpleNamespace(page=self.page, url=PDF_VIEWER, parent_frame=object()),
                SimpleNamespace(page=self.page, url=SOURCE, parent_frame=self.main), None):
            request.frame = frame
            self.assertIsNone(self.pdf.classify_blocked(request))
        request = self.asset(url)
        self.page.url = ORIGIN + '/vehicle/karte/1/analysis'
        self.assertIsNone(self.pdf.classify_blocked(request))
        self.page.url = SOURCE; self.main.url = 'about:blank'
        self.assertIsNone(self.pdf.classify_blocked(request))
        self.main.url = SOURCE
        request = self.asset(PDF_EXTENSION + '/pdf_embedder.css'); request.frame = self.viewer
        self.assertIsNone(self.pdf.classify_blocked(request))

    def test_no_armed_or_no_verified_response_is_not_classified(self):
        request = self.asset(PDF_EXTENSION + '/main.js')
        self.pdf.active['response'] = None
        self.assertIsNone(self.pdf.classify_blocked(request))
        self.pdf.active = None
        self.assertIsNone(self.pdf.classify_blocked(request))

    def test_wrong_pdf_status_type_bytes_and_navigation_fail(self):
        for status, headers, body in ((404, {'Content-Type':'application/pdf'}, BODY),
                (200, {'Content-Type':'text/html'}, BODY),
                (200, {'Content-Type':'application/pdf'}, b'not PDF'),
                (200, {'Content-Type':'application/pdf'}, BODY + b'changed')):
            self.pdf.active['response'] = None
            with self.assertRaises(AssertionError):
                self.pdf.observe_response(self.navigation, status, headers, body)
        for field, value in (('method', 'POST'), ('navigation', False), ('frame', self.viewer), ('resource_type', 'fetch')):
            request = Request(SOURCE, self.main, navigation=True); setattr(request, field, value)
            with self.assertRaises(AssertionError):
                self.pdf.observe_response(request, 200, {'Content-Type':'application/pdf'}, BODY)

    def test_unexpected_requestfailed_is_never_exempted(self):
        request = self.asset(PDF_EXTENSION + '/main.js')
        self.assertFalse(self.pdf.record_request_failed(request))
        self.pdf.abort_if_native(Route(request))
        request.failure = 'net::ERR_BLOCKED_BY_RESPONSE'
        self.assertFalse(self.pdf.record_request_failed(request))
        request.failure = 'net::ERR_FAILED'
        lookalike = self.asset(request.url)
        self.assertFalse(self.pdf.record_request_failed(lookalike))
        self.assertTrue(self.pdf.record_request_failed(request))

    def test_finish_requires_actual_response_and_exact_navigation(self):
        response = SimpleNamespace(url=SOURCE, status=200, request=self.navigation,
                                   headers={'content-type': 'application/pdf'})
        self.page.url = SOURCE + '?changed'
        with self.assertRaises(AssertionError): self.pdf.finish(self.page, response)
        self.page.url = SOURCE
        self.pdf.finish(self.page, response)
        self.assertEqual(self.report['original_pdf_navigations'][0]['source_sha256'], DIGEST)
        self.assertFalse(self.report['native_pdf_viewer_rendering_covered'])
        self.pdf.end()
        self.assertIsNone(self.pdf.classify_blocked(self.asset(PDF_EXTENSION + '/main.js')))

    def test_external_and_credentialed_targets_and_bad_hash_rejected(self):
        for url in ('https://example.com/vehicle/source', ORIGIN + '/other/source',
                ORIGIN + '/vehicle/source#changed', 'http://user@127.0.0.1:8765/vehicle/source'):
            with self.assertRaises(AssertionError): NativePdfNavigation({}, ORIGIN).begin(self.page, url, DIGEST)
        with self.assertRaises(AssertionError): NativePdfNavigation({}, ORIGIN).begin(self.page, SOURCE, 'bad')


if __name__ == '__main__':
    unittest.main(verbosity=2)
