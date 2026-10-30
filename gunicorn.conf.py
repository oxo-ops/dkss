"""Keep HTTP requests responsive while persisted OCR jobs run one at a time."""
import os

# Compatibility recovery profile: the Web process must not consume OCR jobs,
# including when a status GET attempts to wake the in-process worker. Run the
# existing document-import-worker CLI separately at this exact release SHA.
# This does not stop an already-running old process or reclaim its live lease.
os.environ['DOCUMENT_IMPORT_WORKER_ENABLED'] = '0'

worker_class = 'gthread'
workers = int(os.environ.get('WEB_CONCURRENCY', '1'))
threads = int(os.environ.get('WEB_THREADS', '4'))
timeout = 120
graceful_timeout = 30


def post_worker_init(worker):
    # Gunicorn reapplies cfg.env after loading this file (including --env and
    # GUNICORN_CMD_ARGS). Reassert in each initialized worker before requests.
    os.environ['DOCUMENT_IMPORT_WORKER_ENABLED'] = '0'
    from dkss_app.driving_access import initialize_driving_access
    initialize_driving_access(worker.wsgi)
    from dkss_app.vehicle_couplings import initialize_coupling_schema
    initialize_coupling_schema(worker.wsgi)


def worker_exit(server, worker):
    from dkss_app.document_import_worker import stop_worker
    app = getattr(worker, "wsgi", None)
    if app is not None:
        stop_worker(app)
