"""Datei-Import (Plan «Cloud-Datei-Importer» P0): ZIP/Takeout oder Ordner-Upload mit Regeln.

Alle Endpunkte verlangen «Dateien importieren» (files.import, Standard nur Vereins-Admin) und
arbeiten ausschliesslich im eigenen Mandanten (fremde Auftrags-IDs: 404, kein Existenz-Orakel).
Start zusätzlich mit files.manage (Dokumente) bzw. photos.manage (Bilder, Alben). Fehler kommen
als detail={code, message, params}; das Frontend übersetzt den Code.

Die beiden Upload-Endpunkte unter /cloud-import/uploads/ streamen wie der Galerie-Upload direkt
auf den Upload-Datenträger (ImportUploadRoute, UploadAdmissionMiddleware in main.py).
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.db import get_db
from app.core.offload import run_coroutine_in_thread
from app.core.permissions import P
from app.core.rate_limit import enforce_rate_limit
from app.core.security import CurrentUser, get_current_user, require_permission
from app.gallery_upload_route import ImportUploadRoute
from app.models.entities import AppUser, StoredFile
from app.models.import_entities import ImportJob
from app.services.audit_service import AuditService
from app.services.cloud_import import jobs, paths
from app.services.cloud_import.jobs import ImportFailure
from app.services.file_service import FileService
from app.services.upload_pipeline import GALLERY_ZIP_MAX_BYTES, stage_upload_to_disk

# Wie files.py: die Route-Klasse streamt nur die Upload-Pfade (/cloud-import/uploads/), alle anderen
# Routen laufen unverändert.
router = APIRouter(route_class=ImportUploadRoute)

PENDING_PAGE_MAX = 1000
REPORT_PAGE_MAX = 200
FILES_PER_REQUEST = 100


def _http(exc: ImportFailure) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.code, "params": exc.params})


def _require_import(user: CurrentUser) -> int:
    require_permission(user, P.FILES_IMPORT)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    return user.current_tenant_id


def _load(db: Session, user: CurrentUser, job_id: uuid.UUID, *, owner: bool = False, lock: bool = False) -> ImportJob:
    tenant_id = _require_import(user)
    try:
        job = jobs.get_job(db, tenant_id, job_id, lock=lock)
        if owner:
            jobs.require_owner(job, user.user_id)
    except ImportFailure as exc:
        raise _http(exc) from None
    return job


# --- Schemas ----------------------------------------------------------------------------------

TypeFilter = Literal["all", "images", "documents"]


class ImportJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["zip", "folder"]
    type_filter: TypeFilter = "all"
    include_gps: bool = True
    folder_tags: bool = False
    # Album-Regeln wirken nur, wenn eingeschaltet (Standard aus, User-Entscheid 2026-11-22)
    albums_enabled: bool = False


class ManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=2048)
    size: int = Field(ge=0, le=10 * 1024**4)
    modified_at: datetime | None = None


class ManifestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[ManifestEntry] = Field(max_length=jobs.MANIFEST_BATCH_MAX)


class RuleMatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    folder: str | None = Field(default=None, max_length=2048)
    path_glob: str | None = Field(default=None, max_length=1000)
    name_regex: str | None = Field(default=None, max_length=1000)
    kind: Literal["all", "images", "documents"] = "all"
    case_sensitive: bool = False


class RuleActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["add_tags", "set_date", "skip", "add_to_album", "folder_to_album"]
    tags: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=60)
    date: str | None = Field(default=None, max_length=10)
    album_id: uuid.UUID | None = None
    album_name: str | None = Field(default=None, max_length=300)
    folder_level: Literal["parent", "top"] = "parent"


class RuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=40)
    enabled: bool = True
    match: RuleMatchIn = Field(default_factory=RuleMatchIn)
    action: RuleActionIn


class ImportSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[RuleIn] = Field(default_factory=list, max_length=60)
    type_filter: TypeFilter = "all"
    include_gps: bool = True
    folder_tags: bool = False
    albums_enabled: bool = False


class PreviewRequest(ImportSettingsIn):
    view: Literal["all", "import", "skipped", "conflicts"] = "all"
    rule_id: str | None = Field(default=None, max_length=40)
    q: str | None = Field(default=None, max_length=200)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=jobs.PREVIEW_PAGE_MAX)


class RuleErrorRead(BaseModel):
    rule_id: str
    field: str
    code: str


class PreviewItemRead(BaseModel):
    path: str
    kind: str
    size: int
    import_: bool = Field(serialization_alias="import")
    reason: str | None
    tags: list[str]
    date: date | None
    date_source: str | None = None
    albums: list[str]
    rules: list[str]
    conflict: bool


class QuotaRead(BaseModel):
    limit_bytes: int | None
    used_bytes: int
    planned_bytes: int
    fits: bool


class PreviewSummaryRead(BaseModel):
    total: int
    importable: int
    images: int
    documents: int
    planned_bytes: int
    conflicts: int
    skipped: dict[str, int]
    per_rule: dict[str, int]


class PreviewRead(BaseModel):
    summary: PreviewSummaryRead
    quota: QuotaRead
    errors: list[RuleErrorRead]
    items: list[PreviewItemRead]
    filtered_total: int
    folders: list[str]
    saved: bool
    # Albumnamen, die es im Verein schon gibt und die deshalb ergänzt statt neu angelegt werden
    existing_albums: list[str] = Field(default_factory=list)


class AlbumReportRead(BaseModel):
    name: str
    reused: bool
    candidates: int


class ImportJobRead(BaseModel):
    id: uuid.UUID
    source: str
    status: str
    type_filter: str
    include_gps: bool
    folder_tags: bool
    albums_enabled: bool
    takeout: bool
    rules: list[dict]
    total_items: int
    total_bytes: int
    archives: int
    error: str | None
    is_owner: bool
    requested_by_name: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    last_progress_at: datetime | None
    counts: dict[str, int] = Field(default_factory=dict)
    codes: dict[str, int] = Field(default_factory=dict)
    processed_bytes: int = 0
    albums: list[AlbumReportRead] = Field(default_factory=list)


class PendingUploadRead(BaseModel):
    path: str
    size: int


class PendingUploadsRead(BaseModel):
    items: list[PendingUploadRead]
    total: int


class StageResultRead(BaseModel):
    staged: int
    rejected: dict[str, str]


class ReportItemRead(BaseModel):
    path: str
    kind: str
    size: int
    status: str
    result_code: str | None
    tags: list[str]
    estimated_date: date | None
    date_source: str | None = None
    albums: list[str]
    conflict: bool
    file_id: uuid.UUID | None


class ReportRead(BaseModel):
    items: list[ReportItemRead]
    total: int


def _album_label(key: str, names: dict[str, str]) -> str:
    kind, _sep, value = key.partition(":")
    return names.get(value, "") if kind == "id" else value


def _job_read(db: Session, job: ImportJob, user: CurrentUser, *, with_counts: bool = True) -> ImportJobRead:
    creator = db.get(AppUser, job.requested_by) if job.requested_by else None
    read = ImportJobRead(
        id=job.id, source=job.source, status=job.status, type_filter=job.type_filter, include_gps=job.include_gps,
        folder_tags=job.folder_tags, albums_enabled=job.albums_enabled, takeout=job.takeout, rules=list(job.rules or []),
        total_items=job.total_items,
        total_bytes=job.total_bytes, archives=len(job.archives or []), error=job.error,
        is_owner=job.requested_by == user.user_id,
        requested_by_name=(creator.display_name if creator is not None and creator.tenant_id == job.tenant_id else None),
        created_at=job.created_at, started_at=job.started_at, finished_at=job.finished_at,
        last_progress_at=job.last_progress_at,
        albums=[
            AlbumReportRead(name=name, reused=bool(entry.get("reused")), candidates=int(entry.get("candidates") or 0))
            for name, entry in sorted((job.album_report or {}).items())
        ],
    )
    if with_counts:
        read.counts, read.codes, read.processed_bytes = jobs.status_counts(db, job)
    return read


# --- Aufträge ---------------------------------------------------------------------------------


@router.get("/cloud-import/jobs", response_model=list[ImportJobRead])
def list_import_jobs(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    tenant_id = _require_import(user)
    return [_job_read(db, job, user) for job in jobs.list_jobs(db, tenant_id)]


@router.post("/cloud-import/jobs", response_model=ImportJobRead, status_code=status.HTTP_201_CREATED)
def create_import_job(payload: ImportJobCreate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    tenant_id = _require_import(user)
    enforce_rate_limit(f"cloud-import-create:{tenant_id}", limit=30, period_seconds=3600)
    try:
        job = jobs.create_job(
            db, tenant_id=tenant_id, user_id=user.user_id, source=payload.source, type_filter=payload.type_filter,
            include_gps=payload.include_gps, folder_tags=payload.folder_tags, albums_enabled=payload.albums_enabled,
        )
    except ImportFailure as exc:
        raise _http(exc) from None
    db.commit()
    db.refresh(job)
    return _job_read(db, job, user)


@router.get("/cloud-import/jobs/{job_id}", response_model=ImportJobRead)
def get_import_job(job_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    return _job_read(db, _load(db, user, job_id), user)


@router.post("/cloud-import/jobs/{job_id}/manifest", response_model=ImportJobRead)
def add_import_manifest(
    job_id: uuid.UUID, payload: ManifestRequest, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)
):
    job = _load(db, user, job_id, owner=True, lock=True)
    try:
        jobs.add_manifest(db, job, [entry.model_dump() for entry in payload.entries])
    except ImportFailure as exc:
        # Grenzen werden vor jedem Einfügen geprüft - nichts zurückzurollen; die Sitzung endet mit dem Request.
        raise _http(exc) from None
    db.commit()
    return _job_read(db, job, user, with_counts=False)


@router.post("/cloud-import/jobs/{job_id}/finish-listing", response_model=ImportJobRead)
def finish_import_listing(job_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    job = _load(db, user, job_id, owner=True, lock=True)
    try:
        jobs.finish_listing(db, job)
    except ImportFailure as exc:
        raise _http(exc) from None
    db.commit()
    return _job_read(db, job, user)


def _stored_rules(job: ImportJob) -> list[RuleIn]:
    try:
        return [RuleIn.model_validate(rule) for rule in job.rules or []]
    except ValueError as exc:  # gespeicherte Regeln passen nicht mehr zum Schema
        raise _http(ImportFailure(422, "invalid_rules")) from exc


def _evaluate(db: Session, job: ImportJob, payload: ImportSettingsIn) -> tuple[jobs.CompiledJobRules, list[jobs.Outcome]]:
    raw_rules = [rule.model_dump(mode="json") for rule in payload.rules]
    compiled = jobs.compile_job_rules(db, job.tenant_id, raw_rules)
    # Vorschau mit den übergebenen Optionen (der Auftrag selbst bleibt unverändert)
    return compiled, jobs.evaluate_job(
        db, job, compiled.rules, type_filter=payload.type_filter, folder_tags=payload.folder_tags, albums_enabled=payload.albums_enabled,
    )


@router.post("/cloud-import/jobs/{job_id}/preview", response_model=PreviewRead, response_model_by_alias=True)
def preview_import_job(
    job_id: uuid.UUID, payload: PreviewRequest, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)
):
    """Rechnet die Regeln über alle Dateien (rein, RE2) und speichert Regeln und Optionen, solange
    der Auftrag noch nicht gestartet ist und alle Regeln gültig sind."""
    job = _load(db, user, job_id)
    enforce_rate_limit(f"cloud-import-preview:{job.tenant_id}", limit=300, period_seconds=600)
    editable = job.status == "ready" and job.requested_by == user.user_id
    if not editable:
        payload = PreviewRequest(
            rules=_stored_rules(job), type_filter=job.type_filter,
            include_gps=job.include_gps, folder_tags=job.folder_tags, albums_enabled=job.albums_enabled,
            view=payload.view, rule_id=payload.rule_id,
            q=payload.q, offset=payload.offset, limit=payload.limit,
        )
    compiled, outcomes = _evaluate(db, job, payload)
    saved = False
    if editable and not compiled.errors:
        job = _load(db, user, job_id, lock=True)
        # Status nach der Sperre erneut prüfen: ein paralleler Start friert die Regeln ein (Review N2)
        if job.status == "ready" and job.requested_by == user.user_id:
            jobs.save_settings(
                job, raw_rules=[rule.model_dump(mode="json") for rule in payload.rules], type_filter=payload.type_filter,
                include_gps=payload.include_gps, folder_tags=payload.folder_tags, albums_enabled=payload.albums_enabled,
            )
            saved = True
        db.commit()  # gibt die Zeilensperre frei
    summary = jobs.summarize(outcomes)
    quota = jobs.quota_info(db, job.tenant_id, summary.planned_bytes)
    selected = jobs.filter_outcomes(outcomes, view=payload.view, rule_id=payload.rule_id, query=payload.q)
    album_names = {str(key): name for key, name in compiled.album_names.items()}
    page = selected[payload.offset : payload.offset + payload.limit]
    return PreviewRead(
        summary=PreviewSummaryRead(**summary.__dict__),
        quota=QuotaRead(limit_bytes=quota.limit_bytes, used_bytes=quota.used_bytes, planned_bytes=quota.planned_bytes, fits=quota.fits),
        errors=[RuleErrorRead(rule_id=e.rule_id, field=e.field, code=e.code) for e in compiled.errors],
        items=[
            PreviewItemRead(
                path=o.path, kind=o.kind, size=o.size, import_=o.import_, reason=o.reason, tags=o.result.tags,
                date=o.result.date, date_source=o.result.date_source if o.result.date else None,
                albums=[_album_label(key, album_names) for key in o.result.albums],
                rules=o.result.matched, conflict=bool(o.result.conflicts),
            )
            for o in page
        ],
        filtered_total=len(selected),
        folders=jobs.folder_list(outcomes),
        saved=saved,
        # Nur wer Alben verwalten darf, erfährt, welche Namen es schon gibt (Review N1)
        existing_albums=jobs.existing_album_names(db, job.tenant_id, outcomes) if user.can(P.PHOTOS_MANAGE) else [],
    )


@router.post("/cloud-import/jobs/{job_id}/start", response_model=ImportJobRead)
def start_import_job(job_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    job = _load(db, user, job_id, owner=True, lock=True)
    enforce_rate_limit(f"cloud-import-start:{job.tenant_id}", limit=20, period_seconds=3600)
    if job.status != "ready":
        raise _http(ImportFailure(409, "invalid_status", {"status": job.status}))
    settings_in = ImportSettingsIn(
        rules=_stored_rules(job), type_filter=job.type_filter,
        include_gps=job.include_gps, folder_tags=job.folder_tags, albums_enabled=job.albums_enabled,
    )
    compiled, outcomes = _evaluate(db, job, settings_in)
    if compiled.errors:
        raise _http(ImportFailure(422, "invalid_rules"))
    summary = jobs.summarize(outcomes)
    if summary.importable == 0:
        raise _http(ImportFailure(400, "nothing_to_import"))
    # Inhalt bestimmt die zusätzlich nötigen Rechte (Plan 10.4)
    if summary.images:
        require_permission(user, P.PHOTOS_MANAGE)
    if summary.documents:
        require_permission(user, P.FILES_MANAGE)
    quota = jobs.quota_info(db, job.tenant_id, summary.planned_bytes)
    if not quota.fits:
        raise _http(ImportFailure(409, "quota_exceeded"))
    jobs.start(db, job, outcomes)
    AuditService().log(
        db, action="file_import.started", actor=user, entity_type="import_job",
        details={"job_id": str(job.id), "source": job.source, "files": summary.importable, "bytes": summary.planned_bytes, "rules": len(job.rules or [])},
        commit=False,
    )
    db.commit()
    return _job_read(db, job, user)


@router.post("/cloud-import/jobs/{job_id}/cancel", response_model=ImportJobRead)
def cancel_import_job(job_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    job = _load(db, user, job_id, lock=True)
    try:
        jobs.cancel(db, job)
    except ImportFailure as exc:
        raise _http(exc) from None
    AuditService().log(
        db, action="file_import.cancel_requested", actor=user, entity_type="import_job",
        details={"job_id": str(job.id), "source": job.source}, commit=False,
    )
    db.commit()
    return _job_read(db, job, user)


@router.post("/cloud-import/jobs/{job_id}/resume", response_model=ImportJobRead)
def resume_import_job(job_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    job = _load(db, user, job_id, owner=True, lock=True)
    try:
        jobs.resume(db, job)
    except ImportFailure as exc:
        raise _http(exc) from None
    db.commit()
    return _job_read(db, job, user)


@router.get("/cloud-import/jobs/{job_id}/pending-uploads", response_model=PendingUploadsRead)
def list_pending_uploads(
    job_id: uuid.UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=PENDING_PAGE_MAX),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Ordner-Quelle: welche Dateien der Browser noch hochladen soll (nur nicht ausgeschlossene)."""
    job = _load(db, user, job_id, owner=True)
    if job.source != "folder" or job.status not in ("queued", "running"):
        return PendingUploadsRead(items=[], total=0)
    items, total = jobs.pending_uploads(db, job, offset=offset, limit=limit)
    return PendingUploadsRead(items=[PendingUploadRead(path=path, size=size) for path, size in items], total=total)


