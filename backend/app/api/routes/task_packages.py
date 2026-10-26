"""Aufgabenpakete (Vorlagen für wiederkehrende Aufgaben pro Zyklus). Nur Admins, wie die
übrige Vorlagen-Konfiguration. Fachlogik in app/services/task_package_service.py."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.permissions import P
from app.core.security import CurrentUser, get_current_user, require_permission
from app.models import CycleConfig, ListDefinition, ListEntry, Participant, TaskPackage, TaskPackageCycle, TaskPackageItem
from app.schemas.task_package import (
    TaskPackageCreate,
    TaskPackageCycleAssign,
    TaskPackageCycleRead,
    TaskPackageItemCreate,
    TaskPackageItemRead,
    TaskPackageItemUpdate,
    TaskPackagePreview,
    TaskPackagePreviewEntry,
    TaskPackageRead,
    TaskPackageResponsible,
    TaskPackageSyncResult,
    TaskPackageTodoRemovalResult,
    TaskPackageUpdate,
    TodoDeleteMode,
)
from app.services import public_id_service
from app.services import task_package_service as packages
from app.services.audit_service import AuditService

router = APIRouter()
audit = AuditService()


class TaskPackageItemOrder(BaseModel):
    item_ids: list[uuid.UUID]


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _get_package(db: Session, package_id: uuid.UUID, tenant_id: int) -> TaskPackage:
    package = public_id_service.get_by_public_id(db, TaskPackage, package_id, tenant_id=tenant_id)
    if package is None:
        raise HTTPException(status_code=404, detail="Aufgabenpaket nicht gefunden")
    return package


def _get_item(db: Session, package: TaskPackage, item_id: uuid.UUID) -> TaskPackageItem:
    item = public_id_service.get_by_public_id(db, TaskPackageItem, item_id)
    if item is None or item.task_package_id != package.id:
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")
    return item


def _responsible_to_internal(db: Session, responsible: list[TaskPackageResponsible], tenant_id: int) -> list[dict]:
    """Öffentliche IDs -> interne IDs, gleichzeitig Mandantenprüfung (eine fremde ID löst
    schlicht nicht auf)."""
    result: list[dict] = []
    seen: set[tuple] = set()
    for entry in responsible:
        if entry.participant_id is not None:
            participant_id = public_id_service.resolve_internal_id(db, Participant, entry.participant_id, tenant_id=tenant_id)
            if participant_id is None:
                raise ValueError("Person nicht gefunden")
            key: tuple = ("participant", participant_id)
            value = {"participant_id": participant_id}
        else:
            list_definition_id = public_id_service.resolve_internal_id(db, ListDefinition, entry.list_definition_id, tenant_id=tenant_id)
            list_entry_id = public_id_service.resolve_internal_id(db, ListEntry, entry.list_entry_id)
            if (
                list_definition_id is None
                or list_entry_id is None
                or not packages.list_entry_belongs_to_tenant(
                    db, list_definition_id=list_definition_id, list_entry_id=list_entry_id, tenant_id=tenant_id
                )
            ):
                raise ValueError("Listenzeile nicht gefunden")
            key = ("list", list_definition_id, list_entry_id)
            value = {"list_definition_id": list_definition_id, "list_entry_id": list_entry_id}
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _responsible_to_public(db: Session, responsible: list[dict]) -> list[TaskPackageResponsible]:
    result = []
    for entry in responsible or []:
        if entry.get("list_definition_id") and entry.get("list_entry_id"):
            list_definition_id = public_id_service.resolve_public_id(db, ListDefinition, int(entry["list_definition_id"]))
            list_entry_id = public_id_service.resolve_public_id(db, ListEntry, int(entry["list_entry_id"]))
            if list_definition_id and list_entry_id:
                result.append(TaskPackageResponsible(list_definition_id=list_definition_id, list_entry_id=list_entry_id))
        elif entry.get("participant_id"):
            participant_id = public_id_service.resolve_public_id(db, Participant, int(entry["participant_id"]))
            if participant_id:
                result.append(TaskPackageResponsible(participant_id=participant_id))
    return result


def _item_read(db: Session, item: TaskPackageItem) -> TaskPackageItemRead:
    return TaskPackageItemRead(
        id=item.public_id,
        sort_index=item.sort_index,
        task=item.task,
        reference_link=item.reference_link,
        tags=list(item.tags or []),
        responsible=_responsible_to_public(db, item.responsible_json),
        recurrence=item.recurrence_json or {"type": "once"},
        due_rule=item.due_rule_json or {"type": "none"},
    )


def _package_read(db: Session, package: TaskPackage, counts: dict[int, tuple[int, int]] | None = None) -> TaskPackageRead:
    if counts is None:
        counts = packages.todo_counts(db, [package.id])
    cycles = []
    for package_cycle in packages.list_package_cycles(db, package.id):
        cycle_config = db.get(CycleConfig, package_cycle.cycle_config_id)
        if cycle_config is None:
            continue
        current = packages.current_cycle_year(cycle_config)
        cycles.append(
            TaskPackageCycleRead(
                id=package_cycle.public_id,
                cycle_config_id=cycle_config.public_id,
                cycle_config_name=cycle_config.name,
                start_cycle_year=package_cycle.start_cycle_year,
                current_cycle_year=current,
                current_cycle_label=packages.cycle_label(cycle_config, current),
            )
        )
    open_count, total = counts.get(package.id, (0, 0))
    return TaskPackageRead(
        id=package.public_id,
        name=package.name,
        description=package.description,
        is_active=package.is_active,
        cycles=cycles,
        items=[_item_read(db, item) for item in packages.list_items(db, package.id)],
        open_todo_count=open_count,
        todo_count=total,
        created_at=package.created_at,
        updated_at=package.updated_at,
    )


def _item_values(db: Session, payload: TaskPackageItemCreate | TaskPackageItemUpdate, tenant_id: int) -> dict:
    return {
        "task": payload.task.strip(),
        "reference_link": payload.reference_link,
        "tags": payload.tags,
        "responsible_json": _responsible_to_internal(db, payload.responsible, tenant_id),
        "recurrence_json": payload.recurrence.model_dump(exclude_none=True),
        "due_rule_json": payload.due_rule.model_dump(exclude_none=True),
    }


# ---------------------------------------------------------------------------
# Pakete
# ---------------------------------------------------------------------------


@router.get("/task-packages", response_model=list[TaskPackageRead])
def list_task_packages(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.TEMPLATES_MANAGE)
    rows = db.scalars(
        select(TaskPackage).where(TaskPackage.tenant_id == user.current_tenant_id).order_by(TaskPackage.name)
    ).all()
    counts = packages.todo_counts(db, [row.id for row in rows])
    return [_package_read(db, row, counts) for row in rows]


@router.post("/task-packages", response_model=TaskPackageRead, status_code=status.HTTP_201_CREATED)
def create_task_package(
    payload: TaskPackageCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.TEMPLATES_MANAGE)
    package = TaskPackage(
        tenant_id=user.current_tenant_id,
        name=payload.name.strip(),
        description=payload.description,
        is_active=payload.is_active,
    )
    try:
        db.add(package)
        db.commit()
        db.refresh(package)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ein Aufgabenpaket mit diesem Namen existiert bereits") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Aufgabenpaket konnte nicht erstellt werden") from exc
    audit.log(db, action="task_package.created", actor=user, entity_type="task_package", entity_id=package.id)
    return _package_read(db, package)


@router.get("/task-packages/{package_id}", response_model=TaskPackageRead)
def get_task_package(
    package_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.TEMPLATES_MANAGE)
    return _package_read(db, _get_package(db, package_id, user.current_tenant_id))


@router.put("/task-packages/{package_id}", response_model=TaskPackageRead)
def update_task_package(
    package_id: uuid.UUID,
    payload: TaskPackageUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.TEMPLATES_MANAGE)
    package = _get_package(db, package_id, user.current_tenant_id)
    values = payload.model_dump(exclude_unset=True)
    if "name" in values and values["name"] is not None:
        values["name"] = values["name"].strip()
    try:
        for key, value in values.items():
            setattr(package, key, value)
        package.updated_at = func.now()
        db.commit()
        db.refresh(package)
        packages.sync_package(db, package)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ein Aufgabenpaket mit diesem Namen existiert bereits") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Aufgabenpaket konnte nicht gespeichert werden") from exc
    audit.log(db, action="task_package.updated", actor=user, entity_type="task_package", entity_id=package.id, details={"fields": sorted(values)})
    return _package_read(db, package)


@router.delete("/task-packages/{package_id}", response_model=TaskPackageTodoRemovalResult)
def delete_task_package(
    package_id: uuid.UUID,
    todos: TodoDeleteMode = Query(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """todos=all: alle Aufgaben löschen, future: nur Aufgaben ab dem nächsten Zyklus löschen,
    none: Aufgaben behalten (werden zu normalen Todos)."""
    require_permission(user, P.TEMPLATES_MANAGE)
    package = _get_package(db, package_id, user.current_tenant_id)
    internal_id = package.id
    try:
        deleted, kept = packages.delete_package(db, package, mode=todos)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Aufgabenpaket konnte nicht gelöscht werden") from exc
    audit.log(
        db, action="task_package.deleted", actor=user, entity_type="task_package", entity_id=internal_id,
        details={"todos": todos, "deleted_todos": deleted, "kept_todos": kept},
    )
    return TaskPackageTodoRemovalResult(deleted=deleted, kept=kept)


@router.post("/task-packages/{package_id}/sync", response_model=TaskPackageSyncResult)
def sync_task_package(
    package_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Instanzen des laufenden Zyklus sofort nachführen (läuft sonst täglich und nach jeder
    Änderung automatisch)."""
    require_permission(user, P.TEMPLATES_MANAGE)
    package = _get_package(db, package_id, user.current_tenant_id)
    try:
        created, updated = packages.sync_package(db, package)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Aufgaben konnten nicht erzeugt werden") from exc
    audit.log(
        db, action="task_package.synced", actor=user, entity_type="task_package", entity_id=package.id,
        details={"created": created, "updated": updated},
    )
    return TaskPackageSyncResult(created=created, updated=updated)


