"""Cookie-free, read-only public demo, independent of the ordinary Flask app."""
import os
from pathlib import Path

from werkzeug.wrappers import Response

ENTRY_PATHS = frozenset({"/demo", "/demo/"})
LEGACY_HOME_QUERY = "__aonagi_entry=1"
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def snapshot_enabled():
    return os.environ.get("PUBLIC_DEMO_READONLY_ENABLED", "").lower() == "true"


def install_snapshot(app, *, enabled):
    """Terminate these public requests before Flask opens or saves a session."""
    ordinary_wsgi = app.wsgi_app
    snapshot = Path(__file__).with_name("public_demo_snapshot.html").read_bytes() if enabled else None

    def dispatch(environ, start_response):
        path = environ.get("PATH_INFO", "")
        marked_home = path == "/" and environ.get("QUERY_STRING") == LEGACY_HOME_QUERY
        if not (path == "/demo" or path.startswith("/demo/") or marked_home):
            return ordinary_wsgi(environ, start_response)

        if environ["REQUEST_METHOD"] not in {"GET", "HEAD"}:
            response = Response("Method Not Allowed\n", status=405, mimetype="text/plain")
            response.headers["Allow"] = "GET, HEAD"
        elif snapshot is None or (path not in ENTRY_PATHS and not marked_home):
            response = Response("Not Found\n", status=404, mimetype="text/plain")
        else:
            response = Response(snapshot, mimetype="text/html")
        response.headers.update({
            "Cache-Control": "no-store",
            "Content-Security-Policy": CONTENT_SECURITY_POLICY,
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "X-Robots-Tag": "noindex, nofollow",
        })
        return response(environ, start_response)

    app.wsgi_app = dispatch
