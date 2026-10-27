"""Exercise the production handler without loading unrelated app services."""
import ast
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class MissingFile(Exception):
    pass


class S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}


class ManualStorageLegacyTests(unittest.TestCase):
    def setUp(self):
        source = (Path(__file__).resolve().parents[1] / "dkss_app/storage.py").read_text(encoding="utf-8")
        node = next(n for n in ast.parse(source).body
                    if isinstance(n, ast.FunctionDef) and n.name == "s3_manual_file")
        self.client = Mock()
        self.app = SimpleNamespace(
            extensions={"dkss": {"s3_client": self.client}},
            config={"S3_BUCKET_NAME": "test-bucket"},
            send_static_file=Mock(), logger=Mock(),
        )
        self.allowed = Mock(return_value=True)
        self.common = SimpleNamespace(
            session={"company_code": "A"}, os=os,
            ClientError=S3Error, NotFound=MissingFile,
            redirect=lambda url: (url, 302),
        )
        scope = {"_dkss_common": self.common,
                 "_dkss_runtime": SimpleNamespace(app=self.app),
                 "file_belongs_to_current_company": self.allowed}
        exec(compile(ast.Module(body=[node], type_ignores=[]), source, "exec"), scope)
        self.handler = scope["s3_manual_file"]
        self.client.generate_presigned_url.return_value = "signed-url"

    def test_company_key_preferred(self):
        self.assertEqual(self.handler("x.pdf"), ("signed-url", 302))
        self.client.head_object.assert_called_once_with(Bucket="test-bucket", Key="manuals/A/x.pdf")
        self.assertEqual(self.client.generate_presigned_url.call_args.kwargs["Params"]["Key"], "manuals/A/x.pdf")

    def test_s3_legacy_key_used_after_missing_company_key(self):
        self.client.head_object.side_effect = [S3Error("404"), {}]
        self.assertEqual(self.handler("x.pdf"), ("signed-url", 302))
        self.assertEqual(self.client.generate_presigned_url.call_args.kwargs["Params"]["Key"], "manuals/x.pdf")

    def test_both_missing_does_not_issue_url(self):
        self.client.head_object.side_effect = S3Error("NoSuchKey")
        self.assertEqual(self.handler("x.pdf")[1], 404)
        self.client.generate_presigned_url.assert_not_called()

    def test_access_denied_does_not_try_legacy(self):
        self.client.head_object.side_effect = S3Error("AccessDenied")
        self.assertEqual(self.handler("x.pdf")[1], 404)
        self.assertEqual(self.client.head_object.call_count, 1)
        self.client.generate_presigned_url.assert_not_called()

    def test_other_company_file_denied_before_storage(self):
        self.allowed.return_value = False
        self.assertEqual(self.handler("x.pdf")[1], 404)
        self.client.head_object.assert_not_called()
        self.app.send_static_file.assert_not_called()

    def test_no_session_denied(self):
        self.common.session.clear()
        self.assertEqual(self.handler("x.pdf")[1], 404)
        self.allowed.assert_not_called()
        self.client.head_object.assert_not_called()

    def test_local_company_file_preferred(self):
        self.app.extensions["dkss"]["s3_client"] = None
        self.app.send_static_file.return_value = "pdf"
        self.assertEqual(self.handler("x.pdf"), "pdf")
        self.app.send_static_file.assert_called_once_with("manuals/A/x.pdf")

    def test_local_legacy_file(self):
        self.app.extensions["dkss"]["s3_client"] = None
        self.app.send_static_file.side_effect = [MissingFile(), "pdf"]
        self.assertEqual(self.handler("x.pdf"), "pdf")
        self.assertEqual(self.app.send_static_file.call_args.args, ("manuals/x.pdf",))

    def test_local_both_missing(self):
        self.app.extensions["dkss"]["s3_client"] = None
        self.app.send_static_file.side_effect = MissingFile()
        self.assertEqual(self.handler("x.pdf")[1], 404)


if __name__ == "__main__":
    unittest.main()
