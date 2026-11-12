"""Opt-in, bounded analysis runner. No request hook, schema mutation or AI on GET.

PostgreSQL session advisory leadership is held on one dedicated connection, not
on the ORM connection whose per-job commits must not release the leader gate.
"""
from contextlib import contextmanager
import logging
import os
import threading
from datetime import datetime, timezone

from sqlalchemy import text

from .extensions import db

INTERVAL_SECONDS = 60
SCAN_LIMIT = 20
JOB_LIMIT = 1
LOCK_NAMESPACE = 1145787219
LOCK_KEY = 1
_start_lock = threading.Lock()


class Leadership:
    def __init__(self, connection):
        self.connection = connection
        self.backend = connection.execute(text("SELECT pg_backend_pid()")).scalar_one()

    def check(self):
        # A reconnected SQLAlchemy connection does not own the old session lock.
        if self.connection.invalidated or self.connection.closed:
            raise RuntimeError("ANALYSIS_LEADERSHIP_LOST")
        backend = self.connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
        if backend != self.backend:
            raise RuntimeError("ANALYSIS_LEADERSHIP_LOST")


class LocalOwnership:
    def check(self):
        pass


@contextmanager
def leadership(app, *, allow_local=False):
    """Busy returns None. Unsupported web databases fail closed without DDL.

    allow_local preserves the existing explicitly invoked SQLite CLI only. The
    web runner never uses it and no cross-process SQLite guarantee is implied.
    """
    with app.app_context():
        engine = db.engine
        if engine.dialect.name != "postgresql":
            if allow_local and engine.dialect.name == "sqlite":
                yield LocalOwnership()
                return
            raise RuntimeError("ANALYSIS_RUNTIME_REQUIRES_POSTGRESQL")
        connection = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    acquired = False
    try:
        acquired = bool(connection.execute(text(
            "SELECT pg_try_advisory_lock(:namespace, :key)"
        ), {"namespace": LOCK_NAMESPACE, "key": LOCK_KEY}).scalar_one())
        if not acquired:
            yield None
            return
        owner = Leadership(connection)
        # Verify critical schema read-only. Startup does not initialize/migrate it.
        from .models import VehicleKarteAnalysis, Vehicle, Company, AnalysisInputEpoch, ChecklistEvent
        for model in (VehicleKarteAnalysis, Vehicle, Company, AnalysisInputEpoch, ChecklistEvent):
            connection.execute(model.__table__.select().limit(0))
        yield owner
    finally:
        if acquired:
            try:
                connection.execute(text("SELECT pg_advisory_unlock(:namespace, :key)"),
                    {"namespace": LOCK_NAMESPACE, "key": LOCK_KEY})
            except Exception:
                # Never return a possibly locked session to the pool.
                connection.invalidate()
        connection.close()


def scan_batch(app, cursor, *, ownership_check=lambda: None, stopped=None):
    """Keyset scan at most 20 vehicles, retaining normal fingerprint scheduling."""
    from . import analysis
    from .models import Vehicle, Company
    targets = db.session.query(Vehicle.id, Vehicle.company_code).join(
        Company, Company.company_code == Vehicle.company_code,
    ).filter(Vehicle.deleted.is_(False), Company.active.is_(True), Vehicle.id > cursor
    ).order_by(Vehicle.id).limit(SCAN_LIMIT + 1).all()
    db.session.remove()
    scanned = errors = 0
    next_cursor = cursor
    for vehicle_id, company_code in targets[:SCAN_LIMIT]:
        if stopped is not None and stopped.is_set():
            break
        ownership_check()
        next_cursor = vehicle_id
        try:
            vehicle = Vehicle.query.filter_by(id=vehicle_id, company_code=company_code,
                deleted=False).first()
            if vehicle is not None:
                with app.test_request_context("/"):
                    payload, _ = analysis.get_vehicle_karte_analysis_job_data(vehicle)
                ownership_check()
                analysis.queue_vehicle_karte_analysis(vehicle, payload)
                db.session.commit()
                scanned += 1
        except Exception as error:
            db.session.rollback()
            errors += 1
            app.logger.warning("ANALYSIS_SCAN_FAILED vehicle_id=%s error_type=%s",
                vehicle_id, type(error).__name__)
        finally:
            db.session.remove()
    if len(targets) <= SCAN_LIMIT and not (stopped is not None and stopped.is_set()):
        next_cursor = 0
    return next_cursor, scanned, errors


