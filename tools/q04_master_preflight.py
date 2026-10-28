"""Read-only master diagnostics on an explicitly selected nonproduction copy.

No application imports, bootstrap, migrations, DDL, repair or external delivery.
PostgreSQL targets are restricted to loopback Q04 databases; SQLite uses mode=ro.
"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys

from sqlalchemy import MetaData, Table, and_, create_engine, func, inspect, or_, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, SQLAlchemyError


MASTERS = ('office', 'vehicle_type', 'delivery_place', 'license_type', 'patrol_content_type')
KINDS = dict(zip(('offices', 'vehicle-types', 'delivery-places', 'license-types',
                  'patrol-content-types'), MASTERS))
# These are live references or references protected by the existing master routes.
REFERENCES = (
    ('vehicle', 'office', 'office'), ('user', 'office', 'office'),
    ('driver', 'office', 'office'), ('vehicle', 'type', 'vehicle_type'),
    ('vehicle_type_import_mapping', 'vehicle_type_name', 'vehicle_type'),
    ('patrol_result', 'office', 'office'),
    ('patrol_result', 'delivery_place', 'delivery_place'),
    ('patrol_result', 'content_type', 'patrol_content_type'),
    ('checklist_result', 'target_office', 'office'),
    ('news', 'target_value', 'office'),
)


@contextmanager
def read_only_connection(url, expected_database):
    parsed = make_url(url)
    if parsed.query or not expected_database:
        raise ValueError('Explicit expected database and a URL without query overrides are required')
    if parsed.drivername not in {'sqlite', 'sqlite+pysqlite', 'postgresql', 'postgresql+psycopg2'}:
        raise ValueError('Only synchronous SQLite and psycopg2 PostgreSQL connections are supported')
    backend = parsed.get_backend_name()
    if backend == 'sqlite':
        import sqlite3
        path = Path(parsed.database or '').resolve()
        if not path.is_file() or path.name != expected_database:
            raise ValueError('An existing, explicitly named SQLite snapshot is required')
        engine = create_engine('sqlite://', creator=lambda: sqlite3.connect(
            path.as_uri() + '?mode=ro', uri=True))
    elif backend == 'postgresql':
        if (parsed.host not in {'localhost', '127.0.0.1', '::1'}
                or parsed.database != expected_database
                or not (expected_database.startswith('q04_') or expected_database == 'dkss_q04_ci')):
            raise ValueError('Only an explicitly named loopback Q04 PostgreSQL copy is allowed')
        engine = create_engine(parsed, connect_args={'connect_timeout': 5,
            'options': '-cdefault_transaction_read_only=on -cstatement_timeout=15000 -clock_timeout=2000'})
    else:
        raise ValueError('Only PostgreSQL and SQLite are supported')
    try:
        with engine.connect() as connection:
            if backend == 'sqlite':
                connection.exec_driver_sql('PRAGMA query_only=ON')
                connection.exec_driver_sql('BEGIN')
            else:
                connection.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                if connection.scalar(text('SELECT current_database()')) != expected_database:
                    raise ValueError('Connected database does not match the expected database')
                if connection.scalar(text('SHOW transaction_read_only')) != 'on':
                    raise ValueError('Read-only transaction could not be established')
            try:
                yield connection
            finally:
                connection.rollback()
    finally:
        engine.dispose()


class _Audit:
    def __init__(self, connection, schema, sample_limit):
        self.c = connection
        self.inspector = inspect(connection)
        self.schema = schema or self.inspector.default_schema_name
        self.limit = sample_limit
        self.tables = {}
        self.available = set(self.inspector.get_table_names(schema=self.schema))
        self.findings, self.checked = [], []
        self.complete = True

    def add(self, code, table, severity='error', **details):
        self.findings.append(dict(code=code, severity=severity, table=table, **details))

    def table(self, name, columns):
        if name not in self.tables:
            if name not in self.available:
                self.complete = False
                self.add('schema_missing', name, missing=['table'])
                self.tables[name] = None
            else:
                self.tables[name] = Table(name, MetaData(), schema=self.schema, autoload_with=self.c)
                if self.c.dialect.name == 'postgresql' and self.c.scalar(text(
                    'SELECT c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace '
                    'WHERE n.nspname=:schema AND c.relname=:table'), {'schema': self.schema, 'table': name}):
                    self.complete = False
                    self.add('rls_coverage_unverified', name)
        table = self.tables[name]
        if table is not None and not set(columns).issubset(table.c.keys()):
            self.complete = False
            missing = sorted(set(columns) - set(table.c.keys()))
            if not any(f['code'] == 'schema_missing' and f['table'] == name and f.get('missing') == missing for f in self.findings):
                self.add('schema_missing', name, missing=missing)
            return None
        return table

    def query(self, code, table, query, severity='error', **details):
        count = self.c.scalar(select(func.count()).select_from(query.subquery()))
        self.checked.append(dict(check=code, table=table))
        if count:
            self.add(code, table, severity, count=count,
                     samples=[dict(r) for r in self.c.execute(query.limit(self.limit)).mappings()], **details)

    def index(self, table):
        name = 'uq_' + table.name + '_company_name'
        expected = dict(unique=True, columns=['company_code', 'name'], partial=False)
        found = next((i for i in self.inspector.get_indexes(table.name, schema=self.schema)
                      if i['name'] == name), None)
        self.checked.append(dict(check='index_definition', table=table.name))
        if found is None:
            self.add('index_missing', table.name, index=name, expected=expected, actual=None)
            return
        actual = dict(unique=bool(found['unique']), columns=found['column_names'],
                      predicate=next((str(v) for k, v in found.get('dialect_options', {}).items()
                                      if k.endswith('_where') and v is not None), None))
        if (not actual['unique'] or set(actual['columns']) != {'company_code', 'name'}
                or actual['predicate'] is not None):
            self.add('index_definition', table.name, index=name, expected=expected, actual=actual)
        if self.c.dialect.name == 'postgresql':
            state = self.c.execute(text(
                'SELECT i.indisvalid, i.indisready FROM pg_index i '
                'JOIN pg_class x ON x.oid=i.indexrelid JOIN pg_namespace n ON n.oid=x.relnamespace '
                'WHERE n.nspname=:schema AND x.relname=:name'),
                {'schema': self.schema, 'name': name}).mappings().first()
            if not state or not (state['indisvalid'] and state['indisready']):
                self.add('index_invalid', table.name, index=name,
                         expected=dict(indisvalid=True, indisready=True), actual=dict(state) if state else None)

    def masters(self):
        company = self.table('company', ['company_code'])
        for name in MASTERS:
            table = self.table(name, ['id', 'company_code', 'name'])
            if table is None:
                continue
            self.index(table)
            self.query('duplicate_name', name, select(table.c.company_code, table.c.name,
                func.count().label('rows')).group_by(table.c.company_code, table.c.name).having(func.count() > 1))
            self.query('invalid_master_value', name, select(table.c.id, table.c.company_code, table.c.name).where(or_(
                table.c.name.is_(None), func.trim(table.c.name) == '', table.c.company_code.is_(None),
                func.trim(table.c.company_code) == '')))
            if company is not None:
                self.query('unknown_company', name, select(table.c.id, table.c.company_code).where(
                    ~select(company.c.company_code).where(company.c.company_code == table.c.company_code).exists()))

    def reference(self, source, column, master):
        required = ['id', 'company_code', column] + (['target_type'] if source == 'news' else [])
        table, target = self.table(source, required), self.table(master, ['company_code', 'name'])
        if table is None or target is None:
            return
        value = table.c[column]
        missing = ~select(target.c.name).where(and_(target.c.company_code == table.c.company_code,
                                                   target.c.name == value)).exists()
        query = select(table.c.id, table.c.company_code, value.label('value')).where(
            value.is_not(None), value != '', missing)
        if source == 'news':
            query = select(table.c.id, table.c.company_code, value.label('value')).where(
                table.c.target_type == 'office', or_(value.is_(None), value == '', missing))
        self.query('missing_reference', source, query, column=column, master=master)

    def json_references(self):
        driver, licenses = self.table('driver', ['id', 'company_code', 'licenses_json']), self.table('license_type', ['company_code', 'name'])
        if driver is not None and licenses is not None:
            problems = {}
            for row in self.c.execute(select(driver.c.id, driver.c.company_code, driver.c.licenses_json)).mappings():
                try:
                    values = json.loads(row['licenses_json'] or '[]')
                    if not isinstance(values, list) or any(not isinstance(v, dict) or not isinstance(v.get('type'), str) or not v['type'].strip() for v in values):
                        raise ValueError()
                except (ValueError, TypeError):
                    self.collect(problems, 'invalid_json', row, column='licenses_json')
                    continue
                for value in values:
                    exists = self.c.scalar(select(licenses.c.name).where(licenses.c.company_code == row['company_code'],
                                                                        licenses.c.name == value['type']).limit(1))
                    if exists is None:
                        self.collect(problems, 'missing_reference', row, column='licenses_json',
                                     master='license_type', value=value['type'])
            self.finish(problems, 'driver')
        order = self.table('master_display_order', ['id', 'company_code', 'kind', 'ordered_ids_json'])
        if order is not None:
            problems = {}
            for row in self.c.execute(select(order)).mappings():
                if row['kind'] not in KINDS:
                    continue  # checklist/manual ordering belongs to other scopes.
                target = self.table(KINDS[row['kind']], ['id', 'company_code'])
                if target is None:
                    continue
                try:
                    ids = json.loads(row['ordered_ids_json'])
                    if (not isinstance(ids, list) or any(type(v) is not int or v <= 0 for v in ids)
                            or len(ids) != len(set(ids))):
                        raise ValueError()
                    valid = set(self.c.scalars(select(target.c.id).where(target.c.company_code == row['company_code'])))
                    if not set(ids).issubset(valid):
                        raise ValueError()
                except (ValueError, TypeError):
                    self.collect(problems, 'invalid_order', row, column='ordered_ids_json', master=target.name)
            self.finish(problems, 'master_display_order')

    def collect(self, groups, code, row, **details):
        key = (code, details.get('master'), details['column'])
        group = groups.setdefault(key, dict(code=code, count=0, samples=[],
                                           **{k: v for k, v in details.items() if k != 'value'}))
        group['count'] += 1
        if len(group['samples']) < self.limit:
            group['samples'].append(dict(id=row['id'], company_code=row['company_code'],
                                          **({'value': details['value']} if 'value' in details else {})))

    def finish(self, groups, table):
        self.checked.append(dict(check='json_references', table=table))
        for group in groups.values():
            code = group.pop('code')
            self.add(code, table, severity='info' if code == 'historical_name' else 'error', **group)

    def history(self):
        # cost_office is an ORM property, not a physical column. Read its stored
        # JSON evidence without importing the application or resolving today’s office.
        table = self.table('vehicle_maintenance_record', ['id', 'company_code', 'invoice_details_json'])
        target = self.table('office', ['company_code', 'name'])
        if table is None or target is None:
            return
        problems = {}
        for row in self.c.execute(select(table.c.id, table.c.company_code, table.c.invoice_details_json)).mappings():
            try:
                details = json.loads(row['invoice_details_json'] or '{}')
                if not isinstance(details, dict):
                    raise ValueError()
                attribution = details.get('cost_attribution')
                if attribution is None:
                    continue
                if not isinstance(attribution, dict):
                    raise ValueError()
                office = attribution.get('office')
                if office is not None and not isinstance(office, str):
                    raise ValueError()
            except (ValueError, TypeError):
                self.collect(problems, 'invalid_json', row, column='invoice_details_json')
                continue
            if office and self.c.scalar(select(target.c.name).where(
                    target.c.company_code == row['company_code'], target.c.name == office).limit(1)) is None:
                self.collect(problems, 'historical_name', row, master='office',
                             column='invoice_details_json.cost_attribution.office', value=office)
        self.finish(problems, 'vehicle_maintenance_record')

    def run(self):
        self.masters()
        for source, column, master in REFERENCES:
            self.reference(source, column, master)
        self.json_references()
        self.history()

    def report(self):
        return dict(format_version=1, backend=self.c.dialect.name, schema=self.schema,
            complete=self.complete, status=('incomplete' if not self.complete else
                'issues' if any(f['severity'] == 'error' for f in self.findings) else 'ok'),
            findings=self.findings, checked=self.checked,
            limitations=['No repair or bootstrap', 'No person-identity migration validation',
                         'String references cannot prove the generation of a re-created name',
                         'Historical names are observations; business approval is separate',
                         'SQLite has no PostgreSQL indisvalid/indisready state'])


def diagnose(url, expected_database, schema=None, sample_limit=10):
    if not 1 <= sample_limit <= 100:
        raise ValueError('sample_limit must be between 1 and 100')
    with read_only_connection(url, expected_database) as connection:
        audit = _Audit(connection, schema, sample_limit)
        try:
            audit.run()
        except DBAPIError as error:
            audit.complete = False
            audit.add('query_failed', None, sqlstate=getattr(error.orig, 'pgcode', None))
        return audit.report()


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-database', required=True, help='Exact PG database or SQLite snapshot filename')
    parser.add_argument('--schema', help='Explicit PostgreSQL schema (default: connection default schema)')
    parser.add_argument('--sample-limit', type=int, default=10)
    parser.add_argument('--confirm-nonproduction', action='store_true', required=True)
    args = parser.parse_args(argv)
    url = os.environ.get('Q04_PREFLIGHT_DATABASE_URL', '')
    if not url:
        parser.error('Q04_PREFLIGHT_DATABASE_URL must explicitly select a nonproduction copy')
    try:
        report = diagnose(url, args.expected_database, args.schema, args.sample_limit)
    except (ValueError, SQLAlchemyError, OSError):
        # Never print a DSN, password, bound row values or driver error text.
        print('Q04診断を完了できません。接続対象・権限・スキーマを管理者が確認してください。', file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if not report['complete'] else 1 if report['status'] == 'issues' else 0


if __name__ == '__main__':
    raise SystemExit(main())
