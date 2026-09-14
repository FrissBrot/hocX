from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

FileOverviewSource = Literal["protocol_image", "word_import", "submission_upload", "gallery_upload"]

PhotoAlbumKind = Literal["manual", "cycle", "submission", "submission_element"]


class FileAlbumRef(BaseModel):
    """One album a photo belongs to - the unscoped GET /files listing's per-item context
    for the Fotos page's date-group headers and the photo detail viewer's "Bezug" field
    (see FileService.attach_album_context)."""

    id: uuid.UUID
    name: str
    kind: PhotoAlbumKind
    is_best: bool


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
    # Phase 3 (see PhotoAnalysisJobCreate below) - None until this file has been through
    # the worker (or it has no detected face).
    face_quality_score: float | None
    # Set once the worker has processed this file, regardless of whether a face was found -
    # the only reliable "analyzed" marker, since face_quality_score alone is also None when
    # analysis simply hasn't run yet.
    face_analyzed_at: datetime | None = None
    # The photo's logical date for the Fotos page's date-group headers - protocol/word-
    # import date, the Termin's event_date for a gallery upload, else the upload date.
    group_date: date | None = None
    # Short context label for that date group's header (protocol title + block title, word-
    # import display name, submission assignment title, or event title) - None when there's
    # nothing more specific than the plain upload date (e.g. an event-less gallery upload).
    context_label: str | None = None
    # Every album this file belongs to (unscoped GET /files only - see
    # FileService.attach_album_context; empty when the file is in no album).
    albums: list[FileAlbumRef] = []
    # Best-of ("Stern") state. When GET /files was called with album_id, this is that
    # album's state; otherwise it's "best-of in at least one album" (None if the file is in
    # no album at all - see files.py's list_files and FileService.attach_album_context).
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


class PhotoAlbumCreate(BaseModel):
    name: str


class PhotoAlbumRead(BaseModel):
    id: uuid.UUID
    name: str
    # "manual" for an admin-created album; the other three are auto-generated and kept in
    # sync by photo_album_service.py (one per Zyklus+Periode/Abgabe/Abgabe-Element).
    kind: PhotoAlbumKind = "manual"
    # Computed on the fly from photo_album_item (never stored - see
    # photo_album_service.list_albums_with_stats), not tracked here as columns.
    photo_count: int = 0
    best_of_count: int = 0
    # Up to 4 thumbnail URLs (best-of first, then newest) for the Alben tab's cover
    # collage - empty for an album with no items yet.
    cover_thumbnail_urls: list[str] = []


class PhotoAlbumItemsUpdate(BaseModel):
    file_ids: list[uuid.UUID]


class PhotoAlbumItemBestUpdate(BaseModel):
    # "include" (always best-of), "exclude" (never best-of), or None (back to automatic -
    # see photo_album_service.recompute_best_of).
    best_override: Literal["include", "exclude"] | None


class PhotoAnalysisProgress(BaseModel):
    """Tenant-wide summary behind the Fotos page's "Foto-Analyse läuft - X von Y Bildern
    bewertet" progress bar and "Analyse läuft · N Bilder" pill."""

    total_images: int
    analyzed_images: int
    pending_images: int
    active_jobs: int
    active_job_image_count: int


class FileStats(BaseModel):
    """Backs the Dateien page's Dokumente/Fotos/Speicher stat cards."""

    document_count: int
    photo_count: int
    total_bytes: int


class FileBulkDelete(BaseModel):
    file_ids: list[uuid.UUID]


class FileBulkDeleteResult(BaseModel):
    deleted_ids: list[uuid.UUID]
    # Per-file reasons a requested id wasn't deleted (wrong source, not found, ...) - same
    # partial-success shape as GalleryUploadResult.errors.
    errors: list[str]


class FileBulkTagsUpdate(BaseModel):
    file_ids: list[uuid.UUID]
    add_tags: list[str] = []
    remove_tags: list[str] = []