def run_due_job(app, *, ownership_check=lambda: None):
    """At most one due job. Per-job atomic claim/fenced save remain authoritative."""
    from . import analysis
    from .models import VehicleKarteAnalysis as State, Vehicle, Company
    ownership_check()
    now = datetime.now(timezone.utc)
    due = db.session.query(State.id).join(Vehicle, db.and_(
        Vehicle.id == State.vehicle_record_id, Vehicle.company_code == State.company_code,
    )).join(Company, Company.company_code == Vehicle.company_code).filter(
        Vehicle.deleted.is_(False), Company.active.is_(True),
        State.status.in_({"pending", "error", "running"}), State.next_analysis_at <= now,
        db.or_(State.lease_expires_at.is_(None), State.lease_expires_at <= now),
    ).order_by(State.next_analysis_at, State.id).limit(JOB_LIMIT).all()
    db.session.remove()
    completed = failed = 0
    for (state_id,) in due:
        try:
            if analysis.run_vehicle_karte_analysis_job(state_id, ownership_check=ownership_check):
                completed += 1
            else:
                failed += 1
        except Exception as error:
            db.session.rollback()
            failed += 1
            app.logger.warning("ANALYSIS_JOB_FAILED state_id=%s error_type=%s",
                state_id, type(error).__name__)
        finally:
            db.session.remove()
    return completed, failed


def run_worker(app, stopped):
    if app.logger.getEffectiveLevel() > logging.INFO:
        app.logger.setLevel(logging.INFO)
    while not stopped.is_set():
        try:
            with leadership(app) as owner:
                if owner is None:
                    app.logger.info("ANALYSIS_WORKER_STANDBY")
                else:
                    app.logger.info("ANALYSIS_WORKER_STARTED scan_limit=%s job_limit=%s interval=%s",
                        SCAN_LIMIT, JOB_LIMIT, INTERVAL_SECONDS)
                    cursor = 0
                    while not stopped.is_set():
                        owner.check()
                        with app.app_context():
                            try:
                                cursor, scanned, scan_errors = scan_batch(app, cursor,
                                    ownership_check=owner.check, stopped=stopped)
                                completed, failed = (0, 0) if stopped.is_set() else run_due_job(
                                    app, ownership_check=owner.check)
                                app.logger.info(
                                    "ANALYSIS_WORKER_HEARTBEAT cursor=%s scanned=%s scan_errors=%s completed=%s failed=%s",
                                    cursor, scanned, scan_errors, completed, failed)
                            finally:
                                db.session.remove()
                        stopped.wait(INTERVAL_SECONDS)
        except Exception as error:
            with app.app_context():
                db.session.rollback()
                db.session.remove()
            app.logger.error("ANALYSIS_WORKER_ITERATION_FAILED error_type=%s", type(error).__name__)
        if not stopped.is_set():
            stopped.wait(INTERVAL_SECONDS)
    app.logger.info("ANALYSIS_WORKER_STOPPED")


def start_worker(app):
    # Explicit rollout decision: neither deployment nor an imported app enables AI.
    if app.testing or os.environ.get("VEHICLE_ANALYSIS_WORKER_ENABLED", "0") != "1":
        return
    with _start_lock:
        state = app.extensions.get("vehicle_analysis_worker")
        if state and state["thread"].is_alive():
            return
        stopped = threading.Event()
        thread = threading.Thread(target=run_worker, args=(app, stopped), daemon=True,
            name="vehicle-analysis-worker")
        app.extensions["vehicle_analysis_worker"] = {"thread": thread, "stop": stopped}
        thread.start()


def stop_worker(app):
    state = app.extensions.get("vehicle_analysis_worker")
    if state:
        state["stop"].set()
