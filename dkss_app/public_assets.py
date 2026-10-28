"""Lossless transfer encoding for the two measured, public code assets only."""
from functools import wraps
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import gzip

from flask import request, send_file
from werkzeug.exceptions import NotFound
from .profile_images import DisplayImages

ASSETS = {"css/style.css": "text/css", "js/base.js": "text/javascript"}


def install(app):
    original = app.view_functions["static"]

    @wraps(original)
    def static(**kwargs):
        filename = kwargs.get("filename")
        if filename not in ASSETS or not app.static_folder:
            return original(**kwargs)
        root = Path(app.static_folder).resolve()
        path = (root / filename).resolve()
        # Fixed public filenames cannot be redirected to private uploads by a
        # filesystem symlink. Other routes retain their existing authorization.
        if not path.is_relative_to(root / filename.split("/")[0]):
            raise NotFound()
        response = None
        if (request.method in {"GET", "HEAD"} and "Range" not in request.headers
                and request.accept_encodings["gzip"] > 0
                and request.accept_encodings["gzip"] >= request.accept_encodings["identity"]):
            try:
                revision = path.stat()
                # Reuse the byte-bounded LRU, in a SEPARATE app-local cache.
                cache = app.extensions.setdefault("public_asset_gzip",
                    DisplayImages(max_bytes=8*1024*1024, max_entries=16))
                key = (str(path), revision.st_mtime_ns, revision.st_ctime_ns, revision.st_size)
                data = cache.get(key)
                if data is None:
                    with cache.lock:
                        data = cache.get(key)
                        if data is None:
                            raw = path.read_bytes()
                            encoded = gzip.compress(raw, compresslevel=6, mtime=0)
                            if len(encoded) < len(raw):
                                data = encoded
                                cache.put(key, data)
                if data is not None:
                    response = send_file(BytesIO(data), mimetype=ASSETS[filename],
                        conditional=True, etag="gzip-"+sha256(data).hexdigest(),
                        last_modified=revision.st_mtime,
                        max_age=app.get_send_file_max_age(filename))
                    response.headers["Content-Encoding"] = "gzip"
            except OSError:
                pass  # Keep the original missing/unreadable-file response.
        if response is None:
            response = original(**kwargs)
        response.vary.add("Accept-Encoding")
        return response

    app.view_functions["static"] = static
