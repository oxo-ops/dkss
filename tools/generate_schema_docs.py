"""Generate the ORM reference without opening a database connection."""

import contextlib
import io
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def render():
    from sqlalchemy import String
    from sqlalchemy.engine import Engine
    from dkss_app import create_app
    from dkss_app.extensions import db

    with patch.dict(
        os.environ, {"RENDER": "", "AWS_EC2_METADATA_DISABLED": "true"}
    ), patch.object(
        Engine, "connect", side_effect=AssertionError("Schema export connected to DB")
    ), contextlib.redirect_stdout(
        io.StringIO()
    ):
        create_app(
            {
                "SECRET_KEY": "schema-export-only",
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                "S3_BUCKET_NAME": "",
                "RATELIMIT_ENABLED": False,
            }
        )
    lines = [
        "# Database schema",
        "",
        "Generated from SQLAlchemy metadata by `python tools/generate_schema_docs.py`.",
        "Relationships below are declared foreign keys; company scoping is enforced by application queries.",
        "",
        "```mermaid",
        "erDiagram",
        "    direction TB",
    ]
    core = {
        "vehicle",
        "vehicle_maintenance_record",
        "vehicle_part_replacement",
        "vehicle_periodic_inspection_record",
        "vehicle_document_import_draft",
        "vehicle_driving_report_record",
    }
    for name in sorted(core):
        lines.append(f"    {name} {{")
        for column in db.metadata.tables[name].primary_key.columns:
            kind = "string" if isinstance(column.type, String) else "integer"
            lines.append(f"        {kind} {column.name} PK")
        lines.append("    }")
    for name in sorted(core):
        for fk in sorted(
            db.metadata.tables[name].foreign_keys, key=lambda k: k.parent.name
        ):
            if fk.column.table.name in core:
                parent = "|o" if fk.parent.nullable else "||"
                lines.append(
                    f'    {fk.column.table.name} {parent}--o{{ {name} : "{fk.parent.name}"'
                )
    lines.extend(["```", "", f"Tables: {len(db.metadata.tables)}", ""])
    for name, table in sorted(db.metadata.tables.items()):
        lines.extend(
            [
                f"## {name}",
                "",
                "| Column | Type | Nullable | Primary key | Foreign key |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for column in table.columns:
            references = ", ".join(
                sorted(fk.target_fullname for fk in column.foreign_keys)
            )
            lines.append(
                f"| {column.name} | {column.type} | {column.nullable} | {column.primary_key} | {references} |"
            )
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    result = render()
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(result, encoding="utf-8")
    else:
        print(result, end="")
