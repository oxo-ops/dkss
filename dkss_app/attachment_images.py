"""Uncropped display copies, AFTER original attachment authorization.

No original writes and no authorization caching. Unsupported files use the
unchanged original route. Clicking/downloads continue to use that original.
"""
from io import BytesIO
from pathlib import Path
from flask import request, session, send_file
from PIL import Image, ImageOps, UnidentifiedImageError
from threading import BoundedSemaphore
from botocore.exceptions import BotoCoreError, ClientError
from . import profile_images

WIDTHS = {480, 960}
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_DECODE_PIXELS = 2_000_000
PREVIEW_SLOT = BoundedSemaphore(1)
MAX_PREVIEW_PIXELS = 16_000_000  # Avoid full decoding oversized originals in web workers.


def display_preview(filename):
    width = request.args.get("preview", type=int)
    company, user = session.get("company_code"), session.get("username")
    if (width not in WIDTHS or not company or not user
            or Path(filename).suffix.lower() not in {".jpg", ".jpeg"}):
        return None
    try:
        source = profile_images.source_revision(company, filename, max_source_bytes=MAX_SOURCE_BYTES)
        if source is None:
            profile_images.forget(company, filename)
            return None
        revision, read = source
        images = profile_images.cache()
        key = (company, filename, user, session.get("account_identity"), revision, width, "bounded-jpeg-v1")
        data = images.get(key)
        if data is None:
            if not PREVIEW_SLOT.acquire(blocking=False):
                return None
            try:
                data = images.get(key)
                if data is None:
                    original = read()
                    with Image.open(BytesIO(original)) as image:
                        if (image.format != "JPEG" or len(original) > MAX_SOURCE_BYTES
                                or image.width * image.height > MAX_PREVIEW_PIXELS
                                or getattr(image, "is_animated", False)
                                or image.mode != "RGB"):
                            return None
                        image_width = image.height if image.getexif().get(274) in (5, 6, 7, 8) else image.width
                        if image_width <= width:
                            return None
                    with Image.open(BytesIO(original)) as image:
                        effective = image.height if image.getexif().get(274) in (5,6,7,8) else image.width
                        scale = width / effective
                        image.draft("RGB", (max(1, int(image.width*scale)), max(1, int(image.height*scale))))
                        if image.width*image.height > MAX_DECODE_PIXELS:
                            return None
                        image = ImageOps.exif_transpose(image)
                        image.thumbnail((width, image.height), Image.Resampling.LANCZOS)
                        output = BytesIO()
                        image.save(output, format="WEBP", quality=85, method=3, icc_profile=image.info.get("icc_profile") or b"")
                        data = output.getvalue()
                    if not data or len(data) >= len(original):
                        data = b""  # Preserve original if derivative would be larger.
                    images.put(key, data)
            finally:
                PREVIEW_SLOT.release()
        if not data:
            return None
        response = send_file(BytesIO(data), mimetype="image/webp", max_age=0)
        response.cache_control.no_store = True
        return response
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError, ClientError, BotoCoreError):
        profile_images.forget(company, filename)
        return None
