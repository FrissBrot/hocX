import uuid
from types import SimpleNamespace

from sqlalchemy import case, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.schemas.base import MAX_QUERY_OFFSET
from app.core.db import get_db
from app.core.permissions import P
from app.core.security import CurrentUser, get_current_user, permission_denied, require_permission
from app.models.entities import ElementType, Event, Protocol, ProtocolElement, ProtocolElementBlock, ProtocolTodo, Template
from app.schemas.protocol import (
    ProtocolTodoCreate,
    ProtocolTodoRead,
    ProtocolTodoUpdate,
    TodoDetails,
    TodoDetailsUpdate,
    TodoListItem,
    TodoSubmissionCreated,
    TodoSubmissionStatus,
)
from app.services import public_id_service
from app.services.access_service import AccessService
from app.services.audit_service import AuditService
from app.services.protocol_service import ProtocolService
from app.services.protocol_todo_service import ProtocolTodoService
from app.services.file_service import FileService
from app.services import submission_reviewer_service as submission_reviewers
from app.services import todo_fine_service, todo_submission_service
from app.core.sql_like import LIKE_ESCAPE, contains_pattern

router = APIRouter()
_file_service = FileService()
service = ProtocolTodoService()
access_service = AccessService()
audit = AuditService()
protocol_service = ProtocolService()


def _todo_or_404(db: Session, user: CurrentUser, todo_id: uuid.UUID) -> ProtocolTodo:
    """Todo des eigenen Mandanten mit Leserecht. Fremde und unbekannte IDs ergeben 404 (kein
    Existenz-Orakel über Mandanten hinweg, SECURITY-RULES 1.1/1.6)."""
    if user.current_tenant_id is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    todo = public_id_service.get_by_public_id(db, ProtocolTodo, todo_id, tenant_id=user.current_tenant_id)
    if todo is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    access_service.ensure_can_read_todo(db, user, todo.id)
    return todo


def _todo_block_or_404(db: Session, user: CurrentUser, block_id: uuid.UUID) -> ProtocolElementBlock:
    """Block des eigenen Mandanten. ProtocolElementBlock hat keine eigene tenant_id (tenant_id= an
    public_id_service ist dort wirkungslos): über das Protokoll prüfen, damit ein fremder Block
    wie ein unbekannter 404 ergibt statt 403 (Existenz-Orakel, SECURITY-RULES 1.6)."""
    block = public_id_service.get_by_public_id(db, ProtocolElementBlock, block_id)  # nosemgrep: public-id-lookup-without-tenant -- Mandant über das Protokoll direkt danach
    if block is None or user.current_tenant_id is None or service.repository.tenant_id_for_block(db, block.id) != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Protocol element block not found")
    return block


def _get_protocol_or_404(db: Session, protocol_id: int):
    """Todos leben über ihr Protokoll hinaus: auch nach "abgeschlossen" dürfen sie angelegt,
    bearbeitet, erledigt und gelöscht werden. Deshalb hier bewusst nicht
    get_protocol_or_404_not_frozen - das abgeschlossene Protokoll selbst zeigt die beim
    Abschluss eingefrorene Momentaufnahme (protocol.todos_snapshot_json)."""
    protocol = protocol_service.get_protocol(db, protocol_id)
    if protocol is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    return protocol


