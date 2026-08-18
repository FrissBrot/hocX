from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

FileOverviewSource = Literal["protocol_image", "word_import", "submission_upload"]


class FileOverviewItem(BaseModel):
    id: int
    original_name: str
    mime_type: str | None
    file_size_bytes: int | None
    created_at: datetime
    source: FileOverviewSource
    is_image: bool
    content_url: str
    thumbnail_url: str | None
    tags_url: str
    metadata_url: str
    ref_label: str
    ref_date: date | None
    ref_href: str | None
    # User-assigned tags (editable, see PATCH .../tags) - does not include origin_tag below.
    tags: list[str]
    # Auto-derived, non-editable "where did this come from" tag (e.g. "Protokoll 5/2026 –
    # Bilder", "Abgabe: Sommerlager Fotos", "Word-Import: ..."), see StoredFileRepository.
    # Filterable together with `tags` via the /files?tags= query param.
    origin_tag: str


class StoredFileTagsUpdate(BaseModel):
    tags: list[str]


class StoredFileMetadata(BaseModel):
    id: int
    original_name: str
    mime_type: str | None
    file_size_bytes: int | None
    created_at: datetime
    checksum_sha256: str | None
    source: FileOverviewSource
    ref_label: str
    ref_date: date | None
    tags: list[str]
    origin_tag: str
    width: int | None
    height: int | None
    exif_taken_at: datetime | None
    exif_camera: str | None
    uploaded_by_name: str | None
