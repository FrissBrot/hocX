"""Vorschau und Auswahl beim Löschen von Protokollen und Abgaben (Datenschutz-Audit Paket 2)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DeletionPreviewFile(BaseModel):
    id: uuid.UUID
    name: str
    mime_type: str | None = None
    is_image: bool = False
    thumbnail_url: str | None = None
    created_at: datetime | None = None
    group: Literal["protocol_image", "submission", "gallery"]
    # Wird noch anderswo verwendet: bleibt in jedem Fall erhalten, nicht wählbar.
    used_elsewhere: bool = False
    label: str | None = None


class DeletionPreview(BaseModel):
    files: list[DeletionPreviewFile]


class DeletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Dateien, die mitgelöscht werden; alle anderen wählbaren wandern in die Galerie.
    delete_file_ids: list[uuid.UUID] = Field(default_factory=list, max_length=5000)


class DeletionResultRead(BaseModel):
    deleted_files: int
    kept_files: int
    untouched_files: int
