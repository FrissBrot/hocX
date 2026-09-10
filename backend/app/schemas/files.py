from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

FileOverviewSource = Literal["protocol_image", "word_import", "submission_upload", "gallery_upload"]


class FileOverviewItem(BaseModel):
    id: uuid.UUID
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
    # Photo-culling Phase 1 (see photo_quality.py) - None for non-images and for images
    # uploaded before this scoring existed.
    sharpness_score: float | None
    exposure_score: float | None
    # Phase 3 (see PhotoAnalysisJobCreate below) - None until a photo_analysis_job has
    # scored this file (or it has no detected face).
    face_quality_score: float | None
    # Best-of ("Stern") state within the album this item was fetched for - only meaningful
    # when GET /files was called with album_id, None otherwise (see files.py's list_files).
    is_best: bool | None = None


class PhotoAnalysisJobCreate(BaseModel):
    """Same filter shape as GET /files/similarity-groups - "analyze whatever this filtered
    view currently shows"."""

    source: FileOverviewSource | None = None
    search: str | None = None
    tags: list[str] | None = None
    file_ids: list[uuid.UUID] | None = None


class PhotoAnalysisJobRead(BaseModel):
    id: uuid.UUID
    status: Literal["queued", "running", "done", "failed"]
    image_count: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None


class SimilarityGroup(BaseModel):
    """Photo-culling Phase 2 (see photo_similarity.py). `images` is sorted best-first;
    `best_id` is a convenience duplicate of `images[0].id` for a frontend that only wants
    to pre-select/highlight one image per group without re-deriving "first"."""

    best_id: uuid.UUID
    images: list[FileOverviewItem]


class StoredFileTagsUpdate(BaseModel):
    tags: list[str]


class GalleryUploadResult(BaseModel):
    items: list[FileOverviewItem]
    # Per-file problems (too large, no supported image format, infected, ZIP entries that
    # weren't images, ...) - the batch still succeeds for every other file, so this is
    # reported alongside `items` rather than raising.
    errors: list[str]


class StoredFileMetadata(BaseModel):
    id: uuid.UUID
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


PhotoAlbumKind = Literal["manual", "cycle", "submission", "submission_element"]


class PhotoAlbumCreate(BaseModel):
    name: str


class PhotoAlbumRead(BaseModel):
    id: uuid.UUID
    name: str
    # "manual" for an admin-created album; the other three are auto-generated and kept in
    # sync by photo_album_service.py (one per Zyklus+Periode/Abgabe/Abgabe-Element).
    kind: PhotoAlbumKind = "manual"


class PhotoAlbumItemsUpdate(BaseModel):
    file_ids: list[uuid.UUID]


class PhotoAlbumItemBestUpdate(BaseModel):
    # "include" (always best-of), "exclude" (never best-of), or None (back to automatic -
    # see photo_album_service.recompute_best_of).
    best_override: Literal["include", "exclude"] | None
