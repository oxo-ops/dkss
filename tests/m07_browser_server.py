"""Synthetic local SQLite + real HTTP/CSRF; only existing mocked OCR seeds data."""
import hashlib
import json
from pathlib import Path
import sys
import threading
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server
from test_q07_invoice_read_corrections import InvoiceReadCorrectionTests as Cases


def main():
    ready = Path(sys.argv[1]).resolve()
    stop = ready.with_suffix('.stop')
    Cases.setUpClass()
    case = Cases('test_primary_read_then_addition_replacement_preserves_source_and_history')
    case.setUp()
    m, app = case.m, case.m.app

    @app.after_request
    def marker(response):
        response.headers['X-M07-Synthetic-Only'] = 'M07_SYNTHETIC_ONLY'
        return response

    @app.get('/__m07__/state')
    def state():
        record = m.VehicleMaintenanceRecord.query.one()
        return dict(marker='M07_SYNTHETIC_ONLY', total=str(record.total_cost),
            details=json.loads(record.invoice_details_json or '{}'),
            events=[json.loads(e.changes_json) for e in m.VehicleMaintenanceRecordEvent.query.order_by(m.VehicleMaintenanceRecordEvent.id)],
            documents=[dict(id=d.id, status=d.financial_status, payload=json.loads(d.payload_json),
                            decision=json.loads(d.decision_json)) for d in m.VehicleMaintenanceDocument.query.all()],
            originals=[dict(id=d.id, stored=d.source_sha256,
                            actual=hashlib.sha256(d.source_file).hexdigest(),
                            preview=json.loads(d.preview_json)) for d in m.VehicleDocumentImportDraft.query.all()])

    mode = sys.argv[2] if len(sys.argv) > 2 else 'normal'
    primary = None
    if mode == 'manual':
        row = case.target('500')
    else:
        row, primary, _ = case.imported()
    extra, _ = case.additional(row)
    case.assertEqual(case.review(extra).status_code, 302)
    pending, _ = case.additional(row, '20')
    legacy = mode == 'legacy'
    if legacy:
        case.legacy_total(row)
    m.User.query.filter_by(company_code='TEST', username='admin').one().password = generate_password_hash('M07-Synthetic-742!')
    m.db.session.commit()
    fixture = dict(company='TEST', username='admin', password='M07-Synthetic-742!',
                   vehicle_id=case.vehicle.id, record_id=row.id,
                   primary_key='primary:' + primary.id + ':0' if primary else None, extra_id=extra.id,
                   pending_id=pending.id, legacy=legacy, manual=mode == 'manual')
    case.tearDown()
    app.config.update(TESTING=False, WTF_CSRF_ENABLED=True, MFA_ENABLED=False)


    server = make_server('127.0.0.1', 0, app, threaded=True)
    fixture['url'] = 'http://127.0.0.1:' + str(server.server_port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    try:
        thread.start()
        ready.write_text(json.dumps(fixture), encoding='utf-8')
        print('M07_BROWSER_READY', flush=True)
        while not stop.exists():
            threading.Event().wait(.2)
    finally:
        server.shutdown()
        thread.join(10)
        Cases.tearDownClass()


if __name__ == '__main__':
    main()
