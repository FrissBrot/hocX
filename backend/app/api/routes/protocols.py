import json
import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.core.cycle_utils import format_cycle_name
from app.core.security import CurrentUser, get_current_user, require_reader, require_writer
from app.core.db import get_db
from app.core.redis_client import publish_best_effort
from app.schemas.protocol import AttendanceExcusePayload, NextSessionRead, ProtocolCreateFromTemplate, ProtocolCycleEventsRead, ProtocolListCycle, ProtocolRead, ProtocolTemplateSyncRead, ProtocolTodoRead, ProtocolUpdate, QuickTodoCreate, TodoListItem
from app.schemas.deletion import DeletionPreview, DeletionRequest, DeletionResultRead
from app.services import deletion_service, document_render_jobs, protocol_period_service, public_id_service
from app.services.access_service import AccessService
from app.services.audit_service import AuditService
from app.services.collaboration_service import protocol_channel
from app.services.event_service import EventService
from app.services.protocol_service import ProtocolService
from app.services.protocol_todo_service import ProtocolTodoService
from app.models.entities import CycleConfig, DocumentExport, Participant, Protocol, ProtocolElement, StoredFile, Template, UserProtocolScroll, UserProtocolTemplatePreference, WordImportDocument

router = APIRouter()
service = ProtocolService()
todo_service = ProtocolTodoService()
access_service = AccessService()
audit = AuditService()
event_service = EventService()


def _broadcast_template_synced(protocol_id: int, user: CurrentUser) -> None:
    """Offene Editoren dieses Protokolls laden nach einem Vorlagen-Abgleich neu (Blöcke
    wurden ersetzt/ergänzt) - gleicher Kanal wie protocol_elements._broadcast_block_update."""
    publish_best_effort(
        protocol_channel(protocol_id),
        json.dumps({
            "type": "field_update",
            "field_key": "template-synced",
            "patch": None,
            "user_id": user.user_id,
            "display_name": user.display_name,
        }),
    )


def _get_protocol_or_404(db: Session, protocol_id: uuid.UUID, user: CurrentUser) -> Protocol:
    protocol = public_id_service.get_by_public_id(db, Protocol, protocol_id, tenant_id=user.current_tenant_id)
    if protocol is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    return protocol


def _cycle_configs_by_template(db: Session, template_ids: set[int]) -> dict[int, CycleConfig]:
    rows = db.execute(
        select(Template.id, CycleConfig)
        .join(CycleConfig, CycleConfig.id == Template.cycle_config_id)
        .where(Template.id.in_(template_ids))
    ).all()
    return {template_id: cfg for template_id, cfg in rows}


def _protocol_list_cycle(protocol_date: date, cfg: CycleConfig | None, *, today: date) -> ProtocolListCycle:
    """Zyklus eines Protokolls fuer die Gruppierung der Liste - dieselben Grenzen wie die
    Protokoll-Nummerierung (ProtocolService._cycle_bounds), Vorlage ohne Zyklus = Kalenderjahr
    (Reset 31.12., wie dort). Name: Muster der CycleConfig, sonst "<Name> <cy>/<cy_end>"."""
    reset_month, reset_day = (cfg.reset_month, cfg.reset_day) if cfg is not None else (12, 31)
    start, end = service._cycle_bounds(protocol_date, reset_month=reset_month, reset_day=reset_day)
    cycle_year = start.year
    if cfg is None:
        key, name = f"year:{cycle_year}", None
    else:
        key = f"{cfg.public_id}:{cycle_year}"
        name = (
            format_cycle_name(cfg.name_pattern, cycle_year)
            if cfg.name_pattern
            else f"{cfg.name} {format_cycle_name(None, cycle_year)}"
        )
    return ProtocolListCycle(
        key=key,
        name=name,
        cycle_year=cycle_year,
        start_date=start,
        end_date=end,
        is_current=start <= today <= end,
    )


