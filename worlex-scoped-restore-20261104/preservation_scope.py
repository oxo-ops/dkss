"""Minimum reviewed preservation surface; no unrelated business-table sweeps.

This snapshot is not restored-payload, schema, collision, or sequence validation.
Those independent guards must remain in the caller. Never serialize row values.
"""
from sqlalchemy import select

PRESERVATION_CONTRACT = {
    'version': 1,
    'columns': 'all_reflected_columns',
    'tables': {
        'company': {'selector': 'company_code_exact', 'value': 'ITC'},
        'user': {'selector': 'company_code_exact', 'value': 'ITC'},
        'document_queue_schedule': {'selector': 'all_rows'},
        'domain_schema_revision': {'selector': 'all_rows'},
        'audit_log': {'selector': 'all_rows_except_imported_source_ids_after_write'},
        'push_subscription': {'selector': 'all_rows'},
    },
    'push_subscription_sequence': 'exact_unchanged_checked_separately',
}
_TABLES = ('audit_log', 'company', 'document_queue_schedule',
           'domain_schema_revision', 'push_subscription', 'user')
_ITC_TABLES = ('company', 'user')


class PreservationScopeError(ValueError):
    """Invalid preservation inputs; messages never contain row values."""


def snapshot(connection, tables, digest, *, audit_import_ids=()):
    """Hash the six reviewed projections using exactly six SELECTs.

    ITC matching is deliberately exact (not case-folded or NULL-inclusive).
    Audit exclusions are caller-verified imported source IDs, used only after
    insertion. Duplicate row hashes are retained, including on keyless tables.
    """
    if not isinstance(audit_import_ids, (list, tuple)):
        raise PreservationScopeError('INVALID_PRESERVATION_AUDIT_IDS')
    if (any(type(value) is not int or value <= 0 for value in audit_import_ids)
            or len(set(audit_import_ids)) != len(audit_import_ids)):
        raise PreservationScopeError('INVALID_PRESERVATION_AUDIT_IDS')
    # Validate the whole projection before issuing even the first query.
    for name in _TABLES:
        table = tables.get(name)
        if (table is None or getattr(table, 'name', None) != name
                or not len(table.c)):
            raise PreservationScopeError('MISSING_PRESERVATION_TABLE:' + name)
        required = ('company_code',) if name in _ITC_TABLES else ('id',) if name == 'audit_log' else ()
        if any(column not in table.c for column in required):
            raise PreservationScopeError('MISSING_PRESERVATION_SELECTOR:' + name)
    result = {}
    for name in _TABLES:
        table = tables[name]
        statement = select(table)
        if name in _ITC_TABLES:
            statement = statement.where(table.c.company_code == 'ITC')
        elif name == 'audit_log' and audit_import_ids:
            statement = statement.where(table.c.id.not_in(audit_import_ids))
        rows = sorted(digest(dict(row)) for row in connection.execute(statement).mappings())
        result[name] = {'count': len(rows), 'sha256': digest(rows)}
    return result
