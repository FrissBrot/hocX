from __future__ import annotations

import re
import uuid
from datetime import date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from app.schemas.documents import DocumentSummary
from pydantic import BaseModel, Field, field_validator, model_validator

FileOverviewSource = Literal["protocol_image", "word_import", "submission_upload", "gallery_upload", "protocol_export"]

PhotoAlbumKind = Literal["manual", "cycle", "submission", "submission_element"]

DateSource = Literal["corrected", "exif", "estimated", "upload", "context"]

# Obergrenze der Mehrfachaktion «Aufnahmedatum ändern» (POST /files/bulk-capture-date).
MAX_CAPTURE_DATE_BULK = 500

# Ergebnis je Datei eines Uploads bzw. Vorab-Abgleichs (siehe UPLOAD_DUPLICATES.md).
UploadFileStatus = Literal["uploaded", "skipped", "metadata_updated", "failed"]
PrecheckStatus = Literal["upload_required", "already_exists", "metadata_updated", "fallback_required"]
MetadataField = Literal["taken_at", "gps", "camera", "dimensions", "orientation", "estimated_taken_on"]


class FileAlbumRef(BaseModel):
    """One album a photo belongs to - the unscoped GET /files listing's per-item context
    for the Fotos page's date-group headers and the photo detail viewer's "Bezug" field
    (see FileService.attach_album_context)."""

    id: uuid.UUID
    name: str
    kind: PhotoAlbumKind
    is_best: bool


class PhotoTimelineDay(BaseModel):
    """Anzahl Fotos eines Tages (group_date) - Grundlage für Zeitstrahl und Höhen der Galerie."""

    date: date
    count: int


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
    # Abgabe-Uploads: das Element der Abgabe, aus dem die Datei stammt (Termin samt Datum bzw.
    # Listeneintrag) - der Bezug (ref_label) ist die Abgabe selbst.
    element_label: str | None = None
    element_date: date | None = None
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
    # Virenprüfung: "pending" (wird geprüft), "clean", "error" (gesperrt) - die Fotos-Kacheln
    # zeigen damit ein Badge statt eines kaputten Vorschaubilds (Audit Dateien/Fotos).
    scan_status: str = "clean"
    # The photo's logical date for the Fotos page's date-group headers - protocol/word-
    # import date, else the central capture-date priority (capture_date.py): real EXIF date,
    # estimated date, upload date.
    group_date: date | None = None
    # Woher group_date stammt: "corrected" (vom Benutzer korrigiert), "exif" (echtes
    # Aufnahmedatum), "estimated" (geschaetzt),
    # "upload" (Fallback Uploaddatum) oder "context" (Protokoll-/Word-Import-Datum). Steuert
    # die dezente Kennzeichnung in der Galerie.
    date_source: DateSource = "upload"
    exif_taken_at: datetime | None = None
    estimated_taken_on: date | None = None
    capture_corrected_at: datetime | None = None
    # Short context label for that date group's header (protocol title + block title, word-
    # import display name, submission assignment title, or event title) - None when there's
    # nothing more specific than the plain upload date (e.g. an event-less gallery upload).
    context_label: str | None = None
    # Live Photo: content URL of the short MP4 the Fotos grid plays on hover - None for every
    # ordinary photo (see apple_media.py).
    live_video_url: str | None = None
    # Logisches Dokument hinter diesem Eintrag (PDF-Ansicht, Verarbeitungsstatus, Versionen) -
    # None für Bilder, ZIPs und andere Nicht-Dokumente (siehe app/services/documents/formats.py).
    document: DocumentSummary | None = None
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


class SimilarityGroup(BaseModel):
    """Photo-culling Phase 2 (see photo_similarity.py). `images` is sorted best-first;
    `best_id` is a convenience duplicate of `images[0].id` for a frontend that only wants
    to pre-select/highlight one image per group without re-deriving "first"."""

    best_id: uuid.UUID
    images: list[FileOverviewItem]


