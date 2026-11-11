"""Abort-only accounting for a deliberately opened fixture PDF's native viewer.

This does not load the viewer, permit network access, or change response headers.
It proves the original PDF's navigation/status/type/bytes, not native rendering.
Unknown URLs, methods, resource types, pages and frames remain ordinary failures.
"""
import hashlib
from urllib.parse import urlsplit


PDF_EXTENSION = 'chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai'
PDF_VIEWER = PDF_EXTENSION + '/index.html'
# Exact URLs, not a scheme/host allowlist. Chromium's pdf/index.html and
# components/pdf/resources/pdf_embedder.html define these five initial assets.
NATIVE_ASSETS = {
    PDF_EXTENSION + '/pdf_embedder.css': ('stylesheet', 'embedder'),
    PDF_EXTENSION + '/index.css': ('stylesheet', 'viewer'),
    PDF_EXTENSION + '/main.js': ('script', 'viewer'),
    PDF_EXTENSION + '/pdf_viewer_wrapper.js': ('script', 'viewer'),
    'chrome://resources/css/text_defaults_md.css': ('stylesheet', 'viewer'),
}


def require(value, message):
    if not value:
        raise AssertionError(message)


class NativePdfNavigation:
    def __init__(self, report, origin):
        self.report, self.origin, self.active = report, origin, None
        self.aborted = {}
        report['blocked_native_pdf_viewer_resources'] = []
        report['failed_native_pdf_viewer_requests'] = []
        report['original_pdf_navigations'] = []
        report['native_pdf_viewer_rendering_covered'] = False
        report['native_pdf_viewer_limitation'] = (
            'Five exact native viewer assets are still aborted, only in a '
            'verified fixture PDF navigation. Native PDF rendering is not tested.')

    def begin(self, page, url, expected_sha256):
        require(self.active is None, 'Another PDF navigation is active')
        parsed = urlsplit(url)
        require(f'{parsed.scheme}://{parsed.netloc}' == self.origin and
                parsed.username is None and parsed.password is None and
                not parsed.fragment and parsed.path.startswith('/vehicle/'),
                'PDF target must be an exact same-origin vehicle source')
        require(len(expected_sha256) == 64 and
                all(c in '0123456789abcdef' for c in expected_sha256), 'Invalid PDF identity')
        self.active = dict(page=page, url=url, sha256=expected_sha256,
                           response=None, finished=False)

    def observe_response(self, request, status, headers, body):
        """Called before unchanged route.fulfill, never before the real fixture GET."""
        active = self.active
        if active is None or request.url != active['url']:
            return
        require(active['response'] is None, 'Duplicate original PDF navigation response')
        require(request.method == 'GET' and request.resource_type == 'document' and request.is_navigation_request() and
                request.frame is active['page'].main_frame,
                'Original PDF must be a same-page main-frame GET navigation')
        lower = {key.lower(): value for key, value in headers.items()}
        content_type = lower.get('content-type', '')
        require(status == 200 and content_type.split(';', 1)[0].strip().lower() == 'application/pdf',
                'Original navigation must return HTTP 200 application/pdf')
        digest = hashlib.sha256(body).hexdigest()
        require(body.startswith(b'%PDF-') and digest == active['sha256'],
                'Original PDF navigation bytes differ from the real source')
        active['response'] = dict(url=request.url, method=request.method, status=status,
            content_type=content_type, source_sha256=digest, byte_length=len(body),
            main_frame_navigation=True)

    def classify_blocked(self, request):
        """Return evidence only for known native assets; caller STILL aborts them."""
        active = self.active
        resource = NATIVE_ASSETS.get(request.url)
        if (active is None or active['response'] is None or resource is None or
                request.method != 'GET' or request.resource_type != resource[0] or
                request.is_navigation_request()):
            return None
        try:
            frame = request.frame
            page = active['page']
            if (frame.page is not page or page.url != active['url'] or
                    page.main_frame.url != active['url']):
                return None
            if resource[1] == 'embedder':
                if frame is not page.main_frame or frame.url != active['url']:
                    return None
            elif (frame is page.main_frame or frame.parent_frame is not page.main_frame or
                  frame.url != PDF_VIEWER):
                return None
        except Exception:
            # Missing/detached frame evidence is NOT permission to reclassify.
            return None
        parsed = urlsplit(request.url)
        return dict(url=request.url, scheme=parsed.scheme, host=parsed.hostname,
            path=parsed.path, method=request.method, resource_type=request.resource_type,
            frame_url=frame.url, parent_frame_url=frame.parent_frame.url if frame.parent_frame else None,
            source_url=active['url'], source_sha256=active['sha256'], action='abort',
            classification='exact_native_pdf_asset_during_verified_source_navigation')

    def abort_if_native(self, route):
        detail = self.classify_blocked(route.request)
        if detail is None:
            return False
        self.aborted[id(route.request)] = (route.request, detail)
        self.report['blocked_native_pdf_viewer_resources'].append(detail)
        route.abort()
        return True

    def record_request_failed(self, request):
        aborted = self.aborted.get(id(request))
        if aborted is None or aborted[0] is not request or request.failure != 'net::ERR_FAILED':
            return False
        self.report['failed_native_pdf_viewer_requests'].append(
            dict(aborted[1], failure=request.failure))
        return True

    def finish(self, page, response):
        """Call after the actual click's response and source-page networkidle."""
        active = self.active
        require(active is not None and active['page'] is page and
                active['response'] is not None and not active['finished'], 'Unverified PDF navigation')
        require(response.url == active['url'] and response.status == 200 and
                response.request.method == 'GET' and response.request.resource_type == 'document' and response.request.is_navigation_request() and
                response.request.frame is page.main_frame, 'Browser PDF response identity differs')
        require(response.headers.get('content-type', '').split(';', 1)[0].strip().lower() == 'application/pdf',
                'Browser PDF Content-Type differs')
        require(page.url == active['url'] and page.main_frame.url == active['url'],
                'Original link did not navigate the same page to the exact PDF')
        self.report['original_pdf_navigations'].append(dict(active['response'],
            browser_url=page.url, browser_response_verified=True, native_viewer_rendered=False))
        active['finished'] = True

    def end(self):
        require(self.active is not None and self.active['finished'], 'PDF navigation not finished')
        self.active = None