@router.get("/cloud-import/jobs/{job_id}/items", response_model=ReportRead)
def list_import_items(
    job_id: uuid.UUID,
    item_status: Literal["listed", "queued", "staged", "imported", "duplicate", "skipped", "failed", "cancelled"] | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=REPORT_PAGE_MAX),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Bericht: Dateien mit Ergebnis. Dateinamen/Pfade nur hier und nie in Mails oder Logs."""
    job = _load(db, user, job_id)
    items, total = jobs.report_items(db, job, status=item_status, offset=offset, limit=limit)
    # Vorhandene Dateien (Duplikate) nur verlinken, wenn die lesende Person sie sieht (Review N2)
    file_ids = {item.stored_file_id or item.existing_file_id for item in items if item.stored_file_id or item.existing_file_id}
    public = dict(
        db.execute(select(StoredFile.id, StoredFile.public_id).where(StoredFile.tenant_id == job.tenant_id, StoredFile.id.in_(file_ids))).all()
    ) if file_ids else {}
    album_ids: set[uuid.UUID] = set()
    for item in items:
        for key in item.albums or []:
            kind, _sep, value = key.partition(":")
            if kind == "id":
                try:
                    album_ids.add(uuid.UUID(value))
                except ValueError:
                    continue
    names = {str(k): v for k, v in jobs.own_album_ids(db, job.tenant_id, album_ids).items()}
    existing_ids = [public[item.existing_file_id] for item in items if not item.stored_file_id and item.existing_file_id in public]
    visible_existing = set(FileService().visible_overview_items(db, user, existing_ids)) if existing_ids else set()

    def link(item) -> uuid.UUID | None:
        if item.stored_file_id:
            return public.get(item.stored_file_id)
        if item.existing_file_id and public.get(item.existing_file_id) in visible_existing:
            return public[item.existing_file_id]
        return None

    return ReportRead(
        items=[
            ReportItemRead(
                path=item.path, kind=item.kind, size=item.size_bytes, status=item.status,
                result_code=item.result_code or item.listing_code, tags=list(item.tags or []),
                estimated_date=item.estimated_date, date_source=item.date_source,
                albums=[_album_label(key, names) for key in item.albums or []], conflict=item.conflict,
                file_id=link(item),
            )
            for item in items
        ],
        total=total,
    )


# --- Uploads (streamend) ----------------------------------------------------------------------


def authorize_import_upload(request: Request) -> None:
    """ImportUploadRoute ruft das vor dem ersten Dateibyte auf (Security-Review N1/M2): Recht,
    eigener Auftrag (fremde/unbekannte ID: 404), Status und Quelle, Auftragsgrenze, Kontingent,
    Plattenreserve. Die Route prüft nach dem Empfang alles erneut."""
    from app.core.db import SessionLocal
    from app.core.security import get_optional_current_user

    with SessionLocal() as db:
        user = get_current_user(request, get_optional_current_user(request, db=db, session_cookie=None))
        tenant_id = _require_import(user)
        try:
            job_id = uuid.UUID(str(request.path_params.get("job_id", "")))
        except ValueError:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "not_found", "params": {}}) from None
        kind = "archive" if request.url.path.rstrip("/").endswith("/archive") else "files"
        raw_length = request.headers.get("content-length")
        content_length = int(raw_length) if raw_length and raw_length.isdigit() else None
        try:
            job = jobs.get_job(db, tenant_id, job_id)
            jobs.require_owner(job, user.user_id)
            jobs.check_upload_allowed(db, job, kind=kind, content_length=content_length)
        except ImportFailure as exc:
            raise _http(exc) from None


@router.post("/cloud-import/uploads/{job_id}/archive", response_model=ImportJobRead)
async def upload_import_archive(
    job_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """ZIP-Quelle (auch Google-Takeout-Teilarchive): wird gestagt, nur das Inhaltsverzeichnis wird
    gelesen. Entpackt wird erst beim Import, je Eintrag begrenzt (Zip-Bomb-Schutz)."""
    return await run_coroutine_in_thread(_upload_archive_impl, job_id=job_id, file=file, db=db, user=user)


async def _upload_archive_impl(job_id: uuid.UUID, file: UploadFile, db: Session, user: CurrentUser):  # loop-ok: nur über run_coroutine_in_thread (core/offload.py)
    job = _load(db, user, job_id, owner=True)
    if job.status != "draft" or job.source != "zip":
        raise _http(ImportFailure(409, "invalid_status", {"status": job.status}))
    if not (file.filename or "").lower().endswith(".zip"):
        raise _http(ImportFailure(400, "zip_invalid"))
    staged = await stage_upload_to_disk(file, target_dir=jobs.staging_dir(job.id), max_bytes=GALLERY_ZIP_MAX_BYTES, suffix=".zip")
    try:
        job = _load(db, user, job_id, owner=True, lock=True)
        jobs.add_archive(db, job, staged)
        db.commit()
    except ImportFailure as exc:
        # add_archive prüft alles vor dem ersten Schreiben; die Sitzung endet mit dem Request
        staged.unlink(missing_ok=True)
        raise _http(exc) from None
    except BaseException:
        db.rollback()
        staged.unlink(missing_ok=True)
        raise
    return _job_read(db, job, user, with_counts=False)


@router.post("/cloud-import/uploads/{job_id}/files", response_model=StageResultRead)
async def upload_import_files(
    job_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    paths_json: Annotated[str, Form(alias="paths", max_length=FILES_PER_REQUEST * 2100)] = "[]",
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Ordner-Quelle nach dem Start: Dateien zu erwarteten Pfaden (paths = JSON-Liste, gleiche
    Reihenfolge wie files). Unerwartete Pfade werden verworfen, nie gespeichert."""
    return await run_coroutine_in_thread(_upload_files_impl, job_id=job_id, files=files, paths_json=paths_json, db=db, user=user)


