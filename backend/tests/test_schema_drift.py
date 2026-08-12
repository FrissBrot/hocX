"""Catches the exact drift class that produced migration 0040 (see its docstring): a
production database that picked up a table/column outside Alembic (pre-Alembic era code, a
manual hotfix, a migration that only touched the DB and never the model, ...) so
`alembic upgrade head` alone stays green while the migrated schema quietly diverges from what
the ORM models declare - previously only caught by someone manually running compare_metadata
against a scratch database. This runs that same check as a regular test, against whatever
database the CI/dev alembic upgrade head already migrated.

Only add_table/remove_table/add_column/remove_column diffs are checked. compare_metadata's
other diff categories (indexes, constraints, column type/default/identity rendering) produce
a large amount of noise on this schema unrelated to real drift - unnamed UniqueConstraints get
re-derived names every call, Postgres reports IDENTITY columns differently from how SQLAlchemy
renders a matching server_default, VARCHAR/TEXT affinity differs cosmetically, etc. Properly
silencing all of that needs real Alembic comparator tuning (naming_convention, compare_type,
render_item) which is out of scope here; table/column existence is the category that actually
matches the 0040 incident and is cheap to check without that tuning.
"""
from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.db.base import Base
from app.models import *  # noqa: F401,F403  (registers every model onto Base.metadata, same as alembic/env.py)

# Investigated and confirmed harmless (see audit finding F-Niedrig-3):
#  - audit_log: deliberately has no ORM model (AuditService writes it via raw SQL only, see
#    its docstring/module) - not missing from a migration, just never meant to be ORM-mapped.
#  - attendance_fine.delete_comment: added by migration 0012 for a soft-delete flow that was
#    since replaced by a hard DELETE endpoint (see api/routes/fines.py) - confirmed unused
#    anywhere in current app code, a harmless leftover column rather than active drift.
_KNOWN_UNMAPPED_TABLES = {"audit_log"}
_KNOWN_UNMAPPED_COLUMNS = {("attendance_fine", "delete_comment")}


def test_migrated_schema_matches_orm_models(db):
    migration_context = MigrationContext.configure(db.connection())
    diff = compare_metadata(migration_context, Base.metadata)

    structural = []
    for entry in diff:
        if not isinstance(entry, tuple) or not entry:
            continue
        op = entry[0]
        if op in ("add_table", "remove_table"):
            table_name = entry[1].name
            if table_name in _KNOWN_UNMAPPED_TABLES:
                continue
            structural.append(entry)
        elif op in ("add_column", "remove_column"):
            table_name, column = entry[2], entry[3]
            if (table_name, column.name) in _KNOWN_UNMAPPED_COLUMNS:
                continue
            structural.append(entry)

    assert structural == [], (
        "alembic upgrade head no longer produces the tables/columns the ORM models expect - "
        f"either a migration is missing or a model is out of sync: {structural}"
    )
