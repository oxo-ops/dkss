"""Synthetic loopback browser fixture in the guarded Q05 private PG schema."""
import argparse
from datetime import datetime as RealDatetime
import hashlib
import json
from pathlib import Path
import threading

from flask import g, has_request_context, jsonify, redirect, request, session
from werkzeug.serving import make_server

from test_q05_scheduled_safe_start_postgres import PostgresScheduledSafeStartTests as Fixture


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--work-dir', required=True)
    parser.add_argument('--port', type=int, default=51205)
    args = parser.parse_args()
    work = Path(args.work_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    control = work / 'clock.json'
    control.write_text(json.dumps({'instant': '2026-12-31T14:59:59+00:00'}), encoding='utf-8')
    Fixture.setUpClass()  # Requires loopback dkss_q05_ci; creates its own random schema.
    case = Fixture()
    case.setUp()
    try:
        case.seed('2027-01-01')
        m, app = case.m, case.m.app
        stamp = '2099-01-01 00:00:00'
        case.user.password_changed_at = stamp
        entries = [
            ('regular', '一般未来', '2027-01-01', 'user'),
            ('month', '月末未来', '2027-05-01', 'admin'),
            ('leap', 'うるう日起算', '2028-02-29', 'admin'),
            ('march', 'うるう月末', '2028-03-01', 'admin'),
            ('legacy', '旧表記起算', '2028-2-29', 'admin'),
            ('past', '過去起算', '2026-01-01', 'admin'),
            ('blank', '旧空欄', '', 'admin'),
            ('monthonly', '旧年月のみ', '2027-01', 'admin'),
            ('invalid', '旧不正日付', '2027-02-30', 'admin'),
            ('unknown', '旧未設定', None, 'admin'),
        ]
        for username, name, start, role in entries:
            m.db.session.add(m.User(company_code='TEST', username=username, last_name=name,
                password='unused-synthetic', password_changed_at=stamp, role=role,
                office='Tokyo', timezone='Asia/Tokyo'))
            m.db.session.add(m.Driver(company_code='TEST', employee_id=username, name=name,
                role=role, office='Tokyo', safe_start_date=start, vehicles_json='[]', licenses_json='[]'))
        case.user.timezone = 'Asia/Tokyo'
        m.db.session.add(m.Company(company_code='OTHER', company_name='架空他社'))
        m.db.session.add(m.Driver(company_code='OTHER', employee_id='foreign', name='他社除外',
            role='admin', office='Tokyo', safe_start_date='2000-01-01'))
        for value in ['2000-01-01 15:00:00', '2000-01-01T15:00:00Z']:
            m.db.session.add(m.Notification(company_code='TEST', target_username='admin',
                target_user='架空検証者', title='原文維持', message='架空履歴', created_at=value, read=False))
        m.db.session.add(m.AuditLog(company_code='TEST', username='admin', action='q05_fixture_history',
            detail='原文維持', created_at='2000-01-01 15:00:00'))
        m.db.session.commit()
        actors = {u.username: (u.account_identity, u.role) for u in m.User.query.filter_by(company_code='TEST')}

        def snapshot():
            drivers = [(d.company_code, d.employee_id, d.safe_start_date) for d in m.Driver.query.order_by(m.Driver.id)]
            history = [(n.id, n.created_at, n.title, n.message, n.read) for n in m.Notification.query.order_by(m.Notification.id)]
            history += [(a.id, a.created_at, a.action, a.detail) for a in m.AuditLog.query.order_by(m.AuditLog.id)]
            return dict(drivers=drivers, user_timezones=[(u.username, u.timezone)
                for u in m.User.query.order_by(m.User.id)], history_sha256=hashlib.sha256(
                json.dumps(history, ensure_ascii=False).encode()).hexdigest(),
                usage=[dict(company=r.company_code, users=r.user_count, vehicles=r.vehicle_count,
                            login=r.login_count) for r in m.CompanyUsageSummary.query.order_by(m.CompanyUsageSummary.company_code)])

        class Clock(RealDatetime):
            @classmethod
            def now(cls, tz=None):
                value = (getattr(g, 'q05_instant', None) if has_request_context() else None)
                value = value or RealDatetime.fromisoformat(json.loads(control.read_text(encoding='utf-8'))['instant'])
                return value.astimezone(tz) if tz else value.replace(tzinfo=None)

        from dkss_app import common
        import vehicle_inspection_alerts
        import vehicle_inspection_plans
        common.datetime = vehicle_inspection_alerts.datetime = vehicle_inspection_plans.datetime = Clock
        server = make_server('127.0.0.1', args.port, app, threaded=True)

        def fixture_control():
            g.q05_instant = RealDatetime.fromisoformat(json.loads(control.read_text(encoding='utf-8'))['instant'])
            if request.path == '/__q05_health':
                return jsonify(fixture=True)
            if request.path == '/__q05_snapshot':
                return jsonify(snapshot())
            if request.path == '/__q05_stop':
                threading.Thread(target=server.shutdown, daemon=True).start()
                return jsonify(stopping=True)
            if request.path.startswith('/__q05_session/'):
                actor = request.path.rsplit('/', 1)[1]
                if actor not in actors:
                    return 'Unknown synthetic actor', 404
                identity, role = actors[actor]
                session.clear()
                session.update(company_code='TEST', username=actor, role=role,
                    account_identity=identity, password_changed_at=stamp,
                    office='Tokyo', password_expired=False)
                return redirect('/')
        # Hooks exist only in this standalone test process, never the app factory.
        app.before_request_funcs.setdefault(None, []).insert(0, fixture_control)
        manifest = dict(marker='q05-synthetic-only', host='127.0.0.1', port=args.port,
            control=str(control), initial=snapshot(), expected_users=len(actors),
            drivers=[dict(company=d.company_code, actor=d.employee_id, name=d.name,
                          start=d.safe_start_date, role=d.role, office=d.office)
                     for d in m.Driver.query.order_by(m.Driver.id)])
        (work / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Q05 browser fixture ready on loopback', flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()
    finally:
        case.tearDown()
        Fixture.tearDownClass()
        Fixture.doClassCleanups()


if __name__ == '__main__':
    main()
