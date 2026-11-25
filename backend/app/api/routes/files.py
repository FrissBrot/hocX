import json
import math
import re
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from app.schemas.base import MAX_QUERY_OFFSET, reject_nul_characters
from app.models.entities import AppUser, CycleConfig, Event, GalleryUploadJob, PhotoAlbum, PhotoAlbumItem, PhotoAlbumTenantShare, SubmissionAssignment
from app.schemas.files import PhotoAlbumCreate, PhotoAlbumItemBestUpdate, PhotoAlbumItemsRemoveResult, PhotoAlbumRead, PhotoAlbumItemsUpdate, PhotoAlbumUpdate
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

from app.core.db import get_db, release_for_stream
from app.core.config import settings
from app.core.rate_limit import enforce_rate_limit
from app.core.permissions import P
from app.core.features_generated import F
from app.core.security import CurrentUser, get_current_user, require_any_permission, require_feature, require_permission
from app.models import ElementType, GalleryImage, Protocol, ProtocolElement, ProtocolElementBlock, ProtocolImage, StoredFile, Tenant
from app.schemas.files import (
    AlbumPendingReleaseRead,
    AlbumReleaseRequest,
    AlbumReleaseResult,
    SharedTargetAlbumRead,
    AlbumShareCreate,
    AlbumShareUpdate,
    AlbumMyShareRead,
    AlbumMyShareUpdate,
    AlbumShareRequestRead,
    AlbumShareRespond,
    AlbumTenantShareStatus,
    CaptureCorrectionUpdate,
    CaptureDateUpdate,
    FileBulkCaptureDate,
    FileBulkCaptureDateResult,
    MAX_CAPTURE_DATE_BULK,
    ClientImageMetadata,
    DocumentUploadResult,
    FileBulkDelete,
    FileDiscardUploadsRequest,
    FileDiscardUploadsResult,
    FileDuplicateCheckRequest,
    FileDuplicateCheckResponse,
    FileDuplicateMatch,
    FileBulkDeleteResult,
    FileBulkKeywordsResult,
    FileBulkKeywordsUpdate,
    FileBulkTagsUpdate,
    FileKeywordCount,
    FileKeywordsSummaryRequest,
    FileOverviewItem,
    FileTrashAction,
    FileTrashActionResult,
    FileTrashEmptyResult,
    FileTrashItem,
    FileTrashList,
    PhotoTimelineDay,
    FileOverviewSource,
    FileStats,
    GalleryUploadJobDetail,
    GalleryUploadJobRead,
    PhotoAnalysisProgress,
    SimilarityGroupList,
    StoredFileMetadata,
    FileBulkCaptureDatePreview,
    FileBulkEventLink,
    FileBulkEventLinkResult,
    CaptureChangeBatchRead,
    CaptureChangeUndoResult,
    MAX_STORED_FILE_NAME_LENGTH,
    StoredFileRename,
    StoredFileRenameResult,
    StoredFileKeywordsRead,
    StoredFileKeywordsUpdate,
    StoredFileTagsUpdate,
    UploadFileResult,
    UploadPrecheckRequest,
    UploadPrecheckResponse,
)
from app.schemas.protocol import ProtocolImageCaptionUpdate, ProtocolImageRead
from app.services import upload_precheck_service
from app.services import upload_job_service
from app.services import capture_change_service, photo_event_link_service
from app.models.upload_history_entities import CaptureChangeBatch
from app.schemas.upload_jobs import UploadJobOfFile
from app.services import file_keywords
from app.services import photo_places
from app.services import document_service, file_trash_service, image_export_service, image_metadata_service, photo_album_service, photo_album_share_service, public_id_service
from app.core.trash_scope import TRASH_RETENTION, include_trashed
from app.services.access_service import AccessService
from app.services.audit_service import AuditService
from app.services import apple_media
from app.services import context_visibility_service
from app.services.apple_media import pair_live_clips, MAX_LIVE_CLIP_BYTES
from app.core.storage import MAIN, ObjectNotFound, _content_disposition, get_object_store, object_response, read_bytes_or_404, write_object_to_zip
from app.services.photo_metadata_privacy import MetadataPolicy, sanitize_image
from app.services.file_service import BLOCKED_SCAN_STATUSES, MAX_UPLOAD_BYTES, FileService
from app.services import submission_upload_rules
from app.services.submission_service import SubmissionService, _element_ref, _parse_element_ref, raw_element_key
from app.services.upload_pipeline import _CONTROL_CHARS, GALLERY_DIRECT_IMAGE_MAX_BYTES, GALLERY_ZIP_MAX_BYTES, stage_upload_to_disk, inspect_gallery_zip, _enforce_tenant_storage_quota, safe_entry_name
from app.repositories.file_repository import StoredFileRepository
from app.services.upload_lock import acquire_upload_lock
from starlette.concurrency import run_in_threadpool

from app.gallery_upload_route import GalleryUploadRoute
from app.core.offload import run_coroutine_in_thread

# Form einer Abgabe-Element-Referenz (submission_service._element_ref / manual_element_ref)
_ELEMENT_REF_SHAPE = re.compile(r"manual|(?:event|entry|manual)-[0-9a-fA-F-]{36}")

router = APIRouter(route_class=GalleryUploadRoute)
service = FileService()
audit = AuditService()
access_service = AccessService()
submission_service = SubmissionService()

# Ganzer Batch (Summe aller gestagten Dateien eines Upload-Requests): grösszügiger als eine
# einzelne Datei, aber trotzdem endlich - selbes Limit-Muster wie beim Word-Import-Batch-
# Upload. Bewusst gleich gross wie GALLERY_ZIP_MAX_BYTES (eine einzelne ZIP-Datei ist der
# haeufigste Fall) statt eines eigenen, kleineren Werts.
MAX_GALLERY_UPLOAD_BATCH_FILES = 50
MAX_GALLERY_UPLOAD_BATCH_BYTES = GALLERY_ZIP_MAX_BYTES

# Dokument-Upload ("Dateien"-Seite): laeuft inline im Request (kein Hintergrund-Job) und
# haelt einen Batch dafuer kurz im Speicher - deshalb deutlich kleinere Batch-Grenzen als beim
# Galerie-Upload; eine einzelne Datei bleibt bei MAX_UPLOAD_BYTES.
MAX_DOCUMENT_UPLOAD_BATCH_FILES = 20
# Client-Metadaten zum Galerie-Upload (Formularfeld file_metadata, JSON): Obergrenzen gegen
# uebergrosse Formularfelder - 50 Dateien je Batch, grosszuegig Platz je Eintrag.
MAX_FILE_METADATA_JSON_BYTES = 512 * 1024
MAX_DOCUMENT_UPLOAD_BATCH_BYTES = 100 * 1024 * 1024


