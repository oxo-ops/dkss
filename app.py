"""Backward-compatible WSGI/Flask entry point. No schema changes on import.

Initialize or upgrade an existing database explicitly with:
    flask --app app init-db
"""
from dkss_app import create_app
from dkss_app.compat import PUBLIC_SYMBOLS, resolve

app = create_app()
__all__ = [*PUBLIC_SYMBOLS, "create_app"]


def __getattr__(name):
    return resolve(name, app)


if __name__ == "__main__":
    app.run(debug=False)
