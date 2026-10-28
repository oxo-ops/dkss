"""Synthetic-only audit probes. No restoration or external processing is performed."""
import ast
import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
OUT = parser.parse_args().output.resolve()
OUT.mkdir(parents=True, exist_ok=True)
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from test_q08_driving_generation import DrivingGenerationTests
from driving_identity_resolution import resolver
from dkss_app.document_import_queue import owner_available
from flask import session

results = []
DrivingGenerationTests.setUpClass()
try:
    case = DrivingGenerationTests()
    case.setUp()
    try:
        row = case.save(name='架空旧姓人物')
        old = case.m.User(company_code='TEST', username='synthetic-old', role='user',
            password='unused', last_name='架空旧姓人物', password_changed_at='stamp')
        case.m.db.session.add(old); case.m.db.session.commit()
        old_uuid = old.account_identity
        case.m.db.session.delete(old); case.m.db.session.commit()
        new = case.m.User(company_code='TEST', username='synthetic-new', role='user',
            password='unused', last_name='架空旧姓人物', password_changed_at='stamp')
        case.m.db.session.add(new); case.m.db.session.commit()
        with case.m.app.test_request_context():
            session.update(company_code='TEST', username='admin', role='admin')
            user, basis = resolver().resolve(row)
            assert user.id == new.id and basis == 'name'
        case.login('synthetic-new')
        status = case.client.get(f'/safety/driving-reports/{row.id}').status_code
        assert status == 200
        results.append({'probe':'unbound_legacy_report_name_match', 'old_uuid':old_uuid,
            'new_uuid':new.account_identity, 'different_username':True,
            'detail_status':status, 'basis':basis, 'remaining_issue':True,
            'reason':'Existing explicit name-resolution contract requires a separate specification change'})
    finally:
        case.tearDown()
    case = DrivingGenerationTests()
    case.setUp()
    try:
        row = SimpleNamespace(company_code='TEST', created_by_username='admin')
        old = case.m.User.query.filter_by(company_code='TEST', username='admin').one()
        old_uuid = old.account_identity
        assert owner_available(row)
        case.m.db.session.delete(old); case.m.db.session.commit()
        assert not owner_available(row)
        new = case.m.User(company_code='TEST', username='admin', role='admin',
            password='unused', last_name='架空別人管理者')
        case.m.db.session.add(new); case.m.db.session.commit()
        assert new.account_identity != old_uuid and owner_available(row)
        results.append({'probe':'async_owner_recreated_username',
            'old_uuid':old_uuid, 'new_uuid':new.account_identity,
            'owner_available_after_delete':False, 'owner_available_after_recreation':True,
            'external_work_executed':False, 'remaining_issue':True, 'owner':'Q02'})
    finally:
        case.tearDown()
finally:
    DrivingGenerationTests.tearDownClass()

fields=[]
for filename in sorted(str(p.relative_to(ROOT)).replace('\\', '/') for p in (ROOT/'dkss_app').glob('*.py')):
    tree=ast.parse((ROOT/filename).read_text(encoding='utf-8'))
    for cls in [n for n in ast.walk(tree) if isinstance(n,ast.ClassDef) and
                any(isinstance(b, ast.Attribute) and b.attr == 'Model' for b in n.bases)]:
        for stmt in cls.body:
            if isinstance(stmt,ast.Assign):
                for target in stmt.targets:
                    if isinstance(target,ast.Name) and isinstance(stmt.value, ast.Call) and \
                        isinstance(stmt.value.func, ast.Attribute) and stmt.value.func.attr == 'Column' and \
                        any(token in target.id for token in ['username','employee_id','user_id','actor',
                            'created_by','updated_by','confirmed_by','retired_by','reviewed_by','approved_by',
                            'checked_by','target_user','requested_by','countermeasure_by','account_identity',
                            'owner_identity','last_name','first_name','inspector_name','maintenance_person']):
                        fields.append({'model':cls.name,'field':target.id,'file':filename,'line':stmt.lineno})
(OUT/'q08-person-field-inventory.json').write_text(json.dumps(fields,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'q08-person-audit-probes.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'synthetic_probes':results,'person_reference_fields':len(fields)},ensure_ascii=False))
