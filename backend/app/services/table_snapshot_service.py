"""Creates and serves cycle-boundary snapshots of the tables listed in
table_snapshot_config.SNAPSHOT_TABLES - see the cycle-snapshot feature plan for the
overall design (table_snapshot is a JSONB blob per table/cycle, not a parallel shadow
schema; editing a historical snapshot overwrites it in place, gated behind an explicit
confirm flag at the API layer).

Snapshots are only ever created by the daily background loop (main.py's
cycle_snapshot_loop) at a cycle boundary - there is deliberately no manual/on-demand
trigger. This is a historical-record feature, not a backup/restore tool.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Callable

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.core.cycle_utils import get_cycle_year
from app.models.entities import CycleConfig, ListColumn, ListDefinition, ListEntry, TableSnapshot
from app.services import list_columns, list_legacy_adapter
from app.services.snapshot_list_references import snapshot_list_rows
from app.services.table_snapshot_config import SNAPSHOT_TABLES, TRANSITIVE_SNAPSHOT_SCOPE
from app.services.tenant_transfer_common import row_to_dict

# How many cycles run_due_cycle_snapshots will walk backward in one tick to catch up a
# CycleConfig that's behind by more than one cycle - see that function's docstring. A
# snapshot always captures whatever the live tables look like *today*, not a true
# point-in-time record (there is no other source of historical data to draw from), so
# this is already an approximation even for the single most-recently-ended cycle; kept
# deliberately small (rather than large/unbounded) so a brand-new CycleConfig created for
# a tenant with years of pre-existing list data doesn't flood the cycle picker with many
# identical "historical" snapshots that are all really just today's data relabeled - 3
# missed boundaries in a row is already a serious, rare operational outage (this
# module's background loop runs daily), which is the actual scenario this catches up.
MAX_CYCLE_SNAPSHOT_CATCH_UP = 3


class ReconstructionIdentityError(ValueError):
    """Raised when a reconstruction payload references a row (by public_id) that can't
    be resolved to any known identity - neither a live row nor a row already captured
    in some existing snapshot for this cycle_config. Reconstruction can only edit or
    drop rows that already exist somewhere; it can never fabricate a brand new one."""


def _resolve_tenant_scoped_id_query(model: type, tenant_id: int) -> Select:
    """Returns a `select(model.id)` scoped to tenant_id - directly if the model has its
    own tenant_id column, otherwise by walking TRANSITIVE_SNAPSHOT_SCOPE recursively up
    to a directly tenant_id-scoped ancestor. This is the same resolution
    TableSnapshotService.create_snapshot uses for the target table itself, applied here
    to an intermediate parent - today that's just list_entry's single hop up to
    list_definition, but it recurses so a future multi-level chain (a table scoped via a
    parent that is itself only transitively scoped) needs no code change here, only a
    new TRANSITIVE_SNAPSHOT_SCOPE entry."""
    if hasattr(model, "tenant_id"):
        return select(model.id).where(model.tenant_id == tenant_id)
    parent_model, fk_column_name = TRANSITIVE_SNAPSHOT_SCOPE[model.__tablename__]
    parent_ids = _resolve_tenant_scoped_id_query(parent_model, tenant_id)
    fk_column = getattr(model, fk_column_name)
    return select(model.id).where(fk_column.in_(parent_ids))


# Felder einer Listendefinition, die die Rekonstruktion aus dem (bearbeiteten) Entwurf übernimmt;
# Spalten und Rollen-Spalten werden separat gegen bekannte Spalten aufgelöst.
RECONSTRUCT_DEFINITION_FIELDS = ("name", "description", "is_active")


class TableSnapshotService:
    def create_snapshot(
        self,
        db: Session,
        *,
        tenant_id: int,
        cycle_config: CycleConfig,
        cycle_year: int,
    ) -> list[TableSnapshot]:
        """Writes one TableSnapshot row per table in SNAPSHOT_TABLES, scoped to
        tenant_id. Commits once at the end, so a snapshot is all-or-nothing per cycle -
        callers never see a partially-written historical view.

        Skips any table that already has a snapshot for this (tenant, cycle_config,
        cycle_year) - this is what makes run_due_cycle_snapshots idempotent and keeps it
        from ever clobbering a historical edit already made to that table. There is no
        force/overwrite path: a table_snapshot row, once written, is only ever changed
        again through the guarded historical-edit API (see table_snapshots routes), not
        by re-running this.

        A model with its own tenant_id column is fetched with a plain
        `WHERE tenant_id = ...`. A table that is only transitively tenant-scoped (via a
        parent FK - today just list_entry through list_definition) is listed in
        TRANSITIVE_SNAPSHOT_SCOPE instead and fetched via _resolve_tenant_scoped_id_query,
        which walks that chain recursively - see that function's docstring.
        """
        existing_by_table = {
            row.table_name: row
            for row in db.scalars(
                select(TableSnapshot).where(
                    TableSnapshot.tenant_id == tenant_id,
                    TableSnapshot.cycle_config_id == cycle_config.id,
                    TableSnapshot.cycle_year == cycle_year,
                )
            )
        }

        written: list[TableSnapshot] = []
        for table_name, model in SNAPSHOT_TABLES.items():
            existing = existing_by_table.get(table_name)
            if existing is not None:
                written.append(existing)
                continue

            transitive_scope = TRANSITIVE_SNAPSHOT_SCOPE.get(table_name)
            if transitive_scope is not None:
                parent_model, fk_column_name = transitive_scope
                parent_ids = _resolve_tenant_scoped_id_query(parent_model, tenant_id)
                fk_column = getattr(model, fk_column_name)
                query = select(model).where(fk_column.in_(parent_ids))
            else:
                query = select(model).where(model.tenant_id == tenant_id)
            # Order by whatever the model's actual primary key columns are rather than
            # assuming a single `.id` - both list_definition/list_entry have a plain
            # `id`, but a future table with a composite primary key (no single `id`
            # column) would otherwise crash here.
            pk_columns = sa_inspect(model).primary_key
            if pk_columns:
                query = query.order_by(*pk_columns)
            rows = db.scalars(query).all()
            payload: list[dict[str, Any]] = [row_to_dict(row) for row in rows]

            if table_name == "list_entry":
                payload = snapshot_list_rows(db, payload, tenant_id)

            snapshot = TableSnapshot(
                tenant_id=tenant_id,
                cycle_config_id=cycle_config.id,
                cycle_year=cycle_year,
                table_name=table_name,
                snapshot_json=payload,
                row_count=len(payload),
            )
            db.add(snapshot)
            db.flush()
            written.append(snapshot)

        db.commit()
        return written

    def reconstruct_list_period(
        self,
        db: Session,
        *,
        tenant_id: int,
        cycle_config: CycleConfig,
        cycle_year: int,
        list_public_id: str,
        definition_values: dict[str, Any],
        entry_payloads: list[dict[str, Any]],
        edited_by: int,
    ) -> None:
        """Fills a genuine snapshot gap for one list in one period. The caller (the
        reconstruct route) already pre-filled definition_values/entry_payloads from the
        nearest available source (an existing snapshot or the live list) and let a human
        review/edit them - this just resolves each row's real identity (never trusting
        client-supplied ids) and writes it into the period's table_snapshot rows.

        Every identity is re-resolved from a live row or an existing snapshot, so a
        reconstructed row always carries the same id/public_id it has everywhere else in
        the system - see _resolve_list_definition_identity/_resolve_list_entry_identities_batch.
        Raises ReconstructionIdentityError if the list or any entry can't be resolved:
        reconstruction can only edit or drop already-known rows, never fabricate one.
        """
        definition_identity = _resolve_list_definition_identity(
            db, public_id=list_public_id, tenant_id=tenant_id, cycle_config_id=cycle_config.id
        )
        if definition_identity is None:
            raise ReconstructionIdentityError(f"Unknown list {list_public_id}")
        list_internal_id = definition_identity["id"]

        # Spalten: nur solche, die die Liste live oder in einem Backup hat (oder die synthetischen
        # Keys alter Backups) - die Rekonstruktion bearbeitet, erfindet aber nichts
        known_columns = _known_list_columns(db, tenant_id=tenant_id, cycle_config_id=cycle_config.id, list_definition_id=list_internal_id)
        column_rows: list[dict[str, Any]] = []
        for index, column in enumerate(definition_values.get("columns") or []):
            key = str(column.get("key") or column.get("id") or "")
            known = known_columns.get(key)
            if known is None:
                raise ReconstructionIdentityError(f"Unknown list column {key}")
            column_rows.append({
                **known, "list_definition_id": list_internal_id,
                "title": str(column.get("title") or known.get("title") or ""),
                "value_type": column.get("value_type") if column.get("value_type") in list_columns.VALUE_TYPES else known.get("value_type", "text"),
                "sort_index": (index + 1) * 10,
            })
        column_keys = {str(row["key"]) for row in column_rows}
        # Nur bearbeitbare Felder übernehmen (Allowlist): id/public_id/tenant_id/created_at/
        # updated_at und andere Systemfelder kommen ausschliesslich aus definition_identity,
        # sonst liesse sich im Backup eine Zeile mit fremder interner id ablegen (Nachtlauf
        # 2026-11-20, Listenstand-Rekonstruktion).
        plain_values = {key: definition_values[key] for key in RECONSTRUCT_DEFINITION_FIELDS if key in definition_values}
        by_key = {str(row["key"]): row for row in column_rows}
        role = lambda key: by_key[str(key)].get("id") if key and str(key) in by_key else None  # noqa: E731
        definition_row = {
            **definition_identity, "tenant_id": tenant_id, **plain_values,
            "label_column_id": role(definition_values.get("label_column_id")),
            "responsible_column_id": role(definition_values.get("responsible_column_id")),
        }

        entry_identities = _resolve_list_entry_identities_batch(
            db,
            public_ids=[payload.get("public_id") for payload in entry_payloads if payload.get("public_id")],
            list_definition_internal_id=list_internal_id,
            cycle_config_id=cycle_config.id,
            tenant_id=tenant_id,
        )
        entry_rows: list[dict[str, Any]] = []
        for payload in entry_payloads:
            entry_public_id = payload.get("public_id")
            entry_identity = entry_identities.get(entry_public_id) if entry_public_id else None
            if entry_identity is None:
                raise ReconstructionIdentityError(f"Unknown list entry {entry_public_id}")
            values = payload.get("values_json") if isinstance(payload.get("values_json"), dict) else {}
            entry_rows.append({
                **entry_identity,
                "list_definition_id": list_internal_id,
                "sort_index": payload.get("sort_index", 0),
                # Nur Werte bekannter Spalten (keine erfundenen Keys)
                "values_json": {key: value for key, value in values.items() if key in column_keys and isinstance(value, dict)},
            })

        entry_rows = snapshot_list_rows(db, entry_rows, tenant_id)
        now = datetime.now(UTC)
        _upsert_snapshot_rows(
            db, tenant_id=tenant_id, cycle_config_id=cycle_config.id, cycle_year=cycle_year,
            table_name="list_definition",
            keep=lambda row: row.get("id") != list_internal_id,
            new_rows=[definition_row], edited_by=edited_by, edited_at=now,
        )
        _upsert_snapshot_rows(
            db, tenant_id=tenant_id, cycle_config_id=cycle_config.id, cycle_year=cycle_year,
            table_name="list_column",
            keep=lambda row: row.get("list_definition_id") != list_internal_id,
            new_rows=column_rows, edited_by=edited_by, edited_at=now,
        )
        _upsert_snapshot_rows(
            db, tenant_id=tenant_id, cycle_config_id=cycle_config.id, cycle_year=cycle_year,
            table_name="list_entry",
            keep=lambda row: row.get("list_definition_id") != list_internal_id,
            new_rows=entry_rows, edited_by=edited_by, edited_at=now,
        )
        db.commit()


def build_reconstruction_draft(
    db: Session,
    *,
    tenant_id: int,
    cycle_config: CycleConfig,
    cycle_year: int,
    list_public_id: str,
) -> dict[str, Any] | None:
    """Finds the nearest available source for `list_public_id`'s data - the live list,
    or any existing complete snapshot for this cycle_config - ranked by distance
    (|source_cycle_year - cycle_year|, with live ranked by |current_cycle_year -
    cycle_year|) and returns a pre-filled draft the frontend presents as an editable
    starting point for reconstructing this list in `cycle_year`. Tries candidates in
    distance order and skips any that don't actually contain this list (e.g. the
    nearest snapshot predates the list's creation) - returns the first real match.
    None if no source has this list at all (unknown list - reconstruction can't
    fabricate one with no prior existence anywhere)."""
    today = date.today()
    current_cycle_year = get_cycle_year(today, cycle_config.reset_month, cycle_config.reset_day)

    existing_years = sorted({
        row.cycle_year
        for row in db.scalars(
            select(TableSnapshot).where(
                TableSnapshot.tenant_id == tenant_id,
                TableSnapshot.cycle_config_id == cycle_config.id,
                TableSnapshot.table_name == "list_definition",
            )
        )
    })
    candidates: list[tuple[int, str, int | None]] = [(abs(current_cycle_year - cycle_year), "live", None)]
    candidates += [(abs(year - cycle_year), "snapshot", year) for year in existing_years]
    candidates.sort(key=lambda c: c[0])

    for _, source, source_cycle_year in candidates:
        if source == "live":
            draft = _draft_from_live(db, tenant_id=tenant_id, list_public_id=list_public_id)
        else:
            draft = _draft_from_snapshot(
                db, tenant_id=tenant_id, cycle_config_id=cycle_config.id,
                source_cycle_year=source_cycle_year, list_public_id=list_public_id,
            )
        if draft is not None:
            return {"source": source, "source_cycle_year": source_cycle_year, **draft}
    return None


def _draft_from_live(db: Session, *, tenant_id: int, list_public_id: str) -> dict[str, Any] | None:
    live_def = db.scalar(select(ListDefinition).where(ListDefinition.public_id == list_public_id, ListDefinition.tenant_id == tenant_id))
    if live_def is None:
        return None
    columns = list_columns.columns_of(live_def)
    label = list_columns.label_column(live_def)
    responsible = list_columns.responsible_column(live_def)
    definition_values = {
        "name": live_def.name,
        "description": live_def.description,
        "is_active": live_def.is_active,
        "columns": [
            {"key": column.key, "title": column.title, "value_type": column.value_type, "sort_index": column.sort_index}
            for column in columns
        ],
        "label_column_id": label.key if label else None,
        "responsible_column_id": responsible.key if responsible else None,
    }
    live_entries = db.scalars(
        select(ListEntry).where(ListEntry.list_definition_id == live_def.id).order_by(ListEntry.sort_index)
    ).all()
    entries = [
        {"public_id": str(entry.public_id), "sort_index": entry.sort_index, "values_json": dict(entry.values_json or {})}
        for entry in live_entries
    ]
    return {"definition_values": definition_values, "entries": entries}


def _draft_from_snapshot(
    db: Session, *, tenant_id: int, cycle_config_id: int, source_cycle_year: int, list_public_id: str
) -> dict[str, Any] | None:
    def_snapshot = db.scalar(
        select(TableSnapshot).where(
            TableSnapshot.tenant_id == tenant_id,
            TableSnapshot.cycle_config_id == cycle_config_id,
            TableSnapshot.cycle_year == source_cycle_year,
            TableSnapshot.table_name == "list_definition",
        )
    )
    def_row = next((r for r in (def_snapshot.snapshot_json if def_snapshot else []) if r.get("public_id") == list_public_id), None)
    if def_row is None:
        return None
    def lookup(table_name: str) -> TableSnapshot | None:
        return db.scalar(
            select(TableSnapshot).where(
                TableSnapshot.tenant_id == tenant_id,
                TableSnapshot.cycle_config_id == cycle_config_id,
                TableSnapshot.cycle_year == source_cycle_year,
                TableSnapshot.table_name == table_name,
            )
        )

    columns, entry_rows = list_rows_for_definition(
        db, tenant_id=tenant_id, definition_row=def_row, column_snapshot=lookup("list_column"), entry_snapshot=lookup("list_entry")
    )
    by_id = {column.get("id"): column for column in columns}
    role = lambda column_id: str(by_id[column_id]["key"]) if column_id in by_id else None  # noqa: E731
    definition_values = {
        "name": def_row.get("name"),
        "description": def_row.get("description"),
        "is_active": def_row.get("is_active"),
        "columns": [
            {"key": str(column["key"]), "title": column.get("title") or "", "value_type": column.get("value_type") or "text", "sort_index": column.get("sort_index") or 0}
            for column in columns
        ],
        "label_column_id": role(def_row.get("label_column_id")),
        "responsible_column_id": role(def_row.get("responsible_column_id")),
    }
    entries = [
        {"public_id": r.get("public_id"), "sort_index": r.get("sort_index", 0), "values_json": dict(r.get("values_json") or {})}
        for r in entry_rows
    ]
    return {"definition_values": definition_values, "entries": entries}


# ── Spalten in Zyklus-Backups (Migration 0186) ──────────────────────────────────────────────


def _live_legacy_keys(db: Session, tenant_id: int, definition_ids: set[int]) -> dict[int, dict[str, str]]:
    """Liste -> legacy_key -> Key der noch existierenden Spalten (mandantengebunden)."""
    if not definition_ids:
        return {}
    rows = db.execute(
        select(ListColumn.list_definition_id, ListColumn.legacy_key, ListColumn.key)
        .join(ListDefinition, ListDefinition.id == ListColumn.list_definition_id)
        .where(ListColumn.list_definition_id.in_(definition_ids), ListDefinition.tenant_id == tenant_id, ListColumn.legacy_key.is_not(None))
    ).all()
    result: dict[int, dict[str, str]] = {}
    for definition_id, legacy_key, key in rows:
        result.setdefault(definition_id, {})[legacy_key] = str(key)
    return result


def snapshot_columns_by_definition(
    db: Session, *, tenant_id: int, definition_rows: list[dict[str, Any]], column_rows: list[dict[str, Any]] | None
) -> dict[int, list[dict[str, Any]]]:
    """Spalten je Liste eines Backups: aus den list_column-Zeilen (Backups ab 0186), sonst über
    den v1-Adapter aus den alten Feldern der list_definition-Zeilen."""
    result: dict[int, list[dict[str, Any]]] = {}
    for row in column_rows or []:
        result.setdefault(row.get("list_definition_id"), []).append(row)
    missing = [row for row in definition_rows if row.get("id") not in result]
    if missing:
        live = _live_legacy_keys(db, tenant_id, {row.get("id") for row in missing if isinstance(row.get("id"), int)})
        result.update(list_legacy_adapter.table_snapshot_list_columns(missing, live_keys=live))
    for columns in result.values():
        columns.sort(key=lambda column: (column.get("sort_index") or 0, str(column.get("key"))))
    return result


def list_rows_for_definition(
    db: Session, *, tenant_id: int, definition_row: dict[str, Any], column_snapshot: Any, entry_snapshot: Any
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(Spalten, Einträge mit values_json) einer Liste in einem Backup, alte Backups hochgestuft."""
    columns_by_definition = snapshot_columns_by_definition(
        db, tenant_id=tenant_id, definition_rows=[definition_row],
        column_rows=[r for r in (column_snapshot.snapshot_json if column_snapshot else []) if r.get("list_definition_id") == definition_row.get("id")],
    )
    entries = [r for r in (entry_snapshot.snapshot_json if entry_snapshot else []) if r.get("list_definition_id") == definition_row.get("id")]
    entries = list_legacy_adapter.upgrade_table_snapshot_rows("list_entry", entries, columns_by_definition=columns_by_definition)
    return columns_by_definition.get(definition_row.get("id"), []), entries


