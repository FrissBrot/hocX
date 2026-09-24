import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects.postgresql import insert
from app.models.entities import CycleConfig, Event, GalleryUploadJob, PhotoAlbum, PhotoAlbumItem, SubmissionAssignment
from app.schemas.files import PhotoAlbumCreate, PhotoAlbumItemBestUpdate, PhotoAlbumRead, PhotoAlbumItemsUpdate
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.core.db import get_db
from app.core.config import settings
from app.core.security import CurrentUser, get_current_user, require_reader, require_writer
from app.models import GalleryImage, ProtocolElementBlock, ProtocolImage, StoredFile
from app.schemas.files import (
    DocumentUploadResult,
    FileBulkDelete,
    FileBulkDeleteResult,
    FileBulkTagsUpdate,
    FileOverviewItem,
    FileOverviewSource,
    FileStats,
    GalleryUploadJobDetail,
    GalleryUploadJobRead,
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
from app.services.apple_media import pair_live_clips
from app.services.file_service import MAX_UPLOAD_BYTES, FileService, _safe_storage_path
from app.services import submission_upload_rules
from app.services.submission_service import SubmissionService, _element_ref, _parse_element_ref
from app.services.upload_pipeline import GALLERY_DIRECT_IMAGE_MAX_BYTES, GALLERY_ZIP_MAX_BYTES, stage_upload_to_disk

router = APIRouter()
service = FileService()
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
MAX_DOCUMENT_UPLOAD_BATCH_BYTES = 100 * 1024 * 1024


@router.get("/files", response_model=list[FileOverviewItem])
def list_files(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=60, ge=1, le=200),
    source: FileOverviewSource | None = Query(default=None),
    album_id: Annotated[uuid.UUID | None, Query()] = None,
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
    if album_id is not None:
        _get_album(db, user, album_id)
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
        album_id=album_id,
    )
    if album_id is not None:
        # is_best fetched only for this page's items (at most `limit`), not the whole
        # album - the query itself is now scoped by a JOIN on album_id (see
        # StoredFileRepository.list_tenant_files), not a pre-fetched id list, so there's
        # no reason to also pre-fetch every member's is_best up front (audit fix,
        # 2026-09-17 - same over-fetch this whole route used to have for file_ids).
        page_ids = [item.id for item in items]
        best_by_id: dict[uuid.UUID, bool] = dict(
            db.execute(
                select(PhotoAlbumItem.file_id, PhotoAlbumItem.is_best).where(
                    PhotoAlbumItem.album_id == album_id, PhotoAlbumItem.file_id.in_(page_ids)
                )
            ).all()
        ) if page_ids else {}
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
    kind: Literal["duplicate", "series"] = Query(default="duplicate"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Photo-culling Phase 2: clustert die (per Filter eingegrenzten) Bilder des Mandanten
    nach visueller Ähnlichkeit (Perceptual Hash) und markiert pro Gruppe das nach Schärfe/
    Belichtung beste Bild. Gleiche Filter wie GET /files, aber immer nur Bilder und ohne
    Pagination - siehe FileService.group_similar_gallery_images für die Grössenbeschränkung.
    min_size=2 (die "Duplikate"- und "Ähnliche"-Tabs im Frontend) blendet Einzelbilder ohne
    ähnliches Gegenstück aus - der Default 1 behält das bisherige Verhalten für andere
    Aufrufer bei. kind unterscheidet die beiden Tabs: "duplicate" (enger Schwellwert, gleiches
    Bild in anderem Ausschnitt/Qualität) vs. "series" (lockerer Schwellwert, Fotoserie mit
    mehreren unterschiedlichen Aufnahmen derselben Szene)."""
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
        kind=kind,
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


def _gallery_upload_job_to_read(job: GalleryUploadJob) -> GalleryUploadJobRead:
    return GalleryUploadJobRead(
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
        raise HTTPException(status_code=422, detail="Abgabe und Abgabe-Element muessen zusammen angegeben werden")

    target = _UploadTarget()

    if event_id is not None:
        target.event_id = public_id_service.resolve_internal_id(db, Event, event_id, tenant_id=user.current_tenant_id)
        if target.event_id is None:
            raise HTTPException(status_code=404, detail="Termin nicht gefunden")
    elif submission_assignment_id is not None:
        target.assignment_id = public_id_service.resolve_internal_id(
            db, SubmissionAssignment, submission_assignment_id, tenant_id=user.current_tenant_id
        )
        if target.assignment_id is None:
            raise HTTPException(status_code=404, detail="Abgabe nicht gefunden")
        upload_assignment = db.get(SubmissionAssignment, target.assignment_id)
        target.assignment = upload_assignment
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
        target.event_id = match["event_id"]
        target.element_label = match["label"]
    elif cycle_config_id is not None:
        target.cycle_config_id = public_id_service.resolve_internal_id(db, CycleConfig, cycle_config_id, tenant_id=user.current_tenant_id)
        if target.cycle_config_id is None:
            raise HTTPException(status_code=404, detail="Zyklus nicht gefunden")
    return target


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
    require_writer(user)
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

    tag_list = [tag.strip() for tag in (tags or "").split(",") if tag.strip()]

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
    try:
        for position, file in enumerate(files):
            name = file.filename or ""
            is_zip = name.lower().endswith(".zip")
            has_zip = has_zip or is_zip
            max_bytes = GALLERY_ZIP_MAX_BYTES if is_zip else GALLERY_DIRECT_IMAGE_MAX_BYTES
            if rules is not None and not is_zip and position not in clip_positions:
                max_bytes = min(max_bytes, rules.max_bytes)
            staged_path = await stage_upload_to_disk(
                file, target_dir=staging_dir, max_bytes=max_bytes, suffix=Path(name).suffix.lower() or ".bin"
            )
            batch_bytes += staged_path.stat().st_size
            if batch_bytes > MAX_GALLERY_UPLOAD_BATCH_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Gesamtgrösse des Batches überschritten (maximal {MAX_GALLERY_UPLOAD_BATCH_BYTES // 1024 // 1024} MB)",
                )
            staged_paths.append(str(staged_path.relative_to(settings.storage_root)))
            original_filenames.append(name)
    except HTTPException:
        for relative_path in staged_paths:
            (Path(settings.storage_root) / relative_path).unlink(missing_ok=True)
        raise

    if not staged_paths:
        raise HTTPException(status_code=400, detail="Keine Dateien hochgeladen")

    job = GalleryUploadJob(
        tenant_id=user.current_tenant_id,
        staged_paths=staged_paths,
        original_filenames=original_filenames,
        tags=tag_list,
        upload_event_id=upload_event_id,
        upload_assignment_id=upload_assignment_id,
        upload_element_ref=submission_element_ref,
        upload_element_label=upload_element_label,
        upload_cycle_config_id=upload_cycle_config_id,
        requested_by=user.user_id,
        # A ZIP's matching entries are only known once the ingest loop opens it; a batch
        # of individually-selected images (no ZIP at all) knows its count immediately.
        total_files=None if has_zip else len(staged_paths) - len(clip_positions),
    )
    db.add(job)
    db.commit()
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
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Direkter Dokument-Upload fuer die "Dateien"-Seite (PDF, Office/OpenDocument, RTF, Text,
    ZIP - siehe upload_pipeline._sniff_document_mime; Bilder gehoeren auf die "Fotos"-Seite).
    Anders als der Galerie-Upload laeuft alles inline: Magic-Byte-Pruefung, Virenscan und
    Speichern passieren in diesem Request, das Ergebnis (gespeicherte Dateien + Einzelfehler)
    kommt direkt zurueck."""
    require_writer(user)
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
    tag_list = [tag.strip() for tag in (tags or "").split(",") if tag.strip()]

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
        staged.append((name, content))

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
    )
    return DocumentUploadResult(items=items, errors=errors)