@router.get("/files", response_model=list[FileOverviewItem])
def list_files(
    skip: int = Query(default=0, ge=0, le=MAX_QUERY_OFFSET),
    limit: int = Query(default=60, ge=1, le=200),
    source: FileOverviewSource | None = Query(default=None),
    album_id: Annotated[uuid.UUID | None, Query()] = None,
    exclude_album_id: Annotated[uuid.UUID | None, Query()] = None,
    # Nur mit album_id, nur fuer den Besitzer wirksam: True zeigt nur die noch nicht
    # freigegebenen Fotos (Pruefansicht vor der Freigabe).
    share_pending: Annotated[bool | None, Query()] = None,
    only_images: bool = Query(default=False),
    exclude_images: bool = Query(default=False),
    search: str | None = Query(default=None),
    tags: list[str] | None = Query(default=None),
    # relevance: beste Treffer der Suche zuerst (services/photo_search.py), ohne Suche wie group_date
    sort_by: Literal[
        "created_at", "original_name", "file_size_bytes", "sharpness_score", "exposure_score", "face_quality_score", "group_date",
        "relevance",
    ] = Query(default="created_at"),
    sort_dir: Literal["asc", "desc"] = Query(default="desc"),
    # Nur Einträge dieser Tage (group_date, inklusive) - die Zeitleiste der Fotos lädt die sichtbaren Tage.
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    # Upload-Verlauf: nur Dateien dieses Vorgangs (404, wenn die Person ihn nicht sehen darf)
    upload_job_id: Annotated[uuid.UUID | None, Query()] = None,
    # Foto-Standorte (0260): nur Fotos im Umkreis eines Orts (Schlüssel aus GET /places/search),
    # Radius in km (ohne Angabe nach Ortsart); mit sort_by=relevance nach Distanz sortiert.
    near: Annotated[str | None, Query(max_length=80)] = None,
    near_km: Annotated[float | None, Query(ge=0.5, le=200)] = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Alle vom Mandanten hochgeladenen Dateien (Protokoll-Bilder, Word-Import-Quelldokumente,
    Abgabebox-Uploads) fuer die "Dateien"- und "Fotos"-Uebersichtsseiten (only_images/
    exclude_images trennen die beiden). Nur mit files.manage: dies
    ist eine mandantenweite Aggregatsicht ueber alle Protokolle hinweg, nicht scopebar auf
    die feingranulare Pro-Protokoll-Leserechte-Pruefung von ensure_can_read_stored_file."""
    require_any_permission(user, P.FILES_READ, P.PHOTOS_READ)
    # Ablage und Fotos sind getrennte Rechte (Plan «Berechtigungen», Phase 3): wer nur eines hat,
    # sieht nur diese Sorte.
    if not user.can(P.FILES_READ):
        only_images, exclude_images = True, False
    elif not user.can(P.PHOTOS_READ):
        exclude_images, only_images = True, False
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    if upload_job_id is not None:
        upload_job_service.get_visible_job(db, user, upload_job_id)
    album = _get_album(db, user, album_id) if album_id is not None else None
    if exclude_album_id is not None:
        _get_album(db, user, exclude_album_id)
    # Ohne Recht auf Koordinaten: Umkreis nie enger als der Standard der Ortsart und keine
    # Sortierung nach Distanz (sonst liesse sich der Aufnahmeort eingrenzen, Security-Review)
    sees_location = _sees_location(user)
    near_filter = photo_places.resolve_near(db, near, near_km, user.current_tenant_id, precise=sees_location)
    album_share_pending = None
    if album is not None:
        if photo_album_share_service.hides_pending_items(album, user.current_tenant_id):
            album_share_pending = False
        elif share_pending is not None:
            album_share_pending = share_pending
    items = service.list_tenant_files(
        db,
        # None when album_id is set: the album_id JOIN already fully scopes the result to an
        # album _get_album just verified this tenant may see - a plain tenant_id filter on top
        # would silently drop a mandantenuebergreifend geteiltes Album's partner-tenant photos.
        None if album_id is not None else user.current_tenant_id,
        skip=skip,
        limit=limit,
        source=source,
        only_images=only_images,
        exclude_images=exclude_images,
        search=search,
        tags=tags,
        sort_by=sort_by,
        sort_dir=sort_dir,
        album_id=album_id,
        exclude_album_id=exclude_album_id,
        album_share_pending=album_share_pending,
        date_from=date_from,
        date_to=date_to,
        # Geteiltes Album: Fotos des anderen Mandanten ohne dessen Kontext (Tags, Titel).
        viewer_tenant_id=user.current_tenant_id if album_id is not None else None,
        # Reichweite «nur zugewiesene» (Phase 4/5): Abgabe-Dateien anderer Aufträge ausblenden
        readable_assignment_ids=context_visibility_service.readable_assignment_ids(db, user),
        upload_job_id=upload_job_id,
        # Protokollbilder/-exporte nur aus lesbaren Protokollen (1.5.2, Verdacht 2)
        protocol_scope=access_service.protocol_read_scope(db, user),
        near=photo_places.near_subquery(near_filter) if near_filter is not None else None,
        near_sort=sees_location,
    )
    # Ortsname nur für Fotos des eigenen Mandanten; Distanz nur für Konten, die Koordinaten sehen
    photo_places.attach_places(db, user.current_tenant_id, items, near=near_filter, with_distance=sees_location)
    if album_id is not None:
        # is_best fetched only for this page's items (at most `limit`), not the whole
        # album - the query itself is now scoped by a JOIN on album_id (see
        # StoredFileRepository.list_tenant_files), not a pre-fetched id list, so there's
        # no reason to also pre-fetch every member's is_best up front (audit fix,
        # 2026-09-17 - same over-fetch this whole route used to have for file_ids).
        page_ids = [item.id for item in items]
        state_by_id = {
            row.file_id: row
            for row in db.execute(
                select(PhotoAlbumItem.file_id, PhotoAlbumItem.is_best, PhotoAlbumItem.share_pending).where(
                    PhotoAlbumItem.album_id == album_id, PhotoAlbumItem.file_id.in_(page_ids)
                )
            ).all()
        } if page_ids else {}
        for item in items:
            state = state_by_id.get(item.id)
            item.is_best = bool(state and state.is_best)
            item.share_pending = bool(state and state.share_pending)
        # Best-of first within an album, otherwise the caller's own sort/pagination as-is -
        # this only re-orders the (already album-scoped, at most PAGE_SIZE-large) page
        # itself, it doesn't change what page skip/limit fetch.
        items.sort(key=lambda item: not item.is_best)
    else:
        # Unscoped view: is_best/albums aren't tied to one album, so they're filled in
        # separately here rather than by list_tenant_files itself (see
        # FileService.attach_album_context).
        service.attach_album_context(db, user.current_tenant_id, items)
    return items


@router.get("/files/timeline", response_model=list[PhotoTimelineDay])
def files_timeline(
    only_images: bool = Query(default=False),
    search: str | None = Query(default=None),
    tags: list[str] | None = Query(default=None),
    sort_dir: Literal["asc", "desc"] = Query(default="desc"),
    upload_job_id: Annotated[uuid.UUID | None, Query()] = None,
    near: Annotated[str | None, Query(max_length=80)] = None,
    near_km: Annotated[float | None, Query(ge=0.5, le=200)] = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Einträge je Tag (group_date) der Mandantenübersicht, mit denselben Filtern wie GET /files.
    Die Fotogalerie berechnet daraus Höhen und Zeitstrahl, bevor sie Bilder lädt (Alben haben
    ihre eigene Reihenfolge und nutzen das nicht)."""
    require_permission(user, P.PHOTOS_READ)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    if upload_job_id is not None:
        upload_job_service.get_visible_job(db, user, upload_job_id)
    near_filter = photo_places.resolve_near(db, near, near_km, user.current_tenant_id, precise=_sees_location(user))
    return service.tenant_files_timeline(
        db, user.current_tenant_id, sort_dir=sort_dir, only_images=only_images, search=search, tags=tags,
        readable_assignment_ids=context_visibility_service.readable_assignment_ids(db, user),
        upload_job_id=upload_job_id,
        protocol_scope=access_service.protocol_read_scope(db, user),
        near=photo_places.near_subquery(near_filter) if near_filter is not None else None,
    )


@router.get("/files/tags", response_model=list[str])
def list_file_tags(
    query: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Autocomplete-Quelle fuer den Tag-Filter/-Editor auf der "Dateien"-Seite - jeder Tag,
    der aktuell auf irgendeiner Datei des Mandanten liegt, inklusive der automatischen
    Herkunfts-Tags (siehe FileOverviewItem.origin_tag)."""
    require_any_permission(user, P.FILES_READ, P.PHOTOS_READ)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    return service.list_distinct_tags(
        db, user.current_tenant_id, query=query, limit=limit,
        readable_assignment_ids=context_visibility_service.readable_assignment_ids(db, user),
        protocol_scope=access_service.protocol_read_scope(db, user),
    )


@router.get("/files/analysis-progress", response_model=PhotoAnalysisProgress)
def get_analysis_progress(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Tenant-wide summary behind the Fotos page's "Foto-Analyse läuft" progress bar and
    the "Analyse läuft · N Bilder" pill."""
    require_permission(user, P.PHOTOS_READ)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    return service.analysis_progress(db, user.current_tenant_id)


@router.get("/files/stats", response_model=FileStats)
def get_file_stats(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Backs the Dateien page's Dokumente/Fotos/Speicher stat cards."""
    require_any_permission(user, P.FILES_READ, P.PHOTOS_READ)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    return service.file_stats(
        db, user.current_tenant_id, readable_assignment_ids=context_visibility_service.readable_assignment_ids(db, user),
        protocol_scope=access_service.protocol_read_scope(db, user),
    )


@router.get("/files/similarity-groups", response_model=SimilarityGroupList)
def list_similarity_groups(
    source: FileOverviewSource | None = Query(default=None),
    album_id: uuid.UUID | None = Query(default=None),
    search: str | None = Query(default=None),
    tags: list[str] | None = Query(default=None),
    kind: Literal["duplicate", "series"] = Query(default="duplicate"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Tabs "Duplikate" (kind="duplicate": gleiches Bild in anderem Ausschnitt/Qualität) und
    "Ähnliche" (kind="series": Fotoserie derselben Szene). Gruppiert wird im Hintergrund
    (job-worker, FileService.refresh_similarity_results); diese Route liest nur das Ergebnis und
    filtert es mit denselben Filtern wie GET /files - siehe FileService.list_similarity_groups."""
    require_permission(user, P.PHOTOS_READ)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    file_ids = None
    if album_id is not None:
        album = _get_album(db, user, album_id)
        item_query = select(PhotoAlbumItem.file_id).where(PhotoAlbumItem.album_id == album_id)
        if photo_album_share_service.hides_pending_items(album, user.current_tenant_id):
            item_query = item_query.where(PhotoAlbumItem.share_pending.is_(False))
        file_ids = list(db.scalars(item_query))
    return service.list_similarity_groups(
        db,
        user.current_tenant_id,
        kind=kind,
        source=source,
        search=search,
        tags=tags,
        file_ids=file_ids,
        readable_assignment_ids=context_visibility_service.readable_assignment_ids(db, user),
        protocol_scope=access_service.protocol_read_scope(db, user),
    )


def _upload_job_for_request(
    db: Session, user: CurrentUser, upload_job_id: uuid.UUID | None, channel: str, target: "_UploadTarget",
    element_ref: str | None, *, options: dict,
):
    """Vorgang im Upload-Verlauf für einen Upload-Request: der vom Browser geöffnete (gleicher
    Kanal bzw. Pendenz, eigene Person, offen, sonst 404) oder - ältere Clients, API - ein eigener
    Vorgang nur für diesen Request. (Vorgang, neu angelegt?)"""
    channels = (channel, "todo")
    attached = upload_job_service.attach(db, user, upload_job_id, channels, lock=True)
    if attached is not None:
        return attached, False
    job = upload_job_service.open_job(
        db, tenant_id=user.current_tenant_id, channel=channel, created_by=user.user_id, options=options,
        event_id=target.event_id, submission_assignment_id=target.assignment_id,
        submission_element_ref=element_ref if target.assignment_id is not None else None,
        submission_element_label=target.element_label, cycle_config_id=target.cycle_config_id,
    )
    # Kein Browser meldet diesen Vorgang ab: er schliesst, sobald die Verarbeitung fertig ist.
    job.client_closed_at = datetime.now(UTC)
    return job, True


def _gallery_upload_job_to_read(job: GalleryUploadJob) -> GalleryUploadJobRead:
    return GalleryUploadJobRead(
        upload_job_id=job.upload_job_id,
        id=job.id,
        status=job.status,
        total_files=job.total_files,
        processed_files=job.processed_files,
        imported_count=len(job.imported_file_ids),
        error_count=len(job.errors),
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error=job.error,
    )


@dataclass
class _UploadTarget:
    """Internal ids behind the optional Bezug picker shared by the "Fotos" and "Dateien"
    upload windows - at most one of event / Zyklus / Abgabe(+Element) is ever set."""

    event_id: int | None = None
    assignment_id: int | None = None
    # The resolved Abgabe itself - its file rules apply to the upload (see
    # submission_upload_rules.py).
    assignment: SubmissionAssignment | None = None
    element_label: str | None = None
    cycle_config_id: int | None = None


def _resolve_upload_target(
    db: Session,
    user: CurrentUser,
    *,
    event_id: uuid.UUID | None,
    submission_assignment_id: uuid.UUID | None,
    submission_element_ref: str | None,
    cycle_config_id: uuid.UUID | None,
) -> _UploadTarget:
    """Validates the Bezug form fields (mutual exclusion, tenant scoping) and resolves the
    public ids to internal ones - shared by upload_gallery_images and upload_documents."""
    if sum([event_id is not None, submission_assignment_id is not None, cycle_config_id is not None]) > 1:
        raise HTTPException(status_code=422, detail="Nur ein Zielbezug (Termin, Abgabe-Element oder Zyklus) gleichzeitig erlaubt")
    if (submission_assignment_id is None) != (submission_element_ref is None):
        raise HTTPException(status_code=422, detail="Abgabe und Abgabe-Element müssen zusammen angegeben werden")

    target = _UploadTarget()

    if event_id is not None:
        target.event_id = public_id_service.resolve_internal_id(db, Event, event_id, tenant_id=user.current_tenant_id)
        if target.event_id is None:
            raise HTTPException(status_code=404, detail="Termin nicht gefunden")
    elif submission_assignment_id is not None:
        # Ein Abgabe-Bezug schreibt in die Abgabe (Elementkapazität, Übersicht, Pendenzen):
        # dasselbe Recht wie die Abgabenverwaltung, inkl. Feature-Prüfung (kein Schreiben im
        # Nur-Lesen-Zustand nach einem Downgrade). files.manage allein reicht nicht.
        require_permission(user, P.SUBMISSIONS_MANAGE)
        target.assignment_id = public_id_service.resolve_internal_id(
            db, SubmissionAssignment, submission_assignment_id, tenant_id=user.current_tenant_id
        )
        if target.assignment_id is None:
            raise HTTPException(status_code=404, detail="Abgabe nicht gefunden")
        upload_assignment = db.get(SubmissionAssignment, target.assignment_id)
        target.assignment = upload_assignment
        try:
            parsed_key = _parse_element_ref(db, submission_element_ref)
        except ValueError:
            # Formal gültige, aber unbekannte Referenz wie eine fremde: 404 (kein Existenz-Orakel,
            # Security-Review 1.4.1); nur eine kaputte Referenz ist 422.
            if _ELEMENT_REF_SHAPE.fullmatch(submission_element_ref or ""):
                raise HTTPException(status_code=404, detail="Abgabe-Element nicht gefunden") from None
            raise HTTPException(status_code=422, detail="Ungültige Abgabe-Element-Referenz") from None
        # _parse_element_ref resolves the event/list-entry public id without a tenant
        # filter (see its docstring) - only trust it once it's confirmed as one of *this*
        # (already tenant-scoped) assignment's own elements, otherwise a writer could point
        # event_id at another tenant's event and leak this upload into that tenant's Zyklus
        # album.
        elements = submission_service._resolve_raw_elements(db, upload_assignment)
        match = next((e for e in elements if raw_element_key(e) == parsed_key), None)
        if match is None:
            raise HTTPException(status_code=404, detail="Abgabe-Element nicht gefunden")
        target.event_id = match["event_id"]
        target.element_label = match["label"]
    elif cycle_config_id is not None:
        target.cycle_config_id = public_id_service.resolve_internal_id(db, CycleConfig, cycle_config_id, tenant_id=user.current_tenant_id)
        if target.cycle_config_id is None:
            raise HTTPException(status_code=404, detail="Zyklus nicht gefunden")
    return target


def _form_tag_list(tags: str | None) -> list[str]:
    """Tags aus dem Upload-Formular (kommagetrennt). Multipart-Felder prüft NulGuardMiddleware
    nicht (nur JSON): ein NUL-Zeichen liess erst das Speichern von Upload-Verlauf bzw. Auftrag
    scheitern (DataError, 500 plus Fehlerprotokoll; Nachtlauf 2026-11-25). Erwarteter
    Eingabefehler, daher ohne Ursache (kein Fehlerprotokoll)."""
    if tags and "\x00" in tags:
        raise HTTPException(status_code=422, detail="Tags dürfen keine NUL-Zeichen enthalten")
    return [tag.strip() for tag in (tags or "").split(",") if tag.strip()]


def _clean_client_file_name(name: str) -> str:
    """Client-Dateiname ohne Steuerzeichen (v. a. NUL, das PostgreSQL nicht speichert). Ein
    Dateiname enthält nie sinnvoll Steuerzeichen - entfernen statt ablehnen (wie ingest_file)."""
    return _CONTROL_CHARS.sub("", name or "").strip()


def _parse_file_hints(raw: str | None) -> dict[str, dict]:
    """file_metadata-Formularfeld -> {sha256: {"metadata": {...}}}. Ungueltige Eintraege werden
    verworfen statt den Upload abzulehnen - die Hinweise sind optional, der Server analysiert
    jede Datei ohnehin selbst."""
    if not raw:
        return {}
    if len(raw.encode("utf-8")) > MAX_FILE_METADATA_JSON_BYTES:
        raise HTTPException(status_code=413, detail="Metadaten zum Upload sind zu gross")
    try:
        entries = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail="Ungültige Metadaten zum Upload") from None
    if not isinstance(entries, list):
        raise HTTPException(status_code=422, detail="Ungültige Metadaten zum Upload")
    hints: dict[str, dict] = {}
    for entry in entries[: MAX_GALLERY_UPLOAD_BATCH_FILES * 2]:
        if not isinstance(entry, dict):
            continue
        checksum = str(entry.get("sha256") or "").lower()
        if len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
            continue
        try:
            metadata = ClientImageMetadata.model_validate(entry.get("metadata") or {})
        except ValueError:
            continue
        hints[checksum] = {"metadata": metadata.model_dump(mode="json", exclude_none=True)}
    return hints


@router.post("/files/upload-precheck", response_model=UploadPrecheckResponse)
def precheck_uploads(
    payload: UploadPrecheckRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """SHA-256-Vorab-Abgleich vor dem eigentlichen Upload (Galerie, Dokumente,
    Protokollbilder): meldet je Datei, ob sie hochgeladen werden muss oder im eigenen
    Mandanten schon vorhanden ist, und ergaenzt bei Bildern fehlende Metadaten ohne erneute
    Uebertragung - siehe upload_precheck_service. Gleiche Rolle wie die Upload-Endpunkte."""
    require_any_permission(user, P.FILES_MANAGE, P.PHOTOS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    if payload.estimated_taken_on is not None and image_metadata_service.valid_estimated_date(payload.estimated_taken_on) is None:
        raise HTTPException(status_code=422, detail="Ungültiges geschätztes Aufnahmedatum")
    # Vorgang vor dem Abgleich prüfen: ein fremder/abgeschlossener ergibt 404, bevor etwas geschieht
    upload_job = upload_job_service.attach(db, user, payload.upload_job_id, ("gallery", "document", "todo"))
    results = service.precheck_uploads(db, tenant_id=user.current_tenant_id, request=payload, user_id=user.user_id, viewer=user)
    if upload_job is not None:
        by_client = {entry.client_id: entry for entry in payload.files}
        recorded = [
            {
                "name": by_client[result.client_id].name,
                "status": "skipped" if result.status == "already_exists" else "metadata_updated",
                "file_id": str(result.file_id) if result.file_id else None,
                "applied": list(result.applied),
                "size": by_client[result.client_id].size,
                "mime_type": by_client[result.client_id].mime_type,
            }
            for result in results
            if result.status in ("already_exists", "metadata_updated") and result.client_id in by_client
        ]
        upload_job_service.record_results(db, upload_job, recorded)
        db.commit()
    return UploadPrecheckResponse(results=results)


@router.post("/files/duplicate-check", response_model=FileDuplicateCheckResponse)
def check_file_duplicates(
    payload: FileDuplicateCheckRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Gibt es Dateien mit diesem Inhalt (SHA-256) schon? Für die Rückfrage «Bestehende anhängen /
    Kopie hochladen» beim Hochladen in eine Pendenz. Gemeldet werden nur Dateien des eigenen
    Mandanten, die die Person auch in der Dateisuche (GET /files) sehen würde - gleiche Rechte,
    gleiche Reichweite für Abgabe-Dateien, kein Papierkorb. Ein Hash eines fremden Mandanten oder
    einer unsichtbaren Datei ergibt dieselbe Antwort wie ein unbekannter (kein Existenz-Orakel;
    die Sichtbarkeitsabfrage läuft auch ohne Kandidaten, damit die Antwortzeit nichts verrät).
    POST statt GET, damit die Hashes nicht in Logs/URLs landen; der Endpunkt ändert nichts."""
    require_any_permission(user, P.FILES_READ, P.PHOTOS_READ)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    wanted = list(dict.fromkeys(checksum.lower() for checksum in payload.sha256))
    existing = upload_precheck_service.find_existing(db, user.current_tenant_id, wanted)
    candidate_ids = list(dict.fromkeys(row.public_id for rows in existing.values() for row in rows))
    visible = service.visible_overview_items(db, user, candidate_ids)
    matches: list[FileDuplicateMatch] = []
    for checksum in wanted:
        # Älteste sichtbare Datei mit diesem Inhalt (find_existing sortiert nach id)
        match = next((visible[row.public_id] for row in existing.get(checksum, []) if row.public_id in visible), None)
        if match is not None:
            matches.append(FileDuplicateMatch(sha256=checksum, file=match))
    return FileDuplicateCheckResponse(matches=matches)


@router.post("/files/gallery-uploads", response_model=GalleryUploadJobRead, status_code=status.HTTP_201_CREATED)
async def upload_gallery_images(
    files: list[UploadFile] = File(...),
    tags: str | None = Form(default=None),
    # Optional target picker: at most one of event_id, (submission_assignment_id +
    # submission_element_ref) or cycle_config_id - the batch then lands in that Termin's/
    # Abgabe-Element's/Zyklus' auto-album(s) too (see FileService.process_pending_gallery_upload_jobs).
    event_id: uuid.UUID | None = Form(default=None),
    submission_assignment_id: uuid.UUID | None = Form(default=None),
    submission_element_ref: str | None = Form(default=None),
    cycle_config_id: uuid.UUID | None = Form(default=None),
    # Im Upload-Dialog bestaetigt: Fotos, die dabei in ein geteiltes Auto-Album fallen, sofort
    # freigeben (sonst nur vorgemerkt, siehe photo_album_service.add_items).
    release_to_shared_albums: Annotated[bool, Form()] = False,
    # Optionales Schaetzdatum aus dem Upload-Popup - gilt nur fuer Bilder, fuer die der Server
    # kein echtes Aufnahmedatum findet (siehe FileService.save_gallery_uploads).
    estimated_taken_on: Annotated[date | None, Form()] = None,
    # Optionale Browser-Analyse je Datei als JSON-Liste [{sha256, metadata}] - reine Hinweise,
    # angewendet nur bei passendem serverseitigem Hash (siehe _parse_file_hints).
    file_metadata: Annotated[str | None, Form()] = None,
    # «GPS-Daten des Bildes mitsenden» (Datenschutz-Audit Paket 9.3), Standard an
    include_gps: Annotated[bool, Form()] = True,
    # Upload-Verlauf (0250): Vorgang aus POST /upload-jobs; ohne legt dieser Request einen eigenen an.
    upload_job_id: Annotated[uuid.UUID | None, Form()] = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Direkter Bild-Upload fuer die "Fotos"-Galerie (nicht an ein Protokoll/Word-Import/
    Abgabe gebunden) - unterstuetzt einzelne Bilddateien und .zip-Archive, aus denen nur
    Bilddateien uebernommen werden (siehe iter_gallery_zip_entries). This request only
    streams the raw upload(s) to disk and queues a gallery_upload_job - Magic-Byte-Pruefung,
    Virenscan und das eigentliche Speichern laufen danach im Hintergrund (siehe
    app/main.py's gallery_upload_ingest_loop und FileService.process_pending_gallery_upload_jobs),
    damit ein mehrere GB grosses ZIP nicht die ganze Request-Laufzeit ueber im Speicher
    gehalten werden muss und der Upload-Dialog sofort schliessen kann. Poll GET
    .../gallery-upload-jobs/{id} fuer den Fortschritt."""
    # Ganze Verarbeitung im Worker-Thread (Concurrency-Audit CONC-001): sie mischt synchrone
    # DB-Zugriffe mit awaits und blockierte sonst den Event-Loop des ganzen Workers.
    return await run_coroutine_in_thread(_upload_gallery_images_impl, files=files, tags=tags, event_id=event_id, submission_assignment_id=submission_assignment_id, submission_element_ref=submission_element_ref, cycle_config_id=cycle_config_id, release_to_shared_albums=release_to_shared_albums, estimated_taken_on=estimated_taken_on, file_metadata=file_metadata, include_gps=include_gps, upload_job_id=upload_job_id, db=db, user=user)


async def _upload_gallery_images_impl(  # loop-ok: nur über run_coroutine_in_thread (core/offload.py)
    files: list[UploadFile] = File(...),
    tags: str | None = Form(default=None),
    # Optional target picker: at most one of event_id, (submission_assignment_id +
    # submission_element_ref) or cycle_config_id - the batch then lands in that Termin's/
    # Abgabe-Element's/Zyklus' auto-album(s) too (see FileService.process_pending_gallery_upload_jobs).
    event_id: uuid.UUID | None = Form(default=None),
    submission_assignment_id: uuid.UUID | None = Form(default=None),
    submission_element_ref: str | None = Form(default=None),
    cycle_config_id: uuid.UUID | None = Form(default=None),
    # Im Upload-Dialog bestaetigt: Fotos, die dabei in ein geteiltes Auto-Album fallen, sofort
    # freigeben (sonst nur vorgemerkt, siehe photo_album_service.add_items).
    release_to_shared_albums: Annotated[bool, Form()] = False,
    # Optionales Schaetzdatum aus dem Upload-Popup - gilt nur fuer Bilder, fuer die der Server
    # kein echtes Aufnahmedatum findet (siehe FileService.save_gallery_uploads).
    estimated_taken_on: Annotated[date | None, Form()] = None,
    # Optionale Browser-Analyse je Datei als JSON-Liste [{sha256, metadata}] - reine Hinweise,
    # angewendet nur bei passendem serverseitigem Hash (siehe _parse_file_hints).
    file_metadata: Annotated[str | None, Form()] = None,
    # «GPS-Daten des Bildes mitsenden» (Datenschutz-Audit Paket 9.3), Standard an
    include_gps: Annotated[bool, Form()] = True,
    # Upload-Verlauf (0250): Vorgang aus POST /upload-jobs; ohne legt dieser Request einen eigenen an.
    upload_job_id: Annotated[uuid.UUID | None, Form()] = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Direkter Bild-Upload fuer die "Fotos"-Galerie (nicht an ein Protokoll/Word-Import/
    Abgabe gebunden) - unterstuetzt einzelne Bilddateien und .zip-Archive, aus denen nur
    Bilddateien uebernommen werden (siehe iter_gallery_zip_entries). This request only
    streams the raw upload(s) to disk and queues a gallery_upload_job - Magic-Byte-Pruefung,
    Virenscan und das eigentliche Speichern laufen danach im Hintergrund (siehe
    app/main.py's gallery_upload_ingest_loop und FileService.process_pending_gallery_upload_jobs),
    damit ein mehrere GB grosses ZIP nicht die ganze Request-Laufzeit ueber im Speicher
    gehalten werden muss und der Upload-Dialog sofort schliessen kann. Poll GET
    .../gallery-upload-jobs/{id} fuer den Fortschritt."""
    require_permission(user, P.PHOTOS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    if len(files) > MAX_GALLERY_UPLOAD_BATCH_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"Zu viele Dateien in einem Batch (maximal {MAX_GALLERY_UPLOAD_BATCH_FILES})",
        )

    target = _resolve_upload_target(
        db,
        user,
        event_id=event_id,
        submission_assignment_id=submission_assignment_id,
        submission_element_ref=submission_element_ref,
        cycle_config_id=cycle_config_id,
    )
    upload_event_id = target.event_id
    upload_assignment_id = target.assignment_id
    upload_element_label = target.element_label
    upload_cycle_config_id = target.cycle_config_id
    # An Abgabe-Element Bezug brings that Abgabe's file rules along. Direct images are judged
    # right here; a ZIP's entries only exist once the ingest job opens it, so it judges those
    # itself (FileService._ingest_gallery_batch).
    rules = (
        submission_upload_rules.load_rules(db, target.assignment, submission_element_ref)
        if target.assignment is not None and submission_element_ref is not None
        else None
    )
    # Live Photos: an IMG_1.MOV that belongs to an IMG_1.HEIC in this same batch is that photo's
    # clip, not a file of its own - it neither counts against the Abgabe's rules nor the
    # progress total (see FileService._run_gallery_upload_job, which pairs them the same way).
    plain_positions = [i for i, file in enumerate(files) if not (file.filename or "").lower().endswith(".zip")]
    live_pairs = pair_live_clips([files[i].filename or "" for i in plain_positions])
    clip_positions = {plain_positions[clip] for clip in live_pairs.values()}
    if rules is not None:
        direct_positions = set(plain_positions) - clip_positions
        direct_files = [file for i, file in enumerate(files) if i in direct_positions]
        problem = rules.check_count(len(direct_files)) or next(
            (error for error in (rules.check_extension(file.filename or "") for file in direct_files) if error), None
        )
        if problem is not None:
            raise HTTPException(status_code=400, detail=problem)

    tag_list = _form_tag_list(tags)
    if estimated_taken_on is not None and image_metadata_service.valid_estimated_date(estimated_taken_on) is None:
        raise HTTPException(status_code=422, detail="Ungültiges geschätztes Aufnahmedatum")
    file_hints = _parse_file_hints(file_metadata)
    if not include_gps:
        file_hints = {key: {**hint, "metadata": {k: v for k, v in (hint.get("metadata") or {}).items() if k != "gps"}} for key, hint in file_hints.items()}

    # Computed per-request, not as a module-level constant - settings.upload_root must be
    # read fresh each time (tests monkeypatch it; production has no reason to assume it's
    # immutable after import either).
    staging_dir = Path(settings.upload_root) / "_staging" / "gallery"
    staged_paths: list[str] = []
    # Same order as staged_paths - stage_upload_to_disk writes under a randomized filename,
    # so this is the only place a non-ZIP entry's real client-supplied name survives (a
    # ZIP's own entries keep their in-archive names, see iter_gallery_zip_entries).
    original_filenames: list[str] = []
    batch_bytes = 0
    has_zip = False
    reserved_bytes = 0
    try:
        for position, file in enumerate(files):
            name = file.filename or ""
            is_zip = name.lower().endswith(".zip")
            has_zip = has_zip or is_zip
            max_bytes = GALLERY_ZIP_MAX_BYTES if is_zip else (MAX_LIVE_CLIP_BYTES if position in clip_positions else GALLERY_DIRECT_IMAGE_MAX_BYTES)
            if rules is not None and not is_zip and position not in clip_positions:
                max_bytes = min(max_bytes, rules.max_bytes)
            staged_path = await stage_upload_to_disk(
                file, target_dir=staging_dir, max_bytes=max_bytes, suffix=Path(name).suffix.lower() or ".bin"
            )
            staged_paths.append(str(staged_path.relative_to(settings.storage_root)))
            batch_bytes += staged_path.stat().st_size
            reserved_bytes += await run_in_threadpool(inspect_gallery_zip, staged_path) if is_zip else staged_path.stat().st_size
            if reserved_bytes > 20 * 1024**3:
                raise HTTPException(413, "Der Upload ist entpackt grösser als 20 GiB")
            if batch_bytes > MAX_GALLERY_UPLOAD_BATCH_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Gesamtgrösse des Batches überschritten (maximal {MAX_GALLERY_UPLOAD_BATCH_BYTES // 1024 // 1024} MB)",
                )
            original_filenames.append(_clean_client_file_name(name))
    except BaseException:
        for relative_path in staged_paths:
            (Path(settings.storage_root) / relative_path).unlink(missing_ok=True)
        raise

    if not staged_paths:
        raise HTTPException(status_code=400, detail="Keine Dateien hochgeladen")

    try:
        upload_job, _created = _upload_job_for_request(
            db, user, upload_job_id, "gallery", target, submission_element_ref,
            options={"tags": tag_list, "estimated_taken_on": estimated_taken_on, "include_gps": include_gps,
                     "release_to_shared_albums": release_to_shared_albums},
        )
        upload_job_service.mark_processing(db, upload_job)
    except BaseException:
        db.rollback()
        for relative_path in staged_paths:
            (Path(settings.storage_root) / relative_path).unlink(missing_ok=True)
        raise

    job = GalleryUploadJob(
        upload_job_id=upload_job.id,
        tenant_id=user.current_tenant_id,
        reserved_bytes=reserved_bytes,
        staged_paths=staged_paths,
        original_filenames=original_filenames,
        tags=tag_list,
        upload_event_id=upload_event_id,
        upload_assignment_id=upload_assignment_id,
        upload_element_ref=submission_element_ref,
        upload_element_label=upload_element_label,
        upload_cycle_config_id=upload_cycle_config_id,
        release_to_shared_albums=release_to_shared_albums,
        requested_by=user.user_id,
        estimated_taken_on=estimated_taken_on,
        file_hints=file_hints,
        include_gps=include_gps,
        # A ZIP's matching entries are only known once the ingest loop opens it; a batch
        # of individually-selected images (no ZIP at all) knows its count immediately.
        total_files=None if has_zip else len(staged_paths) - len(clip_positions),
    )
    try:
        await acquire_upload_lock(db, user.current_tenant_id)
        _enforce_tenant_storage_quota(db, tenant_id=user.current_tenant_id, repo=StoredFileRepository(), incoming_bytes=reserved_bytes)
        db.add(job)
        db.commit()
    except BaseException:
        db.rollback()
        for relative_path in staged_paths:
            (Path(settings.storage_root) / relative_path).unlink(missing_ok=True)
        raise
    # Once committed, staging belongs to the durable job even if refresh fails.
    db.refresh(job)
    return _gallery_upload_job_to_read(job)


@router.post("/files/document-uploads", response_model=DocumentUploadResult, status_code=status.HTTP_201_CREATED)
async def upload_documents(
    files: list[UploadFile] = File(...),
    tags: str | None = Form(default=None),
    # Same optional Bezug picker as upload_gallery_images (at most one of Termin / Abgabe-
    # Element / Zyklus) - here it is stored on the file itself and shown in the "Bezug"
    # column of the Dateien page, instead of routing it into an auto-album.
    event_id: uuid.UUID | None = Form(default=None),
    submission_assignment_id: uuid.UUID | None = Form(default=None),
    submission_element_ref: str | None = Form(default=None),
    cycle_config_id: uuid.UUID | None = Form(default=None),
    # Pendenz-Dialog: «Kopie hochladen» bzw. keine sichtbare Datei mit gleichem Inhalt - dann
    # wird auch ein (evtl. für die Person unsichtbares) exaktes Duplikat neu gespeichert, statt
    # es zu überspringen und dessen ID zurückzugeben.
    allow_duplicates: Annotated[bool, Form()] = False,
    # Pendenz-Dialog: Bilder (ohne HEIC) wie Dokumente annehmen - nur mit photos.manage.
    allow_images: Annotated[bool, Form()] = False,
    # Wie beim Galerie-Upload: false entfernt GPS-Daten aus Bildern (nur mit allow_images wirksam).
    include_gps: Annotated[bool, Form()] = True,
    # Upload-Verlauf (0250): Vorgang aus POST /upload-jobs; ohne legt dieser Request einen eigenen an.
    upload_job_id: Annotated[uuid.UUID | None, Form()] = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Direkter Dokument-Upload fuer die "Dateien"-Seite (PDF, Office/OpenDocument, RTF, Text,
    ZIP - siehe upload_pipeline._sniff_document_mime; Bilder gehoeren auf die "Fotos"-Seite).
    Anders als der Galerie-Upload laeuft alles inline: Magic-Byte-Pruefung, Virenscan und
    Speichern passieren in diesem Request, das Ergebnis (gespeicherte Dateien + Einzelfehler)
    kommt direkt zurueck."""
    # Ganze Verarbeitung im Worker-Thread (Concurrency-Audit CONC-001): sie mischt synchrone
    # DB-Zugriffe mit awaits und blockierte sonst den Event-Loop des ganzen Workers.
    return await run_coroutine_in_thread(_upload_documents_impl, files=files, tags=tags, event_id=event_id, submission_assignment_id=submission_assignment_id, submission_element_ref=submission_element_ref, cycle_config_id=cycle_config_id, allow_duplicates=allow_duplicates, allow_images=allow_images, include_gps=include_gps, upload_job_id=upload_job_id, db=db, user=user)


async def _upload_documents_impl(  # loop-ok: nur über run_coroutine_in_thread (core/offload.py)
    files: list[UploadFile] = File(...),
    tags: str | None = Form(default=None),
    # Same optional Bezug picker as upload_gallery_images (at most one of Termin / Abgabe-
    # Element / Zyklus) - here it is stored on the file itself and shown in the "Bezug"
    # column of the Dateien page, instead of routing it into an auto-album.
    event_id: uuid.UUID | None = Form(default=None),
    submission_assignment_id: uuid.UUID | None = Form(default=None),
    submission_element_ref: str | None = Form(default=None),
    cycle_config_id: uuid.UUID | None = Form(default=None),
    # Pendenz-Dialog: «Kopie hochladen» bzw. keine sichtbare Datei mit gleichem Inhalt - dann
    # wird auch ein (evtl. für die Person unsichtbares) exaktes Duplikat neu gespeichert, statt
    # es zu überspringen und dessen ID zurückzugeben.
    allow_duplicates: Annotated[bool, Form()] = False,
    # Pendenz-Dialog: Bilder (ohne HEIC) wie Dokumente annehmen - nur mit photos.manage.
    allow_images: Annotated[bool, Form()] = False,
    # Wie beim Galerie-Upload: false entfernt GPS-Daten aus Bildern (nur mit allow_images wirksam).
    include_gps: Annotated[bool, Form()] = True,
    # Upload-Verlauf (0250): Vorgang aus POST /upload-jobs; ohne legt dieser Request einen eigenen an.
    upload_job_id: Annotated[uuid.UUID | None, Form()] = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Direkter Dokument-Upload fuer die "Dateien"-Seite (PDF, Office/OpenDocument, RTF, Text,
    ZIP - siehe upload_pipeline._sniff_document_mime; Bilder gehoeren auf die "Fotos"-Seite).
    Anders als der Galerie-Upload laeuft alles inline: Magic-Byte-Pruefung, Virenscan und
    Speichern passieren in diesem Request, das Ergebnis (gespeicherte Dateien + Einzelfehler)
    kommt direkt zurueck."""
    require_permission(user, P.FILES_MANAGE)
    if allow_images is True:
        # Bilder landen (nach MIME) auch in «Fotos» - dafür braucht es das Foto-Schreibrecht.
        require_permission(user, P.PHOTOS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    if len(files) > MAX_DOCUMENT_UPLOAD_BATCH_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"Zu viele Dateien in einem Batch (maximal {MAX_DOCUMENT_UPLOAD_BATCH_FILES})",
        )
    target = _resolve_upload_target(
        db,
        user,
        event_id=event_id,
        submission_assignment_id=submission_assignment_id,
        submission_element_ref=submission_element_ref,
        cycle_config_id=cycle_config_id,
    )
    tag_list = _form_tag_list(tags)

    # An Abgabe-Element Bezug brings that Abgabe's file rules (Dateitypen, Dateigrösse, Anzahl)
    # along - rejected as a whole like the Abgabebox does, before anything is staged.
    rules = (
        submission_upload_rules.load_rules(db, target.assignment, submission_element_ref)
        if target.assignment is not None and submission_element_ref is not None
        else None
    )
    max_file_bytes = MAX_UPLOAD_BYTES
    if rules is not None:
        problem = rules.check_count(len(files)) or next(
            (error for error in (rules.check_extension(file.filename or "") for file in files) if error), None
        )
        if problem is not None:
            raise HTTPException(status_code=400, detail=problem)
        max_file_bytes = min(max_file_bytes, rules.max_bytes)

    # Streamed to disk first (rather than `await file.read()`) so the per-file size cap is
    # enforced while the bytes arrive, then read back for the scan/ingest step.
    staging_dir = Path(settings.upload_root) / "_staging" / "documents"
    staged: list[tuple[str, bytes]] = []
    batch_bytes = 0
    for file in files:
        name = file.filename or ""
        staged_path = await stage_upload_to_disk(
            file, target_dir=staging_dir, max_bytes=max_file_bytes, suffix=Path(name).suffix.lower() or ".bin"
        )
        try:
            content = staged_path.read_bytes()
        finally:
            staged_path.unlink(missing_ok=True)
        batch_bytes += len(content)
        if batch_bytes > MAX_DOCUMENT_UPLOAD_BATCH_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Gesamtgrösse des Batches überschritten (maximal {MAX_DOCUMENT_UPLOAD_BATCH_BYTES // 1024 // 1024} MB)",
            )
        staged.append((_clean_client_file_name(name), content))

    upload_job, created_here = _upload_job_for_request(
        db, user, upload_job_id, "document", target, submission_element_ref,
        options={"tags": tag_list, "include_gps": include_gps is not False, "allow_duplicates": allow_duplicates is True},
    )
    file_results: list[dict] = []
    items, errors = await service.save_document_uploads(
        db,
        tenant_id=user.current_tenant_id,
        files=staged,
        tags=tag_list,
        created_by=user.user_id,
        upload_event_id=target.event_id,
        upload_assignment=target.assignment,
        upload_element_ref=submission_element_ref if target.assignment is not None else None,
        upload_element_label=target.element_label,
        upload_cycle_config_id=target.cycle_config_id,
        file_results=file_results,
        allow_images=allow_images is True,
        allow_duplicates=allow_duplicates is True,
        include_gps=include_gps is not False,
        # Duplikate nur überspringen, wenn die Person sie sehen darf (Security-Review V-2)
        viewer=user,
        # Verlauf in derselben Transaktion wie die neuen Dateien
        before_commit=lambda: upload_job_service.record_results(db, upload_job, file_results),
    )
    if created_here:
        upload_job_service.finish(db, upload_job)
    db.commit()
    return DocumentUploadResult(
        items=items, errors=errors, file_results=[UploadFileResult(**result) for result in file_results], upload_job_id=upload_job.id
    )


@router.get("/files/gallery-upload-jobs", response_model=list[GalleryUploadJobRead])
def list_gallery_upload_jobs(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Tenant-wide list of not-yet-finished gallery uploads, backing the "Bilder hochladen"
    status bar - same tenant-wide-visibility idea as GET /files/analysis-progress (just a
    list here, not one aggregated object), so the bar shows up for any writer in the tenant
    (any tab, after a refresh, ...), not just whoever's browser sent the original request."""
    require_permission(user, P.PHOTOS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    jobs = db.scalars(
        select(GalleryUploadJob)
        .where(GalleryUploadJob.tenant_id == user.current_tenant_id, GalleryUploadJob.status.in_(["queued", "running"]))
        .order_by(GalleryUploadJob.created_at)
    )
    return [_gallery_upload_job_to_read(job) for job in jobs]


@router.get("/files/gallery-upload-jobs/{job_id}", response_model=GalleryUploadJobDetail)
def get_gallery_upload_job(job_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Full result for one job - fetched once it's left the active listing above, so the
    frontend can show the same (items, errors) summary the old synchronous response used
    to return directly."""
    require_permission(user, P.PHOTOS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    job = db.get(GalleryUploadJob, job_id)
    if job is None or job.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Upload-Auftrag nicht gefunden")
    imported_items = (
        service.list_tenant_files(
            db,
            user.current_tenant_id,
            file_ids=[uuid.UUID(file_id) for file_id in job.imported_file_ids],
            limit=len(job.imported_file_ids),
        )
        if job.imported_file_ids
        else []
    )
    return GalleryUploadJobDetail(
        **_gallery_upload_job_to_read(job).model_dump(),
        imported_items=imported_items,
        errors=list(job.errors),
        file_results=[UploadFileResult(**result) for result in job.file_results or []],
    )


@router.get("/protocol-element-blocks/{protocol_element_block_id}/images", response_model=list[ProtocolImageRead])
def list_images(
    protocol_element_block_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_READ)
    block = public_id_service.get_by_public_id(db, ProtocolElementBlock, protocol_element_block_id)
    if block is None:
        raise HTTPException(status_code=404, detail="Protocol element block not found")
    _ensure_readable_block_or_404(db, user, block.id, "Protocol element block not found")
    return service.list_protocol_images(db, block.id)


@router.get("/protocols/{protocol_id}/block-images", response_model=dict[uuid.UUID, list[ProtocolImageRead]])
def list_protocol_block_images(
    protocol_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Bilder aller Bildblöcke eines Protokolls in einer Anfrage (Block-public_id -> Liste wie
    GET /protocol-element-blocks/{id}/images), statt einer Anfrage je Block. Gleiche Prüfungen
    wie die Einzelroute: meetings.read und Leserecht am Protokoll; fremde oder unbekannte
    Protokolle ergeben 404."""
    require_permission(user, P.MEETINGS_READ)
    protocol = public_id_service.get_by_public_id(db, Protocol, protocol_id, tenant_id=user.current_tenant_id)
    if protocol is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    if not access_service.can_read_protocol(db, user, protocol.id):
        # Wie die Einzelroute: Entwurf ohne Leserecht = unbekannt (SECURITY-RULES 1.6)
        raise HTTPException(status_code=404, detail="Protocol not found")
    blocks = db.execute(
        select(ProtocolElementBlock.id, ProtocolElementBlock.public_id)
        .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
        .join(ElementType, ElementType.id == ProtocolElementBlock.element_type_id)
        .where(ProtocolElement.protocol_id == protocol.id, ElementType.code == "image")
        .order_by(ProtocolElement.sort_index.asc(), ProtocolElementBlock.sort_index.asc(), ProtocolElementBlock.id.asc())
    ).all()
    result: dict[uuid.UUID, list[ProtocolImageRead]] = {block_public_id: [] for _, block_public_id in blocks}
    if not blocks:
        return result
    public_id_by_block = {block_id: block_public_id for block_id, block_public_id in blocks}
    rows = db.execute(
        select(ProtocolImage, StoredFile)
        .join(StoredFile, StoredFile.id == ProtocolImage.stored_file_id)
        .where(ProtocolImage.protocol_element_block_id.in_(list(public_id_by_block)))
        .order_by(ProtocolImage.protocol_element_block_id.asc(), ProtocolImage.sort_index.asc(), ProtocolImage.id.asc())
    ).all()
    # Gleiche Felder wie FileService.list_protocol_images
    for row in rows:
        block_public_id = public_id_by_block[row.ProtocolImage.protocol_element_block_id]
        result[block_public_id].append(
            ProtocolImageRead(
                id=row.ProtocolImage.public_id,
                protocol_element_block_id=block_public_id,
                stored_file_id=row.StoredFile.public_id,
                sort_index=row.ProtocolImage.sort_index,
                title=row.ProtocolImage.title,
                caption=row.ProtocolImage.caption,
                original_name=row.StoredFile.original_name,
                mime_type=row.StoredFile.mime_type,
                file_size_bytes=row.StoredFile.file_size_bytes,
                content_url=service.build_content_url(row.StoredFile.public_id),
            )
        )
    return result


def _ensure_readable_block_or_404(db: Session, user: CurrentUser, protocol_element_block_id: int, detail: str) -> None:
    """Wie access_service.ensure_can_read_protocol_block, aber 404 statt 403: fremde Blöcke und
    Entwürfe ohne Leserecht antworten wie unbekannte IDs (SECURITY-RULES 1.6, vgl.
    protocol_elements._ensure_readable_protocol_or_404). Mandant, Entwurfsrecht und
    Teilnehmer-Zuordnung prüft can_read_protocol."""
    protocol_id = access_service.repository.protocol_id_for_block(db, protocol_element_block_id=protocol_element_block_id)
    if protocol_id is None or not access_service.can_read_protocol(db, user, protocol_id):
        raise HTTPException(status_code=404, detail=detail)


def _ensure_block_protocol_not_frozen(db: Session, protocol_element_block_id: int) -> None:
    """Audit MAIN-BE-007: Bilder abgeschlossener Protokolle sind wie alle anderen Inhalte
    eingefroren (gleiche 409 wie ProtocolService.get_protocol_or_404_not_frozen)."""
    protocol_id = access_service.repository.protocol_id_for_block(db, protocol_element_block_id=protocol_element_block_id)
    protocol = db.get(Protocol, protocol_id) if protocol_id else None
    if protocol is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    if protocol.status == "abgeschlossen":
        raise HTTPException(status_code=409, detail="Protocol is already abgeschlossen")


@router.post("/protocol-element-blocks/{protocol_element_block_id}/images", response_model=ProtocolImageRead)
async def upload_image(
    protocol_element_block_id: uuid.UUID,
    file: UploadFile,
    title: str | None = Form(default=None),
    caption: str | None = Form(default=None),
    include_gps: bool = Form(default=True),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    # Ganze Verarbeitung im Worker-Thread (Concurrency-Audit CONC-001): sie mischt synchrone
    # DB-Zugriffe mit awaits und blockierte sonst den Event-Loop des ganzen Workers.
    return await run_coroutine_in_thread(_upload_image_impl, protocol_element_block_id=protocol_element_block_id, file=file, title=title, caption=caption, include_gps=include_gps, db=db, user=user)


async def _upload_image_impl(  # loop-ok: nur über run_coroutine_in_thread (core/offload.py)
    protocol_element_block_id: uuid.UUID,
    file: UploadFile,
    title: str | None = Form(default=None),
    caption: str | None = Form(default=None),
    include_gps: bool = Form(default=True),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_EDIT)
    # Multipart-Felder prüft NulGuardMiddleware nicht (nur JSON): NUL in Titel/Legende liess erst
    # das INSERT scheitern (400 plus Fehlerprotokoll; Nachtlauf 2026-11-25). Erwarteter
    # Eingabefehler, deshalb ValueError als Ursache (kein Fehlerprotokoll).
    for value in (title, caption):
        try:
            reject_nul_characters(value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Title and caption must not contain NUL characters") from exc
    protocol_element_block = public_id_service.get_by_public_id(db, ProtocolElementBlock, protocol_element_block_id)
    if protocol_element_block is None:
        raise HTTPException(status_code=404, detail="Protocol element block not found")
    _ensure_readable_block_or_404(db, user, protocol_element_block.id, "Protocol element block not found")
    _ensure_block_protocol_not_frozen(db, protocol_element_block.id)
    protocol_id = db.scalar(
        select(ProtocolElement.protocol_id).where(ProtocolElement.id == protocol_element_block.protocol_element_id)
    )

    def record_in_history(stored_file: StoredFile) -> None:
        # Upload-Verlauf (E-6): ein Vorgang je Protokoll und Tag, in derselben Transaktion
        if protocol_id is None:
            return
        job = upload_job_service.protocol_day_job(db, tenant_id=stored_file.tenant_id, protocol_id=protocol_id, created_by=user.user_id)
        upload_job_service.record_new_file(db, job, stored_file)

    try:
        return await service.save_protocol_image(
            db,
            protocol_element_block=protocol_element_block,
            file=file,
            title=title,
            caption=caption,
            created_by=user.user_id,
            include_gps=include_gps,
            viewer=user,
            before_commit=record_in_history,
        )
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Image could not be uploaded") from exc
    except HTTPException as exc:
        # Upload-Verlauf: abgelehnte Bilder (Format, Grösse, Virenfund, Duplikat, Speicher) als
        # Zeile im Vorgang des Protokolls und Tages - in eigener Transaktion, die Ablehnung bleibt.
        reason = _protocol_image_rejection_reason(exc)
        if reason is not None and protocol_id is not None:
            db.rollback()
            _record_protocol_image_rejection(db, user, protocol_element_block, protocol_id, file, reason)
        raise


def _protocol_image_rejection_reason(exc: HTTPException) -> str | None:
    """Grund einer abgelehnten Protokollbild-Datei (UploadRejected.code bzw. Status), None bei
    Fehlern, die nichts mit der Datei zu tun haben (Rechte, gesperrtes Protokoll)."""
    code = getattr(exc, "code", None)
    if code:
        return str(code)
    if exc.status_code == 413:
        return "too_large"
    if exc.status_code == 409:
        return "duplicate_exact"
    detail = str(exc.detail or "")
    if exc.status_code == 400 and ("Unsupported file type" in detail or "Bildformat" in detail):
        return "unsupported_format"
    if exc.status_code == 400 and "Speicherlimit" in detail:
        return "quota_exceeded"
    return None


def _record_protocol_image_rejection(
    db: Session, user: CurrentUser, block: ProtocolElementBlock, protocol_id: int, file: UploadFile, reason: str
) -> None:
    """Best effort: der Verlauf darf die eigentliche Antwort (Ablehnung) nie verändern."""
    try:
        tenant_id = service._resolve_tenant_id(db, block.id)
        if tenant_id is None or tenant_id != user.current_tenant_id:
            return
        job = upload_job_service.protocol_day_job(db, tenant_id=tenant_id, protocol_id=protocol_id, created_by=user.user_id)
        upload_job_service.record_results(
            db, job, [{"name": file.filename or "bild", "status": "skipped" if reason == "duplicate_exact" else "failed", "code": reason, "size": file.size}],
        )
        db.refresh(job)
        job.status = upload_job_service.final_status(job)
        db.commit()
    except Exception as exc:  # noqa: BLE001 - Verlauf ist Zusatz, Fehler nur protokollieren
        db.rollback()
        from app.core.error_log import record_system_error

        record_system_error(db, exc=exc, tenant_id=user.current_tenant_id)


@router.delete("/protocol-images/{image_id}", response_model=dict[str, str])
def delete_image(
    image_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_EDIT)
    protocol_image = public_id_service.get_by_public_id(db, ProtocolImage, image_id)
    if protocol_image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    _ensure_readable_block_or_404(db, user, protocol_image.protocol_element_block_id, "Image not found")
    _ensure_block_protocol_not_frozen(db, protocol_image.protocol_element_block_id)
    try:
        deleted = service.delete_protocol_image(db, protocol_image.id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Image could not be deleted") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Image not found")
    return {"message": "Image deleted"}


# Bildunterschrift nachträglich (Editor 1a) je Konto
IMAGE_CAPTION_LIMIT_PER_MINUTE = 120


@router.patch("/protocol-images/{image_id}", response_model=ProtocolImageRead)
def patch_image_caption(
    image_id: uuid.UUID,
    payload: ProtocolImageCaptionUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Bildunterschrift eines Protokollbilds ändern. Gleiche Regeln wie Bearbeiten des Blocks:
    meetings.edit, Protokoll lesbar und im eigenen Mandanten (sonst 404), nicht abgeschlossen und
    Block nicht von einer anderen Person gesperrt (409). Andere Editoren erhalten die neue
    Bildliste über denselben WS-Schlüssel wie beim Hochladen (block-<id>-images)."""
    from app.api.routes.protocol_elements import _ensure_block_not_locked_by_other
    from app.core.redis_client import publish_best_effort
    from app.services.collaboration_service import protocol_channel

    require_permission(user, P.MEETINGS_EDIT)
    enforce_rate_limit(f"protocol-image-caption:{user.user_id}", limit=IMAGE_CAPTION_LIMIT_PER_MINUTE, period_seconds=60)
    protocol_image = public_id_service.get_by_public_id(db, ProtocolImage, image_id)  # nosemgrep: public-id-lookup-without-tenant -- Bild hat keine tenant_id; Mandant über Block/Protokoll direkt darunter geprüft
    if protocol_image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    _ensure_readable_block_or_404(db, user, protocol_image.protocol_element_block_id, "Image not found")
    protocol_id = access_service.repository.protocol_id_for_block(db, protocol_element_block_id=protocol_image.protocol_element_block_id)
    protocol = db.get(Protocol, protocol_id) if protocol_id else None
    # Schreiben nur im eigenen Mandanten, auch wenn Leserechte einmal weiter reichen (Regel 1.2)
    if protocol is None or protocol.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Image not found")
    _ensure_block_protocol_not_frozen(db, protocol_image.protocol_element_block_id)
    block = db.get(ProtocolElementBlock, protocol_image.protocol_element_block_id)
    _ensure_block_not_locked_by_other(protocol.id, block.public_id, user)
    protocol_image.caption = payload.caption
    db.add(protocol_image)
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Caption could not be saved") from exc
    images = service.list_protocol_images(db, block.id)
    publish_best_effort(
        protocol_channel(protocol.id),
        json.dumps({
            "type": "field_update",
            "field_key": f"block-{block.public_id}-images",
            "patch": jsonable_encoder(images),
            "user_id": str(user.user_public_id),
            "display_name": user.display_name,
        }),
    )
    updated = next((image for image in images if image.id == protocol_image.public_id), None)
    if updated is None:
        raise HTTPException(status_code=404, detail="Image not found")
    return updated


# Partner-Mandant ohne Standortfreigabe (IMGMETA-007): nur der Standort fällt weg, Datum und
# Kamera bleiben wie bisher.
_WITHOUT_LOCATION = MetadataPolicy(location=False, capture_date=True, camera=True)


def _sees_location(user: CurrentUser) -> bool:
    """GPS nur mit Schreibrecht auf Dateien oder Sitzungen (Datenschutz-Audit Paket 9.4, bisher ab
    Rolle writer): Leser sehen weder Koordinaten in den Metadaten noch GPS im ausgelieferten
    Original. Gespeichert bleibt alles unverändert."""
    return user.can(P.FILES_MANAGE) or user.can(P.MEETINGS_EDIT)


def _strips_location(db: Session, user: CurrentUser, stored_file: StoredFile) -> bool:
    if not _sees_location(user):
        return True
    return user.current_tenant_id is not None and not photo_album_share_service.location_shared_with(
        db, user.current_tenant_id, stored_file.id, stored_file.tenant_id
    )


def _temporary_copy(suffix: str) -> Path:
    work_dir = Path(settings.upload_root) / "_staging" / "download"
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir / f"{uuid.uuid4().hex}{suffix}"


def _video_without_metadata(key: str) -> Path:
    """Live-Photo-Clip aus dem Objektspeicher ohne Container-Metadaten als temporäre Datei
    (ffmpeg braucht einen Pfad); der Aufrufer löscht sie nach dem Senden."""
    target = _temporary_copy(".mp4")
    try:
        with get_object_store().local_copy(MAIN, key, work_dir=target.parent, suffix=".mp4") as source:
            cleaned = apple_media.clip_without_metadata(source, target)
    except ObjectNotFound as exc:
        raise HTTPException(status_code=404, detail="File missing on filesystem") from exc
    if not cleaned:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=404, detail="Video ist ohne Standortdaten nicht verfügbar")
    return target


@router.get("/stored-files/{stored_file_id}/content")
def get_stored_file_content(
    stored_file_id: uuid.UUID,
    request: Request = None,  # type: ignore[assignment]  # None nur bei direktem Aufruf in Tests
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_READ)
    stored_file = public_id_service.get_by_public_id(db, StoredFile, stored_file_id)
    if stored_file is None:
        raise HTTPException(status_code=404, detail="Stored file not found")
    access_service.ensure_can_read_stored_file(db, user, stored_file.id)
    if stored_file.scan_status == "infected":
        raise HTTPException(status_code=403, detail="Datei wurde von der Virenprüfung als infiziert erkannt und ist gesperrt")
    if stored_file.scan_status == "error":
        raise HTTPException(422, "Virenprüfung fehlgeschlagen – Datei ist gesperrt")
    if stored_file.scan_status == "pending":
        raise HTTPException(status_code=425, detail="Datei wird noch auf Schadsoftware geprüft, bitte in Kürze erneut versuchen")
    # SECURITY: set nosniff so a browser never MIME-sniffs the content and renders it
    # inline against our wishes, mirroring submission_assignments.get_submission_file_content.
    # inline also covers images now, not just PDF (audit finding, 2026-08-25) - protocol
    # images are rendered directly via <img src> pointing at this same endpoint (see
    # focused-element-editor.tsx's LightboxImage/content_url), which "attachment" would
    # otherwise force browsers to treat as a download instead of image data to paint.
    # nosniff already closes the MIME-confusion risk "attachment" was guarding against
    # for a real image mime type.
    # video/mp4 is the Live Photo clip (see apple_media.py) the Fotos grid plays via <video src>.
    is_inline_safe = stored_file.mime_type in {"application/pdf", "video/mp4"} or (stored_file.mime_type or "").startswith("image/")
    # Partner-Mandant ohne Standortfreigabe (IMGMETA-007): Standort aus Bild bzw. Clip entfernen.
    is_media = stored_file.mime_type == "video/mp4" or (stored_file.mime_type or "").startswith("image/")
    if is_media and _strips_location(db, user, stored_file):
        no_store = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}
        if stored_file.mime_type == "video/mp4":
            clean_path = _video_without_metadata(stored_file.storage_path)
            return release_for_stream(db, FileResponse(
                path=clean_path,
                media_type=stored_file.mime_type,
                filename=stored_file.original_name,
                content_disposition_type="inline",
                headers=no_store,
                background=BackgroundTask(clean_path.unlink, missing_ok=True),
            ))
        content = read_bytes_or_404(MAIN, stored_file.storage_path, detail="File missing on filesystem")
        return Response(
            content=sanitize_image(content, stored_file.mime_type, _WITHOUT_LOCATION),
            media_type=stored_file.mime_type,
            headers={**no_store, **_content_disposition(stored_file.original_name, False)},
        )
    return release_for_stream(db, object_response(
        request,
        MAIN,
        stored_file.storage_path,
        media_type=stored_file.mime_type,
        filename=stored_file.original_name,
        attachment=not is_inline_safe,
        not_found_detail="File missing on filesystem",
        # A stored file's pixels never change after upload (a re-upload creates a new id), so the
        # browser cache can keep this for a long time - saves refetching originals opened again
        # from the Fotos viewer/lightbox within the same session. Einzige Ausnahme sind die
        # EXIF-Datumsfelder (korrigiertes Aufnahmedatum, Migration 0203): die Anzeige ist davon
        # nicht betroffen, Downloads laufen über eigene Endpunkte bzw. die Exportkopie.
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=604800, immutable"},
    ))


@router.patch("/stored-files/{stored_file_id}/tags", response_model=list[str])
def update_stored_file_tags(
    stored_file_id: uuid.UUID,
    payload: StoredFileTagsUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_any_permission(user, P.FILES_MANAGE, P.PHOTOS_MANAGE)
    # Nur Dateien des eigenen Mandanten (Security-Audit SEC-003): ensure_can_read_stored_file
    # erlaubt auch das Lesen von Partner-Fotos aus geteilten Alben - Schreiben darf das nie.
    stored_file = public_id_service.get_by_public_id(db, StoredFile, stored_file_id, tenant_id=user.current_tenant_id)
    if stored_file is None or user.current_tenant_id is None:
        raise HTTPException(status_code=404, detail="Stored file not found")
    access_service.ensure_can_read_stored_file(db, user, stored_file.id, allow_context_grant=False)  # schreibt: nur Rollenrechte
    # Fotos verwaltet photos.manage, übrige Dateien files.manage (Plan «Berechtigungen», Phase 3)
    require_permission(user, P.PHOTOS_MANAGE if (stored_file.mime_type or "").startswith("image/") else P.FILES_MANAGE)
    return service.update_stored_file_tags(db, stored_file, payload.tags)


def _own_file_for_keywords(db: Session, user: CurrentUser, stored_file_id: uuid.UUID) -> StoredFile:
    """Datei des eigenen Mandanten (nie ein Partner-Foto aus einem geteilten Album: Keywords gehören
    dem Besitzer) und nicht im Papierkorb; fremd und unbekannt ergeben dasselbe 404."""
    stored_file = public_id_service.get_by_public_id(db, StoredFile, stored_file_id, tenant_id=user.current_tenant_id)
    if stored_file is None or user.current_tenant_id is None or stored_file.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Stored file not found")
    return stored_file


def _is_image(stored_file: StoredFile) -> bool:
    return (stored_file.mime_type or "").startswith("image/")


@router.get("/stored-files/{stored_file_id}/keywords", response_model=StoredFileKeywordsRead)
def get_stored_file_keywords(
    stored_file_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Keywords einer Datei (nur für die Suche, Migration 0217) für Datei-Detail und Foto-Ansicht."""
    require_any_permission(user, P.FILES_READ, P.PHOTOS_READ)
    stored_file = _own_file_for_keywords(db, user, stored_file_id)
    access_service.ensure_can_read_stored_file(db, user, stored_file.id)
    if _is_image(stored_file):
        require_permission(user, P.PHOTOS_READ)
    else:
        require_permission(user, P.FILES_READ)
    _ensure_files_in_scope(db, user, [stored_file.public_id])
    can_edit = user.can(P.PHOTOS_MANAGE if _is_image(stored_file) else P.FILES_MANAGE)
    return StoredFileKeywordsRead(keywords=list(stored_file.keywords or []), can_edit=can_edit)


@router.patch("/stored-files/{stored_file_id}/keywords", response_model=StoredFileKeywordsRead)
def update_stored_file_keywords(
    stored_file_id: uuid.UUID,
    payload: StoredFileKeywordsUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Keywords ersetzen. Rechte wie beim Tag-Speichern: Bilder photos.manage, übrige Dateien
    files.manage, nur eigener Mandant (Schreiben strenger als Lesen, SEC-003)."""
    require_any_permission(user, P.FILES_MANAGE, P.PHOTOS_MANAGE)
    stored_file = _own_file_for_keywords(db, user, stored_file_id)
    access_service.ensure_can_read_stored_file(db, user, stored_file.id, allow_context_grant=False)  # schreibt: nur Rollenrechte
    if _is_image(stored_file):
        require_permission(user, P.PHOTOS_MANAGE)
    else:
        require_permission(user, P.FILES_MANAGE)
    _ensure_files_in_scope(db, user, [stored_file.public_id])
    keywords = file_keywords.set_keywords(db, stored_file, payload.keywords)
    return StoredFileKeywordsRead(keywords=keywords, can_edit=True)


def _require_kind_permissions(db: Session, user: CurrentUser, ids: list[uuid.UUID], *, write: bool) -> None:
    """Mehrfachaktion über Fotos und/oder Dateien: je Sorte das passende Recht. Alle IDs müssen
    Dateien des eigenen Mandanten sein (sonst 404 ohne Hinweis, welche)."""
    if not ids or len(ids) > file_keywords.MAX_BULK_FILES:
        raise HTTPException(status_code=422, detail="Bitte 1 bis 200 Dateien auswählen")
    mimes = db.execute(
        select(StoredFile.public_id, StoredFile.mime_type).where(
            StoredFile.tenant_id == user.current_tenant_id, StoredFile.public_id.in_(ids)
        )
    ).all()
    if len(mimes) != len(ids):
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    _ensure_files_in_scope(db, user, ids)
    # Wie die Einzelroute: Leserecht je Datei (z. B. Protokollbilder nur aus lesbaren Protokollen;
    # Security-Review F2), beim Schreiben nur Rollenrechte. Nicht lesbar ergibt dasselbe 404.
    if _readable_own_ids(db, user, ids, write=write) != set(ids):
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    has_images = any((row.mime_type or "").startswith("image/") for row in mimes)
    has_documents = any(not (row.mime_type or "").startswith("image/") for row in mimes)
    if has_images:
        require_permission(user, P.PHOTOS_MANAGE if write else P.PHOTOS_READ)
    if has_documents:
        require_permission(user, P.FILES_MANAGE if write else P.FILES_READ)


@router.post("/files/bulk-keywords", response_model=FileBulkKeywordsResult)
def bulk_update_file_keywords(
    payload: FileBulkKeywordsUpdate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)
):
    """Mehrfachbearbeitung in Fotos und Ablage: Keywords hinzufügen und/oder entfernen."""
    require_any_permission(user, P.FILES_MANAGE, P.PHOTOS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    ids = list(dict.fromkeys(payload.file_ids))
    _require_kind_permissions(db, user, ids, write=True)
    updated = file_keywords.bulk_update(db, user.current_tenant_id, ids, payload.add, payload.remove)
    return FileBulkKeywordsResult(updated=updated)


@router.post("/files/keywords-summary", response_model=list[FileKeywordCount])
def file_keywords_summary(
    payload: FileKeywordsSummaryRequest, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)
):
    """Keywords der Auswahl mit Anzahl (Mehrfachbearbeitung «Entfernen»). POST, weil die Auswahl
    bis zu 200 IDs umfasst; ändert nichts."""
    require_any_permission(user, P.FILES_READ, P.PHOTOS_READ)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    ids = list(dict.fromkeys(payload.file_ids))
    _require_kind_permissions(db, user, ids, write=False)
    return [
        FileKeywordCount(keyword=keyword, count=count)
        for keyword, count in file_keywords.summary(db, user.current_tenant_id, ids)
    ]


@router.patch("/stored-files/{stored_file_id}/name", response_model=StoredFileRenameResult)
def rename_stored_file(
    stored_file_id: uuid.UUID,
    payload: StoredFileRename,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Anzeigename einer Datei ändern (Datei-Detail «Umbenennen»). Ändert nur original_name (und
    den Namen des Dokuments, wenn die Datei dessen aktuelles Original ist) - nie den Speicherpfad.
    Rechte und Mandant wie beim Tag-Speichern."""
    require_any_permission(user, P.FILES_MANAGE, P.PHOTOS_MANAGE)
    stored_file = public_id_service.get_by_public_id(db, StoredFile, stored_file_id, tenant_id=user.current_tenant_id)
    if stored_file is None or user.current_tenant_id is None or stored_file.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Stored file not found")
    access_service.ensure_can_read_stored_file(db, user, stored_file.id, allow_context_grant=False)  # schreibt: nur Rollenrechte
    require_permission(user, P.PHOTOS_MANAGE if (stored_file.mime_type or "").startswith("image/") else P.FILES_MANAGE)
    new_name = _keep_extension(stored_file.original_name, payload.name)
    if len(new_name) > MAX_STORED_FILE_NAME_LENGTH + 12:
        raise HTTPException(status_code=422, detail="Name ist zu lang")
    old_name = stored_file.original_name
    if new_name != old_name:
        stored_file.original_name = new_name
        document_service.sync_display_name_for_original(db, stored_file, new_name)
        audit.log(
            db, action="file.renamed", actor=user, entity_type="stored_file", entity_id=stored_file.id,
            details={"from": old_name, "to": new_name}, commit=False,
        )
        db.commit()
    return StoredFileRenameResult(original_name=new_name)


def _keep_extension(old_name: str, new_name: str) -> str:
    """Die Endung bleibt die der hochgeladenen Datei (Symbol, MIME-Typ und Download passen sonst
    nicht mehr zusammen): fehlt sie im neuen Namen, wird sie angehängt."""
    dot = old_name.rfind(".")
    if dot <= 0 or dot == len(old_name) - 1:
        return new_name
    extension = old_name[dot:]
    if new_name.lower().endswith(extension.lower()):
        return new_name[: len(new_name) - len(extension)] + extension
    return f"{new_name}{extension}"


@router.get("/stored-files/{stored_file_id}/metadata", response_model=StoredFileMetadata)
def get_stored_file_metadata(
    stored_file_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_READ)
    stored_file = public_id_service.get_by_public_id(db, StoredFile, stored_file_id)
    if stored_file is None or user.current_tenant_id is None:
        raise HTTPException(status_code=404, detail="Stored file not found")
    access_service.ensure_can_read_stored_file(db, user, stored_file.id)
    metadata = service.get_stored_file_metadata(
        db, stored_file, settings.storage_root, user.current_tenant_id, can_edit=_can_edit_capture_date(user, stored_file),
        protocol_scope=access_service.protocol_read_scope(db, user),
    )
    if metadata is None:
        raise HTTPException(status_code=404, detail="Keine Metadaten verfügbar")
    if not _sees_location(user):
        metadata = metadata.model_copy(update={"gps": None})
    return _with_upload_job(db, user, stored_file, metadata)


def _with_upload_job(db: Session, user: CurrentUser, stored_file: StoredFile, metadata: StoredFileMetadata) -> StoredFileMetadata:
    """Herkunftsvorgang (Upload-Verlauf) nur, wenn die Person den Vorgang sehen darf. Dazu der
    Ortsname (0260) für alle, die das Foto sehen - nur im Mandanten des Fotos."""
    if stored_file.tenant_id == user.current_tenant_id:
        location = photo_places.places_for_files(db, user.current_tenant_id, [stored_file.id]).get(stored_file.id)
        metadata = metadata.model_copy(update={"place": photo_places.place_payload(location)})
    job = upload_job_service.job_for_file(db, user, stored_file)
    if job is None:
        return metadata
    uploader = db.get(AppUser, job.created_by) if job.created_by is not None and job.actor_kind == "user" else None
    return metadata.model_copy(update={"upload_job": UploadJobOfFile(
        id=job.id, channel=job.channel, created_at=job.created_at, uploaded_count=job.uploaded,
        created_by_name=uploader.display_name if uploader is not None else None, reconstructed=job.reconstructed,
    )})


def _can_edit_capture_date(user: CurrentUser, stored_file: StoredFile) -> bool:
    """Schreibrecht im eigenen Mandanten - nie fuer Fotos eines Partner-Mandanten aus einem
    geteilten Album."""
    return user.can(P.PHOTOS_MANAGE) and stored_file.tenant_id == user.current_tenant_id


@router.patch("/stored-files/{stored_file_id}/capture-date", response_model=StoredFileMetadata)
def update_stored_file_capture_date(
    stored_file_id: uuid.UUID,
    payload: CaptureDateUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Geschaetztes Aufnahmedatum setzen, aendern oder (null) entfernen - der einzige Weg,
    ein vorhandenes Schaetzdatum zu ueberschreiben. Echtes Aufnahmedatum (EXIF) und
    Uploaddatum bleiben unveraendert."""
    require_permission(user, P.PHOTOS_MANAGE)
    stored_file = public_id_service.get_by_public_id(db, StoredFile, stored_file_id)
    if stored_file is None or user.current_tenant_id is None or stored_file.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Stored file not found")
    access_service.ensure_can_read_stored_file(db, user, stored_file.id, allow_context_grant=False)  # schreibt: nur Rollenrechte
    try:
        service.update_estimated_capture_date(db, stored_file, payload.estimated_taken_on, user_id=user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    metadata = service.get_stored_file_metadata(
        db, stored_file, settings.storage_root, user.current_tenant_id, can_edit=True, protocol_scope=access_service.protocol_read_scope(db, user)
    )
    if metadata is None:
        raise HTTPException(status_code=404, detail="Keine Metadaten verfügbar")
    return _with_upload_job(db, user, stored_file, metadata)


def _capture_correction_audit(
    db: Session,
    user: CurrentUser,
    *,
    mode: str,
    outcome,
    requested: int,
    entity_id: int | None = None,
    details: dict | None = None,
) -> None:
    """Ein Audit-Eintrag je Aktion (Einzelbearbeitung oder Mehrfachauswahl), in derselben
    Transaktion wie die Änderung (commit=False)."""
    action = {"set": "photo.capture_date_corrected", "shift": "photo.capture_date_shifted", "reset": "photo.capture_date_reset"}[mode]
    audit.log(
        db,
        action=action,
        actor=user,
        entity_type="stored_file",
        entity_id=entity_id,
        details={
            **(details or {}),
            "requested": requested,
            "updated": len(outcome.updated_ids),
            "unchanged": len(outcome.unchanged_ids),
            "skipped_no_date": len(outcome.skipped_no_date_ids),
            "invalid": len(outcome.invalid_ids),
            "not_found": len(outcome.not_found_ids),
            "no_time_unchanged": len(outcome.no_time_unchanged_ids),
            "date_only": len(outcome.date_only_ids),
            # Nur eigene, tatsächlich geänderte Bilder - nie IDs fremder Mandanten.
            "file_ids": [str(public_id) for public_id in outcome.updated_ids],
        },
        commit=False,
    )


@router.patch("/stored-files/{stored_file_id}/capture-correction", response_model=StoredFileMetadata)
def update_stored_file_capture_correction(
    stored_file_id: uuid.UUID,
    payload: CaptureCorrectionUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Korrigiertes Aufnahmedatum eines Bildes setzen (Datum, optional Uhrzeit) oder mit
    corrected_date null entfernen. Vorrang vor EXIF und Schätzung; das EXIF-Datum bleibt als
    Original gespeichert. Die Anzeige gilt sofort, die Datei zieht der Job
    capture_date_file_sync nach (Migration 0203). Gleiche Regel wie das Schätzdatum: photos.manage, nur Bilder des
    eigenen Mandanten, nie Partner-Fotos aus geteilten Alben."""
    require_permission(user, P.PHOTOS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=404, detail="Stored file not found")
    stored_file = public_id_service.get_by_public_id(db, StoredFile, stored_file_id, tenant_id=user.current_tenant_id)
    if stored_file is None or stored_file.tenant_id != user.current_tenant_id or not (stored_file.mime_type or "").startswith("image/"):
        raise HTTPException(status_code=404, detail="Stored file not found")
    access_service.ensure_can_read_stored_file(db, user, stored_file.id, allow_context_grant=False)  # schreibt: nur Rollenrechte
    _ensure_files_in_scope(db, user, [stored_file.public_id])
    mode = "reset" if payload.corrected_date is None else "set"
    corrected = (
        image_metadata_service.corrected_datetime(payload.corrected_date, payload.corrected_time)
        if payload.corrected_date is not None
        else None
    )
    outcome = service.correct_capture_dates(
        db, user.current_tenant_id, [stored_file.public_id], mode=mode, corrected=corrected, user_id=user.user_id
    )
    if outcome.invalid_ids:
        # Nichts geändert (set_capture_correction prüft vor dem Schreiben)
        raise HTTPException(status_code=422, detail="Ungültiges Aufnahmedatum")
    if outcome.updated_ids:
        details = {"corrected_at": corrected[0].isoformat(), "has_time": corrected[1]} if corrected else {}
        _capture_correction_audit(db, user, mode=mode, outcome=outcome, requested=1, entity_id=stored_file.id, details=details)
    db.commit()
    service.recompute_capture_albums(db, outcome)
    db.refresh(stored_file)
    metadata = service.get_stored_file_metadata(
        db, stored_file, settings.storage_root, user.current_tenant_id, can_edit=True, protocol_scope=access_service.protocol_read_scope(db, user)
    )
    if metadata is None:
        raise HTTPException(status_code=404, detail="Keine Metadaten verfügbar")
    return _with_upload_job(db, user, stored_file, metadata)


def _capture_bulk_prepare(db: Session, user: CurrentUser, payload: FileBulkCaptureDate):
    """Gemeinsame Prüfung für Anwenden und Vorschau: (angefragte IDs, beschreibbare IDs, nicht
    lesbare IDs, Zielwert bei «set», Versatz bei «shift»)."""
    require_permission(user, P.PHOTOS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    ids = list(dict.fromkeys(payload.file_ids))
    if not ids or len(ids) > MAX_CAPTURE_DATE_BULK:
        raise HTTPException(status_code=422, detail=f"Bitte 1 bis {MAX_CAPTURE_DATE_BULK} Bilder auswählen")
    # Reichweite «nur zugewiesene» nur für Bilder des eigenen Mandanten prüfen - fremde IDs
    # dürfen hier keine andere Antwort auslösen als unbekannte (kein Existenz-Orakel, auch ohne RLS).
    own_ids = list(
        db.scalars(select(StoredFile.public_id).where(StoredFile.tenant_id == user.current_tenant_id, StoredFile.public_id.in_(ids)))
    )
    _ensure_files_in_scope(db, user, own_ids)
    # Schreiben braucht dieselbe Leseprüfung wie der Einzel-PATCH: Protokollbilder von Protokollen,
    # die das Konto nicht lesen darf, werden nicht angefasst und kommen wie unbekannte als not_found
    # zurück (Security-Review 1.4.1).
    unreadable: list[uuid.UUID] = []
    documents: list[uuid.UUID] = []
    for stored in db.scalars(select(StoredFile).where(StoredFile.tenant_id == user.current_tenant_id, StoredFile.public_id.in_(own_ids))):
        try:
            access_service.ensure_can_read_stored_file(db, user, stored.id, allow_context_grant=False)
        except HTTPException:
            unreadable.append(stored.public_id)
            continue
        if not (stored.mime_type or "").startswith("image/"):
            documents.append(stored.public_id)
    writable_ids = [file_id for file_id in ids if file_id not in set(unreadable)]
    # Dokumente haben kein Aufnahmedatum: sie bleiben immer unverändert. Als «Dokument» gemeldet
    # werden sie nur, wer die Ablage verwalten darf (gleiche Regel wie bulk-tags) - sonst wie
    # bisher als not_found, damit die Antwort nichts über fremde Bereiche verrät.
    not_images = documents if user.can(P.FILES_MANAGE) else []
    corrected = (
        image_metadata_service.corrected_datetime(payload.corrected_date, payload.corrected_time)
        if payload.mode == "set" and payload.corrected_date is not None
        else None
    )
    if corrected is not None and image_metadata_service.valid_capture_datetime(corrected[0]) is None:
        raise HTTPException(status_code=422, detail="Ungültiges Aufnahmedatum")
    shift = (
        timedelta(days=payload.shift_days, hours=payload.shift_hours, minutes=payload.shift_minutes, seconds=payload.shift_seconds)
        if payload.mode == "shift"
        else None
    )
    return ids, writable_ids, unreadable, corrected, shift, not_images


def _split_not_images(outcome, not_images: list[uuid.UUID]) -> list[uuid.UUID]:
    """Dokumente aus not_found_ids herausnehmen (correct_capture_dates kennt nur Bilder)."""
    if not not_images:
        return []
    documents = set(not_images)
    outcome.not_found_ids = [file_id for file_id in outcome.not_found_ids if file_id not in documents]
    return list(not_images)


@router.post("/files/bulk-capture-date", response_model=FileBulkCaptureDateResult)
def bulk_update_capture_date(
    payload: FileBulkCaptureDate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)
):
    """Mehrfachauswahl der Galerie «Aufnahmedatum ändern»: alle auf ein Datum setzen, um einen
    Versatz verschieben (Tage, Stunden, Minuten; Bilder ohne Aufnahmedatum werden übersprungen und
    gemeldet) oder die Korrektur entfernen. Höchstens MAX_CAPTURE_DATE_BULK Bilder je Aufruf - der
    Browser stückelt grössere Auswahlen und sendet ab dem zweiten Stück die batch_id des ersten
    mit, damit «Rückgängig» alles zusammen zurücknimmt (Migration 0251). Nur Bilder des eigenen
    Mandanten, alles andere (unbekannt, fremd, Partner-Foto, kein Bild) kommt einheitlich als
    not_found zurück. Ein Audit-Eintrag pro Aufruf."""
    ids, writable_ids, unreadable, corrected, shift, not_images = _capture_bulk_prepare(db, user, payload)
    upload_job = upload_job_service.get_visible_job(db, user, payload.upload_job_id) if payload.upload_job_id is not None else None
    details: dict = {}
    if corrected is not None:
        details = {"corrected_at": corrected[0].isoformat(), "has_time": corrected[1]}
    elif shift is not None:
        details = {
            "shift_days": payload.shift_days, "shift_hours": payload.shift_hours,
            "shift_minutes": payload.shift_minutes, "shift_seconds": payload.shift_seconds,
        }
    # Korrektur vor dem Ändern öffnen bzw. aufnehmen (fremde/alte batch_id = 404, nichts geändert)
    batch = capture_change_service.open_batch(
        db, user, batch_id=payload.batch_id, mode=payload.mode, params=details, upload_job_id=upload_job.id if upload_job else None
    )
    outcome = service.correct_capture_dates(
        db, user.current_tenant_id, writable_ids, mode=payload.mode, corrected=corrected, shift=shift, user_id=user.user_id
    )
    skipped_not_images = _split_not_images(outcome, not_images)
    outcome.not_found_ids.extend(unreadable)
    capture_change_service.record(db, batch, outcome.changes)
    batch_id = batch.id
    if not outcome.changes and payload.batch_id is None:
        # Nichts geändert: keine leere Korrektur zum Rückgängigmachen anbieten
        db.delete(batch)
        batch_id = None
    _capture_correction_audit(
        db, user, mode=payload.mode, outcome=outcome, requested=len(ids),
        details={
            **details, "batch_id": str(batch_id) if batch_id else None,
            "upload_job_id": str(upload_job.id) if upload_job else None, "skipped_not_image": len(skipped_not_images),
        },
    )
    db.commit()
    service.recompute_capture_albums(db, outcome)
    return FileBulkCaptureDateResult(
        updated_ids=outcome.updated_ids,
        unchanged_ids=outcome.unchanged_ids,
        skipped_no_date_ids=outcome.skipped_no_date_ids,
        invalid_ids=outcome.invalid_ids,
        not_found_ids=outcome.not_found_ids,
        no_time_unchanged_ids=outcome.no_time_unchanged_ids,
        date_only_ids=outcome.date_only_ids,
        skipped_not_image_ids=skipped_not_images,
        batch_id=batch_id,
    )


@router.post("/files/bulk-capture-date/preview", response_model=FileBulkCaptureDatePreview)
def preview_bulk_capture_date(
    payload: FileBulkCaptureDate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)
):
    """Vorschau zu POST /files/bulk-capture-date: gleiche Eingabe und Prüfungen, schreibt nichts.
    Zähler, Stichprobe vorher/nachher und Auswirkungen (Tageswechsel, Terminwechsel automatisch
    verknüpfter Fotos). POST, weil die Auswahl im Body steht; ändert nichts."""
    _ids, writable_ids, unreadable, corrected, shift, not_images = _capture_bulk_prepare(db, user, payload)
    outcome = service.correct_capture_dates(
        db, user.current_tenant_id, writable_ids, mode=payload.mode, corrected=corrected, shift=shift,
        user_id=user.user_id, dry_run=True,
    )
    skipped_not_images = _split_not_images(outcome, not_images)
    effect = capture_change_service.impacts(db, user.current_tenant_id, outcome.changes)
    return FileBulkCaptureDatePreview(
        will_change=len(outcome.updated_ids),
        unchanged=len(outcome.unchanged_ids),
        no_date=len(outcome.skipped_no_date_ids),
        date_only_unchanged=len(outcome.no_time_unchanged_ids),
        date_only_changed=len(outcome.date_only_ids),
        invalid=len(outcome.invalid_ids),
        not_found=len(outcome.not_found_ids) + len(unreadable),
        not_image=len(skipped_not_images),
        no_date_ids=outcome.skipped_no_date_ids[:MAX_CAPTURE_DATE_BULK],
        samples=capture_change_service.samples(service, outcome.changes),
        **effect,
    )


def _capture_batch_or_404(db: Session, user: CurrentUser, batch_id: uuid.UUID) -> CaptureChangeBatch:
    batch = db.scalar(
        select(CaptureChangeBatch).where(CaptureChangeBatch.id == batch_id, CaptureChangeBatch.tenant_id == user.current_tenant_id)
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="Korrektur nicht gefunden")
    return batch


@router.post("/capture-changes/{batch_id}/undo", response_model=CaptureChangeUndoResult)
def undo_capture_change(batch_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Datumskorrektur rückgängig machen (7.5): je Foto der Wert davor, aber nur, wo seither nichts
    anderes geändert wurde. Gleiche Schreibprüfung je Foto wie die Mehrfachauswahl."""
    require_permission(user, P.PHOTOS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=404, detail="Korrektur nicht gefunden")
    batch = _capture_batch_or_404(db, user, batch_id)
    # Sperren und neu laden (Security-Review 1.6, F-3): ein gleichzeitiges zweites «Rückgängig»
    # wartet hier und sieht danach das gesetzte undone_at statt des vorher geladenen Werts
    db.refresh(batch, with_for_update=True)
    if batch.undone_at is not None:
        raise HTTPException(status_code=409, detail="Diese Korrektur wurde bereits rückgängig gemacht")
    readable = context_visibility_service.readable_assignment_ids(db, user)

    def writable(stored: StoredFile) -> bool:
        if readable is not None and not context_visibility_service.abgabe_scope_allows(db, user, stored.id):
            return False
        try:
            access_service.ensure_can_read_stored_file(db, user, stored.id, allow_context_grant=False)
        except HTTPException:
            return False
        return True

    outcome = capture_change_service.undo(db, batch, user_id=user.user_id, writable=writable)
    audit.log(
        db, action="photo.capture_date_shift_undone", actor=user, entity_type="capture_change_batch", entity_id=None,
        details={
            "batch_id": str(batch.id), "mode": batch.mode, "upload_job_id": str(batch.upload_job_id) if batch.upload_job_id else None,
            "restored": len(outcome.restored_ids), "conflicts": len(outcome.conflict_ids),
            "file_ids": [str(public_id) for public_id in outcome.restored_ids],
        },
        commit=False,
    )
    db.commit()
    if outcome.touched_album_ids:
        photo_album_service.recompute_best_of_for_albums(db, service, outcome.touched_album_ids)
    return CaptureChangeUndoResult(restored_ids=outcome.restored_ids, conflict_ids=outcome.conflict_ids, not_found_ids=outcome.not_found_ids)


@router.get("/capture-changes", response_model=list[CaptureChangeBatchRead])
def list_capture_changes(
    upload_job_id: uuid.UUID = Query(...), db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)
):
    """Datumskorrekturen eines Upload-Vorgangs (Reiter «Datumskorrekturen») mit Rückgängig-Status."""
    require_permission(user, P.PHOTOS_MANAGE)
    job = upload_job_service.get_visible_job(db, user, upload_job_id)
    batches = capture_change_service.list_for_job(db, user.current_tenant_id, job.id)
    remaining = capture_change_service.remaining_items(db, [batch.id for batch in batches])
    users = {
        row.id: row.display_name
        for row in db.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_({b.created_by for b in batches if b.created_by})))
    } if batches else {}
    return [
        CaptureChangeBatchRead(
            id=batch.id, mode=batch.mode, params=batch.params or {}, created_at=batch.created_at,
            created_by_name=users.get(batch.created_by), updated_count=batch.updated_count, remaining=remaining.get(batch.id, 0),
            undone_at=batch.undone_at, can_undo=batch.undone_at is None and remaining.get(batch.id, 0) > 0,
        )
        for batch in batches
    ]


@router.get("/stored-files/{stored_file_id}/thumbnail")
def get_stored_file_thumbnail(
    stored_file_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Small JPEG preview for the "Dateien" grid, so scrolling it stays fluid instead of every
    tile pulling in a full-size original - same access rules as get_stored_file_content."""
    require_permission(user, P.MEETINGS_READ)
    stored_file = public_id_service.get_by_public_id(db, StoredFile, stored_file_id)
    if stored_file is None:
        raise HTTPException(status_code=404, detail="Stored file not found")
    access_service.ensure_can_read_stored_file(db, user, stored_file.id)
    if stored_file.scan_status == "infected":
        raise HTTPException(status_code=403, detail="Datei wurde von der Virenprüfung als infiziert erkannt und ist gesperrt")
    if stored_file.scan_status == "error":
        raise HTTPException(422, "Virenprüfung fehlgeschlagen – Datei ist gesperrt")
    if stored_file.scan_status == "pending":
        raise HTTPException(status_code=425, detail="Datei wird noch auf Schadsoftware geprüft, bitte in Kürze erneut versuchen")
    thumbnail_path = service.ensure_thumbnail(db, stored_file, settings.storage_root)
    if thumbnail_path is None:
        raise HTTPException(status_code=404, detail="Keine Vorschau verfügbar")
    return release_for_stream(db, FileResponse(
        path=thumbnail_path,
        media_type="image/jpeg",
        # Same immutability as get_stored_file_content above - once generated, a thumbnail never
        # changes for a given stored_file id, so it's safe to cache far longer than a day.
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=604800, immutable"},
    ))


@router.get("/stored-files/{stored_file_id}/download")
def download_stored_file(
    stored_file_id: uuid.UUID,
    request: Request = None,  # type: ignore[assignment]  # None nur bei direktem Aufruf in Tests
    part: Literal["image", "video", "both"] = "image",
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Explicit download (Content-Disposition: attachment) of a gallery photo. For a Live Photo
    the caller picks what to get: `image` (the still, default), `video` (the clip as MP4) or `both`
    (a ZIP with IMG_1234.jpg + IMG_1234.mp4 - same names, so it can be uploaded again as a Live
    Photo). An ordinary photo has no clip: `video` is a 404, `both` is just the image."""
    require_permission(user, P.MEETINGS_READ)
    stored_file = public_id_service.get_by_public_id(db, StoredFile, stored_file_id)
    if stored_file is None:
        raise HTTPException(status_code=404, detail="Stored file not found")
    access_service.ensure_can_read_stored_file(db, user, stored_file.id)
    if stored_file.scan_status == "infected":
        raise HTTPException(status_code=403, detail="Datei wurde von der Virenprüfung als infiziert erkannt und ist gesperrt")
    if stored_file.scan_status == "error":
        raise HTTPException(422, "Virenprüfung fehlgeschlagen – Datei ist gesperrt")
    if stored_file.scan_status == "pending":
        raise HTTPException(status_code=425, detail="Datei wird noch auf Schadsoftware geprüft, bitte in Kürze erneut versuchen")

    live_video_id = db.scalar(select(GalleryImage.live_video_stored_file_id).where(GalleryImage.stored_file_id == stored_file.id))
    live_video = db.get(StoredFile, live_video_id) if live_video_id is not None else None
    if live_video is not None and live_video.scan_status != "clean":
        live_video = None
    if part == "video" and live_video is None:
        raise HTTPException(status_code=404, detail="Zu diesem Foto gibt es kein Live-Photo-Video")
    if part != "image":
        # Clip und ZIP nur mit Rollenrechten - eine Kontext-Freigabe (Phase 5) gibt nur das Bild
        access_service.ensure_can_read_stored_file(db, user, stored_file.id, allow_context_grant=False)

    store = get_object_store()
    if part != "video" and not store.exists(MAIN, stored_file.storage_path):
        raise HTTPException(status_code=404, detail="File missing on filesystem")
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}

    # Exportfassung (IMGMETA): geschätztes Aufnahmedatum (und nur in der Datenbank vorhandenes
    # GPS) in einer Kopie - das gespeicherte Original bleibt unverändert. Partner ohne
    # Standortfreigabe (IMGMETA-007): Standort danach aus Bild und Clip entfernen, damit kein GPS
    # aus der Datenbank hineinkommt.
    strip_location = _strips_location(db, user, stored_file)
    export_content: bytes | None = None
    if part != "video":
        needs_export = image_export_service.needs_export_processing(stored_file)
        if needs_export or strip_location:
            original = read_bytes_or_404(MAIN, stored_file.storage_path, detail="File missing on filesystem")
            export_content = image_export_service.export_bytes(stored_file, original) if needs_export else None
            if strip_location:
                export_content = sanitize_image(export_content or original, stored_file.mime_type, _WITHOUT_LOCATION)

    if part == "image" or (part == "both" and live_video is None):
        if export_content is not None:
            return Response(
                content=export_content,
                media_type=stored_file.mime_type,
                headers={**headers, **_content_disposition(stored_file.original_name, True)},
            )
        return release_for_stream(db, object_response(
            request, MAIN, stored_file.storage_path, media_type=stored_file.mime_type,
            filename=stored_file.original_name, attachment=True, headers=headers,
        ))

    if not store.exists(MAIN, live_video.storage_path):
        raise HTTPException(status_code=404, detail="File missing on filesystem")
    cleanup_video = _video_without_metadata(live_video.storage_path) if strip_location else None
    if part == "video":
        if cleanup_video is not None:
            return release_for_stream(db, FileResponse(
                path=cleanup_video,
                media_type="video/mp4",
                filename=live_video.original_name,
                content_disposition_type="attachment",
                headers=headers,
                background=BackgroundTask(cleanup_video.unlink, missing_ok=True),
            ))
        return release_for_stream(db, object_response(
            request, MAIN, live_video.storage_path, media_type="video/mp4",
            filename=live_video.original_name, attachment=True, headers=headers,
        ))

    # Both: JPEG and MP4 are already compressed, so the ZIP just stores them. Built on disk (not
    # in memory) and removed once the response has been sent.
    work_dir = Path(settings.upload_root) / "_staging" / "download"
    work_dir.mkdir(parents=True, exist_ok=True)
    zip_path = work_dir / f"{uuid.uuid4().hex}.zip"
    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as archive:
            if export_content is not None:
                archive.writestr((safe_entry_name(stored_file.original_name) or "foto"), export_content)
            else:
                write_object_to_zip(archive, MAIN, stored_file.storage_path, (safe_entry_name(stored_file.original_name) or "foto"))
            if cleanup_video is not None:
                archive.write(cleanup_video, arcname=(safe_entry_name(live_video.original_name) or "video"))
            else:
                write_object_to_zip(archive, MAIN, live_video.storage_path, (safe_entry_name(live_video.original_name) or "video"))
    except ObjectNotFound as exc:
        zip_path.unlink(missing_ok=True)
        raise HTTPException(status_code=404, detail="File missing on filesystem") from exc
    finally:
        if cleanup_video is not None:
            cleanup_video.unlink(missing_ok=True)
    return release_for_stream(db, FileResponse(
        path=zip_path,
        media_type="application/zip",
        filename=f"{Path(stored_file.original_name).stem}-live.zip",
        content_disposition_type="attachment",
        headers=headers,
        background=BackgroundTask(zip_path.unlink, missing_ok=True),
    ))


ALBUM_INVITES_PER_HOUR = 30


def _files_outside_scope(db: Session, user: CurrentUser, public_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """IDs, die die Reichweite «nur zugewiesene» (Phase 4/5) ausblendet: Abgabe-Dateien nicht
    lesbarer Aufträge."""
    readable = context_visibility_service.readable_assignment_ids(db, user)
    if readable is None or not public_ids:
        return set()
    return set(
        db.scalars(
            select(StoredFile.public_id).where(
                StoredFile.public_id.in_(public_ids), ~context_visibility_service.abgabe_scope_clause(StoredFile.id, readable),
            )
        )
    )


def _ensure_files_in_scope(db: Session, user: CurrentUser, public_ids: list[uuid.UUID]) -> None:
    """Reichweite «nur zugewiesene» auch für Mehrfachaktionen: Abgabe-Dateien nicht lesbarer
    Aufträge sind 404 wie im Einzelabruf."""
    if _files_outside_scope(db, user, public_ids):
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")


def _readable_own_ids(db: Session, user: CurrentUser, public_ids: list[uuid.UUID], *, write: bool) -> set[uuid.UUID]:
    """Die IDs aus ``public_ids``, die Dateien des eigenen Mandanten sind und die das Konto lesen
    darf wie im Einzelabruf (Protokollbilder nur aus lesbaren Protokollen); beim Schreiben zählen
    nur Rollenrechte. Für Mehrfachaktionen, die nicht lesbare wie unbekannte behandeln."""
    readable: set[uuid.UUID] = set()
    rows = db.execute(
        select(StoredFile.id, StoredFile.public_id).where(
            StoredFile.tenant_id == user.current_tenant_id, StoredFile.public_id.in_(public_ids)
        )
    ).all()
    for row in rows:
        try:
            access_service.ensure_can_read_stored_file(db, user, row.id, allow_context_grant=not write)
        except HTTPException:
            continue
        readable.add(row.public_id)
    return readable


def _get_album(db: Session, user: CurrentUser, album_id: uuid.UUID):
    # Lesen; schreibende Album-Routen prüfen photos.manage zusätzlich selbst
    require_permission(user, P.PHOTOS_READ)
    album = photo_album_share_service.get_accessible_album(db, album_id, user.current_tenant_id)
    if album is None:
        raise HTTPException(status_code=404, detail="Album nicht gefunden")
    return album


@router.get("/files/albums", response_model=list[PhotoAlbumRead])
def list_albums(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.PHOTOS_READ)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    entries = photo_album_service.list_albums_with_stats(
        db, service, user.current_tenant_id, readable_assignment_ids=context_visibility_service.readable_assignment_ids(db, user)
    )
    own_album_ids = [entry.album.id for entry in entries if entry.album.tenant_id == user.current_tenant_id]
    foreign_entries = [entry for entry in entries if entry.album.tenant_id != user.current_tenant_id]
    shared_ids = photo_album_share_service.shared_album_ids(db, own_album_ids)
    # Gesammelt statt je Album (vorher drei Abfragen pro Album).
    shares_by_album = photo_album_share_service.list_shares_for_albums(db, own_album_ids, owner_tenant_id=user.current_tenant_id)
    owner_names = dict(
        db.execute(
            select(Tenant.id, Tenant.name).where(Tenant.id.in_({entry.album.tenant_id for entry in foreign_entries}))
        ).all()
    ) if foreign_entries else {}
    own_shares = {
        share.album_id: share
        for share in db.scalars(
            select(PhotoAlbumTenantShare).where(
                PhotoAlbumTenantShare.tenant_id == user.current_tenant_id,
                PhotoAlbumTenantShare.album_id.in_([entry.album.id for entry in foreign_entries]),
            )
        )
    } if foreign_entries else {}
    results = []
    for entry in entries:
        is_owner = entry.album.tenant_id == user.current_tenant_id
        owner_tenant_name = None
        shared_with: list[AlbumTenantShareStatus] = []
        my_share: AlbumMyShareRead | None = None
        if is_owner:
            shared_with = [
                AlbumTenantShareStatus(
                    tenant_public_id=row.tenant_public_id,
                    tenant_name=row.tenant_name,
                    tenant_profile_image_url=row.tenant_profile_image_url,
                    status=row.status,
                    invited_at=row.invited_at,
                    responded_at=row.responded_at,
                    share_location=row.share_location,
                    partner_public_links=row.partner_public_links,
                    partner_photos_public=row.partner_photos_public,
                )
                for row in shares_by_album.get(entry.album.id, [])
            ]
        else:
            owner_tenant_name = owner_names.get(entry.album.tenant_id)
            own_share = own_shares.get(entry.album.id)
            if own_share is not None:
                my_share = AlbumMyShareRead(
                    public_links_allowed=own_share.partner_public_links, my_photos_public=own_share.partner_photos_public
                )
        results.append(
            PhotoAlbumRead(
                id=entry.album.id,
                name=entry.album.name,
                kind=entry.album.kind,
                photo_count=entry.photo_count,
                best_of_count=entry.best_of_count,
                cover_thumbnail_urls=entry.cover_thumbnail_urls,
                owner_tenant_name=owner_tenant_name,
                shared_with=shared_with,
                my_share=my_share,
                is_shared=not is_owner or entry.album.id in shared_ids,
                pending_share_count=entry.pending_share_count,
            )
        )
    return results


@router.get("/files/album-pending-releases", response_model=list[AlbumPendingReleaseRead])
def list_album_pending_releases(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Eigene geteilte Alben mit automatisch einsortierten, noch nicht freigegebenen Fotos -
    fuer den Hinweis auf der Fotos-Seite."""
    require_permission(user, P.PHOTOS_READ)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    return [
        AlbumPendingReleaseRead(album_id=row.album_id, album_name=row.album_name, album_kind=row.album_kind, pending_count=row.pending_count)
        for row in photo_album_share_service.list_pending_releases(
            db, user.current_tenant_id, readable_assignment_ids=context_visibility_service.readable_assignment_ids(db, user)
        )
    ]


@router.post("/files/albums/{album_id}/release", response_model=AlbumReleaseResult)
def release_album_items(
    album_id: uuid.UUID, payload: AlbumReleaseRequest, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)
):
    """Gibt vorgemerkte Fotos eines eigenen Albums fuer die Partner frei - nur der Besitzer,
    denn nur er sieht die vorgemerkten Fotos."""
    require_permission(user, P.PHOTOS_MANAGE)
    album = db.scalar(select(PhotoAlbum).where(PhotoAlbum.id == album_id, PhotoAlbum.tenant_id == user.current_tenant_id))
    if album is None:
        raise HTTPException(status_code=404, detail="Album nicht gefunden")
    released = photo_album_share_service.release_pending(db, album.id, payload.file_ids)
    return AlbumReleaseResult(released=released)


@router.get("/files/upload-target-shared-albums", response_model=list[SharedTargetAlbumRead])
def list_upload_target_shared_albums(
    event_id: uuid.UUID | None = Query(default=None),
    submission_assignment_id: uuid.UUID | None = Query(default=None),
    submission_element_ref: str | None = Query(default=None),
    cycle_config_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Welche bereits geteilten Alben ein Galerie-Upload mit diesem Bezug fuellen wuerde - der
    Upload-Dialog fragt damit, ob die Fotos gleich freigegeben werden sollen."""
    require_permission(user, P.PHOTOS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    target = _resolve_upload_target(
        db,
        user,
        event_id=event_id,
        submission_assignment_id=submission_assignment_id,
        submission_element_ref=submission_element_ref,
        cycle_config_id=cycle_config_id,
    )
    albums = photo_album_service.existing_upload_target_albums(
        db,
        tenant_id=user.current_tenant_id,
        event_id=target.event_id,
        assignment_id=target.assignment_id,
        element_ref=submission_element_ref,
        cycle_config_id=target.cycle_config_id,
    )
    shared = photo_album_share_service.shared_album_ids(db, [album.id for album in albums])
    return [SharedTargetAlbumRead(album_id=album.id, album_name=album.name) for album in albums if album.id in shared]


@router.get("/files/album-share-requests", response_model=list[AlbumShareRequestRead])
def list_album_share_requests(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Offene Einladungen ANDERER Mandanten an den eigenen, fuer die "Anfragen"-Sektion auf
    der Fotos-Seite."""
    require_permission(user, P.PHOTOS_READ)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    return [
        AlbumShareRequestRead(
            album_id=row.album_id, album_name=row.album_name, owner_tenant_name=row.owner_tenant_name, created_at=row.created_at
        )
        for row in photo_album_share_service.list_pending_for_tenant(db, user.current_tenant_id)
    ]


@router.post("/files/albums/{album_id}/shares", status_code=204)
def create_album_share(
    album_id: uuid.UUID, payload: AlbumShareCreate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)
):
    """Laedt einen anderen Mandanten (per public_id) zu diesem - eigenen - Album ein. Nur der
    Besitzer-Mandant darf einladen, daher hier bewusst PhotoAlbum.tenant_id statt _get_album
    (die eingeladene Seite soll das Album ja gerade noch NICHT sehen können)."""
    require_permission(user, P.PHOTOS_MANAGE)
    require_feature(user, F.PHOTO_SHARING, write=True)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    album = db.scalar(select(PhotoAlbum).where(PhotoAlbum.id == album_id, PhotoAlbum.tenant_id == user.current_tenant_id))
    if album is None:
        raise HTTPException(status_code=404, detail="Album nicht gefunden")
    # Einladungen gehen an beliebige Mandanten-IDs - begrenzen gegen Spam (Security-Audit SEC-014).
    enforce_rate_limit(f"album-share-invite:{user.current_tenant_id}", limit=ALBUM_INVITES_PER_HOUR, period_seconds=3600)
    target_tenant = public_id_service.get_by_public_id(db, Tenant, payload.target_tenant_public_id)
    if target_tenant is None:
        raise HTTPException(status_code=404, detail="Kein Mandant mit dieser ID gefunden")
    try:
        photo_album_share_service.invite(
            db, album, target_tenant_id=target_tenant.id, invited_by=user.user_id, share_location=payload.share_location
        )
    except photo_album_share_service.AlbumShareError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.patch("/files/albums/{album_id}/shares/{tenant_public_id}", status_code=204)
def update_album_share(
    album_id: uuid.UUID,
    tenant_public_id: uuid.UUID,
    payload: AlbumShareUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Für einen Partner Standort (GPS) teilen und/oder öffentliche Links auf dieses Album erlauben
    - nur der Besitzer-Mandant (SEC-002)."""
    require_permission(user, P.PHOTOS_MANAGE)
    require_feature(user, F.PHOTO_SHARING, write=True)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    album = db.scalar(select(PhotoAlbum).where(PhotoAlbum.id == album_id, PhotoAlbum.tenant_id == user.current_tenant_id))
    if album is None:
        raise HTTPException(status_code=404, detail="Album nicht gefunden")
    shared_tenant = public_id_service.get_by_public_id(db, Tenant, tenant_public_id)
    if shared_tenant is None:
        raise HTTPException(status_code=404, detail="Mandant nicht gefunden")
    try:
        photo_album_share_service.update_share_settings(
            db,
            album=album,
            tenant_id=shared_tenant.id,
            share_location=payload.share_location,
            partner_public_links=payload.partner_public_links,
        )
    except photo_album_share_service.AlbumShareError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.patch("/files/albums/{album_id}/my-share", status_code=204)
def update_my_album_share(
    album_id: uuid.UUID,
    payload: AlbumMyShareUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Partner-Seite einer Freigabe: eigene Fotos in diesem Album in öffentlichen Links zeigen
    oder nicht (SEC-002). Nur für die Freigabe des eigenen Mandanten."""
    require_permission(user, P.PHOTOS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    try:
        photo_album_share_service.set_my_photos_public(db, album_id=album_id, tenant_id=user.current_tenant_id, value=payload.my_photos_public)
    except photo_album_share_service.AlbumShareError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.post("/files/albums/{album_id}/respond", status_code=204)
def respond_album_share(
    album_id: uuid.UUID,
    payload: AlbumShareRespond,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Beantwortet eine offene Einladung an den EIGENEN Mandanten - keine tenant_public_id im
    Pfad noetig, da nur der eingeladene Mandant selbst (user.current_tenant_id) je antworten
    darf, siehe photo_album_share_service.respond."""
    require_permission(user, P.PHOTOS_MANAGE)
    if payload.accept:
        # Annehmen öffnet mandantenübergreifenden Zugriff - nur mit Feature «Foto-Teilen» (Audit
        # Dateien/Fotos). Ablehnen bleibt immer möglich, damit keine Einladung hängen bleibt.
        require_feature(user, F.PHOTO_SHARING, write=True)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    try:
        photo_album_share_service.respond(
            db, album_id=album_id, tenant_id=user.current_tenant_id, accept=payload.accept, responded_by=user.user_id
        )
    except photo_album_share_service.AlbumShareError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.delete("/files/albums/{album_id}/shares/{tenant_public_id}", status_code=204)
def delete_album_share(
    album_id: uuid.UUID, tenant_public_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)
):
    """Besitzer widerruft eine Freigabe, oder der geteilte Mandant verlaesst sie selbst -
    beides die gleiche Operation, siehe photo_album_share_service.revoke."""
    require_permission(user, P.PHOTOS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    album = db.get(PhotoAlbum, album_id)
    if album is None:
        raise HTTPException(status_code=404, detail="Album nicht gefunden")
    shared_tenant = public_id_service.get_by_public_id(db, Tenant, tenant_public_id)  # nosemgrep: public-id-lookup-without-tenant -- Partner-Mandant der Freigabe, revoke() prüft acting_tenant_id
    if shared_tenant is None:
        raise HTTPException(status_code=404, detail="Mandant nicht gefunden")
    try:
        photo_album_share_service.revoke(
            db,
            album_id=album_id,
            tenant_id=shared_tenant.id,
            acting_tenant_id=user.current_tenant_id,
            album_owner_tenant_id=album.tenant_id,
        )
    except photo_album_share_service.AlbumShareError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None


@router.post("/files/albums", response_model=PhotoAlbumRead, status_code=201)
def create_album(payload: PhotoAlbumCreate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.PHOTOS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    try:
        name = photo_album_service.normalize_album_name(payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    album = PhotoAlbum(tenant_id=user.current_tenant_id, name=name, kind="manual")
    db.add(album)
    db.commit()
    db.refresh(album)
    return PhotoAlbumRead(id=album.id, name=album.name, kind=album.kind)


def _get_own_album(db: Session, user: CurrentUser, album_id: uuid.UUID) -> PhotoAlbum:
    """Album des eigenen Mandanten (Besitzer) - Partner eines geteilten Albums dürfen es weder
    umbenennen noch löschen (E-7). Fremde und unbekannte IDs: gleiche 404 (kein Existenz-Orakel)."""
    require_permission(user, P.PHOTOS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    album = db.scalar(select(PhotoAlbum).where(PhotoAlbum.id == album_id, PhotoAlbum.tenant_id == user.current_tenant_id))
    if album is None:
        raise HTTPException(status_code=404, detail="Album nicht gefunden")
    return album


@router.patch("/files/albums/{album_id}", response_model=PhotoAlbumRead)
def rename_album(
    album_id: uuid.UUID, payload: PhotoAlbumUpdate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)
):
    """Album umbenennen - gleiche Rechte wie beim Anlegen (files.manage), nur der Besitzer-Mandant."""
    album = _get_own_album(db, user, album_id)
    try:
        photo_album_service.rename_album(db, album, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    db.commit()
    db.refresh(album)
    return PhotoAlbumRead(id=album.id, name=album.name, kind=album.kind)


@router.delete("/files/albums/{album_id}", status_code=204)
def delete_album(album_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Album löschen, die Fotos bleiben erhalten (nur die Album-Einträge, Freigaben und Album-Links
    verschwinden). Nur der Besitzer-Mandant und nur manuell angelegte Alben."""
    album = _get_own_album(db, user, album_id)
    try:
        photo_album_service.delete_album(db, album)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    db.commit()


@router.post("/files/albums/{album_id}/items/remove", response_model=PhotoAlbumItemsRemoveResult)
def remove_album_items(
    album_id: uuid.UUID, payload: PhotoAlbumItemsUpdate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)
):
    """Fotos aus einem Album nehmen, ohne sie zu löschen. Der Besitzer darf jedes Foto entfernen,
    ein Partner eines geteilten Albums nur Fotos seines eigenen Vereins (E-7)."""
    require_permission(user, P.PHOTOS_MANAGE)
    album = _get_album(db, user, album_id)
    ids = list(dict.fromkeys(payload.file_ids))
    if not ids or len(ids) > 200:
        raise HTTPException(status_code=422, detail="Bitte 1 bis 200 Fotos auswählen")
    in_album = photo_album_service.album_item_ids(db, album, ids)
    if album.tenant_id != user.current_tenant_id:
        own = {item.id for item in service.list_tenant_files(db, user.current_tenant_id, file_ids=ids, limit=len(ids))}
        in_album &= own
    if in_album != set(ids):
        raise HTTPException(status_code=404, detail="Foto nicht gefunden")
    removed = photo_album_service.remove_items(db, album, ids)
    db.commit()
    photo_album_service.recompute_best_of(db, service, album)
    return PhotoAlbumItemsRemoveResult(removed=removed)


@router.post("/files/albums/{album_id}/items", status_code=204)
def add_album_items(album_id: uuid.UUID, payload: PhotoAlbumItemsUpdate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.PHOTOS_MANAGE)
    album = _get_album(db, user, album_id)
    ids = set(payload.file_ids)
    if not ids or len(ids) > 200:
        raise HTTPException(status_code=422, detail="Bitte 1 bis 200 Fotos auswählen")
    photos = service.list_tenant_files(
        db, user.current_tenant_id, only_images=True, file_ids=list(ids), limit=200,
        readable_assignment_ids=context_visibility_service.readable_assignment_ids(db, user),
    )
    if {photo.id for photo in photos} != ids:
        raise HTTPException(status_code=404, detail="Foto nicht gefunden")
    # Leserecht je Foto wie im Einzelabruf (Protokollbilder nur aus lesbaren Protokollen): ein
    # Album gibt seine Fotos weiter (Partner, Links), also nur Rollenrechte.
    if _readable_own_ids(db, user, list(ids), write=True) != ids:
        raise HTTPException(status_code=404, detail="Foto nicht gefunden")
    if any(photo.scan_status in BLOCKED_SCAN_STATUSES for photo in photos):
        # Gesperrte Fotos (Scan-Fehler) sieht im geteilten Album und im Link ohnehin niemand -
        # gar nicht erst aufnehmen (Audit Dateien/Fotos). "pending" bleibt erlaubt: frisch
        # hochgeladene Fotos werden direkt nach dem Upload ins Album gelegt.
        raise HTTPException(status_code=422, detail="Gesperrte Fotos (Virenprüfung) können nicht in ein Album aufgenommen werden.")
    # Manuell hinzugefuegt = bewusst geteilt (das Frontend warnt vorher bei geteilten Alben).
    photo_album_service.add_items(db, album, list(ids), release=True, manual=True)
    db.commit()
    photo_album_service.recompute_best_of(db, service, album)


@router.patch("/files/albums/{album_id}/items/{file_id}/best", status_code=204)
def set_album_item_best(
    album_id: uuid.UUID,
    file_id: uuid.UUID,
    payload: PhotoAlbumItemBestUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Manually pins a photo in/out of its album's best-of ("Stern") selection, or (with
    best_override: null) hands it back to the automatic ranking - see
    photo_album_service.recompute_best_of."""
    require_permission(user, P.PHOTOS_MANAGE)
    album = _get_album(db, user, album_id)
    try:
        photo_album_service.set_best_override(db, service, album, file_id, payload.best_override)
    except KeyError:
        raise HTTPException(status_code=404, detail="Foto ist nicht in diesem Album") from None


@router.patch("/files/{file_id}/best", status_code=204)
def set_file_best_everywhere(
    file_id: uuid.UUID,
    payload: PhotoAlbumItemBestUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Best-of toggle from the unscoped "Alle Fotos" view (no album in context) - applies
    to every album this tenant's photo belongs to, since is_best lives on PhotoAlbumItem,
    not the photo itself. See set_album_item_best for the album-scoped equivalent."""
    require_permission(user, P.PHOTOS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    touched = photo_album_service.set_best_override_everywhere(
        db, service, user.current_tenant_id, file_id, payload.best_override
    )
    if touched == 0:
        raise HTTPException(
            status_code=422, detail="Dieses Foto gehört zu keinem Album – Best-of ist nur innerhalb eines Albums möglich."
        )


# Höchstalter einer Datei, die «Abbrechen» im Pendenz-Dialog noch zurücknimmt (zusätzlich zur
# Anmeldung der Session): ein Dialog bleibt nicht länger offen.
DISCARD_UPLOAD_MAX_AGE = timedelta(hours=12)
DISCARD_CLOCK_TOLERANCE = timedelta(minutes=5)


def _discardable_upload_ids(db: Session, user: CurrentUser, public_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """Nur frisch von dieser Person in dieser Sitzung hochgeladene Dateien ohne jeden Bezug:
    eigener Mandant, created_by = Person, nach Anmeldung bzw. höchstens 12 h alt, keine
    Pendenz-Verknüpfung, kein Termin/Zyklus/Abgabe-Bezug, in keinem Album, keinem Freigabelink. Alles andere wird
    stillschweigend übergangen (gleiche Antwort wie eine unbekannte ID)."""
    from app.models.entities import ProtocolTodoFile, ShareLinkFile

    since = datetime.now(UTC) - DISCARD_UPLOAD_MAX_AGE
    auth_time = user.auth_time
    if auth_time is not None and auth_time.tzinfo is None:
        auth_time = auth_time.replace(tzinfo=UTC)
    if auth_time is not None and auth_time > since:
        # Kleine Toleranz: created_at ist die DB-Zeit (Transaktionsbeginn), auth_time die App-Zeit
        since = max(since, auth_time - DISCARD_CLOCK_TOLERANCE)
    rows = db.execute(
        select(StoredFile.public_id)
        .join(GalleryImage, GalleryImage.stored_file_id == StoredFile.id)
        .where(
            StoredFile.tenant_id == user.current_tenant_id,
            StoredFile.public_id.in_(public_ids),
            StoredFile.created_by == user.user_id,
            StoredFile.created_at >= since,
            StoredFile.deleted_at.is_(None),
            GalleryImage.event_id.is_(None),
            GalleryImage.cycle_config_id.is_(None),
            GalleryImage.submission_assignment_id.is_(None),
            ~select(ProtocolTodoFile.stored_file_id).where(ProtocolTodoFile.stored_file_id == StoredFile.id).exists(),
            ~select(PhotoAlbumItem.file_id).where(PhotoAlbumItem.file_id == StoredFile.public_id).exists(),
            ~select(ShareLinkFile.file_id).where(ShareLinkFile.file_id == StoredFile.public_id).exists(),
        )
    ).scalars()
    return list(dict.fromkeys(rows))


@router.post("/files/discard-uploads", response_model=FileDiscardUploadsResult)
def discard_unlinked_uploads(payload: FileDiscardUploadsRequest, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """«Abbrechen» im Pendenz-Dialog: dort hochgeladene, nicht mit «Speichern» verknüpfte Dateien
    in den Papierkorb (wiederherstellbar, file_trash_service mit seinen Löschrechten). Nie schon
    vorhandene, verknüpfte oder fremde Dateien - siehe _discardable_upload_ids."""
    require_any_permission(user, P.FILES_MANAGE, P.PHOTOS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    ids = _discardable_upload_ids(db, user, list(dict.fromkeys(payload.file_ids)))
    if not ids:
        return FileDiscardUploadsResult(discarded=[])
    trashed, _errors = file_trash_service.trash_files(db, user, ids, hidden_ids=_files_outside_scope(db, user, ids))
    if trashed:
        # Upload-Verlauf: die Items dieser Dateien gelten als «verworfen» (Abbrechen in der Pendenz)
        trashed_ids = list(
            db.scalars(
                select(StoredFile.id)
                .where(StoredFile.tenant_id == user.current_tenant_id, StoredFile.public_id.in_(trashed))
                .execution_options(include_trashed=True)
            )
        )
        upload_job_service.discard_files(db, user.current_tenant_id, trashed_ids)
        db.commit()
    return FileDiscardUploadsResult(discarded=trashed)


@router.post("/files/bulk-delete", response_model=FileBulkDeleteResult)
def bulk_delete_files(payload: FileBulkDelete, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Multi-select "Löschen" auf der Fotos-Seite und "Nur beste behalten" im Ähnliche-Tab -
    legt die Fotos in den Papierkorb (file_trash_service), nur Direkt-Uploads; andere Quellen
    werden als Fehler zurückgemeldet. Endgültig löscht erst der Papierkorb."""
    require_permission(user, P.PHOTOS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    ids = list(dict.fromkeys(payload.file_ids))
    if not ids or len(ids) > 200:
        raise HTTPException(status_code=422, detail="Bitte 1 bis 200 Dateien auswählen")
    # Teil-Erfolg je Datei: ausserhalb der Reichweite wie eine unbekannte ID melden, nicht mit 404
    # für die ganze Anfrage (sonst unterscheidet die Antwort fremde Abgabe-Dateien von unbekannten).
    trashed, errors = file_trash_service.trash_files(db, user, ids, hidden_ids=_files_outside_scope(db, user, ids))
    return FileBulkDeleteResult(deleted_ids=trashed, errors=errors)


# ── Papierkorb (Migration 0199, services/file_trash_service.py) ──────────────────────────────


def _require_trash_access(user: CurrentUser) -> None:
    """Papierkorb sieht, wer löschen darf: photos.manage (Fotos/Videos) oder files.manage (übrige
    Dateien). Welche Einträge, entscheidet file_trash_service je Datei."""
    require_any_permission(user, P.FILES_MANAGE, P.PHOTOS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")


@router.get("/files/trash", response_model=FileTrashList)
def list_trash(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    _require_trash_access(user)
    now = datetime.now(UTC)
    entries = file_trash_service.list_trash(db, user)
    _count, total_bytes = file_trash_service.summary(db, user)
    items = [
        FileTrashItem(
            id=entry.stored_file.public_id,
            original_name=entry.stored_file.original_name,
            mime_type=entry.stored_file.mime_type,
            file_size_bytes=entry.stored_file.file_size_bytes,
            is_image=(entry.stored_file.mime_type or "").startswith("image/"),
            thumbnail_url=(
                f"/api/files/trash/{entry.stored_file.public_id}/thumbnail"
                if (entry.stored_file.mime_type or "").startswith("image/") and entry.stored_file.scan_status == "clean"
                else None
            ),
            deleted_at=entry.stored_file.deleted_at,
            deleted_by_name=entry.deleted_by_name,
            purge_at=entry.purge_at,
            days_left=max(0, math.ceil((entry.purge_at - now).total_seconds() / 86400)),
        )
        for entry in entries
    ]
    return FileTrashList(items=items, total_bytes=total_bytes, retention_days=TRASH_RETENTION.days)


@router.post("/files/trash", response_model=FileTrashActionResult)
def move_to_trash(payload: FileTrashAction, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Löschen einer Datei auf der Dateien-Seite bzw. eines Fotos in der Ansicht: in den Papierkorb."""
    _require_trash_access(user)
    ids = list(dict.fromkeys(payload.file_ids))
    # Teil-Erfolg je Datei: ausserhalb der Reichweite wie eine unbekannte ID melden, nicht mit 404
    # für die ganze Anfrage (sonst unterscheidet die Antwort fremde Abgabe-Dateien von unbekannten).
    trashed, errors = file_trash_service.trash_files(db, user, ids, hidden_ids=_files_outside_scope(db, user, ids))
    return FileTrashActionResult(file_ids=trashed, errors=errors)


@router.post("/files/trash/restore", response_model=FileTrashActionResult)
def restore_from_trash(payload: FileTrashAction, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    _require_trash_access(user)
    restored, errors = file_trash_service.restore(db, user, list(dict.fromkeys(payload.file_ids)))
    return FileTrashActionResult(file_ids=restored, errors=errors)


@router.post("/files/trash/purge", response_model=FileTrashActionResult)
def purge_from_trash(payload: FileTrashAction, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """«Endgültig löschen»: Speicherobjekt, Vorschaubild, Dokument, Album-/Linkeinträge, Journal."""
    _require_trash_access(user)
    try:
        purged, errors = file_trash_service.purge(db, user, list(dict.fromkeys(payload.file_ids)))
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Dateien konnten nicht endgültig gelöscht werden") from exc
    return FileTrashActionResult(file_ids=purged, errors=errors)


@router.post("/files/trash/empty", response_model=FileTrashEmptyResult)
def empty_trash(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    _require_trash_access(user)
    try:
        purged = file_trash_service.empty(db, user)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Papierkorb konnte nicht geleert werden") from exc
    return FileTrashEmptyResult(purged=purged)


@router.get("/files/trash/{file_id}/thumbnail")
def get_trash_thumbnail(file_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Vorschau eines Fotos im Papierkorb - nur für Konten, die es dort sehen (sonst 404)."""
    _require_trash_access(user)
    with include_trashed(db):
        stored_file = file_trash_service.get_trashed(db, user, file_id)
        if stored_file is None or stored_file.scan_status != "clean" or not (stored_file.mime_type or "").startswith("image/"):
            raise HTTPException(status_code=404, detail="Datei nicht im Papierkorb")
        thumbnail_path = service.ensure_thumbnail(db, stored_file, settings.storage_root)
    if thumbnail_path is None:
        raise HTTPException(status_code=404, detail="Keine Vorschau verfügbar")
    return release_for_stream(db, FileResponse(
        path=thumbnail_path,
        media_type="image/jpeg",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    ))


@router.post("/files/bulk-tags", status_code=204)
def bulk_update_file_tags(payload: FileBulkTagsUpdate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Multi-select "Tags hinzufügen" auf der Fotos-Seite."""
    require_permission(user, P.PHOTOS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    ids = list(dict.fromkeys(payload.file_ids))
    if not ids or len(ids) > 200:
        raise HTTPException(status_code=422, detail="Bitte 1 bis 200 Dateien auswählen")
    _ensure_files_in_scope(db, user, ids)
    # Wie das Einzel-Tag (Leserecht je Datei, nur Rollenrechte): nicht lesbare Dateien, z. B.
    # Protokollbilder nicht lesbarer Protokolle, bleiben unverändert wie unbekannte IDs - vor der
    # Dateiart-Prüfung, damit deren 403 die Existenz nicht verrät.
    readable = _readable_own_ids(db, user, ids, write=True)
    ids = [file_id for file_id in ids if file_id in readable]
    if not ids:
        return
    # Dokumente (keine Bilder) taggt nur, wer die Ablage verwalten darf (Phase 3, wie beim Einzel-Tag)
    mimes = db.scalars(select(StoredFile.mime_type).where(StoredFile.tenant_id == user.current_tenant_id, StoredFile.public_id.in_(ids)))
    if any(not (mime or "").startswith("image/") for mime in mimes):
        require_permission(user, P.FILES_MANAGE)
    service.bulk_update_tags(db, user.current_tenant_id, ids, payload.add_tags, payload.remove_tags)


@router.post("/files/bulk-event-link", response_model=FileBulkEventLinkResult)
def bulk_link_event(payload: FileBulkEventLink, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Mehrfachauswahl «Termin zuordnen» (Upload-Verlauf): Fotos fest mit einem Termin verknüpfen
    oder an die automatische Zuordnung zurückgeben. Termin nur aus dem eigenen Mandanten (sonst
    404), je Datei dieselbe Schreibprüfung wie bulk-tags; nicht beschreibbare wie unbekannte."""
    require_permission(user, P.PHOTOS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    event = None
    if payload.event_id is not None:
        event = public_id_service.get_by_public_id(db, Event, payload.event_id, tenant_id=user.current_tenant_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Termin nicht gefunden")
    ids = list(dict.fromkeys(payload.file_ids))
    hidden = _files_outside_scope(db, user, ids)
    readable = _readable_own_ids(db, user, [file_id for file_id in ids if file_id not in hidden], write=True)
    rows = db.execute(
        select(GalleryImage, StoredFile)
        .join(StoredFile, StoredFile.id == GalleryImage.stored_file_id)
        .where(
            GalleryImage.tenant_id == user.current_tenant_id, StoredFile.tenant_id == user.current_tenant_id,
            StoredFile.public_id.in_(list(readable)), StoredFile.mime_type.like("image/%"),
        )
    ).all()
    updated: list[uuid.UUID] = []
    relink: list[StoredFile] = []
    for gallery_image, stored in rows:
        if payload.mode == "set":
            gallery_image.event_id, gallery_image.event_auto_linked = event.id, False
        else:
            gallery_image.event_id, gallery_image.event_auto_linked = None, False
            relink.append(stored)
        updated.append(stored.public_id)
    photo_event_link_service.resync_photos_after_date_change(db, user.current_tenant_id, relink)
    audit.log(
        db, action="photo.event_linked", actor=user, entity_type="stored_file", entity_id=None,
        details={"mode": payload.mode, "event_id": event.id if event else None, "file_ids": [str(i) for i in updated]},
        commit=False,
    )
    db.commit()
    done = set(updated)
    return FileBulkEventLinkResult(updated_ids=updated, not_found_ids=[file_id for file_id in ids if file_id not in done])
