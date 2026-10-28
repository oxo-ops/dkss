"""Public code transfer encoding: byte fidelity, validators and private bypass."""
import gzip
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from sqlalchemy.engine import Engine
from dkss_app import create_app, public_assets


class PublicAssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="q12-public-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/"css").mkdir()
        (self.root/"js").mkdir()
        self.raw = b"body { color: #123; background: white; }\n"*1000
        (self.root/"css/style.css").write_bytes(self.raw)
        (self.root/"js/base.js").write_bytes(b"const message = 'synthetic';\n"*1000)
        with patch.dict(os.environ, {"RENDER": "", "AWS_EC2_METADATA_DISABLED": "true"}):
            self.app = create_app(dict(SECRET_KEY="synthetic-only", SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                TESTING=True, WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False, S3_BUCKET_NAME=""))
        self.app.static_folder = str(self.root)
        self.client = self.app.test_client()

    def get(self, path="/static/css/style.css", headers=None, method="GET"):
        response = self.client.open(path, method=method, headers=headers or {})
        response.get_data()
        response.close()
        return response

    def test_gzip_is_lossless_smaller_correct_mime_and_never_reads_database(self):
        with patch.object(Engine, "connect", side_effect=AssertionError("public asset queried database")):
            response = self.get(headers={"Accept-Encoding": "gzip, deflate, br"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/css")
        self.assertEqual(response.headers["Content-Encoding"], "gzip")
        self.assertEqual(gzip.decompress(response.data), self.raw)
        self.assertLess(len(response.data), len(self.raw)/10)
        self.assertEqual(int(response.headers["Content-Length"]), len(response.data))
        self.assertIn("Accept-Encoding", response.headers["Vary"])
        self.assertEqual((self.root/"css/style.css").read_bytes(), self.raw)

    def test_identity_preference_and_zero_quality_keep_original(self):
        for accept in ("", "br", "gzip;q=0", "gzip;q=.1, identity;q=1"):
            with self.subTest(accept=accept):
                response = self.get(headers={"Accept-Encoding": accept})
                self.assertNotIn("Content-Encoding", response.headers)
                self.assertEqual(response.data, self.raw)
                self.assertIn("Accept-Encoding", response.headers["Vary"])

    def test_each_representation_has_its_own_etag_and_revalidates(self):
        encoded = self.get(headers={"Accept-Encoding": "gzip"})
        identity = self.get()
        self.assertNotEqual(encoded.headers["ETag"], identity.headers["ETag"])
        conditional = self.get(headers={"Accept-Encoding": "gzip", "If-None-Match": encoded.headers["ETag"]})
        self.assertEqual((conditional.status_code, conditional.data), (304, b""))
        self.assertIn("Accept-Encoding", conditional.headers["Vary"])
        other = self.get(headers={"Accept-Encoding": "gzip", "If-None-Match": identity.headers["ETag"]})
        self.assertEqual(other.status_code, 200)
        self.assertEqual(gzip.decompress(other.data), self.raw)

    def test_head_and_identity_byte_ranges_keep_http_semantics(self):
        encoded = self.get(headers={"Accept-Encoding": "gzip"})
        head = self.get(method="HEAD", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(head.data, b"")
        self.assertEqual(head.headers["Content-Length"], encoded.headers["Content-Length"])
        self.assertEqual(head.headers["Content-Encoding"], "gzip")
        ranged = self.get(headers={"Accept-Encoding": "gzip", "Range": "bytes=0-4"})
        self.assertEqual((ranged.status_code, ranged.data), (206, self.raw[:5]))
        self.assertNotIn("Content-Encoding", ranged.headers)

    def test_source_updates_invalidate_and_unchanged_requests_reuse_compression(self):
        with patch.object(public_assets.gzip, "compress", wraps=gzip.compress) as encode:
            first = self.get(headers={"Accept-Encoding": "gzip"})
            self.get(headers={"Accept-Encoding": "gzip"})
            self.assertEqual(encode.call_count, 1)
            updated = self.raw.replace(b"#123", b"#987")
            (self.root/"css/style.css").write_bytes(updated)
            second = self.get(headers={"Accept-Encoding": "gzip"})
            self.assertEqual(gzip.decompress(second.data), updated)
            self.assertNotEqual(first.headers["ETag"], second.headers["ETag"])
            self.assertEqual(encode.call_count, 2)

    def test_private_and_other_assets_are_not_transformed(self):
        (self.root/"uploads").mkdir()
        (self.root/"uploads/private.css").write_bytes(b"synthetic private data")
        denied = self.get("/static/uploads/private.css", {"Accept-Encoding": "gzip"})
        self.assertEqual(denied.status_code, 302)
        self.assertNotIn("Content-Encoding", denied.headers)
        (self.root/"css/other.css").write_bytes(self.raw)
        other = self.get("/static/css/other.css", {"Accept-Encoding": "gzip"})
        self.assertEqual(other.data, self.raw)
        self.assertNotIn("Content-Encoding", other.headers)
        self.assertEqual(self.get("/static/css/missing.css", {"Accept-Encoding": "gzip"}).status_code, 404)

    def test_javascript_and_query_strings_keep_original_bytes(self):
        raw = (self.root/"js/base.js").read_bytes()
        response = self.get("/static/js/base.js?v=synthetic", {"Accept-Encoding": "gzip"})
        self.assertEqual(response.mimetype, "text/javascript")
        self.assertEqual(gzip.decompress(response.data), raw)

    def test_no_benefit_and_compression_errors_fall_back(self):
        (self.root/"css/style.css").write_bytes(b"x")
        self.assertEqual(self.get(headers={"Accept-Encoding": "gzip"}).data, b"x")
        (self.root/"css/style.css").write_bytes(self.raw)
        with patch.object(public_assets.gzip, "compress", side_effect=OSError("synthetic")):
            response = self.get(headers={"Accept-Encoding": "gzip"})
        self.assertEqual(response.data, self.raw)
        self.assertNotIn("Content-Encoding", response.headers)

    def test_public_filename_symlink_cannot_encode_private_data(self):
        (self.root/"uploads").mkdir()
        private = self.root/"uploads/private.css"
        private.write_bytes(b"synthetic private data"*1000)
        (self.root/"css/style.css").unlink()
        try:
            (self.root/"css/style.css").symlink_to(private)
        except OSError:
            self.skipTest("Local OS does not allow symlinks; Linux CI exercises this")
        response = self.get(headers={"Accept-Encoding": "gzip"})
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b"synthetic private data", response.data)
