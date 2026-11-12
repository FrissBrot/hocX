import uuid

from sqlalchemy import Text, cast, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.db import get_db
from app.core.error_log import record_system_error
from app.core.permissions import P
from app.core.security import CurrentUser, get_current_user, require_permission
from app.models import ElementDefinition, ListDefinition, ListEntry, Protocol, ProtocolElement, ProtocolElementBlock
from app.schemas.list_definition import (
    ListDefinitionCreate,
    ListDefinitionRead,
    ListDefinitionUpdate,
    ListEntryCreate,
    ListEntryRead,
    ListEntryUpdate,
)
from app.services import public_id_service
from app.services.list_service import ListService
from app.services.submission_service import SubmissionService
from app.services.task_package_service import sync_packages_after_change

router = APIRouter()
service = ListService()
submission_service = SubmissionService()


def _config_references_list(config: dict | None, list_definition_id: int) -> bool:
    """True if a block/row config's `linked_list_id` (whole-list "Gekoppelte Liste" mode)
    or any `rows[].linked_list_id` (row-link "Zeile aus Liste" mode) points at this list.
    Mirrors the shape read by list_snapshot_service.py and word_import_service.py's
    _template_linked_list_ids - there's no FK for this JSONB link."""
    if not isinstance(config, dict):
        return False
    # A stored linked_list_id that isn't cleanly numeric only happens with already-
    # inconsistent data, but previously raised an uncaught ValueError straight into a 500
    # instead of just not matching (audit finding, 2026-08-25).
    try:
        linked_list_id = config.get("linked_list_id")
        if linked_list_id and int(linked_list_id) == list_definition_id:
            return True
        rows = config.get("rows")
        if isinstance(rows, list):
            for row in rows:
                row_linked_list_id = row.get("linked_list_id") if isinstance(row, dict) else None
                if row_linked_list_id and int(row_linked_list_id) == list_definition_id:
                    return True
    except (TypeError, ValueError):
        return False
    return False


def _list_link_candidates_sql(list_definition_id: int) -> list[str]:
    """LIKE-Muster für die Vorauswahl in SQL: jsonb::text schreibt ``"key": wert`` mit genau
    einem Leerzeichen; die ID steht als Zahl oder als Text. Präfixtreffer (12 → 123) prüft
    _config_references_list danach exakt."""
    return [f'%"linked_list_id": {list_definition_id}%', f'%"linked_list_id": "{list_definition_id}%']


def _list_definition_usages(db: Session, list_definition_id: int, tenant_id: int, *, limit: int = 10) -> list[dict]:
    """Wo eine Liste noch verknüpft ist: Bausteine (element_definition) und Protokolle, deren
    Block-Konfiguration auf sie zeigt. Löschen einer verknüpften Liste würde offene Protokolle auf
    veralteten Daten einfrieren und neue beim Snapshot brechen (H7, 2026-08-12).

    Audit 07 (C10): Vorauswahl per LIKE in SQL statt alle Konfigurationen des Mandanten in Python
    zu laden; U4: die Fundstellen werden genannt statt nur «noch verknüpft»."""
    patterns = _list_link_candidates_sql(list_definition_id)
    usages: list[dict] = []
    element_rows = db.execute(
        select(ElementDefinition.public_id, ElementDefinition.title, ElementDefinition.configuration_json).where(
            ElementDefinition.tenant_id == tenant_id,
            or_(*[cast(ElementDefinition.configuration_json, Text).like(pattern) for pattern in patterns]),
        )
    ).all()
    for row in element_rows:
        for block in (row.configuration_json or {}).get("blocks", []):
            block_config = block.get("configuration_json") if isinstance(block, dict) else None
            if _config_references_list(block_config, list_definition_id):
                usages.append({"kind": "element", "id": str(row.public_id), "name": row.title})
                break

    protocol_rows = db.execute(
        select(Protocol.id, Protocol.public_id, Protocol.protocol_number, Protocol.title, ProtocolElementBlock.configuration_snapshot_json)
        .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
        .join(Protocol, Protocol.id == ProtocolElement.protocol_id)
        .where(
            Protocol.tenant_id == tenant_id,
            or_(*[cast(ProtocolElementBlock.configuration_snapshot_json, Text).like(pattern) for pattern in patterns]),
        )
    ).all()
    seen_protocols: set[int] = set()
    for row in protocol_rows:
        if row.id in seen_protocols:
            continue
        if _config_references_list(row.configuration_snapshot_json, list_definition_id):
            seen_protocols.add(row.id)
            usages.append({"kind": "protocol", "id": str(row.public_id), "name": row.title or row.protocol_number, "number": row.protocol_number})
    return usages[:limit] if limit else usages


def _list_definition_in_use(db: Session, list_definition_id: int, tenant_id: int) -> bool:
    return bool(_list_definition_usages(db, list_definition_id, tenant_id, limit=1))


def _sync_after_entry_change(db: Session, *, tenant_id: int, list_definition_id: int) -> None:
    """Nach dem Speichern eines Eintrags Aufgabenpakete und Abgabe-Todos nachführen. Best effort
    (Audit 07, C11): der Eintrag ist schon gespeichert - eine 500 verleitete zum erneuten Senden
    und damit zu Duplikaten. Fehler landen in system_error_log, submission_todo_sync holt nach."""
    sync_packages_after_change(db, tenant_id=tenant_id, list_definition_id=list_definition_id)
    try:
        submission_service.sync_todos_for_list(db, tenant_id=tenant_id, list_definition_id=list_definition_id)
    except Exception as exc:
        db.rollback()
        record_system_error(db, exc=exc, tenant_id=tenant_id)


