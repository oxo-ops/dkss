"""Private display derivatives; never rewrite originals or cache authorization."""
from collections import OrderedDict
from io import BytesIO
from pathlib import Path
from threading import RLock, BoundedSemaphore

from botocore.exceptions import BotoCoreError, ClientError
from flask import current_app, request, send_file, session
from PIL import Image, ImageOps, UnidentifiedImageError

SIZES = {96, 192}
THUMBNAIL_SIZES = {160, 320, 480}


class DisplayImages:
    def __init__(self, max_bytes=8 * 1024 * 1024, max_entries=128):
        self.values = OrderedDict()
        self.bytes = 0
        self.max_bytes, self.max_entries = max_bytes, max_entries
        self.lock = RLock()
        self.conversions = BoundedSemaphore(2)

    def get(self, key):
        with self.lock:
            value = self.values.get(key)
            if value is not None:
                self.values.move_to_end(key)
            return value

    def put(self, key, value):
        if len(value) > self.max_bytes:
            return
        with self.lock:
            old = self.values.pop(key, None)
            self.bytes -= len(old) if old is not None else 0
            self.values[key] = value
            self.bytes += len(value)
            while self.bytes > self.max_bytes or len(self.values) > self.max_entries:
                _, removed = self.values.popitem(last=False)
                self.bytes -= len(removed)

    def forget(self, company, filename):
        with self.lock:
            for key in list(self.values):
                if key[:2] == (company, filename):
                    self.bytes -= len(self.values.pop(key))


def cache():
    return current_app.extensions.setdefault("profile_display_images", DisplayImages())


def forget(company, filename):
    existing = current_app.extensions.get("profile_display_images")
    if existing:
        existing.forget(company, filename)


def source_revision(company, filename):
    """Validate existence/version on EVERY request, including derivative hits."""
    app = current_app
    client, bucket = app.extensions["dkss"]["s3_client"], app.config["S3_BUCKET_NAME"]
    if client and bucket:
        for key in (f"uploads/{company}/{filename}", f"uploads/{filename}"):
            try:
                meta = client.head_object(Bucket=bucket, Key=key)
            except ClientError as error:
                if str(error.response.get("Error", {}).get("Code")) in {"404", "NoSuchKey", "NotFound"}:
                    continue
                raise
            version, etag = meta.get("VersionId"), meta.get("ETag")
            if not version and not etag:
                return None
            revision = ("s3", bucket, key, version, etag, str(meta.get("LastModified")), meta.get("ContentLength"))
            params = {"Bucket": bucket, "Key": key}
            if version and version != "null":
                params["VersionId"] = version
            elif etag:
                params["IfMatch"] = etag
            else:
                return None

            def read(params=params):
                body = client.get_object(**params)["Body"]
                try:
                    return body.read()
                finally:
                    body.close()
            return revision, read
        return None

    root = (Path(app.static_folder) / "uploads").resolve()
    for parts in ((company, filename), (filename,)):
        path = root.joinpath(*parts).resolve()
        if not path.is_relative_to(root):
            return None
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        if not path.is_file():
            continue
        revision = ("local", str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino)
        return revision, path.read_bytes
    return None


def display_avatar(filename):
    """Called only AFTER uploaded_file's existing login/company/file checks."""
    size = request.args.get("avatar", type=int)
    if size not in SIZES or filename != session.get("profile_image"):
        return None
    return _display(filename, size, False)


def display_thumbnail(filename):
    """Opt-in list thumbnails, after the ORIGINAL file authorization checks."""
    size = request.args.get("thumb", type=int)
    if size not in THUMBNAIL_SIZES or Path(filename).suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return None
    return _display(filename, size, True)


def _encode(read, size, crop, *, lossless=False, width_only=False):
    with Image.open(BytesIO(read())) as image:
        if getattr(image, "is_animated", False):
            return None  # Animation keeps the original response path.
        icc = image.info.get("icc_profile")
        if not lossless:
            image.draft("RGB", (size * 2, size * 2))
        image = ImageOps.exif_transpose(image)
        if crop:
            image = ImageOps.fit(image, (size, size * 3 // 4), Image.Resampling.LANCZOS)
        else:
            image.thumbnail((size, image.height if width_only else size), Image.Resampling.LANCZOS)
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA" if "transparency" in image.info else "RGB")
        output = BytesIO()
        image.save(output, format="WEBP", quality=85, method=4,
                   lossless=lossless, exact=lossless, icc_profile=icc or b"")
        return output.getvalue()


def _display(filename, size, crop):
    company, username = session.get("company_code"), session.get("username")
    if not company or not username:
        return None
    try:
        source = source_revision(company, filename)
        if source is None:
            forget(company, filename)
            return None
        revision, read = source
        images = cache()
        key = (company, filename, username, session.get("account_identity"), revision, size, crop)
        data = images.get(key)
        if data is None:
            # Bound simultaneous decodes; cache hits do not wait for conversions.
            with images.conversions:
                data = images.get(key)
                if data is None:
                    data = _encode(read, size, crop)
                    if data is None:
                        return None
                    images.put(key, data)
        # HTTP/browser caches remain no-store; authorization is rechecked next time.
        return send_file(BytesIO(data), mimetype="image/webp", max_age=0)
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError, ClientError, BotoCoreError):
        forget(company, filename)
        return None  # Existing original handling, including its errors, stays intact.
