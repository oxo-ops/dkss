"""Uncropped, losslessly encoded display images for already-authorized DB originals.

No authorization or HTTP responses are cached. Call only after the original
vehicle/company/completed-document checks. Downloads always use the original.
"""
import hashlib
from io import BytesIO

from flask import session
from PIL import Image, UnidentifiedImageError

from .profile_images import cache, _encode

WIDTHS = (384, 768)


def preview(draft, vehicle_id):
    if not session.get("username") or draft.company_code != session.get("company_code"):
        return None
    source = draft.source_file
    if not source:
        return None
    try:
        with Image.open(BytesIO(source)) as image:
            if getattr(image, "is_animated", False):
                return None
            width, height = image.size
            if image.getexif().get(274) in (5, 6, 7, 8):
                width, height = height, width
        # Hash actual bytes, never trust a possibly stale persisted source_sha256.
        revision = (vehicle_id, hashlib.sha256(source).hexdigest())
        images, variants = cache(), {}
        for size in WIDTHS:
            if size >= width:
                continue  # No upscaling or misleading width descriptors.
            key = (draft.company_code, "document:" + draft.id, session["username"],
                   session.get("account_identity"), revision, size, "lossless-width")
            data = images.get(key)
            if data is None:
                with images.conversions:
                    data = images.get(key)
                    if data is None:
                        data = _encode(lambda: source, size, False, lossless=True, width_only=True)
                        if data is not None:
                            # A zero-byte sentinel avoids re-encoding a variant
                            # that would cost more bandwidth than the original.
                            if len(data) >= len(source):
                                data = b""
                            images.put(key, data)
            if data:
                variants[size] = data  # Do not offer a larger derivative.
        return dict(width=width, height=height, variants=variants)
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        return None  # Preserve original handling for unsupported/damaged images.
