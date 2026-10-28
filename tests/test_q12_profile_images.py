"""Private display images: original integrity, version freshness and revocation."""
from io import BytesIO
from pathlib import Path
import hashlib
import tempfile
import unittest
from unittest.mock import patch

from botocore.exceptions import ClientError
from PIL import Image
from dkss_app import profile_images
import test_workflow_regressions as workflow


def picture(color="red", mode="RGB", size=(1200, 800), format="JPEG", **options):
    out = BytesIO()
    Image.new(mode, size, color).save(out, format=format, **options)
    return out.getvalue()


class ProfileImageDisplayTests(unittest.TestCase):
    setUpClass = classmethod(workflow.WorkflowRegressionTests.setUpClass.__func__)
    tearDownClass = classmethod(workflow.WorkflowRegressionTests.tearDownClass.__func__)
    tearDown = workflow.WorkflowRegressionTests.tearDown

    def setUp(self):
        workflow.WorkflowRegressionTests.setUp(self)
        self.directory = tempfile.TemporaryDirectory(prefix="q12-images-")
        self.addCleanup(self.directory.cleanup)
        previous = self.m.app.static_folder
        self.addCleanup(setattr, self.m.app, "static_folder", previous)
        self.m.app.static_folder = self.directory.name
        original_uploads = self.m.app.config["UPLOAD_FOLDER"]
        self.addCleanup(self.m.app.config.__setitem__, "UPLOAD_FOLDER", original_uploads)
        self.m.app.config["UPLOAD_FOLDER"] = str(Path(self.directory.name, "uploads"))
        self.m.app.extensions.pop("profile_display_images", None)
        self.m.app.extensions["dkss"]["s3_client"] = None
        self.m.app.config["S3_BUCKET_NAME"] = ""
        self.original = picture()
        self.path = self.write("TEST", "avatar.jpg", self.original)
        self.user = self.m.User.query.filter_by(company_code="TEST", username="admin").one()
        self.user.profile_image = "avatar.jpg"
        self.m.db.session.commit()

    def write(self, company, name, data):
        p = Path(self.directory.name, "uploads", company, name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def get(self, name="avatar.jpg", size=96, **options):
        response = self.client.get(f"/files/uploads/{name}?avatar={size}", **options)
        response.get_data()
        response.close()
        return response

    def test_derivative_is_small_original_stays_byte_identical(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        response = self.get()
        self.assertEqual((response.status_code, response.mimetype), (200, "image/webp"))
        self.assertLess(len(response.data), len(self.original) / 10)
        with Image.open(BytesIO(response.data)) as im:
            self.assertLessEqual(max(im.size), 96)
        full = self.client.get("/files/uploads/avatar.jpg", follow_redirects=True)
        self.assertEqual(full.data, self.original)
        full.close()
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_warm_display_reuses_conversion_but_not_authorization(self):
        with patch.object(profile_images.Image, "open", wraps=Image.open) as decode:
            first, second = self.get(), self.get()
        self.assertEqual(first.data, second.data)
        self.assertEqual(decode.call_count, 1)
        self.user.login_locked = True
        self.m.db.session.commit()
        with patch.object(profile_images, "source_revision", side_effect=AssertionError("authorization bypass")):
            self.assertEqual(self.get().status_code, 302)

    def test_update_and_delete_never_serve_previous_revision(self):
        first = self.get().data
        self.path.write_bytes(picture("blue"))
        self.assertNotEqual(self.get().data, first)
        self.path.unlink()
        self.assertEqual(self.get(follow_redirects=True).status_code, 404)
        self.assertFalse(profile_images.cache().values)

    def test_same_filename_and_username_in_another_company_is_isolated(self):
        first = self.get().data
        self.m.db.session.add(self.m.Company(company_code="OTHER", company_name="Synthetic", active=True))
        self.m.db.session.add(self.m.User(company_code="OTHER", username="admin", password="unused", role="admin", last_name="架空",
                                        profile_image="avatar.jpg", password_changed_at=self.user.password_changed_at))
        self.m.db.session.commit()
        self.write("OTHER", "avatar.jpg", picture("blue"))
        with self.client.session_transaction() as session:
            session["company_code"] = "OTHER"
            session["account_identity"] = self.m.User.query.filter_by(company_code="OTHER", username="admin").one().account_identity
        self.assertNotEqual(self.get().data, first)
        self.assertEqual(len(profile_images.cache().values), 2)

    def test_logout_password_change_company_stop_and_user_delete_revoke_cached_image(self):
        for mutation in ("logout", "password", "company", "delete"):
            with self.subTest(mutation=mutation):
                self.assertEqual(self.get().status_code, 200)
                stamp = self.user.password_changed_at
                if mutation == "logout":
                    with self.client.session_transaction() as session:
                        session.clear()
                elif mutation == "password":
                    self.user.password_changed_at = "revoked"
                elif mutation == "company":
                    self.m.Company.query.filter_by(company_code="TEST").one().active = False
                else:
                    self.m.db.session.delete(self.user)
                self.m.db.session.commit()
                self.assertEqual(self.get().status_code, 302)
                if mutation == "delete":
                    break
                self.user.password_changed_at = stamp
                self.m.Company.query.filter_by(company_code="TEST").one().active = True
                self.m.db.session.commit()
                with self.client.session_transaction() as session:
                    session.update(company_code="TEST", username="admin", role="admin", password_changed_at=stamp,
                                   account_identity=self.user.account_identity)

    def test_changed_profile_reference_cannot_retrieve_old_cached_derivative(self):
        self.get()
        self.user.profile_image = "new.jpg"
        self.m.db.session.commit()
        self.assertEqual(self.get().status_code, 404)

    def test_settings_upload_replaces_reference_and_purges_old_display(self):
        self.get()
        replacement = picture("blue")
        response = self.client.post("/settings", data={
            "action": "profile_image", "profile_image": (BytesIO(replacement), "new.jpg"),
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(profile_images.cache().values)
        self.assertFalse(self.path.exists())
        self.m.db.session.refresh(self.user)
        self.assertNotEqual(self.user.profile_image, "avatar.jpg")
        self.assertEqual(self.get().status_code, 404)
        self.assertEqual(self.get(self.user.profile_image).mimetype, "image/webp")
        self.assertEqual(Path(self.directory.name, "uploads", "TEST", self.user.profile_image).read_bytes(), replacement)

    def test_legacy_flat_key_and_unsupported_size_keep_existing_original(self):
        flat = Path(self.directory.name, "uploads", "avatar.jpg")
        self.path.replace(flat)
        self.assertEqual(self.get().mimetype, "image/webp")
        self.assertEqual(self.get(size=2000, follow_redirects=True).data, self.original)

    def test_exif_rotation_and_transparency_without_original_mutation(self):
        exif = Image.Exif()
        exif[0x0112] = 6
        data = picture(size=(60, 120), exif=exif)
        self.path.write_bytes(data)
        with Image.open(BytesIO(self.get().data)) as im:
            self.assertEqual(im.size, (96, 48))
        self.assertEqual(self.path.read_bytes(), data)
        alpha = picture((20, 40, 60, 128), mode="RGBA", format="PNG")
        self.write("TEST", "alpha.png", alpha)
        self.user.profile_image = "alpha.png"
        self.m.db.session.commit()
        with Image.open(BytesIO(self.get("alpha.png").data)) as im:
            self.assertEqual(im.getchannel("A").getextrema(), (128, 128))

    def test_animated_and_invalid_images_fall_back_without_rewriting_original(self):
        out = BytesIO()
        Image.new("RGB", (20, 20), "red").save(out, format="PNG", save_all=True,
            append_images=[Image.new("RGB", (20, 20), "blue")], duration=100, loop=0)
        self.write("TEST", "animated.png", out.getvalue())
        self.user.profile_image = "animated.png"
        self.m.db.session.commit()
        self.assertEqual(self.get("animated.png", follow_redirects=True).data, out.getvalue())
        self.path.write_bytes(b"not an image")
        self.user.profile_image = "avatar.jpg"
        self.m.db.session.commit()
        self.assertEqual(self.get(follow_redirects=True).data, b"not an image")

    def test_generic_deletion_purges_company_derivatives(self):
        self.get()
        from dkss_app.storage import delete_uploaded_file
        with self.m.app.test_request_context("/"):
            from flask import session
            session.update(company_code="TEST", username="admin")
            delete_uploaded_file("avatar.jpg")
        self.assertFalse(profile_images.cache().values)

    def test_s3_head_validates_hits_and_versions_pin_original_reads(self):
        class S3:
            version, missing, denied = "v1", False, False
            gets, heads = [], 0
            def head_object(fake, **kw):
                fake.heads += 1
                if fake.missing or fake.denied:
                    raise ClientError({"Error": {"Code": "AccessDenied" if fake.denied else "NoSuchKey"}}, "HeadObject")
                return {"VersionId": fake.version, "ETag": "etag-" + str(fake.version), "ContentLength": 99}
            def get_object(fake, **kw):
                fake.gets.append(kw)
                if fake.missing or fake.denied:
                    raise ClientError({"Error": {"Code": "AccessDenied" if fake.denied else "NoSuchKey"}}, "GetObject")
                return {"Body": BytesIO(picture("red" if fake.version == "v1" else "blue")), "ContentType": "image/jpeg"}
        s3 = S3()
        self.m.app.extensions["dkss"]["s3_client"] = s3
        self.m.app.config["S3_BUCKET_NAME"] = "fictional-test-only"
        try:
            first = self.get().data
            self.assertEqual(self.get().data, first)
            self.assertEqual((s3.heads, len(s3.gets)), (2, 1))
            self.assertEqual(s3.gets[0]["VersionId"], "v1")
            s3.version = "v2"
            self.assertNotEqual(self.get().data, first)
            s3.version = None
            self.assertEqual(self.get().mimetype, "image/webp")
            self.assertNotIn("VersionId", s3.gets[-1])
            self.assertIn("IfMatch", s3.gets[-1])
            s3.missing = True
            self.assertEqual(self.get().status_code, 404)
            self.assertFalse(profile_images.cache().values)
            s3.missing = False
            s3.version = "v2"
            self.get()
            s3.denied = True
            self.assertEqual(self.get().status_code, 404)
            self.assertFalse(profile_images.cache().values)
        finally:
            self.m.app.extensions["dkss"]["s3_client"] = None
            self.m.app.config["S3_BUCKET_NAME"] = ""


class DisplayImageBudgetTests(unittest.TestCase):
    def test_byte_budget_entry_budget_and_company_purge(self):
        cache = profile_images.DisplayImages(max_bytes=5, max_entries=2)
        cache.put(("A", "one"), b"aaa")
        cache.put(("B", "one"), b"bbb")
        self.assertIsNone(cache.get(("A", "one")))
        cache.put(("B", "two"), b"cc")
        cache.put(("B", "three"), b"d")
        self.assertLessEqual(cache.bytes, 5)
        self.assertLessEqual(len(cache.values), 2)
        cache.forget("B", "two")
        self.assertIsNone(cache.get(("B", "two")))



