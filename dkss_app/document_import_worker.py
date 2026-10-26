"""One bounded background reader per web process; jobs themselves are persisted."""
import os
import threading
from .extensions import db

_lock = threading.Lock()


def start_worker(app):
    if app.testing or os.environ.get('DOCUMENT_IMPORT_WORKER_ENABLED','1') == '0':
        return
    with _lock:
        state = app.extensions.get('document_import_worker')
        if state and state['thread'].is_alive():
            state['wake'].set()
            return
        stopped, wake = threading.Event(), threading.Event()
        def run():
            from .document_import_queue import process_one
            while not stopped.is_set():
                try:
                    worked = process_one(app)
                except Exception:
                    with app.app_context():
                        db.session.rollback()
                        db.session.remove()
                    app.logger.exception('Document import queue iteration failed')
                    worked = False
                if not worked:
                    wake.wait(2)
                    wake.clear()
        thread = threading.Thread(target=run, daemon=True, name='document-import-worker')
        app.extensions['document_import_worker'] = {'thread':thread, 'stop':stopped, 'wake':wake}
        thread.start()


def stop_worker(app):
    state = app.extensions.get('document_import_worker')
    if state:
        state['stop'].set()
        state['wake'].set()
