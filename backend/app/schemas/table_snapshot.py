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
