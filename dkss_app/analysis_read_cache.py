"""Disposable read projections fenced by transactional company input epochs."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo
from flask import current_app
from sqlalchemy import case, func, inspect, select, text
from sqlalchemy.exc import SQLAlchemyError
from .extensions import db
from .models import (
    AnalysisInputEpoch as Epoch,
    AnalysisInputReadCache as Cache,
    DomainSchemaRevision,
)

REVISION = "20261027_analysis_read_cache_v1"
INPUT_TABLES = (
    "vehicle",
    "vehicle_maintenance_record",
    "vehicle_operation_record",
    "vehicle_part_replacement",
    "vehicle_part_replacement_source",
    "vehicle_patrol",
    "vehicle_periodic_inspection_record",
    "vehicle_driving_report_record",
    "vehicle_checklist_result",
    "vehicle_maintenance_inspection_link",
    "vehicle_document_import_draft",
    "vehicle_document_source",
    "vehicle_maintenance_knowledge",
    "maintenance_knowledge_document",
    "maintenance_knowledge_rule_extraction",
    "public_knowledge_file",
    "vehicle_analysis_feedback",
    "vehicle_analysis_evaluation",
)


def utc(value):
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def code_hash():
    state = current_app.extensions["dkss"]
    if "analysis_read_code_hash" not in state:
        root = Path(__file__).resolve().parents[1]
        paths = sorted(
            list(root.glob("*.py"))
            + list((root / "dkss_app").glob("*.py"))
            + list(root.glob("*.json"))
        )
        digest = hashlib.sha256()
        for path in paths:
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
        state["analysis_read_code_hash"] = digest.hexdigest()
    return state["analysis_read_code_hash"]


@dataclass(frozen=True)
class InputToken:
    revision: int
    expires_at: datetime
    observed_at: datetime


class AnalysisReadCacheRepository:
    """Use separate connections; never commit the business ORM session."""

    def token(self, company, now):
        from sqlalchemy.pool import StaticPool

        now = utc(now)
        if os.environ.get("ANALYSIS_READ_CACHE_ENABLED", "1") == "0" or isinstance(
            db.engine.pool, StaticPool
        ):
            return None
        with db.engine.connect() as connection:
            if not inspect(connection).has_table(DomainSchemaRevision.__tablename__):
                return None
            if (
                connection.execute(
                    select(DomainSchemaRevision.revision).where(
                        DomainSchemaRevision.revision == REVISION
                    )
                ).first()
                is None
            ):
                return None
            version = connection.execute(
                select(func.coalesce(func.sum(Epoch.revision), 0)).where(
                    Epoch.company_code == company
                )
            ).scalar_one()
            local = now.astimezone(ZoneInfo("Asia/Tokyo"))
            midnight = (local + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            expiry = min(now + timedelta(minutes=5), midnight.astimezone(timezone.utc))
            files = db.metadata.tables["public_knowledge_file"]
            naive_local = local.replace(tzinfo=None)
            boundaries = connection.execute(
                select(
                    func.min(
                        case(
                            (files.c.last_checked >= naive_local, files.c.last_checked)
                        )
                    ),
                    func.min(
                        case((files.c.next_check >= naive_local, files.c.next_check))
                    ),
                ).where(files.c.company_code == company)
            ).one()
            for boundary in boundaries:
                if boundary is not None:
                    expiry = min(
                        expiry,
                        boundary.replace(tzinfo=ZoneInfo("Asia/Tokyo")).astimezone(
                            timezone.utc
                        ),
                    )
            return InputToken(int(version), expiry, now)

    def get(self, company, vehicle_id, key, token, now):
        with db.engine.connect() as connection:
            row = (
                connection.execute(
                    select(Cache.__table__).where(
                        Cache.company_code == company,
                        Cache.vehicle_record_id == vehicle_id,
                        Cache.context_hash == key,
                        Cache.input_revision == token.revision,
                    )
                )
                .mappings()
                .first()
            )
        if (
            row is None
            or utc(now) >= utc(row["expires_at"])
            or utc(now) < utc(row["computed_at"])
        ):
            return None
        try:
            value = json.loads(row["projection_json"])
            if (
                isinstance(value, dict)
                and isinstance(value.get("fingerprints"), dict)
                and isinstance(value.get("input_summary"), dict)
            ):
                return value
        except (TypeError, ValueError):
            pass
        return None

    def put(self, company, vehicle_id, key, token, projection):
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        from sqlalchemy.dialects.postgresql import insert as postgres_insert

        values = dict(
            company_code=company,
            vehicle_record_id=vehicle_id,
            context_hash=key,
            input_revision=token.revision,
            projection_json=json.dumps(projection, ensure_ascii=False, default=str),
            computed_at=token.observed_at,
            expires_at=token.expires_at,
        )
        insert = (
            postgres_insert if db.engine.dialect.name == "postgresql" else sqlite_insert
        )
        statement = insert(Cache.__table__).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["company_code", "vehicle_record_id"],
            set_={
                name: getattr(statement.excluded, name)
                for name in values
                if name not in {"company_code", "vehicle_record_id"}
            },
            where=Cache.input_revision <= statement.excluded.input_revision,
        )
        try:
            with db.engine.begin() as connection:
                connection.execute(statement)
        except SQLAlchemyError:
            current_app.logger.warning("Analysis read projection could not be cached")


def _bump(company, bucket):
    return f"""INSERT INTO analysis_input_epoch (company_code,bucket,revision)
        SELECT {company},{bucket},1 WHERE {company} IS NOT NULL AND {company}<>''
        ON CONFLICT (company_code,bucket) DO UPDATE SET revision=analysis_input_epoch.revision+1;"""


def trigger_statements(dialect, tables):
    if dialect not in {"sqlite", "postgresql"}:
        raise RuntimeError("Unsupported analysis tracking backend")
    statements = []
    if dialect == "postgresql":
        statements.append(
            """CREATE OR REPLACE FUNCTION dkss_analysis_input_changed() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE new_bucket text; old_bucket text;
        BEGIN
          IF TG_OP <> 'DELETE' THEN
            IF TG_ARGV[0]='id' THEN new_bucket:='vehicle:'||NEW.id::text;
            ELSIF TG_ARGV[0]='vehicle_record_id' THEN new_bucket:=COALESCE('vehicle:'||NEW.vehicle_record_id::text,'shared');
            ELSE new_bucket:='shared'; END IF;
        """
            + _bump("NEW.company_code", "new_bucket")
            + """
          END IF;
          IF TG_OP='DELETE' OR (TG_OP='UPDATE' AND OLD.company_code IS DISTINCT FROM NEW.company_code) THEN
            IF TG_ARGV[0]='id' THEN old_bucket:='vehicle:'||OLD.id::text;
            ELSIF TG_ARGV[0]='vehicle_record_id' THEN old_bucket:=COALESCE('vehicle:'||OLD.vehicle_record_id::text,'shared');
            ELSE old_bucket:='shared'; END IF;
        """
            + _bump("OLD.company_code", "old_bucket")
            + """
          END IF;
          RETURN NULL;
        END; $$"""
        )
        statements.append(
            """CREATE OR REPLACE FUNCTION dkss_analysis_input_truncated() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN UPDATE analysis_input_epoch SET revision=revision+1; RETURN NULL; END; $$"""
        )
    for name in INPUT_TABLES:
        table = tables[name]
        field = (
            "id"
            if name == "vehicle"
            else ("vehicle_record_id" if "vehicle_record_id" in table.c else "")
        )
        trigger = "dkss_analysis_" + name
        if dialect == "postgresql":
            statements.extend(
                [
                    f'DROP TRIGGER IF EXISTS "{trigger}" ON "{name}"',
                    f'CREATE TRIGGER "{trigger}" AFTER INSERT OR UPDATE OR DELETE ON "{name}" FOR EACH ROW EXECUTE FUNCTION dkss_analysis_input_changed(\'{field}\')',
                    f'DROP TRIGGER IF EXISTS "{trigger}_truncate" ON "{name}"',
                    f'CREATE TRIGGER "{trigger}_truncate" AFTER TRUNCATE ON "{name}" FOR EACH STATEMENT EXECUTE FUNCTION dkss_analysis_input_truncated()',
                ]
            )
        else:
            for operation in ("INSERT", "UPDATE", "DELETE"):
                full = trigger + "_" + operation.lower()

                def bucket(row):
                    return (
                        f"COALESCE('vehicle:' || CAST({row}.\"{field}\" AS TEXT),'shared')"
                        if field
                        else "'shared'"
                    )

                body = (
                    _bump("OLD.company_code", bucket("OLD"))
                    if operation == "DELETE"
                    else _bump("NEW.company_code", bucket("NEW"))
                )
                if operation == "UPDATE":
                    body += _bump("OLD.company_code", bucket("OLD")).replace(
                        "WHERE OLD.company_code IS NOT NULL",
                        "WHERE OLD.company_code IS NOT NEW.company_code AND OLD.company_code IS NOT NULL",
                    )
                statements.extend(
                    [
                        f'DROP TRIGGER IF EXISTS "{full}"',
                        f'CREATE TRIGGER "{full}" AFTER {operation} ON "{name}" BEGIN {body} END',
                    ]
                )
    return statements


def upgrade_read_cache():
    with db.engine.begin() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            connection.execute(text("SELECT pg_advisory_xact_lock(824700029)"))
        missing = set(INPUT_TABLES) - set(inspect(connection).get_table_names())
        if missing:
            raise RuntimeError(
                "Initialize required input tables first: " + ", ".join(sorted(missing))
            )
        for table in (Epoch.__table__, Cache.__table__, DomainSchemaRevision.__table__):
            table.create(connection, checkfirst=True)
        connection.execute(
            text(
                """INSERT INTO analysis_input_epoch (company_code,bucket,revision)
            SELECT company_code,'shared',1 FROM company WHERE company_code IS NOT NULL AND company_code<>''
            ON CONFLICT (company_code,bucket) DO UPDATE SET revision=analysis_input_epoch.revision+1"""
            )
        )
        connection.execute(Cache.__table__.delete())
        for statement in trigger_statements(
            connection.dialect.name, db.metadata.tables
        ):
            connection.exec_driver_sql(statement)
        if (
            connection.execute(
                select(DomainSchemaRevision.revision).where(
                    DomainSchemaRevision.revision == REVISION
                )
            ).first()
            is None
        ):
            connection.execute(
                DomainSchemaRevision.__table__.insert().values(revision=REVISION)
            )