# ---------------------------------------------------------------------------
# Aufgaben im Paket
# ---------------------------------------------------------------------------


@router.post("/task-packages/{package_id}/items", response_model=TaskPackageRead, status_code=status.HTTP_201_CREATED)
def create_task_package_item(
    package_id: uuid.UUID,
    payload: TaskPackageItemCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.TEMPLATES_MANAGE)
    package = _get_package(db, package_id, user.current_tenant_id)
    try:
        values = _item_values(db, payload, user.current_tenant_id)
        sort_index = payload.sort_index
        if sort_index is None:
            current_max = db.scalar(select(func.max(TaskPackageItem.sort_index)).where(TaskPackageItem.task_package_id == package.id))
            sort_index = 0 if current_max is None else current_max + 1
        item = TaskPackageItem(task_package_id=package.id, sort_index=sort_index, **values)
        db.add(item)
        db.commit()
        db.refresh(item)
        packages.sync_package(db, package)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Aufgabe konnte nicht erstellt werden") from exc
    audit.log(db, action="task_package.item_created", actor=user, entity_type="task_package_item", entity_id=item.id)
    return _package_read(db, package)


@router.put("/task-packages/{package_id}/items/{item_id}", response_model=TaskPackageRead)
def update_task_package_item(
    package_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: TaskPackageItemUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.TEMPLATES_MANAGE)
    package = _get_package(db, package_id, user.current_tenant_id)
    item = _get_item(db, package, item_id)
    try:
        values = _item_values(db, payload, user.current_tenant_id)
        if payload.sort_index is not None:
            values["sort_index"] = payload.sort_index
        for key, value in values.items():
            setattr(item, key, value)
        item.updated_at = func.now()
        db.commit()
        packages.sync_package(db, package)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Aufgabe konnte nicht gespeichert werden") from exc
    audit.log(db, action="task_package.item_updated", actor=user, entity_type="task_package_item", entity_id=item.id)
    return _package_read(db, package)