@router.get("/lists", response_model=list[ListDefinitionRead])
def list_definitions(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_EDIT)
    return service.list_definitions(db, tenant_id=user.current_tenant_id)


@router.post("/lists", response_model=ListDefinitionRead, status_code=status.HTTP_201_CREATED)
def create_definition(
    payload: ListDefinitionCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_EDIT)
    try:
        return service.create_definition(db, payload, tenant_id=user.current_tenant_id)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Liste konnte nicht erstellt werden") from exc


def _get_definition_or_404(db: Session, list_definition_id: uuid.UUID, user: CurrentUser) -> ListDefinition:
    definition = public_id_service.get_by_public_id(db, ListDefinition, list_definition_id, tenant_id=user.current_tenant_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="Liste nicht gefunden")
    return definition


def _get_entry_or_404(db: Session, list_entry_id: uuid.UUID, user: CurrentUser) -> ListEntry:
    entry = public_id_service.get_by_public_id(db, ListEntry, list_entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    definition = service.get_definition(db, entry.list_definition_id)
    if definition is None or definition.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    return entry


@router.patch("/lists/{list_definition_id}", response_model=ListDefinitionRead)
def patch_definition(
    list_definition_id: uuid.UUID,
    payload: ListDefinitionUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_EDIT)
    current = _get_definition_or_404(db, list_definition_id, user)
    try:
        updated = service.update_definition(db, current.id, payload)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Liste konnte nicht aktualisiert werden") from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Liste nicht gefunden")
    return updated


@router.delete("/lists/{list_definition_id}", response_model=dict[str, str])
def delete_definition(
    list_definition_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_EDIT)
    current = _get_definition_or_404(db, list_definition_id, user)
    # Zeilensperre bis zum Löschen (C10): Einträge können während Prüfung und Löschen nicht
    # mehr geändert werden. Das Verknüpfen in einem Baustein sperrt die Liste ebenfalls
    # (list_service.lock_linked_list_definitions): wer zuerst sperrt, gewinnt.
    db.execute(select(ListDefinition.id).where(ListDefinition.id == current.id).with_for_update())
    usages = _list_definition_usages(db, current.id, user.current_tenant_id)
    if usages:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "list_in_use",
                "message": "Liste ist noch mit einem Template-Baustein oder Protokoll verknüpft und kann nicht gelöscht werden",
                "usages": usages,
            },
        )
    try:
        deleted = service.delete_definition(db, current.id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Liste konnte nicht gelöscht werden") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Liste nicht gefunden")
    return {"message": "Liste gelöscht"}


@router.get("/lists/{list_definition_id}/entries", response_model=list[ListEntryRead])
def list_entries(
    list_definition_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_EDIT)
    definition = _get_definition_or_404(db, list_definition_id, user)
    return service.list_entries(db, list_definition_id=definition.id)


@router.get("/list-entries", response_model=dict[str, list[ListEntryRead]])
def list_all_entries(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Einträge aller Listen des Mandanten in einem Aufruf, nach Listen-ID (Audit 07, C6: die
    Listen-Seite rief vorher je Liste /lists/{id}/entries einzeln ab)."""
    require_permission(user, P.MEETINGS_EDIT)
    return service.entries_by_list(db, tenant_id=user.current_tenant_id)


@router.post("/lists/{list_definition_id}/entries", response_model=ListEntryRead, status_code=status.HTTP_201_CREATED)
def create_entry(
    list_definition_id: uuid.UUID,
    payload: ListEntryCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_EDIT)
    definition = _get_definition_or_404(db, list_definition_id, user)
    try:
        created = service.create_entry(db, definition.id, payload)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc) if isinstance(exc, ValueError) else "Eintrag konnte nicht erstellt werden") from exc
    _sync_after_entry_change(db, tenant_id=definition.tenant_id, list_definition_id=definition.id)
    return created


@router.patch("/list-entries/{list_entry_id}", response_model=ListEntryRead)
def patch_entry(
    list_entry_id: uuid.UUID,
    payload: ListEntryUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_EDIT)
    current = _get_entry_or_404(db, list_entry_id, user)
    try:
        updated = service.update_entry(db, current.id, payload)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc) if isinstance(exc, ValueError) else "Eintrag konnte nicht gespeichert werden") from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    _sync_after_entry_change(db, tenant_id=user.current_tenant_id, list_definition_id=current.list_definition_id)
    return updated


@router.delete("/list-entries/{list_entry_id}", response_model=dict[str, str])
def delete_entry(
    list_entry_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_EDIT)
    current = _get_entry_or_404(db, list_entry_id, user)
    list_definition_id = current.list_definition_id
    try:
        deleted = service.delete_entry(db, current.id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Eintrag konnte nicht gelöscht werden") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    # C2: wie create/patch auch die Abgabe-Todos nachführen (vorher erst beim nächsten Job-Lauf).
    _sync_after_entry_change(db, tenant_id=user.current_tenant_id, list_definition_id=list_definition_id)
    return {"message": "Eintrag gelöscht"}