@router.get("/files/gallery-upload-jobs", response_model=list[GalleryUploadJobRead])
def list_gallery_upload_jobs(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Tenant-wide list of not-yet-finished gallery uploads, backing the "Bilder hochladen"
    status bar - same tenant-wide-visibility idea as GET /files/analysis-progress (just a
    list here, not one aggregated object), so the bar shows up for any writer in the tenant
    (any tab, after a refresh, ...), not just whoever's browser sent the original request."""
    require_writer(user)
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
    require_writer(user)
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
    )


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
    # video/mp4 is the Live Photo clip (see apple_media.py) the Fotos grid plays via <video src>.
    is_inline_safe = stored_file.mime_type in {"application/pdf", "video/mp4"} or (stored_file.mime_type or "").startswith("image/")
    return FileResponse(
        path=file_path,
        media_type=stored_file.mime_type,
        filename=stored_file.original_name,
        content_disposition_type="inline" if is_inline_safe else "attachment",
        # A stored file's bytes never change after upload (a re-upload creates a new id), so the
        # browser cache can keep this for a long time - saves refetching originals opened again
        # from the Fotos viewer/lightbox within the same session.
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=604800, immutable"},
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
        # Same immutability as get_stored_file_content above - once generated, a thumbnail never
        # changes for a given stored_file id, so it's safe to cache far longer than a day.
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=604800, immutable"},
    )


