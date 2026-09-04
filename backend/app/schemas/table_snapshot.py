from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class TableSnapshotTableSummary(BaseModel):
    table_name: str
    row_count: int
    created_at: datetime
    is_edited: bool
    edited_at: datetime | None = None


class TableSnapshotCycleSummary(BaseModel):
    cycle_config_id: uuid.UUID
    cycle_config_name: str
    cycle_year: int
    # False for a period that has at least one protocol (so it's a real, ended period
    # of this cycle) but no table_snapshot yet - a gap the "Ansicht" picker should flag
    # with a warning and offer to reconstruct. See table_snapshots.list_snapshot_cycles.
    has_snapshot: bool
    tables: list[TableSnapshotTableSummary]


class TableSnapshotRowsRead(BaseModel):
    table_name: str
    cycle_year: int
    row_count: int
    is_edited: bool
    rows: list[dict[str, Any]]


class TableSnapshotRowUpdate(BaseModel):
    values: dict[str, Any]
    # Must be explicitly true - never defaulted to true - so a client can't
    # accidentally edit frozen historical data by omission. See TableSnapshotRowDelete.
    confirm_historical_edit: bool = False


class TableSnapshotRowDelete(BaseModel):
    confirm_historical_edit: bool = False


class TableSnapshotListReconstructDraft(BaseModel):
    """Pre-filled starting point for reconstructing one list in a missing period - the
    nearest available source (an existing snapshot for this cycle_config, or the live
    list if nothing is closer) resolved server-side, so the frontend never has to
    duplicate the cycle-year distance math. The frontend lets the user edit this, then
    posts it back as a TableSnapshotListReconstructRequest."""

    source: str  # "live" or "snapshot"
    source_cycle_year: int | None
    definition_values: dict[str, Any]
    entries: list[dict[str, Any]]


class TableSnapshotListReconstructRequest(BaseModel):
    """Fills a genuine gap - a period with no snapshot yet - for one list, using data
    the client pre-filled from the nearest available source (an existing snapshot or
    the live list) and let the user review/edit. Every entry must already exist
    somewhere (live or in another snapshot) - reconstruction can edit or drop rows, not
    fabricate new ones with no prior identity; see table_snapshots.reconstruct_list_period."""

    definition_values: dict[str, Any]
    entries: list[dict[str, Any]]
