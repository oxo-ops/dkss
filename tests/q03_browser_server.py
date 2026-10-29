"""Q03 browser-only acceptance on Q10's marked, owned PostgreSQL fixture."""
import hashlib, json, sys, threading, socket, atexit
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server
from q10_postgres_support import PostgresFixture

class Fixture(PostgresFixture, TestCase):
    pass

def main():
    ready = Path(sys.argv[1]).resolve()
    stop = ready.with_suffix('.stop')
    Fixture.setUpClass()
    atexit.register(Fixture.doClassCleanups)
    app, db, m = (Fixture.app, Fixture.db, Fixture.models)
    app.config.update(TESTING=False, WTF_CSRF_ENABLED=True, MFA_ENABLED=False)
    from dkss_app import notifications_delivery, checklist_common
    from dkss_app.checklist_notify_identity import VehicleChecklistNotifyAccount
    records = {}

    @app.after_request
    def marker(response):
        response.headers['X-Q03-Synthetic-Only'] = 'Q03_BROWSER_ONLY'
        return response

    @app.get('/__q03__/state')
    def state():

        def rows(model):
            return [{c.name: getattr(r, c.name) for c in model.__table__.columns} for r in model.query.order_by(model.id)]
        snapshot = {model.__tablename__: rows(model) for model in [m.ChecklistResult, m.VehicleChecklistResult, m.VehicleChecklistNotifySetting, VehicleChecklistNotifyAccount, m.ChecklistEvent, m.Notification, m.AuditLog]}
        case_states = {}
        for key, info in records.items():
            if info['kind'] == 'reminder':
                settings = m.VehicleChecklistNotifySetting.query.filter_by(company_code='Q03B', checklist_id=info['checklist_id'], vehicle_record_id=info['vehicle_id']).all()
                case_states[key] = {'settings': [{'id': s.id, 'names': json.loads(s.notify_users_json)} for s in settings]}
                continue
            model = m.ChecklistResult if info['kind'] == 'safety' else m.VehicleChecklistResult
            r = db.session.get(model, info['id'])
            events = m.ChecklistEvent.query.filter_by(company_code='Q03B', result_type=info['kind'], result_id=r.id).order_by(m.ChecklistEvent.id).all()
            notices = [n for n in m.Notification.query.all() if (n.link or '').split('#')[0] == info['page']]
            case_states[key] = {'status': r.status, 'answers': json.loads(r.answers_json), 'approvals': json.loads(r.approvals_json), 'events': [{'id': e.id, 'kind': e.event_type, 'actor_identity': e.actor_identity} for e in events], 'notifications': [{'id': n.id, 'title': n.title, 'owner_identity': n.owner_identity} for n in notices]}
        return {'marker': 'Q03_BROWSER_ONLY', 'csrf_enabled': app.config['WTF_CSRF_ENABLED'], 'dialect': db.engine.dialect.name, 'cases': case_states, 'snapshot_sha256': hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest()}
    with app.app_context():
        db.create_all()
        db.session.add(m.Company(company_code='Q03B', company_name='Synthetic Q03', active=True, vehicle_limit=30))
        db.session.add(m.Office(company_code='Q03B', name='Synthetic Office'))
        for username, role in [('admin', 'admin'), ('checker', 'user'), ('approver', 'user'), ('other', 'user')]:
            db.session.add(m.User(company_code='Q03B', username=username, role=role, password=generate_password_hash('Q03-Browser-Synthetic-742!'), last_name='Synthetic', first_name=username, office='Synthetic Office', password_changed_at='2026-10-29 10:00:00'))
        db.session.add(m.Driver(company_code='Q03B', employee_id='checker', name='Syntheticchecker', office='Synthetic Office'))
        db.session.commit()
        checker = m.User.query.filter_by(company_code='Q03B', username='checker').one()
        for device, day in [('pc', '23'), ('phone', '24')]:
            for kind in ['safety', 'vehicle', 'reminder']:
                key = device + '-' + kind
                items = [{'item_type': 'check', 'category': 'Synthetic', 'content': 'Q03 answer ' + key, 'input_type': 'text', 'answer_required': False}, {'item_type': 'approval', 'approval_label': 'Record review', 'approval_allow_general': True}]
                cl = m.Checklist(company_code='Q03B', name='Browser ' + key, target='安全管理' if kind == 'safety' else '車両管理', frequency_unit='day', display_type='month', active=True, items_json=json.dumps(items))
                db.session.add(cl)
                db.session.flush()
                snapshot = checklist_common.checklist_to_dict(cl)
                vehicle = None
                if kind != 'safety':
                    vehicle = m.Vehicle(company_code='Q03B', chassis_number='BROWSER-' + key, office='Synthetic Office', deleted=False)
                    db.session.add(vehicle)
                    db.session.flush()
                page = f'/vehicle/checklists/{cl.id}?vehicle_record_id={vehicle.id}&year=2026&month=10&active_day={day}' if vehicle else None
                if kind == 'reminder':
                    records[key] = {'kind': kind, 'page': page, 'checklist_id': cl.id, 'vehicle_id': vehicle.id}
                    continue
                values = dict(company_code='Q03B', checklist_id=cl.id, checked_by='Syntheticchecker', checked_by_username='checker', checked_by_user_id=checker.id, checked_by_identity=checker.account_identity, checked_date='2026-10-' + day + ' 10:00', status='承認待ち', approvals_json=json.dumps([{'label': 'Record review', 'allow_general': True, 'candidate_usernames': [], 'candidate_user_ids': [], 'candidate_identities': [], 'approved_by': '', 'approved_by_username': '', 'approved_date': ''}]), answers_json=json.dumps([{'item_no': 0, 'content': 'Q03 answer ' + key, 'category': 'Synthetic', 'input_type': 'text', 'value': 'OLD_ANSWER_' + key, 'comment': '', 'files': []}]), checklist_snapshot_json=json.dumps(snapshot))
                if kind == 'safety':
                    r = m.ChecklistResult(**values, target_type='user', target_user='Syntheticchecker', target_username='checker', target_user_id=checker.id, target_identity=checker.account_identity)
                else:
                    r = m.VehicleChecklistResult(**values, vehicle_record_id=vehicle.id, year='2026', month='10', day=day)
                db.session.add(r)
                db.session.flush()
                if kind == 'safety':
                    page = f'/safety/checklist-results/{r.id}'
                records[key] = {'kind': kind, 'id': r.id, 'page': page, 'checklist_id': cl.id, 'vehicle_id': vehicle.id if vehicle else None, 'day': day}
        db.session.commit()
    original_connect = socket.socket.connect

    def loopback_only(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', 'localhost', '::1'):
            raise RuntimeError('External connection blocked in Q03 browser acceptance')
        return original_connect(sock, address)
    server = make_server('127.0.0.1', 0, app, threaded=True)
    try:
        with patch.object(notifications_delivery, 'dispatch_external_notification', return_value=None), patch.object(socket.socket, 'connect', loopback_only):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            ready.write_text(json.dumps({'marker': 'Q03_BROWSER_ONLY', 'url': f'http://127.0.0.1:{server.server_port}', 'company': 'Q03B', 'password': 'Q03-Browser-Synthetic-742!', 'records': records, 'schema': Fixture.schema, 'csrf_enabled': True}), encoding='utf8')
            print('Q03_BROWSER_READY', server.server_port, flush=True)
            while not stop.exists():
                threading.Event().wait(0.2)
    finally:
        server.shutdown()
        with app.app_context():
            db.session.remove()
        Fixture.doClassCleanups()
if __name__ == '__main__':
    main()
