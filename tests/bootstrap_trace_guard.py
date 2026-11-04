"""Public catalog guard, copied exactly; identity is always synthetic CI-owned data."""
TARGET_GUARD_SQL = """
SELECT current_database()=:database AS database_matches,
       session_user=:login AS login_matches,
       current_user=:login AS role_matches,
       current_schema()='public' AS schema_matches,
       current_setting('transaction_read_only')='on' AS read_only,
       has_schema_privilege(current_user,'public','USAGE') AS public_usage,
       has_schema_privilege(current_user,'public','CREATE') AS public_create,
       current_setting('server_version_num')::int BETWEEN 180000 AND 189999 AS postgres18,
       COALESCE((SELECT ssl FROM pg_catalog.pg_stat_ssl WHERE pid=pg_backend_pid()),false) AS tls,
       (SELECT pg_catalog.pg_get_userbyid(datdba)=current_user FROM pg_catalog.pg_database WHERE datname=current_database()) AS owner_ok,
       NOT pg_catalog.pg_is_in_recovery() AS primary_ok,
       NOT EXISTS(SELECT 1 FROM pg_catalog.pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()
                  AND (backend_type='client backend' OR backend_type IS NULL)) AS other_clients_absent,
       NOT EXISTS(SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname !~ '^pg_' AND nspname NOT IN ('public','information_schema')) AS no_other_user_schema,
       NOT EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public') AS no_public_relations,
       NOT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public') AS no_public_functions,
       NOT EXISTS(SELECT 1 FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='public') AS no_public_types,
       NOT EXISTS(SELECT 1 FROM pg_catalog.pg_extension WHERE extname<>'plpgsql') AS no_extra_extensions,
       NOT EXISTS(SELECT 1 FROM pg_catalog.pg_event_trigger) AS no_event_triggers,
       NOT EXISTS(SELECT 1 FROM pg_catalog.pg_largeobject_metadata) AS no_large_objects,
       NOT EXISTS(SELECT 1 FROM pg_catalog.pg_prepared_xacts WHERE database=current_database()) AS no_prepared_transactions
"""

EXPECTED_GUARD_FLAGS = {"database_matches", "login_matches", "role_matches", "schema_matches", "read_only",
                        "public_usage", "public_create", "postgres18", "tls", "owner_ok", "primary_ok",
                        "other_clients_absent", "no_other_user_schema", "no_public_relations", "no_public_functions",
                        "no_public_types", "no_extra_extensions", "no_event_triggers", "no_large_objects", "no_prepared_transactions"}

def guard_empty(engine, database, login, result):
    from sqlalchemy import text
    with engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        flags = dict(connection.execute(text(TARGET_GUARD_SQL), {"database": database, "login": login}).mappings().one())
        if set(flags) != EXPECTED_GUARD_FLAGS or not all(value is True for value in flags.values()):
            raise AssertionError("SYNTHETIC_TARGET_OR_EMPTY_GUARD_FAILED")
        connection.rollback()
    result["target_flags"] = flags
    result["empty_database_guard_passed"] = True
