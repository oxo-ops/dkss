"""Loopback-only, synthetic PostgreSQL server for the Q10 browser drill.

No fixture is inserted through a production application. This process builds a
new owned schema and mocks only external OCR and delivery; CSRF stays enabled.
"""
import hashlib
import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server
from sqlalchemy import text

from q10_postgres_support import PostgresFixture
from test_inspection_document_ai import extraction, pdf_bytes


class Fixture(PostgresFixture, TestCase):
    pass


def main():
    ready_path = Path(sys.argv[1]).resolve()
    stop_path = ready_path.with_suffix('.stop')
    Fixture.setUpClass()
    app, db, m = Fixture.app, Fixture.db, Fixture.models
    app.config.update(TESTING=False, WTF_CSRF_ENABLED=True, MFA_ENABLED=False)
    from dkss_app import document_import_queue as queue, vehicle_imports, notifications_delivery
    attempts = {}

    @app.after_request
    def synthetic_marker(response):
        response.headers['X-Q10-Synthetic-Only'] = 'Q10_SYNTHETIC_ONLY'
        return response

    def extract(source, filename=None, progress_callback=None):
        key = hashlib.sha256(source).hexdigest()
        attempts[key] = attempts.get(key, 0) + 1
        if attempts[key] == 1:
            raise RuntimeError('OPENAI_NETWORK_OR_TIMEOUT: q10-synthetic-failure')
        return extraction(source)

    @app.get('/__q10__/state')
    def state():
        return dict(marker='Q10_SYNTHETIC_ONLY', dialect=db.engine.dialect.name,
                    vehicles=[r.chassis_number for r in m.Vehicle.query.order_by(m.Vehicle.id)],
                    inspections=m.VehiclePeriodicInspectionRecord.query.count(),
                    drafts=m.VehicleDocumentImportDraft.query.count(), attempts=attempts)

    with app.app_context():
        db.create_all()
        stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        db.session.add(m.Company(company_code='Q10', company_name='Q10 synthetic', active=True, vehicle_limit=30))
        db.session.add(m.Office(company_code='Q10', name='Q10 Office'))
        db.session.add(m.VehicleType(company_code='Q10', name='Q10 Type'))
        db.session.add(m.User(company_code='Q10', username='admin', role='admin',
            password=generate_password_hash('Q10-Synthetic-742!'), last_name='Synthetic', first_name='Admin',
            office='Q10 Office', password_changed_at=stamp))
        vehicle = m.Vehicle(company_code='Q10', chassis_number='TEST-001', office='Q10 Office', type='Q10 Type')
        db.session.add(vehicle)
        db.session.flush()
        source = pdf_bytes()
        draft = m.VehicleDocumentImportDraft(id='q10-browser-driving', batch_id='q10-browser-driving',
            company_code='Q10', created_by_username='admin', document_type='driving_report',
            status='completed', source_filename='synthetic-driving.pdf', source_file=source,
            source_sha256=hashlib.sha256(source).hexdigest(), preview_json='{}', result_json='{}')
        db.session.add(draft)
        db.session.flush()
        for day in range(1, 31):
            payload = dict(driver_name='Synthetic Admin', driver_code='Q10-DRIVER',
                source_system='q10-synthetic', record_date=f'2026-09-{day:02d}',
                distance='100', report_scope='daily', report_items=[], source_pages=[1])
            db.session.add(m.VehicleDrivingReportRecord(company_code='Q10', vehicle_record_id=vehicle.id,
                operation_date=payload['record_date'], content=f'Q10 synthetic {day}',
                details_json=json.dumps(payload), source_draft_id=draft.id, source_record_index=day,
                created_by_username='admin'))
        db.session.commit()
    upload_path = ready_path.with_suffix('.pdf')
    upload_path.write_bytes(pdf_bytes())
    stopping = threading.Event()
    def worker():
        while not stopping.wait(.2):
            queue.process_one(app)
    server = make_server('127.0.0.1', 0, app, threaded=True)
    patches = [patch.object(vehicle_imports, 'vehicle_document_extractor', return_value=extract),
               patch.object(queue, 'detect_document_types', return_value={'types':['inspection'], 'certainty':'clear', 'supported':True}),
               patch.object(notifications_delivery, 'dispatch_external_notification', return_value=None)]
    try:
        for item in patches:
            item.start()
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        worker_thread = threading.Thread(target=worker, daemon=True)
        server_thread.start()
        worker_thread.start()
        ready_path.write_text(json.dumps(dict(url=f'http://127.0.0.1:{server.server_port}',
            company='Q10', username='admin', password='Q10-Synthetic-742!', dialect='postgresql',
            upload_path=str(upload_path))), encoding='utf-8')
        print('Q10_BROWSER_READY', server.server_port, flush=True)
        while not stopping.wait(.2):
            if stop_path.exists():
                break
    finally:
        stopping.set()
        server.shutdown()
        worker_thread.join(10)
        for item in reversed(patches):
            item.stop()
        with app.app_context():
            db.session.remove()
        Fixture.doClassCleanups()


if __name__ == '__main__':
    main()
