"""Real file authorization is applied before every attachment thumbnail hit."""
import hashlib
import json
import unittest
from io import BytesIO
from unittest.mock import patch
from PIL import Image
import test_q12_profile_images as profiles
from dkss_app import profile_images


class AttachmentThumbnailTests(unittest.TestCase):
    setUpClass = classmethod(profiles.ProfileImageDisplayTests.setUpClass.__func__)
    tearDownClass = classmethod(profiles.ProfileImageDisplayTests.tearDownClass.__func__)
    tearDown = profiles.ProfileImageDisplayTests.tearDown
    write = profiles.ProfileImageDisplayTests.write

    def setUp(self):
        profiles.ProfileImageDisplayTests.setUp(self)
        self.user.profile_image = None
        self.record = self.m.PatrolResult(company_code="TEST", target_type="user",
            target_username="recipient", created_by_username="creator", date="2026-10-29",
            category="Bad", content="Synthetic", files_json=json.dumps(["avatar.jpg"]))
        self.m.db.session.add(self.record)
        self.m.db.session.commit()

    def get(self, name="avatar.jpg", size=160, **kw):
        response = self.client.get(f"/files/uploads/{name}?thumb={size}", **kw)
        response.get_data()
        response.close()
        return response

    def test_display_crop_original_download_and_no_store(self):
        before = hashlib.sha256(self.original).hexdigest()
        response = self.get()
        self.assertEqual((response.status_code, response.mimetype), (200, "image/webp"))
        with Image.open(BytesIO(response.data)) as image:
            self.assertEqual(image.size, (160, 120))
        self.assertLess(len(response.data), len(self.original) / 10)
        with patch.object(profile_images, "source_revision", side_effect=AssertionError("original must bypass derivative")):
            full = self.client.get("/files/uploads/avatar.jpg", follow_redirects=True)
            self.assertEqual(full.data, self.original)
            full.close()
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_authorization_revocation_denies_a_warm_cache(self):
        self.assertEqual(self.get().status_code, 200)
        self.user.role = "user"
        self.m.db.session.commit()
        with patch.object(profile_images, "source_revision", side_effect=AssertionError("authorization bypass")):
            self.assertEqual(self.get().status_code, 404)

    def test_reference_removal_and_source_deletion_do_not_serve_cached_bytes(self):
        self.get()
        self.record.files_json = "[]"
        self.m.db.session.commit()
        self.assertEqual(self.get().status_code, 404)
        self.record.files_json = json.dumps(["avatar.jpg"])
        self.m.db.session.commit()
        self.path.unlink()
        self.assertEqual(self.get(follow_redirects=True).status_code, 404)
        self.assertFalse(profile_images.cache().values)

    def test_source_update_and_sizes_are_separate(self):
        first = self.get().data
        self.path.write_bytes(profiles.picture("blue"))
        self.assertNotEqual(self.get().data, first)
        for size in (160, 320, 480):
            with Image.open(BytesIO(self.get(size=size).data)) as image:
                self.assertEqual(image.size, (size, size*3//4))
        self.assertEqual(len(profile_images.cache().values), 4)

    def test_company_and_account_caches_are_separate(self):
        first = self.get().data
        m = self.m
        m.db.session.add(m.Company(company_code="OTHER", company_name="Synthetic", active=True))
        other = m.User(company_code="OTHER", username="admin", role="admin", password="unused",
                       last_name="Synthetic", password_changed_at=self.user.password_changed_at)
        m.db.session.add(other)
        m.db.session.add(m.PatrolResult(company_code="OTHER", target_type="user",
            target_username="recipient", created_by_username="creator",
            files_json=json.dumps(["avatar.jpg"])))
        m.db.session.commit()
        self.write("OTHER", "avatar.jpg", profiles.picture("blue"))
        with self.client.session_transaction() as state:
            state.update(company_code="OTHER", account_identity=other.account_identity)
        self.assertNotEqual(self.get().data, first)
        self.assertEqual(len(profile_images.cache().values), 2)
        other.login_locked = True
        m.db.session.commit()
        self.assertEqual(self.get().status_code, 302)

    def test_nonrecipient_and_other_folder_cannot_use_thumbnail_query(self):
        self.get()
        reader = self.m.User(company_code="TEST", username="reader", role="user", password="unused",
                             last_name="Synthetic", password_changed_at=self.user.password_changed_at)
        self.m.db.session.add(reader)
        self.m.db.session.commit()
        with self.client.session_transaction() as state:
            state.update(username="reader", account_identity=reader.account_identity)
        self.assertEqual(self.get().status_code, 404)
        self.assertEqual(self.client.get("/files/manuals/avatar.jpg?thumb=160").status_code, 404)

    def test_pdf_animation_invalid_image_and_unsupported_size_keep_original(self):
        out = BytesIO()
        Image.new("RGB", (10, 10), "red").save(out, format="PNG", save_all=True,
            append_images=[Image.new("RGB", (10, 10), "blue")], duration=100, loop=0)
        for name, data in [("document.pdf", b"%PDF-synthetic-only"), ("animated.png", out.getvalue()),
                           ("invalid.jpg", b"invalid")]:
            with self.subTest(name=name):
                self.write("TEST", name, data)
                self.record.files_json = json.dumps([name])
                self.m.db.session.commit()
                self.assertEqual(self.get(name, follow_redirects=True).data, data)
        self.record.files_json = json.dumps(["avatar.jpg"])
        self.m.db.session.commit()
        self.assertEqual(self.get(size=999, follow_redirects=True).data, self.original)

    def test_list_is_lazy_but_detail_keeps_its_original_source(self):
        page = self.client.get("/pointouts?page_size=10").get_data(as_text=True)
        self.assertIn("thumb=160", page)
        self.assertIn('loading="lazy"', page)
        self.assertIn("320w", page)
        detail = self.client.get(f"/pointouts/{self.record.id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("/files/uploads/avatar.jpg", detail.get_data(as_text=True))
        self.assertNotIn("thumb=160", detail.get_data(as_text=True))

    def test_s3_thumbnail_checks_live_revision_and_closes_the_source(self):
        from botocore.exceptions import ClientError
        class S3:
            version, denied = "v1", False
            def __init__(fake):
                fake.heads, fake.reads, fake.bodies = 0, [], []
            def head_object(fake, **kw):
                fake.heads += 1
                if fake.denied:
                    raise ClientError({"Error": {"Code": "AccessDenied"}}, "HeadObject")
                return {"VersionId": fake.version, "ETag": fake.version}
            def get_object(fake, **kw):
                if fake.denied:
                    raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")
                fake.reads.append(kw)
                body = BytesIO(profiles.picture("red" if fake.version == "v1" else "blue"))
                fake.bodies.append(body)
                return {"Body": body}
        fake = S3()
        self.m.app.extensions["dkss"]["s3_client"] = fake
        self.m.app.config["S3_BUCKET_NAME"] = "synthetic-only"
        self.addCleanup(self.m.app.extensions["dkss"].__setitem__, "s3_client", None)
        self.addCleanup(self.m.app.config.__setitem__, "S3_BUCKET_NAME", "")
        first = self.get().data
        self.assertEqual(self.get().data, first)
        self.assertEqual((fake.heads, len(fake.reads)), (2, 1))
        self.assertEqual(fake.reads[0]["Key"], "uploads/TEST/avatar.jpg")
        self.assertEqual(fake.reads[0]["VersionId"], "v1")
        self.assertTrue(fake.bodies[0].closed)
        fake.version = "v2"
        self.assertNotEqual(self.get().data, first)
        fake.denied = True
        self.assertEqual(self.get().status_code, 404)
        self.assertFalse(profile_images.cache().values)

    def test_simultaneous_same_file_misses_are_bounded_and_reused(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier, Lock
        import time
        state = dict(company_code="TEST", username="admin", role="admin",
            account_identity=self.user.account_identity, password_changed_at=self.user.password_changed_at)
        barrier, lock = Barrier(6), Lock()
        active = maximum = calls = 0
        encode = profile_images._encode
        def measured(*args):
            nonlocal active, maximum, calls
            with lock:
                active += 1
                calls += 1
                maximum = max(maximum, active)
            try:
                time.sleep(.05)
                return encode(*args)
            finally:
                with lock:
                    active -= 1
        def fetch(_):
            with self.m.app.test_client() as client:
                with client.session_transaction() as session:
                    session.update(state)
                barrier.wait(timeout=10)
                response = client.get("/files/uploads/avatar.jpg?thumb=320")
                self.assertEqual(response.status_code, 200)
                return response.data
        with patch.object(profile_images, "_encode", side_effect=measured):
            with ThreadPoolExecutor(max_workers=6) as pool:
                results = list(pool.map(fetch, range(6)))
        self.assertEqual(len(set(results)), 1)
        self.assertLessEqual(maximum, 2)
        self.assertLessEqual(calls, 2)