class SimilarityGroupList(BaseModel):
    """Abruf der vorberechneten Gruppen (FileService.list_similarity_groups). `pending`: der
    Hintergrundjob hat für diesen Mandanten noch nichts berechnet; `too_many`: mehr Bilder als
    MAX_BACKGROUND_GROUPING_IMAGES. `computed_at` ist der Stand der Berechnung - neue Fotos
    erscheinen nach dem nächsten Lauf, gelöschte fallen sofort heraus."""

    status: Literal["ready", "pending", "too_many"]
    computed_at: datetime | None = None
    groups: list[SimilarityGroup]


class StoredFileTagsUpdate(BaseModel):
    tags: list[str]


# Anzeigename einer Datei (Datei-Detail «Umbenennen»). Nur der Name in der Oberfläche und beim
# Herunterladen - der Speicherpfad wird nie aus diesem Wert gebaut.
MAX_STORED_FILE_NAME_LENGTH = 200
_FILE_NAME_FORBIDDEN = re.compile(r"[\x00-\x1f\x7f/\\]")


class StoredFileRename(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_STORED_FILE_NAME_LENGTH)

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        value = value.strip()
        if not value or value in {".", ".."}:
            raise ValueError("Name darf nicht leer sein")
        # Steuerzeichen (inkl. NUL) und Pfadtrenner: der Name landet im Content-Disposition-Header
        # und in ZIP-Exporten.
        if _FILE_NAME_FORBIDDEN.search(value):
            raise ValueError("Name enthält ungültige Zeichen")
        return value


class StoredFileRenameResult(BaseModel):
    original_name: str


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


UploadFailureCode = Literal[
    "too_large", "unsupported_format", "scan_failed", "infected", "quota_exceeded", "heic_unreadable", "rule_violation"
]


class UploadFileResult(BaseModel):
    """Ergebnis einer einzelnen Datei: hochgeladen, übersprungen (exaktes Duplikat, nichts zu
    tun), übersprungen mit ergänzten Metadaten oder fehlgeschlagen. `applied` nennt nur
    tatsächlich gespeicherte Ergänzungen."""

    name: str
    status: UploadFileStatus
    file_id: uuid.UUID | None = None
    applied: list[MetadataField] = []
    conflicts: list[MetadataField] = []
    message: str | None = None
    # Maschinenlesbarer Grund eines Fehlschlags (IMGMETA-012) - das Frontend übersetzt ihn;
    # `message` bleibt deutscher Text für ältere Clients und unbekannte Codes.
    code: UploadFailureCode | None = None
    params: dict[str, int | str] = {}


class GalleryUploadJobDetail(GalleryUploadJobRead):
    """Full result, fetched once a job has left the active listing (GET
    /files/gallery-upload-jobs/{id}) - same (items, errors) shape the old synchronous
    GalleryUploadResult response had, just arriving later."""

    imported_items: list[FileOverviewItem]
    errors: list[str]
    file_results: list[UploadFileResult] = []


class DocumentUploadResult(BaseModel):
    """POST /files/document-uploads response: what got saved plus per-file problems (too
    large, unsupported format, infected, ...) - partial success, like GalleryUploadJobDetail."""

    items: list[FileOverviewItem]
    errors: list[str]
    file_results: list[UploadFileResult] = []