def _known_list_columns(db: Session, *, tenant_id: int, cycle_config_id: int, list_definition_id: int) -> dict[str, dict[str, Any]]:
    """Alle Spalten, die eine Liste live oder in einem Backup dieses Zyklus hat(te), nach Key."""
    known: dict[str, dict[str, Any]] = {}
    definition = db.get(ListDefinition, list_definition_id)
    if definition is not None and definition.tenant_id == tenant_id:
        for column in definition.columns:
            known[column.key] = {"id": column.id, "public_id": str(column.public_id), "key": column.key, "title": column.title, "value_type": column.value_type, "legacy_key": column.legacy_key}
    snapshots = db.scalars(
        select(TableSnapshot).where(
            TableSnapshot.tenant_id == tenant_id, TableSnapshot.cycle_config_id == cycle_config_id,
            TableSnapshot.table_name.in_(("list_definition", "list_column")),
        )
    ).all()
    definition_rows = [r for s in snapshots if s.table_name == "list_definition" for r in s.snapshot_json if r.get("id") == list_definition_id]
    column_rows = [r for s in snapshots if s.table_name == "list_column" for r in s.snapshot_json if r.get("list_definition_id") == list_definition_id]
    for row in column_rows:
        known.setdefault(str(row.get("key")), {k: row.get(k) for k in ("id", "public_id", "key", "title", "value_type", "legacy_key")})
    for columns in list_legacy_adapter.table_snapshot_list_columns(definition_rows, live_keys=_live_legacy_keys(db, tenant_id, {list_definition_id})).values():
        for column in columns:
            known.setdefault(str(column["key"]), {"id": None, "public_id": None, **{k: column.get(k) for k in ("key", "title", "value_type", "legacy_key")}})
    return known


