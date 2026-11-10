"""Shared assertions for isolated PostgreSQL bootstrap acceptance.

The normal full CLI is run separately by the test fixture. Boundary tests stop
before account identity migration and never stand in for full initialization.
"""
import os
from unittest.mock import patch
from uuid import UUID

def require(condition, message):
    if not condition:
        raise AssertionError(message)


def verify_full_bootstrap(url, environment, password):
    from sqlalchemy import inspect, text
    from werkzeug.security import check_password_hash
    from dkss_app import create_app
    from dkss_app.extensions import db
    from dkss_app.models import User, Company, PatrolContentType
    from dkss_app.analysis_read_cache import INPUT_TABLES, REVISION as CACHE_REVISION
    from dkss_app.document_sources import REVISION as SOURCE_REVISION
    from dkss_app.master_generations import validate_storage, valid_generation
    with patch.dict(os.environ, environment, clear=True):
        app = create_app({"SQLALCHEMY_DATABASE_URI": url})
        with app.app_context():
            try:
                inspector = inspect(db.engine)
                tables = set(inspector.get_table_names())
                require(set(db.metadata.tables).issubset(tables), "Missing model tables")
                for name, table in db.metadata.tables.items():
                    columns = {column["name"] for column in inspector.get_columns(name)}
                    require(set(table.c.keys()).issubset(columns), "Missing model columns: " + name)
                for table, name, columns in [
                    ("user", "uq_user_company_username", ("company_code", "username")),
                    ("user", "uq_user_account_identity", ("account_identity",)),
                    ("driver", "uq_driver_company_employee_id", ("company_code", "employee_id")),
                    *[(table, "uq_" + table + "_company_name", ("company_code", "name"))
                      for table in ("office", "vehicle_type", "delivery_place", "license_type", "patrol_content_type")],
                    ("vehicle_checklist_result", "uq_vehicle_checklist_result_target_date",
                     ("company_code", "checklist_id", "vehicle_record_id", "year", "month", "day")),
                ]:
                    indexes = {item["name"]: item for item in inspector.get_indexes(table)}
                    index = indexes.get(name)
                    require(index and index["unique"] and tuple(index["column_names"]) == columns,
                            "Wrong bootstrap unique index: " + name)
                with db.engine.connect() as connection:
                    validate_storage(connection)
                    revisions = set(connection.scalars(text("SELECT revision FROM domain_schema_revision")))
                    require({SOURCE_REVISION, CACHE_REVISION}.issubset(revisions), "Missing extra schema revisions")
                    triggers = set(connection.execute(text("SELECT c.relname,t.tgname,t.tgenabled "
                        "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                        "JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname='public' AND NOT t.tgisinternal")))
                    expected = {(name, "dkss_analysis_" + name + suffix, "O")
                                for name in INPUT_TABLES for suffix in ("", "_truncate")}
                    require(expected.issubset(triggers), "Missing or disabled PostgreSQL analysis triggers")
                    invalid_indexes = connection.scalar(text("SELECT count(*) FROM pg_index i "
                        "JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname='public' AND NOT (i.indisvalid AND i.indisready)"))
                    require(invalid_indexes == 0, "Invalid or unready PostgreSQL index")
                    require(connection.scalar(text("SELECT revision FROM analysis_input_epoch "
                        "WHERE company_code='ITC' AND bucket='shared'")) >= 1, "Missing initial analysis epoch")
                administrator = User.query.filter_by(company_code="ITC", username="itc").one()
                require(administrator.role == "itc", "Initial administrator has wrong role")
                require(bool(UUID(administrator.account_identity).int), "Missing administrator identity")
                require(check_password_hash(administrator.password, password), "Wrong administrator password hash")
                company = Company.query.filter_by(company_code="ITC").one()
                require(company.active and company.vehicle_limit == 9999, "Wrong initial company")
                rows = PatrolContentType.query.filter_by(company_code="ITC").all()
                require({row.name for row in rows} == {"落下", "車両", "環境", "荷扱い", "ルール違反", "Good", "その他"},
                        "Missing or duplicated initial content types")
                require(len(rows) == 7 and all(valid_generation(row.master_generation) for row in rows),
                        "Invalid initial master generations")
                return {"model_tables": len(db.metadata.tables), "analysis_triggers": len(expected),
                        "administrator": "verified", "extra_schema_revisions": "verified"}
            finally:
                db.session.remove()
                db.engine.dispose()


def boundary_test(url, environment, control=False):
    """Real PostgreSQL validation/create_all, stopped BEFORE identity upgrade.

    The control uses the former session-held connection sequence. Neither this
    control nor the candidate boundary test is a full initialization test.
    """
    import psycopg2
    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError
    from dkss_app import create_app, database, account_identity
    from dkss_app.extensions import db
    from dkss_app.master_generations import validate_storage
    class StopAtIdentity(Exception):
        pass
    attempts = []
    injected = []
    with patch.dict(os.environ, environment, clear=True):
        app = create_app({"SQLALCHEMY_DATABASE_URI": url})
        with app.app_context():
            engine = db.engine
            def reject_second(dialect, record, args, kwargs):
                attempts.append(1)
                if len(attempts) == 2:
                    injected.append(1)
                    raise psycopg2.OperationalError("SYNTHETIC_SECOND_CONNECTION_REJECTED")
            event.listen(engine, "do_connect", reject_second)
            try:
                if control:
                    # Equivalent to the old entry boundary, not a full baseline run.
                    try:
                        validate_storage(db.session.connection(), allow_empty=True)
                        db.create_all()
                    except OperationalError:
                        require(len(injected) == 1, "Unexpected control connection failure")
                    else:
                        raise AssertionError("Control did not exercise second-connection rejection")
                    require(len(attempts) == 2, "Unexpected control connection count")
                    return {"physical_connection_attempts": 2, "injection_fired": True,
                            "scope": "former session-held boundary only"}
                with patch.object(account_identity, "upgrade_account_identity", side_effect=StopAtIdentity):
                    try:
                        database.init_db()
                    except StopAtIdentity:
                        pass
                    else:
                        raise AssertionError("Candidate did not reach identity boundary")
                require(len(attempts) == 1 and not injected, "Candidate acquired a second physical connection")
                return {"physical_connection_attempts": 1, "injection_fired": False,
                        "scope": "candidate through post-create validation only"}
            finally:
                db.session.remove()
                event.remove(engine, "do_connect", reject_second)
                engine.dispose()
