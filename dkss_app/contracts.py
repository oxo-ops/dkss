"""Inspect registration and ORM definitions without querying a database."""
from sqlalchemy.schema import CreateTable, CreateIndex
from sqlalchemy.dialects import postgresql


def application_contract(app, db):
    def callback_name(callback):
        return getattr(callback, '__name__', getattr(
            getattr(callback, 'func', None), '__name__', type(callback).__name__))

    return {
        'routes': sorted([[r.rule, r.endpoint, sorted(r.methods), r.strict_slashes, r.subdomain]
                          for r in app.url_map.iter_rules()]),
        'tables': {name: str(CreateTable(table).compile(dialect=postgresql.dialect()))
                   for name, table in sorted(db.metadata.tables.items())},
        'indexes': sorted(str(CreateIndex(index).compile(dialect=postgresql.dialect()))
                          for table in db.metadata.tables.values() for index in table.indexes),
        'hooks': {kind: {str(key): [callback_name(f) for f in callbacks]
                         for key, callbacks in getattr(app, kind).items()}
                  for kind in ['before_request_funcs', 'after_request_funcs', 'template_context_processors']},
        'filters': sorted(app.jinja_env.filters),
    }