def _resolve_list_definition_identity(
    db: Session, *, public_id: str, tenant_id: int, cycle_config_id: int
) -> dict[str, Any] | None:
    """Resolves {id, public_id, created_at, updated_at} for a list_definition addressed
    by public_id - the live row if it still exists (tenant-scoped), otherwise any
    existing table_snapshot("list_definition") row for this cycle_config that already
    captured it. None if neither source has it."""
    live = db.scalar(select(ListDefinition).where(ListDefinition.public_id == public_id, ListDefinition.tenant_id == tenant_id))
    if live is not None:
        return {
            "id": live.id,
            "public_id": str(live.public_id),
            "created_at": live.created_at.isoformat(),
            "updated_at": live.updated_at.isoformat(),
        }
    other_snapshots = db.scalars(
        select(TableSnapshot).where(
            TableSnapshot.tenant_id == tenant_id,
            TableSnapshot.cycle_config_id == cycle_config_id,
            TableSnapshot.table_name == "list_definition",
        )
    )
    for snap in other_snapshots:
        for row in snap.snapshot_json:
            if row.get("public_id") == public_id:
                return {"id": row["id"], "public_id": row["public_id"], "created_at": row.get("created_at"), "updated_at": row.get("updated_at")}
    return None


def _resolve_list_entry_identities_batch(
    db: Session, *, public_ids: list[str], list_definition_internal_id: int, tenant_id: int, cycle_config_id: int
) -> dict[str, dict[str, Any]]:
    """Batched counterpart to _resolve_list_definition_identity, for every requested
    list_entry at once - scoped to the already-resolved list_definition_internal_id
    (itself tenant-verified), so no separate tenant filter is needed on ListEntry (it has
    no tenant_id column). Returns {public_id: {id, public_id, created_at, updated_at}} for
    every id resolvable via a live row or an existing table_snapshot("list_entry") row for
    this cycle_config; a requested id absent from the result was resolvable in neither.

    Resolves every id in at most one live query plus one full pass over this
    cycle_config's list_entry snapshots, instead of a query and a full snapshot-array
    rescan per entry (audit fix, 2026-09-17: reconstructing a list whose live rows are
    gone - the common case, that's the whole point of reconstruction - used to cost
    O(entries x existing snapshot rows), since the previous per-entry version re-ran both
    the query and the linear scan from scratch for every single entry)."""
    resolved: dict[str, dict[str, Any]] = {}
    remaining = set(public_ids)
    if not remaining:
        return resolved

    live_rows = db.scalars(
        select(ListEntry).where(ListEntry.public_id.in_(remaining), ListEntry.list_definition_id == list_definition_internal_id)
    )
    for entry in live_rows:
        pid = str(entry.public_id)
        resolved[pid] = {
            "id": entry.id, "public_id": pid,
            "created_at": entry.created_at.isoformat(), "updated_at": entry.updated_at.isoformat(),
        }
    remaining -= resolved.keys()
    if not remaining:
        return resolved

    other_snapshots = db.scalars(
        select(TableSnapshot).where(
            TableSnapshot.tenant_id == tenant_id,
            TableSnapshot.cycle_config_id == cycle_config_id,
            TableSnapshot.table_name == "list_entry",
        )
    )
    for snap in other_snapshots:
        for row in snap.snapshot_json:
            pid = row.get("public_id")
            if pid in remaining and row.get("list_definition_id") == list_definition_internal_id:
                resolved[pid] = {"id": row["id"], "public_id": row["public_id"], "created_at": row.get("created_at"), "updated_at": row.get("updated_at")}
        remaining -= resolved.keys()
        if not remaining:
            break
    return resolved