@router.post("/todos", response_model=TodoListItem, status_code=status.HTTP_201_CREATED)
def create_standalone_todo(
    payload: ProtocolTodoCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Create a todo not tied to any protocol block."""
    require_permission(user, P.MEETINGS_EDIT)
    try:
        todo = service.create_standalone_todo(db, user.current_tenant_id, payload, actor_user_id=user.user_id)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Todo could not be created") from exc
    row = service.repository.get_row(db, todo.id)
    if row is None:
        raise HTTPException(status_code=500, detail="Created todo not found")
    return service._row_to_list_item(db, row)


@router.get("/todos/blocks")
def list_todo_blocks(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Aufgabenblöcke der Protokolle, die der Benutzer lesen darf (dieselbe Regel wie die
    Protokollliste - vorher sahen eingeschränkte Leser hier Titel aller Protokolle, S-3)."""
    require_permission(user, P.MEETINGS_READ)
    return service.list_todo_blocks(db, user.current_tenant_id, visible=access_service.protocol_visibility(db, user))


@router.get("/todos/tags", response_model=list[str])
def list_todo_tags(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Alle Tags, die Pendenzen des Mandanten tragen (Vorschläge, z. B. «Tags für die Pendenzen» im
    Abgabe-Assistenten) - nicht die Termin- oder Datei-Tags. Eingeschränkte Leser bekommen keine
    Vorschläge (sie sehen nicht alle Pendenzen)."""
    require_permission(user, P.MEETINGS_READ)
    if access_service._is_restricted_reader(db, user):
        return []
    rows = db.execute(
        text(
            "SELECT DISTINCT tag FROM protocol_todo, jsonb_array_elements_text(tags) AS tag"
            " WHERE tenant_id = :tenant_id AND jsonb_typeof(tags) = 'array' LIMIT 2000"
        ),
        {"tenant_id": user.current_tenant_id},
    ).scalars().all()
    seen: dict[str, str] = {}
    for tag in rows:
        value = str(tag).strip()
        if value and value.lower() not in seen:
            seen[value.lower()] = value
    return sorted(seen.values(), key=str.casefold)


@router.get("/todos", response_model=list[TodoListItem])
def list_all_todos(
    skip: int = Query(default=0, ge=0, le=MAX_QUERY_OFFSET),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Every role sees all tenant todos, except restricted readers (participant-linked or
    otherwise scoped accounts) who only see todos from protocols they have access to, plus
    anything directly assigned to them."""
    require_permission(user, P.MEETINGS_READ)
    if access_service._is_restricted_reader(db, user):
        protocol_ids = access_service.repository.list_protocol_ids(db, user_id=user.user_id, tenant_id=user.current_tenant_id)
        return service.list_todos_for_protocols_or_assigned(db, user.current_tenant_id, protocol_ids, user.user_id, skip=skip, limit=limit)
    return service.list_todos_for_tenant(db, user.current_tenant_id, skip=skip, limit=limit)


@router.get("/todos/my", response_model=list[TodoListItem])
def list_my_todos(
    skip: int = Query(default=0, ge=0, le=MAX_QUERY_OFFSET),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Always returns only todos assigned to the current user."""
    require_permission(user, P.MEETINGS_READ)
    return service.list_todos_for_user(db, user.current_tenant_id, user.user_id, skip=skip, limit=limit)


@router.get("/protocol-element-blocks/{protocol_element_block_id}/todos", response_model=list[ProtocolTodoRead])
def list_todos(
    protocol_element_block_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_READ)
    block = _todo_block_or_404(db, user, protocol_element_block_id)
    # Gleiche Prüfung wie ensure_can_read_protocol_block, aber das Protokoll nur einmal ermitteln
    protocol_id = access_service.repository.protocol_id_for_block(db, protocol_element_block_id=block.id)
    if protocol_id is None:
        raise HTTPException(status_code=404, detail="Protocol element block not found")
    # Meldung wie _todo_block_or_404: nicht lesbarer Entwurf = unbekannter Block
    access_service.ensure_can_read_protocol(db, user, protocol_id, detail="Protocol element block not found")
    snapshot = _frozen_todo_snapshot(db, protocol_id)
    if snapshot is not None:
        return service.snapshot_todos_for_block(snapshot, block.id)
    return service.list_todos(db, block.id)


def _frozen_todo_snapshot(db: Session, protocol_id: int) -> dict | None:
    """Eingefrorene Aufgaben eines abgeschlossenen Protokolls (frozen_snapshot), ohne die ganze
    Protokollzeile zu laden: das Snapshot-JSON nur, wenn das Protokoll abgeschlossen ist."""
    row = db.execute(
        select(
            Protocol.status,
            case((Protocol.status == "abgeschlossen", Protocol.todos_snapshot_json), else_=None).label("todos_snapshot_json"),
        ).where(Protocol.id == protocol_id)
    ).one_or_none()
    if row is None:
        return None
    return service.frozen_snapshot(SimpleNamespace(status=row.status, todos_snapshot_json=row.todos_snapshot_json))


@router.get("/protocols/{protocol_id}/block-todos", response_model=dict[uuid.UUID, list[ProtocolTodoRead]])
def list_protocol_block_todos(
    protocol_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Aufgaben aller Aufgabenblöcke eines Protokolls in einer Anfrage (Block-public_id ->
    Liste wie GET /protocol-element-blocks/{id}/todos). Die Protokollseite holte sie vorher
    mit einer Anfrage je Block. Gleiche Prüfungen wie die Einzelroute: meetings.read und
    Leserecht am Protokoll (Mandant, Status, Teilnehmer-Zuordnung); fremde oder unbekannte
    Protokolle ergeben 404."""
    require_permission(user, P.MEETINGS_READ)
    protocol = public_id_service.get_by_public_id(db, Protocol, protocol_id, tenant_id=user.current_tenant_id)
    if protocol is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    access_service.ensure_can_read_protocol(db, user, protocol.id)
    blocks = db.execute(
        select(ProtocolElementBlock.id, ProtocolElementBlock.public_id)
        .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
        .join(ElementType, ElementType.id == ProtocolElementBlock.element_type_id)
        .where(ProtocolElement.protocol_id == protocol.id, ElementType.code == "todo")
        .order_by(ProtocolElement.sort_index.asc(), ProtocolElementBlock.sort_index.asc(), ProtocolElementBlock.id.asc())
    ).all()
    result: dict[uuid.UUID, list[ProtocolTodoRead]] = {}
    snapshot = service.frozen_snapshot(protocol)
    if snapshot is not None:
        for block_id, block_public_id in blocks:
            result[block_public_id] = service.snapshot_todos_for_block(snapshot, block_id)
        return result
    query, *_ = service.repository._base_todo_query()
    rows = db.execute(
        query.where(ProtocolTodo.protocol_element_block_id.in_([block_id for block_id, _ in blocks])).order_by(
            ProtocolTodo.protocol_element_block_id.asc(), ProtocolTodo.sort_index.asc(), ProtocolTodo.id.asc()
        )
    ).all() if blocks else []
    service._prime_public_ids(db, rows)
    rows_by_block: dict[int, list] = {}
    for row in rows:
        rows_by_block.setdefault(row.ProtocolTodo.protocol_element_block_id, []).append(row)
    for block_id, block_public_id in blocks:
        result[block_public_id] = [service._row_to_todo_read(db, row) for row in rows_by_block.get(block_id, [])]
    return result


@router.post(
    "/protocol-element-blocks/{protocol_element_block_id}/todos",
    response_model=ProtocolTodoRead,
    status_code=status.HTTP_201_CREATED,
)
def create_todo(
    protocol_element_block_id: uuid.UUID,
    payload: ProtocolTodoCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_EDIT)
    block = _todo_block_or_404(db, user, protocol_element_block_id)
    protocol_id = access_service.repository.protocol_id_for_block(db, protocol_element_block_id=block.id)
    if protocol_id is None:
        raise HTTPException(status_code=404, detail="Protocol element block not found")
    access_service.ensure_can_read_protocol(db, user, protocol_id, detail="Protocol element block not found")
    protocol = _get_protocol_or_404(db, protocol_id)
    track_changes_active = bool(protocol.status == "geplant" and protocol.track_changes_enabled)
    try:
        todo = service.create_todo(db, block.id, payload, track_changes_active=track_changes_active, actor_user_id=user.user_id)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Todo could not be created") from exc
    todos = service.list_todos(db, block.id)
    return next(item for item in todos if item.id == todo.public_id)


@router.get("/protocol-todos/{todo_id}/due-events")
def get_todo_due_events(
    todo_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Return upcoming events for due-date selection, filtered by the template's todo_due_event_tag."""
    require_permission(user, P.MEETINGS_READ)
    todo = _todo_or_404(db, user, todo_id)
    today = todo_fine_service.today()

    tag_filter: str | None = None
    next_event_public_id: uuid.UUID | None = None

    if todo.protocol_element_block_id:
        row = db.execute(
            select(Template.todo_due_event_tag, Template.next_event_id)
            .join(Protocol, Protocol.template_id == Template.id)
            .join(ProtocolElement, ProtocolElement.protocol_id == Protocol.id)
            .join(ProtocolElementBlock, ProtocolElementBlock.protocol_element_id == ProtocolElement.id)
            .where(ProtocolElementBlock.id == todo.protocol_element_block_id)
        ).first()
        if row:
            tag_filter = row.todo_due_event_tag
            if row.next_event_id is not None:
                next_event_public_id = public_id_service.resolve_public_id(db, Event, row.next_event_id)

    stmt = select(Event).where(
        Event.tenant_id == user.current_tenant_id,
        Event.event_date >= today,
    )
    if tag_filter:
        tag_lower = tag_filter.strip().lower()
        stmt = stmt.where(Event.tag.ilike(contains_pattern(tag_lower), escape=LIKE_ESCAPE))
    stmt = stmt.order_by(Event.event_date.asc()).limit(50)
    events = db.execute(stmt).scalars().all()

    return {
        "next_event_id": next_event_public_id,
        "tag_filter": tag_filter,
        "events": [
            {
                "id": e.public_id,
                "title": e.title,
                "event_date": e.event_date.isoformat(),
                "event_end_date": e.event_end_date.isoformat() if e.event_end_date else None,
                "tag": e.tag,
            }
            for e in events
        ],
    }



# Validierungsfehler aus ProtocolTodoService.update_todo → stabiler Code und lesbare Meldung
_TODO_VALUE_ERRORS = {
    "Assigned participant is not available for this template": (
        "todo_assignee_unavailable",
        "Die verantwortliche Person ist für dieses Protokoll nicht mehr verfügbar (z. B. aus der Vorlage entfernt oder inaktiv). Bitte eine andere Person wählen.",
    ),
    "Assigned participants must be a list": ("todo_invalid", "Die Pendenz konnte nicht gespeichert werden: ungültige Angabe."),
    "Due event is not available for this tenant": ("todo_due_event_unavailable", "Der gewählte Fälligkeitstermin ist nicht mehr verfügbar."),
    "Assigned user is not available for this tenant": ("todo_assignee_unavailable", "Die verantwortliche Person ist nicht mehr verfügbar. Bitte eine andere Person wählen."),
    "Unknown todo status": ("todo_invalid", "Unbekannter Status."),
}

@router.patch("/protocol-todos/{todo_id}", response_model=ProtocolTodoRead)
def patch_todo(
    todo_id: uuid.UUID,
    payload: ProtocolTodoUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    # Deliberately not gated by the collaboration Redis lock the way
    # protocol_elements.py's block PATCH/text PUT now are: unlike protocol element blocks,
    # individual todos have no corresponding field_key in the collaboration lock domain
    # today (session-todos-section.tsx/todo-list-view.tsx never call lockField for a todo
    # edit - only the focused-element-editor's per-block/per-cell text and config fields
    # do). Adding a check here would either be a permanent no-op (no lock is ever held
    # under a "todo-<id>" key) or would have to piggyback on the parent block's lock, which
    # would reject normal todo edits any time someone else merely has that block's text
    # field focused - a worse false-positive than the gap it would close. Two people
    # editing the same todo concurrently therefore remains last-write-wins, same as before
    # this pass; a real fix would need the frontend to start locking todos as its own
    # field_key first.
    if user.can(P.MEETINGS_EDIT):
        existing = _todo_or_404(db, user, todo_id)
    else:
        # «Eigene Pendenzen erledigen» (Plan «Berechtigungen», Phase 3): nur den Status der
        # eigenen (zugewiesenen) Pendenz - ohne dieses Recht ist der Zugang read-only.
        require_permission(user, P.TODOS_COMPLETE_OWN)
        if payload.model_fields_set - {"todo_status_id", "completed_at"}:
            raise permission_denied()
        existing = _todo_or_404(db, user, todo_id)
        if user.user_id not in access_service._todo_assignee_user_ids(db, existing):
            raise HTTPException(status_code=404, detail="Todo not found")  # wie fremde: kein Orakel
    previous_status_id = existing.todo_status_id
    protocol_id = access_service.repository.protocol_id_for_todo(db, todo_id=existing.id)
    # Standalone todos (protocol_id None) have no protocol at all.
    protocol = _get_protocol_or_404(db, protocol_id) if protocol_id else None
    track_changes_active = bool(protocol and protocol.status == "geplant" and protocol.track_changes_enabled)
    fine_changes: dict = {}
    try:
        todo = service.update_todo(
            db, existing.id, payload, track_changes_active=track_changes_active, actor_user_id=user.user_id,
            can_manage_fines=user.can(P.FINES_MANAGE), fine_changes=fine_changes,
        )
    except todo_fine_service.TodoFineError as exc:
        # Die Prüfung läuft vor jedem Schreiben - nichts zurückzurollen
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc
    except ValueError as exc:
        # Erwartete Validierung (nicht ins Fehlerprotokoll): Grund mit stabilem Code zurückgeben,
        # statt ihn hinter «Todo could not be updated» zu verstecken
        db.rollback()
        code, message = _TODO_VALUE_ERRORS.get(str(exc), ("todo_invalid", "Die Pendenz konnte nicht gespeichert werden: ungültige Angabe."))
        raise HTTPException(status_code=400, detail={"code": code, "message": message}) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Todo could not be updated") from exc
    if todo is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    if payload.todo_status_id is not None and payload.todo_status_id != previous_status_id:
        audit.log(
            db, action="todo.status_changed", actor=user, entity_type="protocol_todo", entity_id=existing.id,
            details={"from_status_id": previous_status_id, "to_status_id": payload.todo_status_id},
        )
    if fine_changes:
        # Fälligkeit, Verantwortliche, Tags oder Abbrechen: kann eine laufende Busse ändern
        audit.log(db, action="todo.fine_relevant_changed", actor=user, entity_type="protocol_todo", entity_id=existing.id, details=fine_changes)
    if todo.protocol_element_block_id is None:
        # Standalone (z. B. aus einem Aufgabenpaket): nur diese eine Zeile laden statt aller
        # protokollfreien Todos.
        row = service.repository.get_row(db, todo.id)
        if row is None:
            raise HTTPException(status_code=404, detail="Todo not found")
        return service._row_to_todo_read(db, row)
    todos = service.list_todos(db, todo.protocol_element_block_id)
    return next(item for item in todos if item.id == todo_id)


@router.post("/protocol-todos/{todo_id}/create-submission", response_model=TodoSubmissionCreated, status_code=status.HTTP_201_CREATED)
def create_submission_from_todo(
    todo_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """«Als Abgabe einsammeln»: Einzelabgabe aus der Pendenz anlegen, die Pendenz wird die Pendenz
    ihres Elements (todo_submission_service). Braucht Abgaben verwalten (inkl. Modul Abgabebox)
    und Pendenzen bearbeiten wie PATCH /protocol-todos/{id}."""
    require_permission(user, P.SUBMISSIONS_MANAGE)  # bindet das Modul abgabebox (require_feature, write)
    require_permission(user, P.MEETINGS_EDIT)
    existing = _todo_or_404(db, user, todo_id)
    protocol_id = access_service.repository.protocol_id_for_todo(db, todo_id=existing.id)
    if protocol_id:
        protocol = _get_protocol_or_404(db, protocol_id)
        if protocol.status == "abgeschlossen":
            # Abgeschlossene Protokolle sind eingefroren (Momentaufnahme der Pendenzen)
            raise HTTPException(status_code=409, detail={"code": "protocol_closed", "message": "Das Protokoll ist abgeschlossen."})
    try:
        # Gebüsste Person selbst: Fälligkeit/Status liefen danach über die Abgabe (wie PATCH)
        todo_fine_service.ensure_may_change(db, existing, actor_user_id=user.user_id, can_manage=user.can(P.FINES_MANAGE))
        result = todo_submission_service.create_from_todo(db, existing, tenant_id=user.current_tenant_id)
    except todo_fine_service.TodoFineError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc
    except todo_submission_service.TodoSubmissionError as exc:
        # Alle Prüfungen laufen vor dem ersten Schreiben (create_from_todo) - nichts zurückzurollen
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail={"code": "submission_invalid", "message": str(exc)}) from exc
    except IntegrityError as exc:
        # Gleichzeitig derselbe Slug angelegt (uq_submission_assignment_tenant_slug) oder die
        # Pendenz eben verknüpft (uix_protocol_todo_submission_element)
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "submission_conflict", "message": "Die Abgabe konnte nicht erstellt werden. Bitte erneut versuchen."}) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Abgabe konnte nicht erstellt werden") from exc
    assignment = result.assignment
    audit.log(
        db, action="submission_assignment.created", actor=user, entity_type="submission_assignment", entity_id=assignment.id,
        details={"origin": "todo", "todo_id": str(existing.public_id), "title": assignment.title},
    )
    row = service.repository.get_row(db, existing.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    service._prime_public_ids(db, [row])
    return TodoSubmissionCreated(
        assignment_id=assignment.public_id,
        title=assignment.title,
        public_slug=assignment.public_slug,
        element_url=result.element_url,
        todo=service._row_to_list_item(db, row),
    )


@router.get("/protocol-todos/{todo_id}/submission", response_model=TodoSubmissionStatus)
def get_todo_submission(
    todo_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Laufende Abgabe der Pendenz für «Pendenz bearbeiten» › Dateien: Link, seit wann,
    eingereichte Dateien. Braucht Pendenzen lesen und Abgaben lesen in der eigenen Reichweite
    (die Antwort enthält den Link-Token); sonst 404 wie für eine unbekannte Pendenz."""
    require_permission(user, P.MEETINGS_READ)
    require_permission(user, P.SUBMISSIONS_READ)  # bindet das Modul abgabebox (lesend)
    todo = _todo_or_404(db, user, todo_id)
    assignment = todo_submission_service.linked_assignment(db, todo)
    if assignment is None or assignment.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail={"code": "todo_not_submission", "message": "Diese Pendenz gehört zu keiner Abgabe."})
    submission_reviewers.ensure_can_read(db, user, assignment)  # Reichweite «zugewiesene» → 404
    result = todo_submission_service.submission_status(db, todo, assignment)
    if result.can_stop:
        # «Beenden» nur anbieten, wenn die Route es auch erlaubte (Rechte wie stop-submission)
        result.can_stop = user.can(P.SUBMISSIONS_MANAGE) and user.can(P.MEETINGS_EDIT) and not _todo_protocol_closed(db, todo)
    return result


@router.post("/protocol-todos/{todo_id}/stop-submission", response_model=TodoListItem)
def stop_submission_from_todo(
    todo_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """«Beenden» im Abschnitt Dateien: Einsammeln abbrechen, solange nichts eingereicht ist. Die
    Pendenz bleibt (Status, Notizen, Dateien), die leere Einzelabgabe wird gelöscht
    (todo_submission_service.stop_collecting). Rechte wie create-submission."""
    require_permission(user, P.SUBMISSIONS_MANAGE)  # bindet das Modul abgabebox (require_feature, write)
    require_permission(user, P.MEETINGS_EDIT)
    existing = _todo_or_404(db, user, todo_id)
    if _todo_protocol_closed(db, existing):
        raise HTTPException(status_code=409, detail={"code": "protocol_closed", "message": "Das Protokoll ist abgeschlossen."})
    assignment = todo_submission_service.linked_assignment(db, existing)
    if assignment is None or assignment.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail={"code": "todo_not_submission", "message": "Diese Pendenz gehört zu keiner Abgabe."})
    assignment_internal_id, title = assignment.id, assignment.title
    try:
        # Wie create-submission: die gebüsste Person selbst ändert den Ablauf ihrer Busse nicht
        todo_fine_service.ensure_may_change(db, existing, actor_user_id=user.user_id, can_manage=user.can(P.FINES_MANAGE))
        todo_submission_service.stop_collecting(db, existing, actor_user_id=user.user_id)
    except todo_fine_service.TodoFineError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc
    except todo_submission_service.TodoSubmissionError as exc:
        # Beide Prüfungen laufen vor dem ersten Schreiben (stop_collecting) - nichts zurückzurollen;
        # der Advisory-Lock endet mit der Transaktion der Anfrage
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Abgabe konnte nicht beendet werden") from exc
    audit.log(
        db, action="submission_assignment.deleted", actor=user, entity_type="submission_assignment", entity_id=assignment_internal_id,
        details={"origin": "todo_stop", "todo_id": str(existing.public_id), "title": title, "deleted_files": 0, "kept_files": 0},
    )
    row = service.repository.get_row(db, existing.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    service._prime_public_ids(db, [row])
    return service._row_to_list_item(db, row)


def _todo_protocol_closed(db: Session, todo: ProtocolTodo) -> bool:
    """Pendenz eines abgeschlossenen Protokolls (eingefroren wie bei create-submission)."""
    protocol_id = access_service.repository.protocol_id_for_todo(db, todo_id=todo.id)
    if not protocol_id:
        return False
    protocol = db.get(Protocol, protocol_id)
    return protocol is not None and protocol.status == "abgeschlossen"


@router.get("/protocol-todos/{todo_id}/details", response_model=TodoDetails)
def get_todo_details(
    todo_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Notizen und verknüpfte Dateien für das Todo-Popup (nicht in Liste/Übersicht/Export)."""
    require_permission(user, P.MEETINGS_READ)
    return service.get_details(db, _todo_or_404(db, user, todo_id))


@router.put("/protocol-todos/{todo_id}/details", response_model=TodoDetails)
def put_todo_details(
    todo_id: uuid.UUID,
    payload: TodoDetailsUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_EDIT)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    todo = _todo_or_404(db, user, todo_id)
    if payload.file_ids is not None:
        # Neu verknüpfen nur, was die Person in der Dateisuche sieht (sonst zeigte GET .../details
        # Name und Grösse einer für sie unsichtbaren Datei). Schon verknüpfte bleiben erlaubt.
        # Unsichtbar und unbekannt ergeben dieselbe Antwort (kein Existenz-Orakel).
        linked = {file.id for file in service.get_details(db, todo).files}
        added = [file_id for file_id in dict.fromkeys(payload.file_ids) if file_id not in linked]
        if added and len(_file_service.visible_overview_items(db, user, added)) != len(added):
            raise HTTPException(status_code=400, detail="Todo details could not be saved")
    try:
        return service.update_details(db, todo, payload, tenant_id=user.current_tenant_id)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Todo details could not be saved") from exc


@router.post("/protocol-todos/{todo_id}/accept-tracked-change")
def accept_todo_tracked_change(
    todo_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """'Ausblenden' for one todo's red tracked-change highlight - keeps the todo, just
    stops marking it as changed/added/pending-delete."""
    require_permission(user, P.MEETINGS_EDIT)
    existing = _todo_or_404(db, user, todo_id)
    protocol_id = access_service.repository.protocol_id_for_todo(db, todo_id=existing.id)
    # Standalone todos (protocol_id None) have no tracked-change concept in practice, but
    # guard consistently with patch/delete above rather than special-casing this endpoint.
    if protocol_id:
        protocol_service.get_protocol_or_404_not_frozen(db, protocol_id)
    try:
        result = service.accept_tracked_change(db, existing.id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Change could not be accepted") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    hard_deleted, block_id = result
    if hard_deleted or block_id is None:
        return {"todo": None}
    todos = service.list_todos(db, block_id)
    todo_read = next((item for item in todos if item.id == todo_id), None)
    return {"todo": todo_read}


@router.delete("/protocol-todos/{todo_id}")
def delete_todo(
    todo_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_EDIT)
    existing = _todo_or_404(db, user, todo_id)
    protocol_id = access_service.repository.protocol_id_for_todo(db, todo_id=existing.id)
    # Standalone todos (protocol_id None) have no protocol at all.
    protocol = _get_protocol_or_404(db, protocol_id) if protocol_id else None
    track_changes_active = bool(protocol and protocol.status == "geplant" and protocol.track_changes_enabled)
    # Löschen beendet eine laufende Busse: nicht durch die gebüsste Person selbst. Eingefrorene
    # Bussen bleiben stehen (todo_fine.protocol_todo_id ON DELETE SET NULL, Snapshots).
    try:
        todo_fine_service.ensure_may_change(db, existing, actor_user_id=user.user_id, can_manage=user.can(P.FINES_MANAGE))
    except todo_fine_service.TodoFineError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc
    running_before = todo_fine_service.running_amount(db, existing)
    try:
        result = service.delete_todo(db, existing.id, track_changes_active=track_changes_active)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Todo could not be deleted") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    hard_deleted, block_id = result
    audit.log(
        db, action="todo.deleted", actor=user, entity_type="protocol_todo", entity_id=existing.id,
        details={"running_fine_before": str(running_before)} if running_before else None,
    )
    if hard_deleted or block_id is None:
        return {"pending_delete": False, "message": "Todo deleted", "todo": None}
    todos = service.list_todos(db, block_id)
    todo_read = next((item for item in todos if item.id == todo_id), None)
    return {"pending_delete": True, "message": "Todo pending delete", "todo": todo_read}
