import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects.postgresql import insert
from app.models.entities import CycleConfig, Event, PhotoAlbum, PhotoAlbumItem, SubmissionAssignment
from app.schemas.files import PhotoAlbumCreate, PhotoAlbumItemBestUpdate, PhotoAlbumRead, PhotoAlbumItemsUpdate
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.core.db import get_db
from app.core.config import settings
from app.core.security import CurrentUser, get_current_user, require_reader, require_writer
from app.models import ProtocolElementBlock, ProtocolImage, StoredFile
from app.schemas.files import (
    FileBulkDelete,
    FileBulkDeleteResult,
    FileBulkTagsUpdate,
    FileOverviewItem,
    FileOverviewSource,
    FileStats,
    GalleryUploadResult,
    PhotoAnalysisJobCreate,
    PhotoAnalysisJobRead,
    PhotoAnalysisProgress,
    SimilarityGroup,
    StoredFileMetadata,
    StoredFileTagsUpdate,
)
from app.schemas.protocol import ProtocolImageRead
from app.services import photo_album_service, public_id_service
from app.services.access_service import AccessService
from app.services.file_service import MAX_UPLOAD_BYTES, MAX_ZIP_TOTAL_BYTES, FileService, _safe_storage_path, extract_image_files_from_zip
from app.services.submission_service import SubmissionService, _element_ref, _parse_element_ref

router = APIRouter()
service = FileService()
access_service = AccessService()
submission_service = SubmissionService()

# Ganzer Batch (Summe aller akzeptierten Dateien eines Upload-Requests, ausserhalb von
# ZIPs - deren eigener Grenzwert ist MAX_ZIP_TOTAL_BYTES): grösszügiger als eine einzelne
# Datei, aber trotzdem endlich - selbes Limit-Muster wie beim Word-Import-Batch-Upload.
MAX_GALLERY_UPLOAD_BATCH_FILES = 50
MAX_GALLERY_UPLOAD_BATCH_BYTES = 150 * 1024 * 1024


async def _read_upload_within_limit(file: UploadFile, max_bytes: int) -> bytes | None:
    """Rejects an oversized upload using Starlette's already-known `.size` (populated by
    the multipart parser before the route runs) instead of buffering the whole thing into a
    `bytes` object first just to measure it. Returns None if too large. Mirrors
    word_import.py's helper of the same name - kept local rather than shared since routes
    don't otherwise import each other's private helpers in this codebase."""
    if file.size is not None and file.size > max_bytes:
        return None
    content = await file.read()
    if len(content) > max_bytes:
        return None
    return content