async def _upload_files_impl(job_id: uuid.UUID, files: list[UploadFile], paths_json: str, db: Session, user: CurrentUser):  # loop-ok: nur über run_coroutine_in_thread (core/offload.py)
    job = _load(db, user, job_id, owner=True)
    if job.source != "folder" or job.status not in ("queued", "running"):
        raise _http(ImportFailure(409, "invalid_status", {"status": job.status}))
    try:
        wanted = json.loads(paths_json)
    except ValueError:
        raise _http(ImportFailure(422, "invalid_paths")) from None
    if not isinstance(wanted, list) or len(wanted) != len(files) or len(files) > FILES_PER_REQUEST or not all(isinstance(p, str) for p in wanted):
        raise _http(ImportFailure(422, "invalid_paths"))
    if await run_in_threadpool(jobs.staged_bytes, db, job) > jobs.MAX_STAGED_BYTES:
        raise _http(ImportFailure(429, "staging_busy"))
    expected = {path: item.kind for path, item in jobs.expected_items(db, job, wanted).items()}
    target_dir = jobs.staging_dir(job.id)
    db.commit()  # nur gelesen: Zeilensperren freigeben, bevor das Stagen dauert
    staged: list[tuple[str, Path]] = []
    rejected: dict[str, str] = {}
    too_large: list[str] = []
    try:
        for raw_path, file in zip(wanted, files):
            normalized = paths.normalize_path(raw_path) or ""
            if any(path == normalized for path, _target in staged) or normalized in too_large:
                rejected[raw_path[:300]] = "duplicate_path"
                continue
            kind = expected.get(normalized)
            if kind is None:
                rejected[raw_path[:300]] = "not_expected"
                continue
            limit = paths.MAX_BYTES_BY_KIND.get(kind)
            if limit is None:
                rejected[raw_path[:300]] = "unsupported_format"
                continue
            try:
                target = await stage_upload_to_disk(file, target_dir=target_dir, max_bytes=limit, suffix=".bin")
            except HTTPException as exc:
                if exc.status_code == 413:
                    rejected[raw_path[:300]] = "too_large"
                    too_large.append(normalized)
                    continue
                raise
            staged.append((normalized, target))
        job = _load(db, user, job_id, owner=True, lock=True)
        if job.status not in ("queued", "running"):
            raise _http(ImportFailure(409, "invalid_status", {"status": job.status}))
        current = jobs.expected_items(db, job, [path for path, _target in staged] + too_large)
        for normalized in too_large:
            # Grösser als angegeben: gleich als «zu gross» abschliessen, nicht erneut anfordern.
            if normalized in current:
                current[normalized].status = "failed"
                current[normalized].result_code = "too_large"
        accepted = 0
        for normalized, target in staged:
            item = current.get(normalized)
            if item is None:
                target.unlink(missing_ok=True)
                continue
            item.status = "staged"
            item.staged_path = str(target.relative_to(settings.storage_root))
            item.size_bytes = target.stat().st_size
            accepted += 1
        job.last_progress_at = jobs.now()
        jobs.touch(job)
        db.commit()
    except BaseException:
        db.rollback()
        for _normalized, target in staged:
            target.unlink(missing_ok=True)
        raise
    return StageResultRead(staged=accepted, rejected=rejected)
