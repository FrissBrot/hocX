"""Central list of tables covered by the cycle-snapshot feature (see
table_snapshot_service.py). Adding/removing a table here is a one-line change, no
migration needed - table_snapshot.table_name is plain text, not a DB-level enum/FK.

Scope is deliberately narrow: only the user-created "Listen" feature (list_definition +
list_entry), not every domain table in the schema. A tenant's own structured lists are
the thing that actually needs a historical record across cycles; participants,
protocols, templates etc. are not in scope here.
"""

from __future__ import annotations

from app.models.entities import ListDefinition, ListEntry

SNAPSHOT_TABLES: dict[str, type] = {
    "list_definition": ListDefinition,
    "list_entry": ListEntry,
}

# Tables in SNAPSHOT_TABLES whose model has no tenant_id column of its own - scoped
# instead via a FK to a parent model. Maps table_name -> (parent_model, fk_column_name).
# The parent is resolved recursively by TableSnapshotService: if the parent model itself
# has no tenant_id, its own __tablename__ must also be a key here. Mirrors the join
# pattern tenant_export_service.py already uses for list_entry.
#
# Read the FK column name directly off the model in app/models/entities.py when adding
# an entry here, never assume it from a naming convention - some FKs in this schema
# don't follow the `f"{parent_table}_id"` pattern (e.g. SubmissionUpload.assignment_id).
# Getting this wrong would leak another tenant's rows into a snapshot.
TRANSITIVE_SNAPSHOT_SCOPE: dict[str, tuple[type, str]] = {
    "list_entry": (ListDefinition, "list_definition_id"),
}
