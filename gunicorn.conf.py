"""Keep HTTP requests responsive while persisted OCR jobs run one at a time."""
import os

worker_class = 'gthread'
workers = int(os.environ.get('WEB_CONCURRENCY', '1'))
threads = int(os.environ.get('WEB_THREADS', '4'))
timeout = 120
graceful_timeout = 30


def post_worker_init(worker):
    from dkss_app.driving_access import initialize_driving_access
    initialize_driving_access(worker.wsgi)
    from dkss_app.vehicle_couplings import initialize_coupling_schema
    initialize_coupling_schema(worker.wsgi)
    from dkss_app.document_import_worker import start_worker
    start_worker(worker.wsgi)


def worker_exit(server, worker):
    from dkss_app.document_import_worker import stop_worker
    app = getattr(worker, "wsgi", None)
    if app is not None:
        stop_worker(app)