@router.delete("/task-packages/{package_id}/items/{item_id}", response_model=TaskPackageRead)
def delete_task_package_item(
    package_id: uuid.UUID,
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Entfernt die Aufgabe aus dem Paket. Bereits erzeugte Aufgaben bleiben als normale Todos
    bestehen (FK ON DELETE SET NULL) - das Paket löscht nie selbst Aufgaben."""
    require_permission(user, P.TEMPLATES_MANAGE)
    package = _get_package(db, package_id, user.current_tenant_id)
    item = _get_item(db, package, item_id)
    internal_id = item.id
    try:
        db.delete(item)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Aufgabe konnte nicht entfernt werden") from exc
    audit.log(db, action="task_package.item_deleted", actor=user, entity_type="task_package_item", entity_id=internal_id)
    return _package_read(db, package)


@router.post("/task-packages/{package_id}/items/reorder", response_model=TaskPackageRead)
def reorder_task_package_items(
    package_id: uuid.UUID,
    payload: TaskPackageItemOrder,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.TEMPLATES_MANAGE)
    package = _get_package(db, package_id, user.current_tenant_id)
    items = {item.public_id: item for item in packages.list_items(db, package.id)}
    if set(payload.item_ids) != set(items):
        raise HTTPException(status_code=400, detail="Die Reihenfolge muss alle Aufgaben des Pakets enthalten")
    try:
        for index, public_id in enumerate(payload.item_ids):
            items[public_id].sort_index = index
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Reihenfolge konnte nicht gespeichert werden") from exc
    audit.log(db, action="task_package.items_reordered", actor=user, entity_type="task_package", entity_id=package.id)
    return _package_read(db, package)


# ---------------------------------------------------------------------------
# Zyklus-Zuweisungen
# ---------------------------------------------------------------------------


@router.post("/task-packages/{package_id}/cycles", response_model=TaskPackageRead, status_code=status.HTTP_201_CREATED)
def assign_task_package_cycle(
    package_id: uuid.UUID,
    payload: TaskPackageCycleAssign,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Weist das Paket einem Zyklus zu. Gilt der Start schon für den laufenden Zyklus, entstehen
    dessen Aufgaben sofort."""
    require_permission(user, P.TEMPLATES_MANAGE)
    package = _get_package(db, package_id, user.current_tenant_id)
    cycle_config = public_id_service.get_by_public_id(db, CycleConfig, payload.cycle_config_id, tenant_id=user.current_tenant_id)
    if cycle_config is None:
        raise HTTPException(status_code=404, detail="Zyklus nicht gefunden")
    start_cycle_year = payload.start_cycle_year or packages.current_cycle_year(cycle_config)
    try:
        package_cycle = TaskPackageCycle(task_package_id=package.id, cycle_config_id=cycle_config.id, start_cycle_year=start_cycle_year)
        db.add(package_cycle)
        db.commit()
        packages.sync_package(db, package)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Das Paket ist diesem Zyklus bereits zugewiesen") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Zyklus konnte nicht zugewiesen werden") from exc
    audit.log(
        db, action="task_package.cycle_assigned", actor=user, entity_type="task_package", entity_id=package.id,
        details={"cycle_config_id": cycle_config.id, "start_cycle_year": start_cycle_year},
    )
    return _package_read(db, package)