def _upsert_snapshot_rows(
    db: Session,
    *,
    tenant_id: int,
    cycle_config_id: int,
    cycle_year: int,
    table_name: str,
    keep: Callable[[dict[str, Any]], bool],
    new_rows: list[dict[str, Any]],
    edited_by: int,
    edited_at: datetime,
) -> None:
    """Get-or-create the (tenant, cycle_config, cycle_year, table_name) snapshot row,
    drop whichever existing entries `keep` rejects (the ones being replaced), append
    new_rows, and flag it as edited. Used by reconstruct_list_period to fold one list's
    reconstructed data into a period's snapshot without disturbing any other list
    already captured there (each call only ever touches rows for the one list it's
    reconstructing)."""
    snapshot = db.scalar(
        select(TableSnapshot).where(
            TableSnapshot.tenant_id == tenant_id,
            TableSnapshot.cycle_config_id == cycle_config_id,
            TableSnapshot.cycle_year == cycle_year,
            TableSnapshot.table_name == table_name,
        )
    )
    if snapshot is None:
        snapshot = TableSnapshot(
            tenant_id=tenant_id, cycle_config_id=cycle_config_id, cycle_year=cycle_year,
            table_name=table_name, snapshot_json=[],
        )
        db.add(snapshot)
        db.flush()
    updated_rows = [row for row in snapshot.snapshot_json if keep(row)] + new_rows
    snapshot.snapshot_json = updated_rows
    snapshot.row_count = len(updated_rows)
    snapshot.is_edited = True
    snapshot.edited_at = edited_at
    snapshot.edited_by = edited_by


