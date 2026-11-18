"""Browser-only reuse of exact, public, content-versioned brand assets.

No authorization checks are skipped. Business/upload/document/image derivatives
and dynamic responses are never eligible.
"""
from flask import request, session

PUBLIC_ASSET_VERSIONS = {
    "images/alseon/wordmark.webp": "9738ba4ccf561378c7c2e616178cdccdd38a2edfe8c357cb63dbc30d80f9f5c9",
    "images/alseon/symbol.webp": "1d0f897854a13d8b62998a0d4a012d446a6dd0c3a92585c248c50c82aaf8a521",
}

def apply_bundled_asset_cache(response):
    filename = (request.view_args or {}).get("filename")
    version = PUBLIC_ASSET_VERSIONS.get(filename)
    if (request.endpoint == "static" and request.method in {"GET", "HEAD"}
            and response.status_code in {200, 304} and version
            and set(request.args) == {"v"} and request.args.getlist("v") == [version]
            and not session.modified and not session.permanent
            and not response.headers.getlist("Set-Cookie")):
        # Private avoids introducing a CDN/shared cache, even for these public bytes.
        # Version is the full source SHA256, verified in the asset contract test.
        response.headers["Cache-Control"] = "private, max-age=86400, immutable"
    elif request.endpoint == "static" and version:
        response.headers["Cache-Control"] = "private, no-store"
    return response
