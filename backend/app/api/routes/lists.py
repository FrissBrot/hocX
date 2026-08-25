from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_writer
from app.models import ElementDefinition, Protocol, ProtocolElement, ProtocolElementBlock
from app.schemas.list_definition import (
    ListDefinitionCreate,
    ListDefinitionRead,
    ListDefinitionUpdate,
    ListEntryCreate,
    ListEntryRead,
    ListEntryUpdate,
)
from app.services.list_service import ListService

router = APIRouter()
service = ListService()


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


def _list_definition_in_use(db: Session, list_definition_id: int, tenant_id: int) -> bool:
    """Whether any template element block config or protocol block snapshot still links
    to this list. Deleting a still-linked list would leave open protocols permanently
    frozen on stale data and break new protocols during snapshot construction (see H7,
    2026-08-12 audit). Scoped to tenant_id (audit finding, 2026-08-25) - list_definition_id
    is already globally unique so scanning every tenant was functionally harmless, just an
    unnecessary full-table scan and an inconsistency with the tenant-scoping used
    everywhere else in this codebase."""
    for configuration_json in db.scalars(
        select(ElementDefinition.configuration_json).where(ElementDefinition.tenant_id == tenant_id)
    ):
        for block in (configuration_json or {}).get("blocks", []):
            block_config = block.get("configuration_json") if isinstance(block, dict) else None
            if _config_references_list(block_config, list_definition_id):
                return True

    protocol_block_configs = db.scalars(
        select(ProtocolElementBlock.configuration_snapshot_json)
        .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
        .join(Protocol, Protocol.id == ProtocolElement.protocol_id)
        .where(Protocol.tenant_id == tenant_id)
    )
    for configuration_snapshot_json in protocol_block_configs:
        if _config_references_list(configuration_snapshot_json, list_definition_id):
            return True

    return False


@router.get("/lists", response_model=list[ListDefinitionRead])
def list_definitions(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    return service.list_definitions(db, tenant_id=user.current_tenant_id)


@router.post("/lists", response_model=ListDefinitionRead, status_code=status.HTTP_201_CREATED)
def create_definition(
    payload: ListDefinitionCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    try:
        return service.create_definition(db, payload, tenant_id=user.current_tenant_id)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Liste konnte nicht erstellt werden") from exc


@router.patch("/lists/{list_definition_id}", response_model=ListDefinitionRead)
def patch_definition(
    list_definition_id: int,
    payload: ListDefinitionUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    current = service.get_definition(db, list_definition_id)
    if current is None or current.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Liste nicht gefunden")
    try:
        updated = service.update_definition(db, list_definition_id, payload)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Liste konnte nicht aktualisiert werden") from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Liste nicht gefunden")
    return updated


@router.delete("/lists/{list_definition_id}", response_model=dict[str, str])
def delete_definition(
    list_definition_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    current = service.get_definition(db, list_definition_id)
    if current is None or current.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Liste nicht gefunden")
    if _list_definition_in_use(db, list_definition_id, user.current_tenant_id):
        raise HTTPException(
            status_code=409,
            detail="Liste ist noch mit einem Template-Baustein oder Protokoll verknuepft und kann nicht geloescht werden",
        )
    try:
        deleted = service.delete_definition(db, list_definition_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Liste konnte nicht geloescht werden") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Liste nicht gefunden")
    return {"message": "Liste geloescht"}


@router.get("/lists/{list_definition_id}/entries", response_model=list[ListEntryRead])
def list_entries(
    list_definition_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    definition = service.get_definition(db, list_definition_id)
    if definition is None or definition.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Liste nicht gefunden")
    return service.list_entries(db, list_definition_id=list_definition_id)


@router.post("/lists/{list_definition_id}/entries", response_model=ListEntryRead, status_code=status.HTTP_201_CREATED)
def create_entry(
    list_definition_id: int,
    payload: ListEntryCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    definition = service.get_definition(db, list_definition_id)
    if definition is None or definition.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Liste nicht gefunden")
    try:
        created = service.create_entry(db, list_definition_id, payload)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc) if isinstance(exc, ValueError) else "Eintrag konnte nicht erstellt werden") from exc
    return created


@router.patch("/list-entries/{list_entry_id}", response_model=ListEntryRead)
def patch_entry(
    list_entry_id: int,
    payload: ListEntryUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    current = service.get_entry(db, list_entry_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    definition = service.get_definition(db, current.list_definition_id)
    if definition is None or definition.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    try:
        updated = service.update_entry(db, list_entry_id, payload)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc) if isinstance(exc, ValueError) else "Eintrag konnte nicht gespeichert werden") from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    return updated


@router.delete("/list-entries/{list_entry_id}", response_model=dict[str, str])
def delete_entry(
    list_entry_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    current = service.get_entry(db, list_entry_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    definition = service.get_definition(db, current.list_definition_id)
    if definition is None or definition.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    try:
        deleted = service.delete_entry(db, list_entry_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Eintrag konnte nicht geloescht werden") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    return {"message": "Eintrag geloescht"}