def _build_protocol_reads(db: Session, protocols: list) -> list[ProtocolRead]:
    """Converts raw Protocol ORM rows to ProtocolRead, bulk-attaching the latest PDF url
    and Word-Import source link. Side-loaded data is looked up by the ORM rows' *internal*
    ids (still available here, before conversion to ProtocolRead's public id) - keep this
    combined instead of splitting into separate pre/post-conversion passes, since anything
    keying off ProtocolRead.id after conversion would only have the public UUID, not the
    internal id these joins need."""
    internal_ids = [p.id for p in protocols]
    if not internal_ids:
        return []

    pdf_rows = db.execute(
        select(DocumentExport.protocol_id, StoredFile.public_id.label("file_public_id"))
        .join(StoredFile, StoredFile.id == DocumentExport.stored_file_id)
        .where(
            DocumentExport.protocol_id.in_(internal_ids),
            DocumentExport.document_type == "protocol",
        )
        .order_by(DocumentExport.created_at.desc(), DocumentExport.id.desc())
    ).all()
    pdf_by_protocol: dict[int, uuid.UUID] = {}
    for row in pdf_rows:
        if row.protocol_id not in pdf_by_protocol:
            pdf_by_protocol[row.protocol_id] = row.file_public_id

    import_rows = db.execute(
        select(
            WordImportDocument.protocol_id,
            WordImportDocument.original_filename,
            StoredFile.public_id.label("stored_file_public_id"),
        )
        .join(StoredFile, StoredFile.id == WordImportDocument.stored_file_id)
        .where(WordImportDocument.protocol_id.in_(internal_ids))
    ).all()
    import_by_protocol = {row.protocol_id: (row.original_filename, row.stored_file_public_id) for row in import_rows}

    cycle_by_template = _cycle_configs_by_template(db, {p.template_id for p in protocols})
    ProtocolRead.prime_public_ids(db, protocols)
    today = date.today()

    result = []
    for p in protocols:
        r = ProtocolRead.model_validate(p)
        r.cycle = _protocol_list_cycle(p.protocol_date, cycle_by_template.get(p.template_id), today=today)
        if p.id in pdf_by_protocol:
            r.latest_pdf_url = f"/api/stored-files/{pdf_by_protocol[p.id]}/content"
        if p.id in import_by_protocol:
            filename, stored_file_public_id = import_by_protocol[p.id]
            r.import_source_filename = filename
            r.import_source_url = f"/api/stored-files/{stored_file_public_id}/content"
        result.append(r)
    return result


