"""One bounded background reader per web process; jobs themselves are persisted."""

import os
import threading
from .extensions import db

_lock = threading.Lock()


def run_worker(app, stopped, wake=None):
    import logging
    import time
    from .document_import_queue import process_one
    from .models import VehicleDocumentImportDraft as Draft

    wake = wake or threading.Event()
    heartbeat_at = 0
    if app.logger.getEffectiveLevel() > logging.INFO:
        app.logger.setLevel(logging.INFO)
    app.logger.info("OCR_WORKER_STARTED")
    while not stopped.is_set():
        try:
            worked = process_one(app)
            if time.monotonic() >= heartbeat_at:
                with app.app_context():
                    counts = dict(
                        db.session.query(Draft.status, db.func.count(Draft.id))
                        .group_by(Draft.status)
                        .all()
                    )
                    db.session.remove()
                app.logger.info(
                    "OCR_WORKER_HEARTBEAT queued=%s reading=%s failed=%s",
                    counts.get("queued", 0),
                    counts.get("reading", 0),
                    counts.get("read_error", 0),
                )
                heartbeat_at = time.monotonic() + 60
        except Exception:
            with app.app_context():
                db.session.rollback()
                db.session.remove()
            app.logger.exception("Document import queue iteration failed")
            worked = False
        if not worked and not stopped.is_set():
            wake.wait(2)
            wake.clear()


def start_worker(app):
    if app.testing or os.environ.get("DOCUMENT_IMPORT_WORKER_ENABLED", "1") == "0":
        return
    with _lock:
        state = app.extensions.get("document_import_worker")
        if state and state["thread"].is_alive():
            state["wake"].set()
            return
        stopped, wake = threading.Event(), threading.Event()

        def run():
            run_worker(app, stopped, wake)

        thread = threading.Thread(
            target=run, daemon=True, name="document-import-worker"
        )
        app.extensions["document_import_worker"] = {
            "thread": thread,
            "stop": stopped,
            "wake": wake,
        }
        thread.start()


def stop_worker(app):
    state = app.extensions.get("document_import_worker")
    if state:
        state["stop"].set()
        state["wake"].set()
