"""Upload-Verlauf (routes/upload_jobs.py, services/upload_job_service.py)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

UploadChannel = Literal[
    "gallery", "document", "protocol_image", "todo", "submission_link", "abgabebox", "word_import", "tenant_import", "cloud_import"
]
UploadJobStatus = Literal["open", "processing", "done", "partial", "failed", "cancelled"]
UploadItemStatus = Literal["uploaded", "duplicate", "metadata_updated", "rejected", "infected", "failed", "discarded"]
# Abgeleiteter Zustand der Datei eines Items beim Lesen (nie gespeichert)
UploadItemFileState = Literal["ok", "trashed", "deleted", "infected_later", "scan_pending", "hidden"]

# Höchstens so viele Datei-IDs liefert GET /upload-jobs/{id}/file-ids (Grundlage «Alle N auswählen»)
MAX_JOB_FILE_IDS = 10_000
MAX_CLIENT_RESULTS_PER_CALL = 500
MAX_CLIENT_RESULTS_PER_JOB = 2000
# Grösse einer vom Browser gemeldeten Datei: höchstens BIGINT (upload_job_item.size_bytes). Ohne
# Grenze scheiterte ein grösserer Wert erst beim INSERT (DataError, 500 plus Fehlerprotokoll).
MAX_REPORTED_SIZE_BYTES = 2**63 - 1


class UploadJobCreate(BaseModel):
    channel: Literal["gallery", "document", "todo"]
    event_id: uuid.UUID | None = None
    submission_assignment_id: uuid.UUID | None = None
    submission_element_ref: str | None = Field(default=None, max_length=200)
    cycle_config_id: uuid.UUID | None = None
    protocol_todo_id: uuid.UUID | None = None
    tags: list[str] = Field(default_factory=list, max_length=50)
    estimated_taken_on: date | None = None
    include_gps: bool = True


class UploadClientResult(BaseModel):
    """Eine vom Browser vor dem Senden abgelehnte Datei (E-14): nur Name, Grösse und Code."""

    name: str = Field(max_length=500)
    size: int | None = Field(default=None, ge=0, le=MAX_REPORTED_SIZE_BYTES)
    code: Literal["too_large", "unsupported_format", "rule_violation", "heic_unreadable", "client_rejected"] = "client_rejected"


class UploadClientResults(BaseModel):
    items: list[UploadClientResult] = Field(min_length=1, max_length=MAX_CLIENT_RESULTS_PER_CALL)


class UploadJobRef(BaseModel):
    """Bezug des Vorgangs für die Anzeige (nur, was die Person ohnehin sieht)."""

    kind: Literal["event", "submission", "cycle", "protocol", "todo", "import"]
    id: uuid.UUID | None = None
    label: str | None = None
    on_date: date | None = None


class UploadJobCounts(BaseModel):
    total: int = 0
    uploaded: int = 0
    duplicates: int = 0
    metadata_updated: int = 0
    rejected: int = 0
    infected: int = 0
    failed: int = 0
    discarded: int = 0


class UploadJobRead(BaseModel):
    id: uuid.UUID
    channel: UploadChannel
    actor_kind: str
    # Anzeigename des Kontos; None = ohne Konto (Abgabebox) oder gelöschtes Konto (siehe actor_kind)
    created_by_name: str | None = None
    created_by_deleted: bool = False
    is_mine: bool = False
    status: UploadJobStatus
    reconstructed: bool = False
    created_at: datetime
    finished_at: datetime | None = None
    counts: UploadJobCounts
    ref: UploadJobRef | None = None
    # Anteil Bilder (für die Wahl Foto-Raster oder nur Ergebnisliste)
    image_count: int | None = None


class UploadJobList(BaseModel):
    items: list[UploadJobRead]
    # Keyset-Cursor für «Mehr laden» (keine Gesamtzahl)
    next_cursor: str | None = None


class CameraGroup(BaseModel):
    """Eine Kamera im Vorgang (Make/Model, bei gleichen Modellen zusätzlich das Kürzel der
    Seriennummer - als Gruppenschlüssel, nie die Seriennummer selbst)."""

    key: str
    camera_make: str | None = None
    camera_model: str | None = None
    # Laufende Nummer bei mehreren Geräten desselben Modells (1, 2, …), sonst None
    device_index: int | None = None
    count: int
    earliest: datetime | None = None
    latest: datetime | None = None
    with_time: int = 0
    with_gps_time: int = 0
    # Vorschlag aus der GPS-Zeit (Minuten, Kamera minus Satellitenzeit), wenn eindeutig
    suggested_shift_minutes: int | None = None
    suggestion_samples: int = 0


class UploadJobDetail(UploadJobRead):
    options: dict = {}
    import_job_id: uuid.UUID | None = None
    cameras: list[CameraGroup] = []
    # Dateien des Vorgangs, die es noch gibt (inkl. Papierkorb) bzw. davon beschreibbare
    file_count: int = 0


class UploadJobItemFile(BaseModel):
    # Nur gesetzt, wenn die Person die Datei sehen darf (sonst nur der Zustand)
    id: uuid.UUID | None = None
    state: UploadItemFileState
    is_image: bool = False
    thumbnail_url: str | None = None


class UploadJobItemRead(BaseModel):
    id: int
    position: int
    name: str | None
    status: UploadItemStatus
    reason_code: str | None = None
    reason_params: dict = {}
    source: Literal["server", "client"]
    size_bytes: int | None = None
    mime_type: str | None = None
    applied: list[str] = []
    file: UploadJobItemFile | None = None
    existing_file: UploadJobItemFile | None = None


class UploadJobItemList(BaseModel):
    items: list[UploadJobItemRead]
    next_cursor: int | None = None


class UploadJobFileIds(BaseModel):
    file_ids: list[uuid.UUID]
    # Dateien des Vorgangs (ohne Papierkorb) - Unterschied zu file_ids = nicht beschreibbar
    total: int
    truncated: bool = False


class UploadJobOfFile(BaseModel):
    """Anzeige an der Datei: «über Upload mit 48 Fotos»."""

    id: uuid.UUID
    channel: UploadChannel
    created_at: datetime
    created_by_name: str | None = None
    uploaded_count: int
    reconstructed: bool = False