def run_due_cycle_snapshots(db: Session, service: TableSnapshotService) -> None:
    """Daily-loop entry point (see main.py's cycle_snapshot_loop): for every CycleConfig,
    snapshots the most recently *completed* cycle (current_cycle_year - 1) if any table in
    SNAPSHOT_TABLES is missing a snapshot for it yet - same as always, so a brand-new
    CycleConfig (even one set up for a group that's already run cycles for years before
    adopting this system) still only ever gets that one cycle's worth of snapshots, not a
    pile of extra ones that would all just be today's data relabeled as older years (there
    is no other source of historical data to draw from, so a snapshot dated further back
    than "the cycle that just ended" is already an approximation, not a real record of
    that time).

    If the CycleConfig already has at least one snapshot from some earlier tick, though,
    this additionally walks further backward (bounded by MAX_CYCLE_SNAPSHOT_CATCH_UP,
    stopping at the first cycle that's already fully snapshotted) to self-heal a real
    operational outage spanning more than one cycle boundary - previously this only ever
    looked exactly one cycle back regardless, so once a second boundary passed with the
    loop down, the older missed cycle could never be reached again (audit fix,
    2026-09-17): current_cycle_year - 1 always points at whichever cycle *just* ended,
    never further, so it silently and permanently skipped it.

    Whether a table already has a snapshot for a given cycle is checked directly against
    table_snapshot rather than tracked in a separate marker column/table, so this is both
    idempotent and self-heals a missed check day. Checked per-table, not just "does this
    cycle have any snapshot at all": otherwise a table added to SNAPSHOT_TABLES after a
    cycle was already (even partially) snapshotted would never get backfilled
    automatically - the loop would see the cycle as "done" from its first snapshotted
    table onward and skip it forever. create_snapshot() itself already skips any table
    that already has a snapshot, so calling it again here only ever fills in what's
    missing - it never touches an admin's historical edits on an already-snapshotted
    table.
    """
    today = date.today()
    for cycle_config in db.scalars(select(CycleConfig)):
        current_cycle_year = get_cycle_year(today, cycle_config.reset_month, cycle_config.reset_day)
        candidate_cycle_year = current_cycle_year - 1
        has_prior_snapshot = (
            db.scalar(select(TableSnapshot.id).where(TableSnapshot.cycle_config_id == cycle_config.id).limit(1)) is not None
        )
        max_cycles_this_tick = MAX_CYCLE_SNAPSHOT_CATCH_UP if has_prior_snapshot else 1
        for _ in range(max_cycles_this_tick):
            existing_tables = set(
                db.scalars(
                    select(TableSnapshot.table_name).where(
                        TableSnapshot.cycle_config_id == cycle_config.id,
                        TableSnapshot.cycle_year == candidate_cycle_year,
                    )
                )
            )
            if existing_tables >= SNAPSHOT_TABLES.keys():
                break
            service.create_snapshot(
                db,
                tenant_id=cycle_config.tenant_id,
                cycle_config=cycle_config,
                cycle_year=candidate_cycle_year,
            )
            candidate_cycle_year -= 1