@router.get("/stored-files/{stored_file_id}/download")
def download_stored_file(
    stored_file_id: uuid.UUID,
    part: Literal["image", "video", "both"] = "image",
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Explicit download (Content-Disposition: attachment) of a gallery photo. For a Live Photo
    the caller picks what to get: `image` (the still, default), `video` (the clip as MP4) or `both`
    (a ZIP with IMG_1234.jpg + IMG_1234.mp4 - same names, so it can be uploaded again as a Live
    Photo). An ordinary photo has no clip: `video` is a 404, `both` is just the image."""
    require_reader(user)
    stored_file = public_id_service.get_by_public_id(db, StoredFile, stored_file_id)
    if stored_file is None:
        raise HTTPException(status_code=404, detail="Stored file not found")
    access_service.ensure_can_read_stored_file(db, user, stored_file.id)
    if stored_file.scan_status == "infected":
        raise HTTPException(status_code=403, detail="Datei wurde von der Virenprüfung als infiziert erkannt und ist gesperrt")
    if stored_file.scan_status == "pending":
        raise HTTPException(status_code=425, detail="Datei wird noch auf Schadsoftware geprüft, bitte in Kürze erneut versuchen")

    live_video_id = db.scalar(select(GalleryImage.live_video_stored_file_id).where(GalleryImage.stored_file_id == stored_file.id))
    live_video = db.get(StoredFile, live_video_id) if live_video_id is not None else None
    if live_video is not None and live_video.scan_status != "clean":
        live_video = None
    if part == "video" and live_video is None:
        raise HTTPException(status_code=404, detail="Zu diesem Foto gibt es kein Live-Photo-Video")

    image_path = _safe_storage_path(settings.storage_root, stored_file.storage_path)
    if part != "video" and not image_path.exists():
        raise HTTPException(status_code=404, detail="File missing on filesystem")
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}

    if part == "image" or (part == "both" and live_video is None):
        return FileResponse(
            path=image_path,
            media_type=stored_file.mime_type,
            filename=stored_file.original_name,
            content_disposition_type="attachment",
            headers=headers,
        )

    video_path = _safe_storage_path(settings.storage_root, live_video.storage_path)
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="File missing on filesystem")
    if part == "video":
        return FileResponse(
            path=video_path,
            media_type="video/mp4",
            filename=live_video.original_name,
            content_disposition_type="attachment",
            headers=headers,
        )

    # Both: JPEG and MP4 are already compressed, so the ZIP just stores them. Built on disk (not
    # in memory) and removed once the response has been sent.
    work_dir = Path(settings.upload_root) / "_staging" / "download"
    work_dir.mkdir(parents=True, exist_ok=True)
    zip_path = work_dir / f"{uuid.uuid4().hex}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.write(image_path, arcname=Path(stored_file.original_name).name)
        archive.write(video_path, arcname=Path(live_video.original_name).name)
    return FileResponse(
        path=zip_path,
        media_type="application/zip",
        filename=f"{Path(stored_file.original_name).stem}-live.zip",
        content_disposition_type="attachment",
        headers=headers,
        background=BackgroundTask(zip_path.unlink, missing_ok=True),
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
