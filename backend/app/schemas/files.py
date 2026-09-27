from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

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
    # End date of the linked Termin's range (Event.event_end_date) - None for a single-day
    # Termin or when there's no linked Termin at all. Together with ref_date and group_date,
    # lets the Fotos gallery label a multi-day Termin's date sections "Termin, Tag 1",
    # "Termin, Tag 2", ... (see grouping.ts's groupContextLabel).
    ref_end_date: date | None = None
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
    # Original pixel dimensions (see StoredFile.width/height) - lets the Fotos gallery's
    # masonry grid reserve each tile's correct aspect-ratio box before the thumbnail has
    # loaded. None for non-images and for images uploaded before this column existed whose
    # thumbnail hasn't been regenerated since.
    width: int | None = None
    height: int | None = None
    # The photo's logical date for the Fotos page's date-group headers - protocol/word-
    # import date, the Termin's event_date for a gallery upload, else the upload date.
    group_date: date | None = None
    # Short context label for that date group's header (protocol title + block title, word-
    # import display name, submission assignment title, or event title) - None when there's
    # nothing more specific than the plain upload date (e.g. an event-less gallery upload).
    context_label: str | None = None
    # Live Photo: content URL of the short MP4 the Fotos grid plays on hover - None for every
    # ordinary photo (see apple_media.py).
    live_video_url: str | None = None
    # Every album this file belongs to (unscoped GET /files only - see
    # FileService.attach_album_context; empty when the file is in no album).
    albums: list[FileAlbumRef] = []
    # Best-of ("Stern") state. When GET /files was called with album_id, this is that
    # album's state; otherwise it's "best-of in at least one album" (None if the file is in
    # no album at all - see files.py's list_files and FileService.attach_album_context).
    is_best: bool | None = None
    # Nur mit album_id und nur fuer den Besitzer des Albums: automatisch einsortiert, aber noch
    # nicht fuer die Partner freigegeben (siehe photo_album_share_service).
    share_pending: bool = False


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


class GalleryUploadJobRead(BaseModel):
    """Lightweight shape for the tenant-wide active-jobs listing the "Bilder hochladen"
    status bar polls (GET /files/gallery-upload-jobs) - no per-file detail, just enough to
    render a progress bar and know when to fetch the full GalleryUploadJobDetail."""

    id: uuid.UUID
    status: Literal["queued", "running", "done", "failed"]
    # None until a ZIP has been opened and its matching entries counted (see
    # FileService.process_pending_gallery_upload_jobs) - a batch of individually-selected images
    # knows this immediately.
    total_files: int | None
    processed_files: int
    imported_count: int
    error_count: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None


class GalleryUploadJobDetail(GalleryUploadJobRead):
    """Full result, fetched once a job has left the active listing (GET
    /files/gallery-upload-jobs/{id}) - same (items, errors) shape the old synchronous
    GalleryUploadResult response had, just arriving later."""

    imported_items: list[FileOverviewItem]
    errors: list[str]


class DocumentUploadResult(BaseModel):
    """POST /files/document-uploads response: what got saved plus per-file problems (too
    large, unsupported format, infected, ...) - partial success, like GalleryUploadJobDetail."""

    items: list[FileOverviewItem]
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


class AlbumTenantShareStatus(BaseModel):
    tenant_public_id: uuid.UUID
    # None ohne Trust zwischen Besitzer und Partner (siehe tenant_trust_service).
    tenant_name: str | None = None
    tenant_profile_image_url: str | None = None
    status: Literal["pending", "accepted", "declined"]
    invited_at: datetime
    responded_at: datetime | None = None


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
    # Set when the viewing tenant isn't the album's owner (i.e. it sees this album through an
    # accepted photo_album_tenant_share) - name of the tenant that actually owns it.
    owner_tenant_name: str | None = None
    # Partner tenants this album has been shared with - only populated for the owning tenant
    # (see files.py's list_albums), drives the "Freigabe verwalten" section.
    shared_with: list[AlbumTenantShareStatus] = []
    # Gerade geteilt (Mandanten-Freigabe offen/angenommen oder aktiver Album-Link) - fuer ein
    # Partner-Album immer True. Steuert den Warnhinweis beim Hinzufuegen von Fotos.
    is_shared: bool = False
    # Nur fuer den Besitzer: automatisch einsortierte, noch nicht freigegebene Fotos.
    pending_share_count: int = 0


class AlbumPendingReleaseRead(BaseModel):
    """Ein eigenes, geteiltes Album mit noch nicht freigegebenen Fotos - fuer den Hinweis auf
    der Fotos-Seite (GET /files/album-pending-releases)."""

    album_id: uuid.UUID
    album_name: str
    album_kind: PhotoAlbumKind
    pending_count: int


class AlbumReleaseRequest(BaseModel):
    # None = alle vorgemerkten Fotos des Albums freigeben.
    file_ids: list[uuid.UUID] | None = Field(default=None, max_length=200)


class AlbumReleaseResult(BaseModel):
    released: int


class SharedTargetAlbumRead(BaseModel):
    """Ein bereits geteiltes Auto-Album, in das ein Galerie-Upload mit dem gewaehlten Bezug
    fallen wuerde (GET /files/upload-target-shared-albums)."""

    album_id: uuid.UUID
    album_name: str


class AlbumShareCreate(BaseModel):
    target_tenant_public_id: uuid.UUID


class AlbumShareRespond(BaseModel):
    accept: bool


class AlbumShareRequestRead(BaseModel):
    """One open cross-tenant share invitation for the current tenant - backs the "Anfragen"
    section on the Fotos page (see files.py's GET /files/album-share-requests)."""

    album_id: uuid.UUID
    album_name: str
    owner_tenant_name: str
    created_at: datetime


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
    # partial-success shape as GalleryUploadJobDetail.errors.
    errors: list[str]


class FileBulkTagsUpdate(BaseModel):
    file_ids: list[uuid.UUID]
    add_tags: list[str] = []
    remove_tags: list[str] = []


class ShareLinkCreate(BaseModel):
    """Exactly one of file_ids/album_id must be set (files.py validates this) - a fixed
    selection vs. a "live" link that always shows an album's current contents."""

    name: str
    expires_at: datetime | None = None
    file_ids: list[uuid.UUID] | None = None
    album_id: uuid.UUID | None = None


class ShareLinkRead(BaseModel):
    id: uuid.UUID
    name: str
    url: str
    album_name: str | None = None
    file_count: int
    created_at: datetime
    created_by_name: str | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    status: Literal["active", "expired", "revoked"]


class PublicShareFile(BaseModel):
    id: uuid.UUID
    original_name: str
    mime_type: str | None
    file_size_bytes: int | None
    is_image: bool
    thumbnail_url: str | None
    download_url: str


class PublicShareRead(BaseModel):
    name: str
    files: list[PublicShareFile]
    download_all_url: str | None = None
