"""青凪 snapshot checks using only synthetic requests and local files."""
import os
import socket
import unittest
from html.parser import HTMLParser
from unittest.mock import patch

from flask import Flask, request, session
from flask.sessions import SecureCookieSessionInterface
from werkzeug.middleware.proxy_fix import ProxyFix

from dkss_app.public_demo import MARKER, install
from dkss_app.public_demo_snapshot import CONTENT_SECURITY_POLICY


ON = {"PUBLIC_DEMO_READONLY_ENABLED": "true"}
ENTRIES = ("/demo", "/demo/", "/?__aonagi_entry=1")


class CountingSessions(SecureCookieSessionInterface):
    def __init__(self):
        self.opened = 0
        self.saved = 0

    def open_session(self, app, request):
        self.opened += 1
        return super().open_session(app, request)

    def save_session(self, app, session, response):
        self.saved += 1
        super().save_session(app, session, response)


class SnapshotMarkup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.links = []
        self.tags = []
        self.resource_attrs = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        for key, value in attrs:
            if key == "id":
                self.ids.add(value)
            if tag == "a" and key == "href":
                self.links.append(value)
            if key in {"href", "src", "srcset", "action", "poster", "ping"} or key.startswith("on"):
                self.resource_attrs.append((tag, key, value))


class SnapshotBoundaryTests(unittest.TestCase):
    def clients(self, *, env=ON, testing=False):
        app = Flask(__name__)
        app.config.update(SECRET_KEY="isolated-fixture-signer", TESTING=testing)
        app.session_interface = CountingSessions()
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
        visits = []

        @app.route("/", methods=["GET", "POST"])
        @app.route("/login", methods=["GET", "POST"])
        @app.route("/demo-ordinary")
        def ordinary():
            visits.append((request.endpoint, request.scheme, request.host))
            return session.get("username", "anonymous")

        @app.before_request
        def ordinary_hook():
            visits.append("hook")

        with patch.dict(os.environ, env, clear=True):
            install(app)
        return app, app.test_client(), visits

    def prohibit_service_calls(self):
        for target in ("socket.socket.connect", "socket.create_connection",
                       "sqlite3.connect", "sqlite3.dbapi2.connect"):
            blocker = patch(target, side_effect=AssertionError("external service not allowed"))
            blocker.start()
            self.addCleanup(blocker.stop)

    def test_get_and_head_are_cookie_free_and_do_not_enter_flask(self):
        self.prohibit_service_calls()
        app, client, visits = self.clients()
        first = None
        for path in ENTRIES:
            for agent in ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)", "Mozilla/5.0 Desktop"):
                response = client.get(path, headers={"User-Agent": agent})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["Content-Type"], "text/html; charset=utf-8")
                self.assertEqual(response.headers["Content-Security-Policy"], CONTENT_SECURITY_POLICY)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
                self.assertEqual(response.headers["X-Robots-Tag"], "noindex, nofollow")
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                self.assertNotIn("Set-Cookie", response.headers)
                self.assertNotIn("Vary", response.headers)
                self.assertTrue(first is None or response.data == first)
                first = response.data
            head = client.head(path)
            self.assertEqual((head.status_code, head.data), (200, b""))
            self.assertEqual(head.content_length, len(first))
        self.assertFalse(visits)
        self.assertEqual((app.session_interface.opened, app.session_interface.saved), (0, 0))

    def test_snapshot_markup_is_fixed_self_contained_and_usable_by_links(self):
        _, client, _ = self.clients()
        html = client.get("/demo").get_data(as_text=True)
        parser = SnapshotMarkup()
        parser.feed(html)
        for word in ("103号車", "受信済みの通知", "運行不可", "車両カルテ", "整備履歴と費用",
                     "整備の提案例（固定表示）", "この画面でAIは実行されません"):
            self.assertIn(word, html)
        for tag in ("script", "form", "input", "button", "iframe", "img", "audio", "video"):
            self.assertNotIn(tag, parser.tags)
        self.assertIn("details", parser.tags)
        self.assertIn("summary", parser.tags)
        self.assertGreater(len(parser.links), 5)
        self.assertEqual(len(parser.ids), 7)
        for link in parser.links:
            self.assertTrue(link.startswith("#") and link[1:] in parser.ids)
        for tag, key, value in parser.resource_attrs:
            self.assertTrue((tag == "a" and key == "href") or (tag, key, value) == ("link", "href", "data:,"))
        self.assertNotIn("url(", html.lower())

    def test_nonread_methods_and_retired_role_never_reach_flask(self):
        self.prohibit_service_calls()
        app, client, visits = self.clients()
        for path in (*ENTRIES, "/demo/role"):
            for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
                response = client.open(path, method=method, data="isolated-fixture")
                self.assertEqual(response.status_code, 405)
                self.assertEqual(response.headers["Allow"], "GET, HEAD")
                self.assertNotIn("Set-Cookie", response.headers)
        self.assertEqual(client.get("/demo/role").status_code, 404)
        self.assertFalse(visits)
        self.assertEqual((app.session_interface.opened, app.session_interface.saved), (0, 0))

    def test_ordinary_permanent_cookie_is_untouched_on_demo_but_login_unchanged(self):
        app, client, visits = self.clients()
        signer = app.session_interface.get_signing_serializer(app)
        key = app.config["SESSION_COOKIE_NAME"]
        cookie = signer.dumps({"username": "ordinary-synthetic", "_permanent": True})
        client.set_cookie(key, cookie)
        for path in ENTRIES:
            response = client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("Set-Cookie", response.headers)
            self.assertEqual(client.get_cookie(key).value, cookie)
        self.assertFalse(visits)
        self.assertEqual((app.session_interface.opened, app.session_interface.saved), (0, 0))
        for path in ("/", "/login", "/demo-ordinary"):
            self.assertEqual(client.get(path).text, "ordinary-synthetic")
        forwarded = {"X-Forwarded-Proto": "https", "X-Forwarded-Host": "ordinary-synthetic.invalid"}
        self.assertEqual(client.post("/login", headers=forwarded).text, "ordinary-synthetic")
        self.assertEqual(visits[-1], ("ordinary", "https", "ordinary-synthetic.invalid"))

    def test_stale_shared_flag_and_identity_cannot_reactivate_legacy_workflow(self):
        app, client, visits = self.clients(env={"PUBLIC_DEMO_ENABLED": "true", "RENDER": "true"}, testing=True)
        self.assertNotIn("PUBLIC_DEMO_CANDIDATE", app.config)
        for path in ENTRIES:
            self.assertEqual(client.get(path).status_code, 404)
        self.assertFalse(visits)
        self.assertEqual((app.session_interface.opened, app.session_interface.saved), (0, 0))
        signer = app.session_interface.get_signing_serializer(app)
        client.set_cookie(app.config["SESSION_COOKIE_NAME"],
                          signer.dumps({MARKER: True, "username": "legacy-synthetic"}))
        self.assertEqual(client.get("/").status_code, 410)
        self.assertFalse(visits)

    def test_off_by_default(self):
        for env in ({}, {"PUBLIC_DEMO_READONLY_ENABLED": "false"}, {"PUBLIC_DEMO_READONLY_ENABLED": "yes"}):
            app, client, visits = self.clients(env=env)
            for path in ENTRIES:
                response = client.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn("Set-Cookie", response.headers)
            self.assertFalse(visits)
            self.assertEqual((app.session_interface.opened, app.session_interface.saved), (0, 0))


if __name__ == "__main__":
    unittest.main()