@router.get("/files", response_model=list[FileOverviewItem])
def list_files(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=60, ge=1, le=200),
    source: FileOverviewSource | None = Query(default=None),
    album_id: uuid.UUID | None = Query(default=None),
    only_images: bool = Query(default=False),
    exclude_images: bool = Query(default=False),
    search: str | None = Query(default=None),
    tags: list[str] | None = Query(default=None),
    sort_by: Literal[
        "created_at", "original_name", "file_size_bytes", "sharpness_score", "exposure_score", "face_quality_score", "group_date"
    ] = Query(default="created_at"),
    sort_dir: Literal["asc", "desc"] = Query(default="desc"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Alle vom Mandanten hochgeladenen Dateien (Protokoll-Bilder, Word-Import-Quelldokumente,
    Abgabebox-Uploads) fuer die "Dateien"- und "Fotos"-Uebersichtsseiten (only_images/
    exclude_images trennen die beiden). Gleiche Rolle wie "Abgaben" (require_writer): dies
    ist eine mandantenweite Aggregatsicht ueber alle Protokolle hinweg, nicht scopebar auf
    die feingranulare Pro-Protokoll-Leserechte-Pruefung von ensure_can_read_stored_file."""
    require_writer(user)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    file_ids = None
    best_by_id: dict[uuid.UUID, bool] = {}
    if album_id is not None:
        _get_album(db, user, album_id)
        item_rows = list(db.execute(select(PhotoAlbumItem.file_id, PhotoAlbumItem.is_best).where(PhotoAlbumItem.album_id == album_id)))
        file_ids = [row.file_id for row in item_rows]
        best_by_id = {row.file_id: row.is_best for row in item_rows}
    items = service.list_tenant_files(
        db,
        user.current_tenant_id,
        skip=skip,
        limit=limit,
        source=source,
        only_images=only_images,
        exclude_images=exclude_images,
        search=search,
        tags=tags,
        sort_by=sort_by,
        sort_dir=sort_dir,
        file_ids=file_ids,
    )
    if album_id is not None:
        for item in items:
            item.is_best = best_by_id.get(item.id, False)
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
    require_writer(user)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    return service.list_distinct_tags(db, user.current_tenant_id, query=query, limit=limit)


@router.get("/files/analysis-progress", response_model=PhotoAnalysisProgress)
def get_analysis_progress(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Tenant-wide summary behind the Fotos page's "Foto-Analyse läuft" progress bar and
    the "Analyse läuft · N Bilder" pill."""
    require_writer(user)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    return service.analysis_progress(db, user.current_tenant_id)


@router.get("/files/stats", response_model=FileStats)
def get_file_stats(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Backs the Dateien page's Dokumente/Fotos/Speicher stat cards."""
    require_writer(user)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    return service.file_stats(db, user.current_tenant_id)


@router.get("/files/similarity-groups", response_model=list[SimilarityGroup])
def list_similarity_groups(
    source: FileOverviewSource | None = Query(default=None),
    album_id: uuid.UUID | None = Query(default=None),
    search: str | None = Query(default=None),
    tags: list[str] | None = Query(default=None),
    min_size: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Photo-culling Phase 2: clustert die (per Filter eingegrenzten) Bilder des Mandanten
    nach visueller Ähnlichkeit (Perceptual Hash) und markiert pro Gruppe das nach Schärfe/
    Belichtung beste Bild. Gleiche Filter wie GET /files, aber immer nur Bilder und ohne
    Pagination - siehe FileService.group_similar_gallery_images für die Grössenbeschränkung.
    min_size=2 (die "Ähnliche"-Tab im Frontend) blendet Einzelbilder ohne ähnliches
    Gegenstück aus - der Default 1 behält das bisherige Verhalten für andere Aufrufer bei."""
    require_writer(user)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    file_ids = None
    if album_id is not None:
        _get_album(db, user, album_id)
        file_ids = list(db.scalars(select(PhotoAlbumItem.file_id).where(PhotoAlbumItem.album_id == album_id)))
    return service.group_similar_gallery_images(
        db,
        user.current_tenant_id,
        source=source,
        search=search,
        tags=tags,
        file_ids=file_ids,
        min_size=min_size,
    )


def _job_to_read(job) -> PhotoAnalysisJobRead:
    return PhotoAnalysisJobRead(
        id=job.id,
        status=job.status,
        image_count=len(job.stored_file_ids),
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error=job.error,
    )


@router.post("/files/analysis-jobs", response_model=PhotoAnalysisJobRead, status_code=status.HTTP_201_CREATED)
def create_analysis_job(
    payload: PhotoAnalysisJobCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Photo-culling Phase 3: queues a batch of (filtered) images for the separate
    photo-analysis-worker container to score. Returns immediately with status "queued" -
    poll GET .../{id} for progress."""
    require_writer(user)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    job = service.create_analysis_job(
        db,
        user.current_tenant_id,
        source=payload.source,
        search=payload.search,
        tags=payload.tags,
        file_ids=payload.file_ids,
        requested_by=user.user_id,
    )
    return _job_to_read(job)


@router.get("/files/analysis-jobs/{job_id}", response_model=PhotoAnalysisJobRead)
def get_analysis_job(job_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_writer(user)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    job = service.get_analysis_job(db, user.current_tenant_id, job_id)
    return _job_to_read(job)


@router.post("/files/gallery-uploads", response_model=GalleryUploadResult, status_code=status.HTTP_201_CREATED)
async def upload_gallery_images(
    files: list[UploadFile] = File(...),
    tags: str | None = Form(default=None),
    # Optional target picker: at most one of event_id, (submission_assignment_id +
    # submission_element_ref) or cycle_config_id - the batch then lands in that Termin's/
    # Abgabe-Element's/Zyklus' auto-album(s) too (see FileService.save_gallery_uploads).
    event_id: uuid.UUID | None = Form(default=None),
    submission_assignment_id: uuid.UUID | None = Form(default=None),
    submission_element_ref: str | None = Form(default=None),
    cycle_config_id: uuid.UUID | None = Form(default=None),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Direkter Bild-Upload fuer die "Fotos"-Galerie (nicht an ein Protokoll/Word-Import/
    Abgabe gebunden) - unterstuetzt einzelne Bilddateien und .zip-Archive, aus denen nur
    Bilddateien uebernommen werden (siehe extract_image_files_from_zip), jeweils durch
    dieselbe Pipeline wie jeder andere Upload in dieser App: Magic-Byte-Pruefung,
    Grössenlimit, Virenscan (siehe FileService.save_gallery_uploads)."""
    require_writer(user)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    if len(files) > MAX_GALLERY_UPLOAD_BATCH_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"Zu viele Dateien in einem Batch (maximal {MAX_GALLERY_UPLOAD_BATCH_FILES})",
        )

    if sum([event_id is not None, submission_assignment_id is not None, cycle_config_id is not None]) > 1:
        raise HTTPException(status_code=422, detail="Nur ein Zielbezug (Termin, Abgabe-Element oder Zyklus) gleichzeitig erlaubt")
    if (submission_assignment_id is None) != (submission_element_ref is None):
        raise HTTPException(status_code=422, detail="Abgabe und Abgabe-Element muessen zusammen angegeben werden")

    upload_event_id: int | None = None
    upload_assignment: SubmissionAssignment | None = None
    upload_element_label: str | None = None
    upload_cycle_config: CycleConfig | None = None

    if event_id is not None:
        upload_event_id = public_id_service.resolve_internal_id(db, Event, event_id, tenant_id=user.current_tenant_id)
        if upload_event_id is None:
            raise HTTPException(status_code=404, detail="Termin nicht gefunden")
    elif submission_assignment_id is not None:
        assignment_id = public_id_service.resolve_internal_id(db, SubmissionAssignment, submission_assignment_id, tenant_id=user.current_tenant_id)
        if assignment_id is None:
            raise HTTPException(status_code=404, detail="Abgabe nicht gefunden")
        upload_assignment = db.get(SubmissionAssignment, assignment_id)
        try:
            parsed_event_id, parsed_list_entry_id = _parse_element_ref(db, submission_element_ref)
        except ValueError:
            raise HTTPException(status_code=422, detail="Ungueltige Abgabe-Element-Referenz") from None
        # _parse_element_ref resolves the event/list-entry public id without a tenant
        # filter (see its docstring) - only trust it once it's confirmed as one of *this*
        # (already tenant-scoped) assignment's own elements, otherwise a writer could point
        # event_id at another tenant's event and leak this upload into that tenant's Zyklus
        # album.
        elements = submission_service._resolve_raw_elements(db, upload_assignment)
        match = next((e for e in elements if e["event_id"] == parsed_event_id and e["list_entry_id"] == parsed_list_entry_id), None)
        if match is None:
            raise HTTPException(status_code=404, detail="Abgabe-Element nicht gefunden")
        upload_event_id = match["event_id"]
        upload_element_label = match["label"]
    elif cycle_config_id is not None:
        cycle_config_id_internal = public_id_service.resolve_internal_id(db, CycleConfig, cycle_config_id, tenant_id=user.current_tenant_id)
        if cycle_config_id_internal is None:
            raise HTTPException(status_code=404, detail="Zyklus nicht gefunden")
        upload_cycle_config = db.get(CycleConfig, cycle_config_id_internal)

    tag_list = [tag.strip() for tag in (tags or "").split(",") if tag.strip()]

    file_payloads: list[tuple[str, bytes]] = []
    errors: list[str] = []
    batch_bytes = 0
    for file in files:
        name = file.filename or ""
        if batch_bytes > MAX_GALLERY_UPLOAD_BATCH_BYTES:
            errors.append(f"{name or 'Datei'}: übersprungen - Gesamtgrösse des Batches überschritten")
            continue
        if name.lower().endswith(".zip"):
            zip_bytes = await _read_upload_within_limit(file, MAX_ZIP_TOTAL_BYTES)
            if zip_bytes is None:
                errors.append(f"{name}: ZIP-Datei zu gross (maximal {MAX_ZIP_TOTAL_BYTES // 1024 // 1024} MB)")
                continue
            matched, notes = extract_image_files_from_zip(zip_bytes)
            file_payloads.extend(matched)
            batch_bytes += sum(len(content) for _, content in matched)
            errors.extend(f"{name}: {note}" for note in notes)
            continue
        content = await _read_upload_within_limit(file, MAX_UPLOAD_BYTES)
        if content is None:
            errors.append(f"{name or 'Datei'}: zu gross (maximal {MAX_UPLOAD_BYTES // 1024 // 1024} MB)")
            continue
        file_payloads.append((name, content))
        batch_bytes += len(content)

    items, save_errors = service.save_gallery_uploads(
        db,
        tenant_id=user.current_tenant_id,
        files=file_payloads,
        tags=tag_list,
        created_by=user.user_id,
        upload_event_id=upload_event_id,
        upload_assignment=upload_assignment,
        upload_element_ref=submission_element_ref,
        upload_element_label=upload_element_label,
        upload_cycle_config=upload_cycle_config,
    )
    return GalleryUploadResult(items=items, errors=errors + save_errors)


@router.get("/protocol-element-blocks/{protocol_element_block_id}/images", response_model=list[ProtocolImageRead])
def list_images(
    protocol_element_block_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    block = public_id_service.get_by_public_id(db, ProtocolElementBlock, protocol_element_block_id)
    if block is None:
        raise HTTPException(status_code=404, detail="Protocol element block not found")
    access_service.ensure_can_read_protocol_block(db, user, block.id)
    return service.list_protocol_images(db, block.id)


@router.post("/protocol-element-blocks/{protocol_element_block_id}/images", response_model=ProtocolImageRead)
async def upload_image(
    protocol_element_block_id: uuid.UUID,
    file: UploadFile,
    title: str | None = Form(default=None),
    caption: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    protocol_element_block = public_id_service.get_by_public_id(db, ProtocolElementBlock, protocol_element_block_id)
    if protocol_element_block is None:
        raise HTTPException(status_code=404, detail="Protocol element block not found")
    access_service.ensure_can_read_protocol_block(db, user, protocol_element_block.id)
    try:
        return await service.save_protocol_image(
            db,
            protocol_element_block=protocol_element_block,
            file=file,
            title=title,
            caption=caption,
            created_by=user.user_id,
        )
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Image could not be uploaded") from exc


@router.delete("/protocol-images/{image_id}", response_model=dict[str, str])
def delete_image(
    image_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    protocol_image = public_id_service.get_by_public_id(db, ProtocolImage, image_id)
    if protocol_image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    access_service.ensure_can_read_protocol_block(db, user, protocol_image.protocol_element_block_id)
    try:
        deleted = service.delete_protocol_image(db, protocol_image.id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Image could not be deleted") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Image not found")
    return {"message": "Image deleted"}


@router.get("/stored-files/{stored_file_id}/content")
def get_stored_file_content(
    stored_file_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    stored_file = public_id_service.get_by_public_id(db, StoredFile, stored_file_id)
    if stored_file is None:
        raise HTTPException(status_code=404, detail="Stored file not found")
    access_service.ensure_can_read_stored_file(db, user, stored_file.id)
    if stored_file.scan_status == "infected":
        raise HTTPException(status_code=403, detail="Datei wurde von der Virenprüfung als infiziert erkannt und ist gesperrt")
    if stored_file.scan_status == "pending":
        raise HTTPException(status_code=425, detail="Datei wird noch auf Schadsoftware geprüft, bitte in Kürze erneut versuchen")
    file_path = _safe_storage_path(settings.storage_root, stored_file.storage_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File missing on filesystem")
    # SECURITY: set nosniff so a browser never MIME-sniffs the content and renders it
    # inline against our wishes, mirroring submission_assignments.get_submission_file_content.
    # inline also covers images now, not just PDF (audit finding, 2026-08-25) - protocol
    # images are rendered directly via <img src> pointing at this same endpoint (see
    # focused-element-editor.tsx's LightboxImage/content_url), which "attachment" would
    # otherwise force browsers to treat as a download instead of image data to paint.
    # nosniff already closes the MIME-confusion risk "attachment" was guarding against
    # for a real image mime type.
    is_inline_safe = stored_file.mime_type == "application/pdf" or (stored_file.mime_type or "").startswith("image/")
    return FileResponse(
        path=file_path,
        media_type=stored_file.mime_type,
        filename=stored_file.original_name,
        content_disposition_type="inline" if is_inline_safe else "attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.patch("/stored-files/{stored_file_id}/tags", response_model=list[str])
def update_stored_file_tags(
    stored_file_id: uuid.UUID,
    payload: StoredFileTagsUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    stored_file = public_id_service.get_by_public_id(db, StoredFile, stored_file_id)
    if stored_file is None:
        raise HTTPException(status_code=404, detail="Stored file not found")
    access_service.ensure_can_read_stored_file(db, user, stored_file.id)
    return service.update_stored_file_tags(db, stored_file, payload.tags)


@router.get("/stored-files/{stored_file_id}/metadata", response_model=StoredFileMetadata)
def get_stored_file_metadata(
    stored_file_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    stored_file = public_id_service.get_by_public_id(db, StoredFile, stored_file_id)
    if stored_file is None or user.current_tenant_id is None:
        raise HTTPException(status_code=404, detail="Stored file not found")
    access_service.ensure_can_read_stored_file(db, user, stored_file.id)
    metadata = service.get_stored_file_metadata(db, stored_file, settings.storage_root, user.current_tenant_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="Keine Metadaten verfügbar")
    return metadata


@router.get("/stored-files/{stored_file_id}/thumbnail")
def get_stored_file_thumbnail(
    stored_file_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Small JPEG preview for the "Dateien" grid, so scrolling it stays fluid instead of every
    tile pulling in a full-size original - same access rules as get_stored_file_content."""
    require_reader(user)
    stored_file = public_id_service.get_by_public_id(db, StoredFile, stored_file_id)
    if stored_file is None:
        raise HTTPException(status_code=404, detail="Stored file not found")
    access_service.ensure_can_read_stored_file(db, user, stored_file.id)
    if stored_file.scan_status == "infected":
        raise HTTPException(status_code=403, detail="Datei wurde von der Virenprüfung als infiziert erkannt und ist gesperrt")
    if stored_file.scan_status == "pending":
        raise HTTPException(status_code=425, detail="Datei wird noch auf Schadsoftware geprüft, bitte in Kürze erneut versuchen")
    thumbnail_path = service.ensure_thumbnail(db, stored_file, settings.storage_root)
    if thumbnail_path is None:
        raise HTTPException(status_code=404, detail="Keine Vorschau verfügbar")
    return FileResponse(
        path=thumbnail_path,
        media_type="image/jpeg",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=86400"},
    )


def _get_album(db: Session, user: CurrentUser, album_id: uuid.UUID):
    require_writer(user)
    album = db.scalar(select(PhotoAlbum).where(PhotoAlbum.id == album_id, PhotoAlbum.tenant_id == user.current_tenant_id))
    if album is None:
        raise HTTPException(status_code=404, detail="Album nicht gefunden")
    return album


@router.get("/files/albums", response_model=list[PhotoAlbumRead])
def list_albums(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_writer(user)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    return [
        PhotoAlbumRead(
            id=entry.album.id,
            name=entry.album.name,
            kind=entry.album.kind,
            photo_count=entry.photo_count,
            best_of_count=entry.best_of_count,
            cover_thumbnail_urls=entry.cover_thumbnail_urls,
        )
        for entry in photo_album_service.list_albums_with_stats(db, service, user.current_tenant_id)
    ]


@router.post("/files/albums", response_model=PhotoAlbumRead, status_code=201)
def create_album(payload: PhotoAlbumCreate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_writer(user)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    name = payload.name.strip()
    if not name or len(name) > 120:
        raise HTTPException(status_code=422, detail="Albumname muss zwischen 1 und 120 Zeichen lang sein")
    album = PhotoAlbum(tenant_id=user.current_tenant_id, name=name, kind="manual")
    db.add(album)
    db.commit()
    db.refresh(album)
    return PhotoAlbumRead(id=album.id, name=album.name, kind=album.kind)


@router.post("/files/albums/{album_id}/items", status_code=204)
def add_album_items(album_id: uuid.UUID, payload: PhotoAlbumItemsUpdate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    album = _get_album(db, user, album_id)
    ids = set(payload.file_ids)
    if not ids or len(ids) > 200:
        raise HTTPException(status_code=422, detail="Bitte 1 bis 200 Fotos auswählen")
    photos = service.list_tenant_files(db, user.current_tenant_id, only_images=True, file_ids=list(ids), limit=200)
    if {photo.id for photo in photos} != ids:
        raise HTTPException(status_code=404, detail="Foto nicht gefunden")
    db.execute(insert(PhotoAlbumItem).values([{"album_id": album_id, "file_id": file_id} for file_id in ids]).on_conflict_do_nothing())
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
    require_writer(user)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    touched = photo_album_service.set_best_override_everywhere(
        db, service, user.current_tenant_id, file_id, payload.best_override
    )
    if touched == 0:
        raise HTTPException(
            status_code=422, detail="Dieses Foto gehört zu keinem Album – Best-of ist nur innerhalb eines Albums möglich."
        )


@router.post("/files/bulk-delete", response_model=FileBulkDeleteResult)
def bulk_delete_files(payload: FileBulkDelete, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Multi-select "Löschen" auf der Fotos-Seite und "Nur beste behalten" im Ähnliche-Tab -
    löscht endgültig, nur Direkt-Uploads (siehe FileService.delete_gallery_images für die
    Begründung; andere Quellen werden als Fehler zurückgemeldet statt gelöscht)."""
    require_writer(user)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    ids = list(dict.fromkeys(payload.file_ids))
    if not ids or len(ids) > 200:
        raise HTTPException(status_code=422, detail="Bitte 1 bis 200 Dateien auswählen")
    touched_album_ids = photo_album_service.drop_items_for_files(db, ids)
    deleted, errors = service.delete_gallery_images(db, user.current_tenant_id, ids)
    db.commit()
    for album_id in touched_album_ids:
        album = db.get(PhotoAlbum, album_id)
        if album is not None:
            photo_album_service.recompute_best_of(db, service, album)
    return FileBulkDeleteResult(deleted_ids=deleted, errors=errors)


@router.post("/files/bulk-tags", status_code=204)
def bulk_update_file_tags(payload: FileBulkTagsUpdate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Multi-select "Tags hinzufügen" auf der Fotos-Seite."""
    require_writer(user)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    ids = list(dict.fromkeys(payload.file_ids))
    if not ids or len(ids) > 200:
        raise HTTPException(status_code=422, detail="Bitte 1 bis 200 Dateien auswählen")
    service.bulk_update_tags(db, user.current_tenant_id, ids, payload.add_tags, payload.remove_tags)
