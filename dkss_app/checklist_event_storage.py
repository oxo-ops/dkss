"""Explicit widening only: preserve legacy text and complete ISO timestamps."""
from sqlalchemy import String, inspect, text


def upgrade_checklist_event_timestamps(engine):
    with engine.begin() as connection:
        columns = {c['name']: c for c in inspect(connection).get_columns('checklist_event')}
        kind = columns['created_at']['type']
        if not isinstance(kind, String):
            raise RuntimeError('ChecklistEvent.created_at must be text; inspect the existing schema first')
        if engine.dialect.name == 'sqlite':
            # SQLite does not enforce VARCHAR lengths. No table rebuild or row rewrite.
            return False
        if engine.dialect.name != 'postgresql':
            raise RuntimeError('Only SQLite and PostgreSQL are supported')
        if kind.length is None or kind.length >= 40:
            return False
        connection.execute(text('ALTER TABLE checklist_event ALTER COLUMN created_at TYPE VARCHAR(40)'))
        return True