@router.patch("/task-packages/{package_id}/cycles/{package_cycle_id}", response_model=TaskPackageRead)
def update_task_package_cycle(
    package_id: uuid.UUID,
    package_cycle_id: uuid.UUID,
    payload: TaskPackageCycleAssign,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Startjahr ändern. Ein späterer Start löscht keine bereits erzeugten Aufgaben."""
    require_permission(user, P.TEMPLATES_MANAGE)
    package = _get_package(db, package_id, user.current_tenant_id)
    package_cycle = public_id_service.get_by_public_id(db, TaskPackageCycle, package_cycle_id)
    if package_cycle is None or package_cycle.task_package_id != package.id:
        raise HTTPException(status_code=404, detail="Zuweisung nicht gefunden")
    cycle_config = db.get(CycleConfig, package_cycle.cycle_config_id)
    try:
        package_cycle.start_cycle_year = payload.start_cycle_year or packages.current_cycle_year(cycle_config)
        db.commit()
        packages.sync_package(db, package)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Zuweisung konnte nicht gespeichert werden") from exc
    audit.log(
        db, action="task_package.cycle_updated", actor=user, entity_type="task_package", entity_id=package.id,
        details={"cycle_config_id": package_cycle.cycle_config_id, "start_cycle_year": package_cycle.start_cycle_year},
    )
    return _package_read(db, package)


@router.delete("/task-packages/{package_id}/cycles/{package_cycle_id}", response_model=TaskPackageTodoRemovalResult)
def unassign_task_package_cycle(
    package_id: uuid.UUID,
    package_cycle_id: uuid.UUID,
    todos: TodoDeleteMode = Query(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.TEMPLATES_MANAGE)
    package = _get_package(db, package_id, user.current_tenant_id)
    package_cycle = public_id_service.get_by_public_id(db, TaskPackageCycle, package_cycle_id)
    if package_cycle is None or package_cycle.task_package_id != package.id:
        raise HTTPException(status_code=404, detail="Zuweisung nicht gefunden")
    cycle_config_id = package_cycle.cycle_config_id
    try:
        deleted, kept = packages.unassign_cycle(db, package, package_cycle, mode=todos)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Zuweisung konnte nicht entfernt werden") from exc
    audit.log(
        db, action="task_package.cycle_unassigned", actor=user, entity_type="task_package", entity_id=package.id,
        details={"cycle_config_id": cycle_config_id, "todos": todos, "deleted_todos": deleted, "kept_todos": kept},
    )
    return TaskPackageTodoRemovalResult(deleted=deleted, kept=kept)


@router.get("/task-packages/{package_id}/preview", response_model=TaskPackagePreview)
def preview_task_package(
    package_id: uuid.UUID,
    cycle_config_id: uuid.UUID,
    cycle_year: int | None = Query(default=None, ge=1900, le=3000),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.TEMPLATES_MANAGE)
    package = _get_package(db, package_id, user.current_tenant_id)
    cycle_config = public_id_service.get_by_public_id(db, CycleConfig, cycle_config_id, tenant_id=user.current_tenant_id)
    if cycle_config is None:
        raise HTTPException(status_code=404, detail="Zyklus nicht gefunden")
    year = cycle_year or packages.current_cycle_year(cycle_config, date.today())
    entries = packages.preview(db, package, cycle_config=cycle_config, cycle_year=year)
    return TaskPackagePreview(
        cycle_config_id=cycle_config.public_id,
        cycle_year=year,
        cycle_label=packages.cycle_label(cycle_config, year),
        entries=[
            TaskPackagePreviewEntry(
                item_id=entry["item"].public_id,
                task=entry["item"].task,
                occurrence_key=entry["occurrence"].key,
                occurrence_date=entry["occurrence"].anchor,
                due_date=entry["due_date"],
                assignee_names=entry["assignee_names"],
                exists=entry["exists"],
            )
            for entry in entries
        ],
    )