@router.get("/protocols", response_model=list[ProtocolRead])
def list_protocols(
    q: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    # Unrestricted readers may only see finalized protocols; restricted readers are further
    # scoped below via restrict_to_assigned. Kassier/writer/admin see everything, all statuses.
    if user.current_role == "reader" and not access_service._is_restricted_reader(db, user):
        status_filter = "abgeschlossen"
        q = None
    protocols = service.list_protocols(
        db,
        tenant_id=user.current_tenant_id,
        query=q,
        status=status_filter,
        user_id=user.user_id,
        restrict_to_assigned=access_service._is_restricted_reader(db, user),
        skip=skip,
        limit=limit,
    )
    return _build_protocol_reads(db, protocols)


class TemplatePreferencePayload(BaseModel):
    template_id: uuid.UUID | None = None


@router.get("/protocols/template-preference", response_model=TemplatePreferencePayload)
def get_template_preference(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_writer(user)
    row = db.get(UserProtocolTemplatePreference, (user.user_id, user.current_tenant_id))
    template = db.get(Template, row.template_id) if row and row.template_id else None
    return {"template_id": template.public_id if template and template.tenant_id == user.current_tenant_id else None}


@router.put("/protocols/template-preference", status_code=status.HTTP_204_NO_CONTENT)
def save_template_preference(payload: TemplatePreferencePayload, db: Session = Depends(get_db),
                             user: CurrentUser = Depends(get_current_user)):
    require_writer(user)
    template_id = None
    if payload.template_id is not None:
        template_id = public_id_service.resolve_internal_id(db, Template, payload.template_id, tenant_id=user.current_tenant_id)
        if template_id is None:
            raise HTTPException(status_code=404, detail="Template not found")
    db.execute(pg_insert(UserProtocolTemplatePreference)
               .values(user_id=user.user_id, tenant_id=user.current_tenant_id, template_id=template_id)
               .on_conflict_do_update(index_elements=["user_id", "tenant_id"], set_={"template_id": template_id}))
    db.commit()


@router.get("/protocols/preview", response_model=dict[str, str | None])
def preview_protocol(template_id: uuid.UUID, protocol_date: date,
                     db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_writer(user)
    template = public_id_service.get_by_public_id(db, Template, template_id, tenant_id=user.current_tenant_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return service.preview_names(db, tenant_id=user.current_tenant_id, template=template, protocol_date=protocol_date)


@router.post("/protocols/from-template", response_model=dict[str, uuid.UUID], status_code=status.HTTP_201_CREATED)
def create_protocol_from_template(
    payload: ProtocolCreateFromTemplate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    try:
        protocol_id = service.create_from_template(db, payload, tenant_id=user.current_tenant_id, created_by=user.user_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Protocol could not be created") from exc
    protocol_public_id = public_id_service.resolve_public_id(db, Protocol, protocol_id)
    return {"id": protocol_public_id}


@router.get("/protocols/next-session", response_model=NextSessionRead)
def get_next_session(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_reader(user)
    return service.get_next_session_attendance(db, user.current_tenant_id)


@router.get("/protocols/upcoming-sessions", response_model=list[NextSessionRead])
def get_upcoming_sessions(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_reader(user)
    protocol_ids = None
    if access_service._is_restricted_reader(db, user):
        protocol_ids = access_service.repository.list_protocol_ids(db, user_id=user.user_id, tenant_id=user.current_tenant_id)
    return service.get_upcoming_sessions_attendance(db, user.current_tenant_id, protocol_ids=protocol_ids)


@router.post("/protocols/{protocol_id}/attendance/{participant_id}/excuse", response_model=dict[str, str])
def excuse_participant(
    protocol_id: uuid.UUID,
    participant_id: uuid.UUID,
    payload: AttendanceExcusePayload = AttendanceExcusePayload(),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    protocol = _get_protocol_or_404(db, protocol_id, user)
    participant_internal_id = public_id_service.resolve_internal_id(db, Participant, participant_id, tenant_id=user.current_tenant_id)
    if participant_internal_id is None:
        raise HTTPException(status_code=404, detail="Participant not found")
    # Frozen (abgeschlossen) protocols must never have their attendance/fines touched after
    # the fact - matches the guard every other write path on a protocol's content goes through.
    service.get_protocol_or_404_not_frozen(db, protocol.id)
    try:
        updated = service.set_attendance_excused(db, protocol.id, participant_internal_id, payload.excused)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Attendance status could not be updated") from exc
    if not updated:
        raise HTTPException(status_code=404, detail="No attendance entry found for this participant")
    return {"message": "Participant excused" if payload.excused else "Participant marked unentschuldigt"}


@router.get("/protocols/{protocol_id}", response_model=ProtocolRead)
def get_protocol(protocol_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_reader(user)
    protocol = _get_protocol_or_404(db, protocol_id, user)
    access_service.ensure_can_read_protocol(db, user, protocol.id)
    return _build_protocol_reads(db, [protocol])[0]


@router.patch("/protocols/{protocol_id}", response_model=ProtocolRead)
def patch_protocol(
    protocol_id: uuid.UUID,
    payload: ProtocolUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    existing = _get_protocol_or_404(db, protocol_id, user)
    protocol_id = existing.id
    # Vor dem Update festhalten: existing ist dasselbe Objekt, das update_protocol ändert.
    previous_status = existing.status
    if payload.session_notes is not None and payload.expected_session_notes is not None:
        # Audit MAIN-BE-011: Protokollzeile bis zum Commit sperren und frisch lesen, damit
        # zwei gleichzeitige Saves mit gleichem erwarteten Stand nicht beide durchgehen.
        existing = db.scalar(
            select(Protocol).where(Protocol.id == protocol_id).with_for_update().execution_options(populate_existing=True)
        )
    if (
        payload.session_notes is not None
        and payload.expected_session_notes is not None
        and payload.expected_session_notes != (existing.session_notes or "")
    ):
        raise HTTPException(
            status_code=409,
            detail="Die Sitzungsnotizen wurden zwischenzeitlich geändert. Der lokale Entwurf bleibt erhalten.",
        )
    try:
        protocol = service.update_protocol(db, protocol_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Protocol could not be updated") from exc
    if protocol is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    if payload.status is not None and payload.status != previous_status:
        audit.log(db, action="protocol.status_changed", actor=user, entity_type="protocol", entity_id=protocol_id,
                  details={"from": previous_status, "to": payload.status})
        if payload.status == "abgeschlossen":
            # Signiertes Protokoll-PDF als dauerhafter Auftrag für den job-worker (CONC-020) statt
            # als BackgroundTask im Request-Prozess (ging bei Neustart oder belegtem Compile-Platz verloren).
            document_render_jobs.enqueue_protocol_pdf(db, protocol=protocol)
    return protocol


_PREVIOUS_STATUS: dict[str, str] = {
    "vorbereitet": "geplant",
    "durchgeführt": "vorbereitet",
    "abgeschlossen": "durchgeführt",
}


@router.post("/protocols/{protocol_id}/revert-status", response_model=ProtocolRead)
def revert_protocol_status(
    protocol_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    existing = _get_protocol_or_404(db, protocol_id, user)
    prev = _PREVIOUS_STATUS.get(existing.status)
    if prev is None:
        raise HTTPException(status_code=400, detail="Protocol is already at the initial status")
    try:
        protocol = service.update_protocol(db, existing.id, ProtocolUpdate(status=prev))
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Status could not be reverted") from exc
    if protocol is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    audit.log(db, action="protocol.status_reverted", actor=user, entity_type="protocol", entity_id=existing.id,
              details={"from": existing.status, "to": prev})
    return protocol


@router.post("/protocols/{protocol_id}/sync-template", response_model=ProtocolTemplateSyncRead)
def sync_protocol_with_template(
    protocol_id: uuid.UUID,
    dry_run: bool = Query(False),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Elemente eines offenen Protokolls aus der aktuellen Vorlage neu laden, erfasste Daten
    bleiben erhalten. Mit dry_run=true nur die Übersicht der Änderungen."""
    require_writer(user)
    existing = _get_protocol_or_404(db, protocol_id, user)
    access_service.ensure_can_read_protocol(db, user, existing.id)
    try:
        summary = service.sync_with_template(db, existing.id, dry_run=dry_run)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Protocol could not be synced with its template") from exc
    if summary["applied"]:
        audit.log(db, action="protocol.template_synced", actor=user, entity_type="protocol", entity_id=existing.id,
                  details={key: value for key, value in summary.items() if key != "applied"})
        _broadcast_template_synced(existing.id, user)
    return summary


@router.get("/protocols/{protocol_id}/pending-todos", response_model=list[TodoListItem])
def get_pending_todos(
    protocol_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Open session todos from earlier protocols of the same template. Abgeschlossene
    Protokolle zeigen den Stand beim Abschluss (Momentaufnahme)."""
    require_reader(user)
    protocol = _get_protocol_or_404(db, protocol_id, user)
    snapshot = todo_service.frozen_snapshot(protocol)
    if snapshot is not None:
        return todo_service.snapshot_pending(snapshot)
    return todo_service.list_pending_for_protocol(
        db,
        protocol_id=protocol.id,
        template_id=protocol.template_id,
        protocol_date=protocol.protocol_date,
    )


@router.get("/protocols/{protocol_id}/period", response_model=dict[str, str | None])
def get_protocol_period(
    protocol_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Datum des vorherigen Protokolls und Zyklusgrenzen (Finanz- und Bussenblöcke)."""
    require_reader(user)
    protocol = _get_protocol_or_404(db, protocol_id, user)
    return protocol_period_service.protocol_period(db, protocol)


@router.get("/protocols/{protocol_id}/cycle-events", response_model=ProtocolCycleEventsRead)
def get_cycle_events(
    protocol_id: uuid.UUID,
    scope: str = Query("current", pattern="^(current|all)$"),
    search: str = Query(""),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    cycle_config_id: uuid.UUID | None = Query(None),
    cycle_offset: int = Query(0, ge=-10, le=10),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Termin-Pool für die Planungsmodus-Popups (Terminübersicht, Checkbox-Auswahl).

    scope=current: nur Termine des aktuellen Zyklus des Protokolls (Template-CycleConfig
    + protocol_date). Fällt auf alle Termine zurück (cycle=null), wenn kein Zyklus
    konfiguriert ist. scope=all: alle Termine des Mandanten, unabhängig vom Zyklus.
    cycle_config_id/cycle_offset: Termine eines bestimmten Zyklus relativ zum
    Protokolldatum (Zyklus-Filter automatischer Matrix-Spalten), überschreibt scope.
    """
    require_reader(user)
    protocol = _get_protocol_or_404(db, protocol_id, user)
    try:
        items, total, cycle = event_service.list_for_protocol_cycle(
            db, protocol=protocol, scope=scope, search=search, skip=skip, limit=limit,
            cycle_config_public_id=cycle_config_id, cycle_offset=cycle_offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ProtocolCycleEventsRead(items=items, total=total, cycle=cycle)


@router.post("/protocols/{protocol_id}/quick-todos", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_quick_todo(
    protocol_id: uuid.UUID,
    payload: QuickTodoCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Create a session todo, auto-creating the Sitzungsnotizen element+block if needed."""
    require_writer(user)
    existing = _get_protocol_or_404(db, protocol_id, user)
    # Same freeze guard as todos.py's create_todo/patch_todo/delete_todo - a frozen
    # (abgeschlossen) protocol must not gain new blocks/todos after the fact.
    service.get_protocol_or_404_not_frozen(db, existing.id)
    try:
        block, todo = service.create_quick_todo(
            db,
            protocol_id=existing.id,
            task=payload.task,
            tag=payload.tag,
            created_by=user.user_id,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Todo could not be created") from exc
    return {
        "block_id": block.public_id,
        "todo_id": todo.public_id,
        "element_id": public_id_service.resolve_public_id(db, ProtocolElement, block.protocol_element_id),
    }


def _delete_protocol_with_files(db: Session, existing: Protocol, user: CurrentUser, delete_file_ids: set[uuid.UUID] | None) -> DeletionResultRead:
    """Gemeinsamer Ablauf von DELETE (alle Dateien) und POST …/delete (Auswahl) - PRIV-004."""
    from app.services.file_service import FileService

    service.get_protocol_or_404_not_frozen(db, existing.id)
    audit_details = {"protocol_number": existing.protocol_number, "title": existing.title, "status": existing.status}
    protocol_internal_id = existing.id
    try:
        result = deletion_service.delete_protocol(db, existing, delete_file_ids=delete_file_ids, actor_user_id=user.user_id, file_service=FileService())
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Protocol could not be deleted") from exc
    audit.log(
        db, action="protocol.deleted", actor=user, entity_type="protocol", entity_id=protocol_internal_id,
        details={**audit_details, "deleted_files": result.deleted_files, "kept_files": result.kept_files},
    )
    return DeletionResultRead(deleted_files=result.deleted_files, kept_files=result.kept_files, untouched_files=result.untouched_files)


@router.get("/protocols/{protocol_id}/deletion-preview", response_model=DeletionPreview)
def preview_protocol_deletion(
    protocol_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Welche Bilder mit dem Protokoll verschwinden würden (Lösch-Dialog, Datenschutz-Audit PRIV-004)."""
    require_writer(user)
    existing = _get_protocol_or_404(db, protocol_id, user)
    return deletion_service.preview_read(deletion_service.protocol_preview(db, existing))


@router.post("/protocols/{protocol_id}/delete", response_model=DeletionResultRead)
def delete_protocol_with_selection(
    protocol_id: uuid.UUID,
    payload: DeletionRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Löscht das Protokoll; gewählte Bilder werden mitgelöscht, die übrigen in die Galerie übernommen."""
    require_writer(user)
    existing = _get_protocol_or_404(db, protocol_id, user)
    return _delete_protocol_with_files(db, existing, user, set(payload.delete_file_ids))


@router.delete("/protocols/{protocol_id}", response_model=dict[str, str])
def delete_protocol(
    protocol_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Ohne Auswahl: alle Bilder, die nur dieses Protokoll verwendet, werden mitgelöscht."""
    require_writer(user)
    existing = _get_protocol_or_404(db, protocol_id, user)
    _delete_protocol_with_files(db, existing, user, None)
    return {"message": "Protocol deleted"}


class ElementPositionPayload(BaseModel):
    element_id: uuid.UUID


@router.get("/protocols/{protocol_id}/scroll-position")
def get_element_position(
    protocol_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    # Audit S11, 2026-08-16: only require_reader (any tenant) was checked before, no
    # protocol-tenant scoping - the (user_id, protocol_id) key limits blast radius (can only
    # ever affect this user's own remembered scroll position), but a fremde protocol_id
    # should still 404 rather than silently succeed.
    protocol = _get_protocol_or_404(db, protocol_id, user)
    row = db.get(UserProtocolScroll, (user.user_id, protocol.id))
    if row is None:
        return {"element_id": None}
    return {"element_id": public_id_service.resolve_public_id(db, ProtocolElement, row.last_element_id)}


@router.put("/protocols/{protocol_id}/scroll-position", status_code=status.HTTP_204_NO_CONTENT)
def save_element_position(
    protocol_id: uuid.UUID,
    payload: ElementPositionPayload,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    # Audit S11, 2026-08-16 - see get_element_position's identical check above.
    protocol = _get_protocol_or_404(db, protocol_id, user)
    # Nur Elemente dieses Protokolls (Security-Audit SEC-015).
    element = public_id_service.get_by_public_id(db, ProtocolElement, payload.element_id)
    if element is None or element.protocol_id != protocol.id:
        raise HTTPException(status_code=404, detail="Element not found")
    element_internal_id = element.id
    stmt = (
        pg_insert(UserProtocolScroll)
        .values(user_id=user.user_id, protocol_id=protocol.id, last_element_id=element_internal_id)
        .on_conflict_do_update(
            index_elements=["user_id", "protocol_id"],
            set_={"last_element_id": element_internal_id, "updated_at": func.now()},
        )
    )
    db.execute(stmt)
    db.commit()
