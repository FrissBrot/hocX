"""Upload-Verlauf (Plan «Upload-Verlauf» 2026-11-21, Migration 0250).

Lesen: wer das Recht des Bereichs hat, sieht die Vorgänge des Kanals (E-2, upload_job_service.
visibility_clause); fremde oder unbekannte IDs ergeben 404. Schreiben (Öffnen, Abschliessen,
Browser-Ablehnungen) nur für eigene, offene Vorgänge. Bulk-Aktionen auf den Dateien eines Vorgangs
laufen über die bestehenden Endpunkte unter /files, die jede Datei erneut prüfen - die Vorgangs-ID
öffnet keine zusätzlichen Rechte.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, date, datetime, time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.permissions import P
from app.core.security import CurrentUser, get_current_user, require_any_permission, require_permission
from app.models.entities import AppUser, CycleConfig, Event, Protocol, ProtocolTodo, StoredFile, SubmissionAssignment
from app.models.upload_history_entities import UploadJob, UploadJobItem
from app.schemas.upload_jobs import (
    MAX_CLIENT_RESULTS_PER_JOB,
    MAX_JOB_FILE_IDS,
    UploadClientResults,
    UploadJobCounts,
    UploadJobCreate,
    UploadJobDetail,
    UploadJobFileIds,
    UploadJobItemFile,
    UploadJobItemList,
    UploadJobItemRead,
    UploadJobList,
    UploadJobRead,
    UploadJobRef,
)
from app.services import context_visibility_service, public_id_service, upload_job_service
from app.services.file_service import BLOCKED_SCAN_STATUSES, FileService
from app.services.access_service import AccessService, protocol_file_clause
from app.services.file_trash_service import may_manage

router = APIRouter()
service = FileService()



def _require_read(user: CurrentUser) -> None:
    # Ausgeschrieben statt *_READ_ANY, damit route-map/Rechte-Matrix die Prüfung erkennen
    require_any_permission(user, P.PHOTOS_MANAGE, P.FILES_MANAGE, P.FILES_IMPORT, P.MEETINGS_READ, P.SUBMISSIONS_READ, P.SETTINGS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=404, detail="Upload-Vorgang nicht gefunden")


# --- Lesemodell ------------------------------------------------------------------------------


def _counts(job: UploadJob) -> UploadJobCounts:
    return UploadJobCounts(
        total=job.total, uploaded=job.uploaded, duplicates=job.duplicates, metadata_updated=job.metadata_updated,
        rejected=job.rejected, infected=job.infected, failed=job.failed, discarded=job.discarded,
    )


def _refs(db: Session, jobs: list[UploadJob], tenant_id: int, user: CurrentUser | None = None) -> dict[uuid.UUID, UploadJobRef]:
    """Bezug je Vorgang mit einer Abfrage je Art (nur Objekte des eigenen Mandanten)."""
    def load(model, ids, *columns):
        ids = {i for i in ids if i is not None}
        if not ids:
            return {}
        return {row.id: row for row in db.execute(select(model.id, *columns).where(model.id.in_(ids), model.tenant_id == tenant_id))}

    events = load(Event, [j.event_id for j in jobs], Event.public_id, Event.title, Event.event_date)
    assignments = load(SubmissionAssignment, [j.submission_assignment_id for j in jobs], SubmissionAssignment.public_id, SubmissionAssignment.title)
    cycles = load(CycleConfig, [j.cycle_config_id for j in jobs], CycleConfig.public_id, CycleConfig.name)
    protocols = load(Protocol, [j.protocol_id for j in jobs], Protocol.public_id, Protocol.title, Protocol.protocol_number, Protocol.protocol_date)
    todos = load(ProtocolTodo, [j.protocol_todo_id for j in jobs], ProtocolTodo.public_id, ProtocolTodo.task)
    refs: dict[uuid.UUID, UploadJobRef] = {}
    for job in jobs:
        if job.import_job_id is not None:
            refs[job.id] = UploadJobRef(kind="import", id=job.import_job_id)
        elif (row := events.get(job.event_id)) is not None:
            refs[job.id] = UploadJobRef(kind="event", id=row.public_id, label=row.title, on_date=row.event_date)
        elif (row := assignments.get(job.submission_assignment_id)) is not None:
            label = " · ".join(part for part in (row.title, job.submission_element_label) if part)
            refs[job.id] = UploadJobRef(kind="submission", id=row.public_id, label=label)
        elif (row := cycles.get(job.cycle_config_id)) is not None:
            refs[job.id] = UploadJobRef(kind="cycle", id=row.public_id, label=row.name)
        elif (row := protocols.get(job.protocol_id)) is not None:
            refs[job.id] = UploadJobRef(kind="protocol", id=row.public_id, label=row.title or row.protocol_number, on_date=row.protocol_date)
        elif (row := todos.get(job.protocol_todo_id)) is not None and _can_read_todo(db, user, row.id):
            refs[job.id] = UploadJobRef(kind="todo", id=row.public_id, label=row.task[:120])
    return refs


def _can_read_todo(db: Session, user: CurrentUser | None, todo_id: int) -> bool:
    """Pendenztext nur mit Leserecht der Pendenz (Security-Review M-1)."""
    if user is None:
        return False
    try:
        AccessService().ensure_can_read_todo(db, user, todo_id)
    except HTTPException:
        return False
    return True


def _names(db: Session, jobs: list[UploadJob]) -> dict[int, str]:
    ids = {job.created_by for job in jobs if job.created_by is not None}
    if not ids:
        return {}
    return dict(db.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(ids))).all())


def _to_read(job: UploadJob, user: CurrentUser, names: dict[int, str], refs: dict, cls=UploadJobRead, **extra):
    # Persönlicher Abgabe-Link ohne Konto und Abgabebox: keine Person anzeigen (E-15)
    name = names.get(job.created_by) if job.created_by is not None and job.actor_kind == "user" else None
    return cls(
        id=job.id, channel=job.channel, actor_kind=job.actor_kind, created_by_name=name,
        created_by_deleted=job.created_by is None and job.actor_kind == "user" and not job.reconstructed,
        is_mine=job.created_by == user.user_id, status=job.status, reconstructed=job.reconstructed,
        created_at=job.created_at, finished_at=job.finished_at, counts=_counts(job), ref=refs.get(job.id), **extra,
    )


def _encode_cursor(job: UploadJob) -> str:
    return base64.urlsafe_b64encode(f"{job.created_at.isoformat()}|{job.id}".encode()).decode()


def _decode_cursor(raw: str) -> tuple[datetime, uuid.UUID]:
    try:
        created, job_id = base64.urlsafe_b64decode(raw.encode()).decode().split("|", 1)
        return datetime.fromisoformat(created), uuid.UUID(job_id)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Ungültiger Cursor") from exc


# --- Routen ----------------------------------------------------------------------------------


@router.post("/upload-jobs", response_model=UploadJobRead, status_code=201)
def create_upload_job(payload: UploadJobCreate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Vorgang öffnen, bevor der Browser Vorab-Abgleich und Pakete sendet. Bezug wird wie beim
    Upload geprüft (eigener Mandant); höchstens MAX_OPEN_JOBS_PER_USER offene Vorgänge je Person."""
    require_any_permission(user, P.PHOTOS_MANAGE, P.FILES_MANAGE)
    # Kanal-Recht: Galerie photos.manage, Ablage files.manage, Pendenz eines von beiden
    if payload.channel == "gallery":
        require_permission(user, P.PHOTOS_MANAGE)
    elif payload.channel == "document":
        require_permission(user, P.FILES_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    if (
        upload_job_service.count_open_jobs(db, user.current_tenant_id, user.user_id) >= upload_job_service.MAX_OPEN_JOBS_PER_USER
        or upload_job_service.count_recent_jobs(db, user.current_tenant_id, user.user_id) >= upload_job_service.MAX_JOBS_PER_USER_HOUR
    ):
        raise HTTPException(status_code=429, detail="Zu viele Upload-Vorgänge")
    from app.api.routes.files import _resolve_upload_target  # gleiche Prüfung wie der Upload selbst

    target = _resolve_upload_target(
        db, user, event_id=payload.event_id, submission_assignment_id=payload.submission_assignment_id,
        submission_element_ref=payload.submission_element_ref, cycle_config_id=payload.cycle_config_id,
    )
    todo_id = None
    if payload.protocol_todo_id is not None:
        todo = public_id_service.get_by_public_id(db, ProtocolTodo, payload.protocol_todo_id, tenant_id=user.current_tenant_id)
        if todo is None:
            raise HTTPException(status_code=404, detail="Pendenz nicht gefunden")
        # Nur lesbare Pendenzen (Security-Review M-1): sonst verriete die Antwort deren Text
        AccessService().ensure_can_read_todo(db, user, todo.id)
        todo_id = todo.id
    channel = "todo" if todo_id is not None else payload.channel
    job = upload_job_service.open_job(
        db, tenant_id=user.current_tenant_id, channel=channel, created_by=user.user_id,
        options={"tags": payload.tags, "estimated_taken_on": payload.estimated_taken_on, "include_gps": payload.include_gps},
        event_id=target.event_id, submission_assignment_id=target.assignment_id,
        submission_element_ref=payload.submission_element_ref if target.assignment_id is not None else None,
        submission_element_label=target.element_label, cycle_config_id=target.cycle_config_id, protocol_todo_id=todo_id,
    )
    db.commit()
    db.refresh(job)
    return _to_read(job, user, _names(db, [job]), _refs(db, [job], user.current_tenant_id, user))


@router.post("/upload-jobs/{job_id}/complete", response_model=UploadJobRead)
def complete_upload_job(job_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Der Browser hat alle Pakete gesendet; abgeschlossen wird, sobald der Ingest fertig ist."""
    require_any_permission(user, P.PHOTOS_MANAGE, P.FILES_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=404, detail="Upload-Vorgang nicht gefunden")
    job = upload_job_service.attach(db, user, job_id, tuple(upload_job_service.OPENABLE_CHANNELS), lock=True)
    upload_job_service.client_complete(db, job)
    db.commit()
    db.refresh(job)
    return _to_read(job, user, _names(db, [job]), _refs(db, [job], user.current_tenant_id, user))


@router.post("/upload-jobs/{job_id}/client-results", status_code=204)
def report_client_results(
    job_id: uuid.UUID, payload: UploadClientResults, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)
):
    """Vom Browser vor dem Senden abgelehnte Dateien (E-14), gekennzeichnet als source=client."""
    require_any_permission(user, P.PHOTOS_MANAGE, P.FILES_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=404, detail="Upload-Vorgang nicht gefunden")
    job = upload_job_service.attach(db, user, job_id, tuple(upload_job_service.OPENABLE_CHANNELS), lock=True)
    reported = db.scalar(
        select(func.count()).select_from(UploadJobItem).where(UploadJobItem.upload_job_id == job.id, UploadJobItem.source == "client")
    ) or 0
    if reported + len(payload.items) > MAX_CLIENT_RESULTS_PER_JOB:
        raise HTTPException(status_code=422, detail="Zu viele gemeldete Dateien")
    upload_job_service.record_items(
        db, job,
        [
            upload_job_service.ItemIn(status="rejected", name=item.name, reason_code=item.code, source="client", size_bytes=item.size)
            for item in payload.items
        ],
    )
    db.commit()


@router.get("/upload-jobs", response_model=UploadJobList)
def list_upload_jobs(
    mine: bool = Query(default=False),
    channel: Annotated[list[str] | None, Query()] = None,
    problems: bool = Query(default=False),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Verlauf, neueste zuerst, Keyset über (created_at, id), keine Gesamtzahl."""
    _require_read(user)
    query = select(UploadJob).where(upload_job_service.visibility_clause(db, user, mine_only=mine))
    if channel:
        query = query.where(UploadJob.channel.in_(channel[:12]))
    if problems:
        query = query.where(UploadJob.rejected + UploadJob.infected + UploadJob.failed > 0)
    if date_from is not None:
        query = query.where(UploadJob.created_at >= datetime.combine(date_from, time.min, tzinfo=UTC))
    if date_to is not None:
        query = query.where(UploadJob.created_at < datetime.combine(date_to, time.max, tzinfo=UTC))
    if cursor:
        created, last_id = _decode_cursor(cursor)
        query = query.where(or_(UploadJob.created_at < created, and_(UploadJob.created_at == created, UploadJob.id < last_id)))
    jobs = list(db.scalars(query.order_by(UploadJob.created_at.desc(), UploadJob.id.desc()).limit(limit + 1)))
    has_more = len(jobs) > limit
    jobs = jobs[:limit]
    names, refs = _names(db, jobs), _refs(db, jobs, user.current_tenant_id, user)
    return UploadJobList(
        items=[_to_read(job, user, names, refs) for job in jobs], next_cursor=_encode_cursor(jobs[-1]) if has_more and jobs else None
    )


@router.get("/upload-jobs/{job_id}", response_model=UploadJobDetail)
def get_upload_job(job_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    _require_read(user)
    job = upload_job_service.get_visible_job(db, user, job_id)
    count_query = (
        select(func.count(), func.count().filter(StoredFile.mime_type.like("image/%")))
        .select_from(StoredFile)
        .where(StoredFile.tenant_id == job.tenant_id, StoredFile.upload_job_id == job.id)
        .execution_options(include_trashed=True)
    )
    protocol_visible = _protocol_visible(db, user)
    if protocol_visible is not None:
        count_query = count_query.where(protocol_visible)
    files = db.execute(count_query).one()
    return _to_read(
        job, user, _names(db, [job]), _refs(db, [job], user.current_tenant_id, user), cls=UploadJobDetail,
        options=job.options or {}, import_job_id=job.import_job_id, file_count=int(files[0]), image_count=int(files[1]),
        cameras=upload_job_service.camera_groups(db, job),
    )


def _protocol_visible(db: Session, user: CurrentUser):
    """Wie GET /files (1.5.2, ProtocolReadScope): Dateien, die nur an nicht lesbaren Protokollen
    hängen (z. B. in einen Entwurf übernommene Fotos), erscheinen im Upload-Verlauf weder mit ID
    noch in Zählern. None = keine Einschränkung."""
    scope = AccessService().protocol_read_scope(db, user)
    return None if scope is None else protocol_file_clause(StoredFile.id, scope)


def _file_states(db: Session, user: CurrentUser, file_ids: set[int]) -> dict[int, UploadJobItemFile]:
    """Zustand je Datei (Papierkorb, späterer Virenfund, Prüfung ausstehend) und - nur für
    sichtbare Dateien - ID und Vorschaubild."""
    if not file_ids:
        return {}
    rows = db.execute(
        select(StoredFile.id, StoredFile.public_id, StoredFile.mime_type, StoredFile.scan_status, StoredFile.deleted_at)
        .where(StoredFile.tenant_id == user.current_tenant_id, StoredFile.id.in_(file_ids))
        .execution_options(include_trashed=True)
    ).all()
    visible = service.visible_overview_items(db, user, [row.public_id for row in rows if row.deleted_at is None])
    # Papierkorb: Zustand (und damit der Name) nur, wenn die Datei nicht ausschliesslich an nicht
    # lesbaren Protokollen hängt - sonst wie eine unsichtbare Datei
    protocol_visible = _protocol_visible(db, user)
    trashed_hidden: set[int] = set()
    trashed = [row.id for row in rows if row.deleted_at is not None]
    if protocol_visible is not None and trashed:
        trashed_hidden = set(trashed) - set(
            db.scalars(select(StoredFile.id).where(StoredFile.id.in_(trashed), protocol_visible).execution_options(include_trashed=True))
        )
    states: dict[int, UploadJobItemFile] = {}
    for row in rows:
        is_image = bool(row.mime_type and row.mime_type.startswith("image/"))
        if row.id in trashed_hidden:
            state = "hidden"
        elif row.deleted_at is not None:
            state = "trashed"
        elif row.scan_status in BLOCKED_SCAN_STATUSES:
            state = "infected_later"
        elif row.scan_status == "pending":
            state = "scan_pending"
        elif row.public_id not in visible:
            state = "hidden"
        else:
            state = "ok"
        shown = state in ("ok", "scan_pending") and row.public_id in visible
        states[row.id] = UploadJobItemFile(
            id=row.public_id if shown else None, state=state, is_image=is_image,
            thumbnail_url=service.build_thumbnail_url(row.public_id) if shown and is_image and state == "ok" else None,
        )
    return states


@router.get("/upload-jobs/{job_id}/items", response_model=UploadJobItemList)
def list_upload_job_items(
    job_id: uuid.UUID,
    status: Annotated[list[str] | None, Query()] = None,
    cursor: int | None = Query(default=None, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    _require_read(user)
    job = upload_job_service.get_visible_job(db, user, job_id)
    query = select(UploadJobItem).where(UploadJobItem.upload_job_id == job.id, UploadJobItem.tenant_id == job.tenant_id)
    if status:
        query = query.where(UploadJobItem.status.in_(status[:7]))
    if cursor is not None:
        query = query.where(UploadJobItem.id > cursor)
    rows = list(db.scalars(query.order_by(UploadJobItem.id).limit(limit + 1)))
    has_more = len(rows) > limit
    rows = rows[:limit]
    states = _file_states(db, user, {i for row in rows for i in (row.stored_file_id, row.existing_file_id) if i is not None})

    def visible_name(row: UploadJobItem) -> str | None:
        # Name nicht sichtbarer Dateien bleibt verborgen (Security-Review M-1)
        state = states.get(row.stored_file_id) if row.stored_file_id is not None else None
        return None if state is not None and state.state == "hidden" else row.original_name

    deleted = UploadJobItemFile(state="deleted")
    items = []
    for row in rows:
        file = states.get(row.stored_file_id) if row.stored_file_id is not None else (deleted if row.status == "uploaded" else None)
        items.append(
            UploadJobItemRead(
                id=row.id, position=row.position, name=visible_name(row), status=row.status, reason_code=row.reason_code,
                reason_params=row.reason_params or {}, source=row.source, size_bytes=row.size_bytes, mime_type=row.mime_type,
                applied=list(row.applied or []), file=file,
                existing_file=states.get(row.existing_file_id) if row.existing_file_id is not None else None,
            )
        )
    return UploadJobItemList(items=items, next_cursor=rows[-1].id if has_more and rows else None)


@router.get("/upload-jobs/{job_id}/file-ids", response_model=UploadJobFileIds)
def list_upload_job_file_ids(
    job_id: uuid.UUID,
    only_images: bool = Query(default=False),
    camera: str | None = Query(default=None, max_length=80),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Alle Dateien des Vorgangs, die die Person ändern darf (ohne Papierkorb), höchstens
    MAX_JOB_FILE_IDS - Grundlage für «Alle N dieses Uploads auswählen». Nicht beschreibbare
    (fehlendes Recht der Dateiart, Abgabe ausserhalb der Reichweite) fallen still weg; der
    Unterschied zu total wird angezeigt. Die Bulk-Endpunkte prüfen jede ID ohnehin erneut."""
    _require_read(user)
    job = upload_job_service.get_visible_job(db, user, job_id)
    query = select(StoredFile.id, StoredFile.public_id, StoredFile.mime_type).where(
        StoredFile.tenant_id == job.tenant_id, StoredFile.upload_job_id == job.id
    )
    if only_images:
        query = query.where(StoredFile.mime_type.like("image/%"))
    if camera:
        query = query.where(upload_job_service.camera_clause(db, job, camera))
    rows = db.execute(query.order_by(StoredFile.id).limit(MAX_JOB_FILE_IDS + 1)).all()
    truncated = len(rows) > MAX_JOB_FILE_IDS
    rows = rows[:MAX_JOB_FILE_IDS]
    readable = context_visibility_service.readable_assignment_ids(db, user)
    outside: set[int] = set()
    if readable is not None and rows:
        outside = set(
            db.scalars(
                select(StoredFile.id).where(
                    StoredFile.id.in_([row.id for row in rows]),
                    ~context_visibility_service.abgabe_scope_clause(StoredFile.id, readable),
                )
            )
        )
    protocol_visible = _protocol_visible(db, user)
    if protocol_visible is not None and rows:
        shown = set(db.scalars(select(StoredFile.id).where(StoredFile.id.in_([row.id for row in rows]), protocol_visible)))
        # Nicht sichtbare Dateien zählen auch nicht in total (kein Hinweis auf ihre Existenz)
        rows = [row for row in rows if row.id in shown]
    writable = [row.public_id for row in rows if row.id not in outside and may_manage(user, row.mime_type)]
    return UploadJobFileIds(file_ids=writable, total=len(rows), truncated=truncated)