def get_snapshot_row(
    db: Session,
    *,
    tenant_id: int,
    cycle_config_id: int,
    cycle_year: int,
    table_name: str,
    row_public_id: str,
) -> tuple[TableSnapshot, dict[str, Any], int] | None:
    """Looks up one row inside a table_snapshot's snapshot_json by its original
    (unremapped) public_id - every snapshotted table has one, and addressing by
    public_id rather than the raw internal bigint id matches how every other route in
    this codebase exposes row identity to clients (see public_id_service module
    docstring). Returns (snapshot, row_dict, index_in_array) so a caller can mutate
    snapshot_json[index] in place, or None if the snapshot or the row within it doesn't
    exist. Used by the guarded historical-edit/delete API routes; also the natural place
    a future block-reference-resolution feature would call into (see the cycle-snapshot
    feature plan, section 6).

    A table without a public_id column (composite primary key instead) would have every
    row's "public_id" key simply absent, so this returns None for it rather than
    matching by coincidence - not an issue for list_definition/list_entry today, both of
    which have a public_id, but relevant if a junction-style table is ever added here."""
    snapshot = db.scalar(
        select(TableSnapshot).where(
            TableSnapshot.tenant_id == tenant_id,
            TableSnapshot.cycle_config_id == cycle_config_id,
            TableSnapshot.cycle_year == cycle_year,
            TableSnapshot.table_name == table_name,
        )
    )
    if snapshot is None:
        return None
    for index, row in enumerate(snapshot.snapshot_json):
        if row.get("public_id") == row_public_id:
            return snapshot, row, index
    return None
