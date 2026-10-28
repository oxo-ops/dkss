"""Uncovered license/content master uniqueness, lifecycle and atomic deletion."""
import json
import os
from unittest.mock import patch

from sqlalchemy import event, inspect, text

from q04_pg_helpers import PrivatePostgresCase


class NamedMasterGapTests(PrivatePostgresCase):
    def setUp(self):
        super().setUp()
        self.master_ids = {}
        with self.app.app_context():
            for kind, model in self.masters():
                for company in (self.company, self.other):
                    row = model(company_code=company, name='Synthetic-A')
                    self.db.session.add(row)
                    self.db.session.flush()
                    if company == self.company:
                        self.master_ids[kind] = row.id
                    self.db.session.add(self.m.MasterDisplayOrder(company_code=company, kind=kind,
                        ordered_ids_json=json.dumps([row.id])))
            self.db.session.commit()
            from dkss_app.database import init_db
            with patch.dict(os.environ, {'ITC_INITIAL_PASSWORD': 'Q04-Disposable-Only-742!'}):
                init_db()
        self.foreign_before = self.snapshot(self.other)

    def masters(self):
        return (('license-types', self.m.LicenseType), ('patrol-content-types', self.m.PatrolContentType))

    def model(self, kind):
        return dict(self.masters())[kind]

    def index_name(self, kind):
        return 'uq_' + self.model(kind).__tablename__ + '_company_name'

    def action_for(self, kind, operation, name='Synthetic-B', ident=None):
        return self.action('/master/' + kind + '/' + ('' if operation == 'new' else
            str(ident or self.master_ids[kind]) + '/') + operation, {'name': name})

    def check_case(self, kind, scenario):
        model, table = self.model(kind), self.model(kind).__tablename__
        if scenario == 'schema':
            with self.app.app_context():
                indices = inspect(self.engine).get_indexes(table)
            self.assertTrue(any(x['unique'] and x['column_names'] == ['company_code', 'name'] for x in indices))
        elif scenario in ('create', 'target'):
            first = self.action_for(kind, 'new', 'Concurrent')
            if scenario == 'target':
                with self.app.app_context():
                    row = model(company_code=self.company, name='Other')
                    self.db.session.add(row)
                    self.db.session.commit()
                    ident = row.id
                first = self.action_for(kind, 'edit', 'Concurrent')
                second = self.action_for(kind, 'edit', 'Concurrent', ident)
            else:
                second = first
            # License renames now serialize on Driver before their final UPDATE.
            # Pause both after duplicate prechecks but before acquiring that lock;
            # parking A at UPDATE would prevent B reaching the SQL barrier.
            prefix = ('select driver.' if kind == 'license-types' and scenario == 'target'
                      else ('insert into ' if scenario == 'create' else 'update ') + table + ' ')
            responses, _ = self.schedule(first, second, table, prefix)
            self.assertCountEqual([r.get('status') for r in responses], [302, 409])
            self.assertEqual(sum(r['name'] == 'Concurrent' for r in self.snapshot(self.company)[table]), 1)
        elif scenario == 'companies':
            responses, _ = self.schedule(self.action_for(kind, 'new', 'Concurrent'),
                self.action('/master/' + kind + '/new', {'name': 'Concurrent'}, self.other),
                table, 'insert into ' + table + ' ')
            self.assertEqual([r.get('status') for r in responses], [302, 302])
            for company in (self.company, self.other):
                self.assertEqual(sum(r['name'] == 'Concurrent' for r in self.snapshot(company)[table]), 1)
            return
        elif scenario == 'lifecycle':
            self.assertEqual(self.post('A', self.action_for(kind, 'edit'))['status'], 302)
            self.assertEqual(self.post('A', self.action_for(kind, 'delete'))['status'], 302)
            self.assertEqual(self.post('A', self.action_for(kind, 'new', 'Synthetic-B'))['status'], 302)
            before = self.snapshot(self.company)
            self.assertEqual(self.post('A', self.action_for(kind, 'delete'))['status'], 302)
            self.assertEqual(self.snapshot(self.company), before)
            self.assertEqual(sum(r['action'] == table + '_deleted' for r in before['audit_log']), 1)
        elif scenario == 'rollback':
            before = self.snapshot(self.company)
            reached = []
            def fail(connection, cursor, statement, parameters, context, executemany):
                if statement.lower().startswith('delete from ' + table + ' '):
                    reached.append(True)
                    raise RuntimeError('Q04_NAMED_MASTER_AFTER_DELETE')
            event.listen(self.engine, 'after_cursor_execute', fail)
            try:
                response = self.post('A', self.action_for(kind, 'delete'))
            finally:
                event.remove(self.engine, 'after_cursor_execute', fail)
            self.assertEqual(reached, [True])
            self.assertTrue(response.get('error') or response.get('status') == 500, repr(response))
            self.assertEqual(self.snapshot(self.company), before)
            self.assertEqual(self.post('A', self.action_for(kind, 'delete'))['status'], 302)
        elif scenario == 'legacy':
            from dkss_app.database import init_db
            with self.app.app_context():
                self.db.session.execute(text('DROP INDEX IF EXISTS ' + self.index_name(kind)))
                self.db.session.commit()
            before = self.snapshot(self.company)
            with self.app.app_context():
                init_db()
                init_db()
            self.assertEqual(self.snapshot(self.company), before)
            self.check_case(kind, 'schema')
        elif scenario == 'legacy_duplicates':
            from dkss_app.database import init_db
            with self.app.app_context():
                self.db.session.execute(text('DROP INDEX IF EXISTS ' + self.index_name(kind)))
                self.db.session.add(model(company_code=self.company, name='Synthetic-A'))
                self.db.session.commit()
            before = self.snapshot(self.company)
            try:
                with self.app.app_context():
                    with self.assertRaisesRegex(RuntimeError, '免許種別' if kind == 'license-types' else '内容区分'):
                        init_db()
                self.assertEqual(self.snapshot(self.company), before)
                with self.app.app_context():
                    self.assertNotIn(self.index_name(kind), [x['name'] for x in inspect(self.engine).get_indexes(table)])
            finally:
                with self.app.app_context():
                    duplicate = model.query.filter_by(company_code=self.company, name='Synthetic-A').order_by(model.id.desc()).first()
                    self.db.session.delete(duplicate)
                    self.db.session.commit()
                    init_db()
        self.assertEqual(self.snapshot(self.other), self.foreign_before)


def case(kind, scenario):
    def check(self):
        self.check_case(kind, scenario)
    return check


for _kind in ('license-types', 'patrol-content-types'):
    for _scenario in ('schema', 'create', 'target', 'companies', 'lifecycle', 'rollback', 'legacy', 'legacy_duplicates'):
        setattr(NamedMasterGapTests, 'test_' + _kind.replace('-', '_') + '_' + _scenario, case(_kind, _scenario))
