"""Schemas der Foto-Standorte (services/photo_places.py)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class PhotoPlaceRead(BaseModel):
    """Ort am Foto - ohne Koordinaten. ``key`` startet die Umgebungssuche (präziser Ort, sonst
    Ortschaft); ``near``: «Nähe …»; ``distance_m`` nur in der Umkreissuche und nur für Konten, die
    auch Koordinaten sehen dürfen."""

    key: str | None = None
    name: str | None = None
    kind: str | None = None
    locality_name: str | None = None
    locality_kind: str | None = None
    admin1_code: str | None = None
    country_code: str | None = None
    near: bool = False
    source: Literal["gps", "manual"] = "gps"
    distance_m: int | None = None


class PlaceSearchHit(BaseModel):
    key: str
    name: str
    kind: str
    admin1_code: str | None = None
    admin1_name: str | None = None
    country_code: str | None = None
    locality_name: str | None = None
    radius_km: float


class PlaceAssign(BaseModel):
    file_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    # None: manuellen Ort entfernen
    place_key: str | None = Field(default=None, max_length=80)
    upload_job_id: uuid.UUID | None = None
    # Gestückelte Auswahl: ab dem zweiten Stück die ID der ersten Antwort (ein Rückgängig für alles)
    batch_id: uuid.UUID | None = None


class PlaceAssignResult(BaseModel):
    updated_ids: list[uuid.UUID]
    unchanged_ids: list[uuid.UUID]
    skipped_gps_ids: list[uuid.UUID]
    not_found_ids: list[uuid.UUID]
    batch_id: uuid.UUID | None = None


class PlaceChangeBatchRead(BaseModel):
    id: uuid.UUID
    mode: str
    params: dict[str, Any]
    created_at: datetime
    created_by_name: str | None = None
    updated_count: int
    remaining: int
    undone_at: datetime | None = None
    can_undo: bool


class PlaceChangeUndoResult(BaseModel):
    restored_ids: list[uuid.UUID]
    conflict_ids: list[uuid.UUID]
    not_found_ids: list[uuid.UUID]


class GeoDatasetRead(BaseModel):
    source: str
    version: str
    imported_at: datetime
    rows: int
    attribution: str