class ClientGpsMetadata(BaseModel):
    """GPS aus der Browser-Analyse - WGS84-Dezimalgrad, Süd/West negativ. Bereichsprüfung
    hier, Plausibilitätsprüfung (z. B. 0/0) in image_metadata_service."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    altitude_m: float | None = None
    direction_deg: float | None = None
    accuracy_m: float | None = None
    timestamp: datetime | None = None


class ClientImageMetadata(BaseModel):
    """Im Browser extrahierte Metadaten - nicht vertrauenswürdig, siehe image_metadata_service."""

    # Lokale Kamerazeit ohne Zeitzone ("YYYY-MM-DDTHH:MM:SS"); ein Offset kommt separat.
    taken_at: str | None = Field(default=None, max_length=40)
    taken_offset: str | None = Field(default=None, max_length=8)
    gps: ClientGpsMetadata | None = None
    camera_make: str | None = Field(default=None, max_length=200)
    camera_model: str | None = Field(default=None, max_length=200)
    width: int | None = None
    height: int | None = None
    orientation: int | None = None


class UploadPrecheckFile(BaseModel):
    # Frei wählbare Kennung des Clients, kommt unverändert zurück.
    client_id: str = Field(max_length=100)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    name: str = Field(default="", max_length=500)
    size: int = Field(ge=0)
    mime_type: str | None = Field(default=None, max_length=100)
    # "ok": vollständig analysiert, "unsupported"/"failed": Browser konnte die Datei nicht
    # (sicher) analysieren - der Server fällt dann auf den normalen Upload zurück.
    analysis: Literal["ok", "unsupported", "failed"] = "ok"
    metadata: ClientImageMetadata | None = None


class UploadPrecheckRequest(BaseModel):
    context: Literal["gallery", "document", "protocol_image"] = "gallery"
    # Schätzdatum aus dem Upload-Popup - gilt nur für Bilder ohne echtes Aufnahmedatum.
    estimated_taken_on: date | None = None
    files: list[UploadPrecheckFile] = Field(max_length=500)


class UploadPrecheckResult(BaseModel):
    client_id: str
    status: PrecheckStatus
    # Nur bei already_exists/metadata_updated: das vorhandene Bild (immer aus dem eigenen Mandanten).
    file_id: uuid.UUID | None = None
    applied: list[MetadataField] = []
    conflicts: list[MetadataField] = []


class UploadPrecheckResponse(BaseModel):
    results: list[UploadPrecheckResult]


class CaptureDateUpdate(BaseModel):
    """PATCH /stored-files/{id}/capture-date - null entfernt das geschätzte Datum."""

    estimated_taken_on: date | None


class CaptureCorrectionUpdate(BaseModel):
    """PATCH /stored-files/{id}/capture-correction - korrigiertes Aufnahmedatum setzen
    (Datum, optional Uhrzeit) oder mit corrected_date null entfernen."""

    corrected_date: date | None
    corrected_time: time | None = None


class FileBulkCaptureDate(BaseModel):
    """POST /files/bulk-capture-date - Mehrfachauswahl der Galerie.

    mode "set": alle auf corrected_date (+ optional corrected_time); "shift": um shift_days/
    shift_hours verschieben (Bilder ohne Aufnahmedatum werden übersprungen); "reset":
    Korrektur entfernen."""

    file_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_CAPTURE_DATE_BULK)
    mode: Literal["set", "shift", "reset"]
    corrected_date: date | None = None
    corrected_time: time | None = None
    shift_days: int = Field(default=0, ge=-36500, le=36500)
    shift_hours: int = Field(default=0, ge=-8760, le=8760)

    @model_validator(mode="after")
    def _check_mode(self) -> "FileBulkCaptureDate":
        if self.mode == "set" and self.corrected_date is None:
            raise ValueError("corrected_date fehlt")
        if self.mode != "set" and (self.corrected_date is not None or self.corrected_time is not None):
            raise ValueError("corrected_date/corrected_time nur mit mode 'set'")
        if self.mode == "shift" and self.shift_days == 0 and self.shift_hours == 0:
            raise ValueError("Versatz fehlt")
        if self.mode != "shift" and (self.shift_days or self.shift_hours):
            raise ValueError("Versatz nur mit mode 'shift'")
        return self


class FileBulkCaptureDateResult(BaseModel):
    updated_ids: list[uuid.UUID]
    # Schon auf dem Zielwert (z. B. «zurücksetzen» ohne Korrektur).
    unchanged_ids: list[uuid.UUID]
    # Nur beim Verschieben: kein Aufnahmedatum (weder korrigiert, EXIF noch geschätzt).
    skipped_no_date_ids: list[uuid.UUID]
    # Ergebnis ausserhalb des gültigen Bereichs (vor 1826 oder in der Zukunft).
    invalid_ids: list[uuid.UUID]
    # Unbekannt, fremder Mandant (auch Partner-Fotos geteilter Alben) oder kein Bild -
    # bewusst nicht unterschieden (kein Existenz-Orakel).
    not_found_ids: list[uuid.UUID]


class GpsMetadataRead(BaseModel):
    latitude: float
    longitude: float
    altitude_m: float | None = None
    direction_deg: float | None = None
    accuracy_m: float | None = None
    timestamp: datetime | None = None
    source: str | None = None


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
    # Drei getrennte Datumsarten plus das daraus nach capture_date.py gewählte Datum.
    exif_taken_offset: str | None = None
    exif_taken_source: str | None = None
    estimated_taken_on: date | None = None
    estimated_taken_set_at: datetime | None = None
    estimated_taken_set_by_name: str | None = None
    # Korrigiertes Aufnahmedatum (Vorrang vor EXIF, Migration 0200); ohne Uhrzeit steht technisch
    # 12:00 drin und capture_corrected_has_time ist False.
    capture_corrected_at: datetime | None = None
    capture_corrected_has_time: bool = False
    capture_corrected_set_at: datetime | None = None
    capture_corrected_set_by_name: str | None = None
    effective_date: date | None = None
    date_source: DateSource = "upload"
    camera_make: str | None = None
    camera_model: str | None = None
    gps: GpsMetadataRead | None = None
    # Darf der aktuelle Benutzer das geschätzte Datum bearbeiten (nur Bilder, Schreibrecht)?
    can_edit_capture_date: bool = False


class PhotoAlbumCreate(BaseModel):
    name: str


class PhotoAlbumUpdate(BaseModel):
    """Album umbenennen (nur der Besitzer-Mandant)."""

    name: str


class AlbumTenantShareStatus(BaseModel):
    tenant_public_id: uuid.UUID
    # None ohne Trust zwischen Besitzer und Partner (siehe tenant_trust_service).
    tenant_name: str | None = None
    tenant_profile_image_url: str | None = None
    status: Literal["pending", "accepted", "declined"]
    invited_at: datetime
    responded_at: datetime | None = None
    # Standort (GPS) der Fotos mit diesem Partner teilen (IMGMETA-007).
    share_location: bool = True
    # Öffentliche Links (SEC-002): Partner darf das Album verlinken (Besitzer entscheidet) bzw.
    # Fotos des Partners dürfen in öffentlichen Links erscheinen (Partner entscheidet, hier nur Anzeige).
    partner_public_links: bool = True
    partner_photos_public: bool = True


class AlbumMyShareRead(BaseModel):
    """Die eigene Freigabe in einem Album eines anderen Mandanten (nur für Partner gesetzt)."""

    # Vom Besitzer: darf ich dieses Album öffentlich verlinken?
    public_links_allowed: bool
    # Meine Entscheidung: dürfen meine Fotos in öffentlichen Links erscheinen?
    my_photos_public: bool


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
    # Nur für Partner (fremdes Album): eigene Freigabe-Einstellungen für öffentliche Links.
    my_share: AlbumMyShareRead | None = None
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
    # Standard an: Mandanten, die ein Album teilen, vertrauen sich (Freigabe-Links: Standard aus).
    share_location: bool = True


class AlbumShareUpdate(BaseModel):
    """Vom Besitzer für einen Partner: Standort teilen und/oder öffentliche Links erlauben."""

    share_location: bool | None = None
    partner_public_links: bool | None = None


class AlbumMyShareUpdate(BaseModel):
    """Vom Partner für die eigene Freigabe: eigene Fotos in öffentlichen Links zeigen."""

    my_photos_public: bool


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


class PhotoAlbumItemsRemoveResult(BaseModel):
    removed: int


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
    # Seit dem Papierkorb (Migration 0199): in den Papierkorb gelegt, nicht endgültig gelöscht.
    deleted_ids: list[uuid.UUID]
    # Per-file reasons a requested id wasn't deleted (wrong source, not found, ...) - same
    # partial-success shape as GalleryUploadJobDetail.errors.
    errors: list[str]


class FileTrashItem(BaseModel):
    """Eine Datei im Papierkorb (file_trash_service)."""

    id: uuid.UUID
    original_name: str
    mime_type: str | None
    file_size_bytes: int | None
    is_image: bool
    thumbnail_url: str | None
    deleted_at: datetime
    deleted_by_name: str | None
    purge_at: datetime
    days_left: int


class FileTrashList(BaseModel):
    items: list[FileTrashItem]
    total_bytes: int
    retention_days: int


class FileTrashAction(BaseModel):
    file_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class FileTrashActionResult(BaseModel):
    file_ids: list[uuid.UUID]
    errors: list[str]


class FileTrashEmptyResult(BaseModel):
    purged: int


class FileBulkTagsUpdate(BaseModel):
    file_ids: list[uuid.UUID]
    add_tags: list[str] = []
    remove_tags: list[str] = []


_DATE_ONLY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_SHARE_EXPIRY_TZ = ZoneInfo("Europe/Zurich")


class ShareLinkCreate(BaseModel):
    """Exactly one of file_ids/album_id must be set (files.py validates this) - a fixed
    selection vs. a "live" link that always shows an album's current contents."""

    # Optional: ohne Namen vergibt create_share_link einen (Albumname, Dateiname, «N Dateien»)
    name: str | None = None
    expires_at: datetime | None = None
    file_ids: list[uuid.UUID] | None = None
    album_id: uuid.UUID | None = None
    # Welche Foto-Metadaten oeffentlich mitgehen (siehe photo_metadata_privacy.py).
    share_location: bool = False
    share_capture_date: bool = True
    share_camera: bool = False

    @field_validator("expires_at", mode="before")
    @classmethod
    def _date_means_end_of_swiss_day(cls, value: object) -> object:
        """Das Freigabe-Modal schickt das Ablaufdatum aus dem DateInput als reines Datum; die
        öffentliche Seite zeigt «gültig bis <Datum>». Ein reines Datum gilt deshalb bis zum Ende
        dieses Tages in Schweizer Zeit (sonst liefe der Link schon um 00:00 UTC desselben Tages
        ab). Vollständige Zeitpunkte bleiben unverändert."""
        if isinstance(value, str) and _DATE_ONLY_RE.fullmatch(value.strip()):
            value = date.fromisoformat(value.strip())
        if isinstance(value, date) and not isinstance(value, datetime):
            return datetime.combine(value, time(23, 59, 59), tzinfo=_SHARE_EXPIRY_TZ)
        return value


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
    share_location: bool = False
    share_capture_date: bool = True
    share_camera: bool = False


class PublicShareFile(BaseModel):
    id: uuid.UUID
    original_name: str
    mime_type: str | None
    file_size_bytes: int | None
    is_image: bool
    width: int | None = None
    height: int | None = None
    taken_at: datetime | None = None
    thumbnail_url: str | None
    # Grossansicht in der Lightbox: das Original inline, wenn der Browser es sicher darstellen
    # kann (JPEG/PNG/WebP/GIF), sonst die Vorschau; None fuer Nicht-Bilder.
    view_url: str | None = None
    download_url: str
    # Seitenzahl eines Dokuments (PDF, Word, …), sobald die Dokument-Pipeline es gelesen hat.
    page_count: int | None = None


class PublicShareRead(BaseModel):
    name: str
    # Untertitel ueber dem Titel (z. B. Albumname, wenn der Link anders heisst).
    context: str | None = None
    is_album: bool = False
    tenant_name: str
    expires_at: datetime | None = None
    total_size_bytes: int = 0
    date_from: datetime | None = None
    date_to: datetime | None = None
    files: list[PublicShareFile]
    # Immer ein ZIP; mit ?ids=<uuid>,<uuid> nur die Auswahl.
    download_all_url: str | None = None
