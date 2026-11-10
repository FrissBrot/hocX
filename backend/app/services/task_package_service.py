"""Aufgabenpakete: wiederkehrende Aufgaben pro Zyklus.

Ein Paket (z. B. "Sommerlager") ist einem oder mehreren Zyklen zugewiesen (task_package_cycle,
ab start_cycle_year). Für jeden Zyklus, in dem es gilt, entstehen aus seinen Aufgaben echte
Todos (protocol_todo ohne Protokollblock) - eine Instanz je Aufgabe und Wiederholung, eindeutig
über (task_package_item_id, cycle_config_id, cycle_year, occurrence_key).

Regeln:
- Erzeugt wird nur der *laufende* Zyklus eines Zyklus-Configs (beim Zuweisen, beim Ändern des
  Pakets, bei Listenänderungen und täglich im Job task_package_rollover - dieser legt beim
  Zykluswechsel die Instanzen des neuen Zyklus an).
- Verantwortliche kommen live aus der Liste (gleiche Form/Auflösung wie im Protokoll, siehe
  responsible_label_service). Weil nur der laufende Zyklus angefasst wird, bleiben Aufgaben
  vergangener Zyklen bei einer Listenänderung unverändert.
- Änderungen an Paket oder Liste gelten für offene Instanzen des laufenden Zyklus; erledigte
  oder abgebrochene Instanzen und von Hand geänderte Felder (overridden_fields) bleiben.
- Es wird nie automatisch gelöscht. Löschen nur explizit über remove_todos (Paket oder
  Zyklus-Zuweisung entfernen) mit Modus all/future/none.
"""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.error_log import record_system_error
from app.core.cycle_utils import cycle_bounds, format_cycle_name, get_cycle_year
from app.core.features_generated import F
from app.models import (
    CycleConfig,
    Event,
    ListDefinition,
    ListEntry,
    Participant,
    ProtocolTodo,
    ProtocolTodoAssignee,
    TaskPackage,
    TaskPackageCycle,
    TaskPackageItem,
    TenantFeature,
    TodoStatus,
)
from app.services.responsible_label_service import _resolve_ids_for_assignments

_logger = logging.getLogger(__name__)

# Felder, die das Paket in seinen Instanzen pflegt. Ein Feld, das von Hand geändert wurde,
# landet in protocol_todo.overridden_fields und wird danach nicht mehr überschrieben.
MANAGED_FIELDS = ("task", "reference_link", "tags", "due_date", "assignees")
_CLOSED_STATUS_CODES = ("done", "cancelled")


@dataclass(frozen=True)
class Occurrence:
    key: str
    anchor: date


# ---------------------------------------------------------------------------
# Reine Berechnungen (ohne DB, ausser Termin-Abfrage)
# ---------------------------------------------------------------------------


def current_cycle_year(cycle_config: CycleConfig, today: date | None = None) -> int:
    return get_cycle_year(today or date.today(), cycle_config.reset_month, cycle_config.reset_day)


def cycle_label(cycle_config: CycleConfig, cycle_year: int) -> str:
    return format_cycle_name(cycle_config.name_pattern, cycle_year)


def _clamped(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def occurrences_for(
    db: Session, item: TaskPackageItem, *, tenant_id: int, cycle_config: CycleConfig, cycle_year: int
) -> list[Occurrence]:
    start, end = cycle_bounds(cycle_year, cycle_config.reset_month, cycle_config.reset_day)
    recurrence = item.recurrence_json or {}
    kind = recurrence.get("type") or "once"
    if kind == "monthly":
        day = int(recurrence.get("day_of_month") or 1)
        result = []
        year, month = start.year, start.month
        while date(year, month, 1) <= end:
            candidate = _clamped(year, month, day)
            if start <= candidate <= end:
                result.append(Occurrence(candidate.isoformat(), candidate))
            month += 1
            if month > 12:
                year, month = year + 1, 1
        return result
    if kind == "weekly":
        weekday = int(recurrence.get("weekday") or 0)
        current = start + timedelta(days=(weekday - start.weekday()) % 7)
        result = []
        while current <= end:
            result.append(Occurrence(current.isoformat(), current))
            current += timedelta(days=7)
        return result
    if kind == "events":
        tag = (recurrence.get("event_tag") or "").strip()
        if not tag:
            return []
        events = db.execute(
            select(Event.id, Event.event_date)
            .where(
                Event.tenant_id == tenant_id,
                Event.tag == tag,
                Event.is_cancelled.is_(False),
                Event.event_date >= start,
                Event.event_date <= end,
            )
            .order_by(Event.event_date, Event.id)
        ).all()
        return [Occurrence(f"event:{row.id}", row.event_date) for row in events]
    return [Occurrence("once", start)]


def due_date_for(item: TaskPackageItem, occurrence: Occurrence, *, cycle_config: CycleConfig, cycle_year: int) -> date | None:
    rule = item.due_rule_json or {}
    kind = rule.get("type") or "none"
    if kind == "offset":
        return occurrence.anchor + timedelta(days=int(rule.get("offset_days") or 0))
    if kind == "fixed":
        start, end = cycle_bounds(cycle_year, cycle_config.reset_month, cycle_config.reset_day)
        month, day = int(rule.get("month") or 1), int(rule.get("day") or 1)
        for year in (start.year, start.year + 1):
            candidate = _clamped(year, month, day)
            if start <= candidate <= end:
                return candidate
        return None
    return None


def resolve_assignee_ids(db: Session, item: TaskPackageItem, *, tenant_id: int) -> list[int]:
    """Verantwortliche einer Aufgabe, live aus den verknüpften Listenzeilen. Nur Personen des
    eigenen Mandanten - responsible_json wird zwar beim Speichern geprüft, eine Listenzeile kann
    sich danach aber ändern."""
    ids = _resolve_ids_for_assignments(item.responsible_json, live=True, db=db)
    if not ids:
        return []
    allowed = set(
        db.scalars(select(Participant.id).where(Participant.id.in_(ids), Participant.tenant_id == tenant_id))
    )
    return [pid for pid in ids if pid in allowed]


# ---------------------------------------------------------------------------
# Instanzen erzeugen und nachführen
# ---------------------------------------------------------------------------


def _status_ids(db: Session) -> tuple[int, set[int]]:
    rows = db.execute(select(TodoStatus.id, TodoStatus.code)).all()
    open_id = next((row.id for row in rows if row.code == "open"), 1)
    closed = {row.id for row in rows if row.code in _CLOSED_STATUS_CODES}
    return open_id, closed


def set_todo_assignees(db: Session, todo: ProtocolTodo, participant_ids: list[int]) -> None:
    """Setzt alle Verantwortlichen eines Todos. Die erste Person steht zusätzlich in
    assigned_participant_id (bestehende Anzeigen/Filter lesen nur dieses Feld)."""
    db.execute(delete(ProtocolTodoAssignee).where(ProtocolTodoAssignee.protocol_todo_id == todo.id))
    for index, participant_id in enumerate(participant_ids):
        db.add(ProtocolTodoAssignee(protocol_todo_id=todo.id, participant_id=participant_id, sort_index=index))
    todo.assigned_participant_id = participant_ids[0] if participant_ids else None
    # Sessions laufen mit autoflush=False - spätere Abfragen in derselben Transaktion sollen
    # die neuen Zeilen sehen.
    db.flush()


def todo_assignee_ids(db: Session, todo_id: int) -> list[int]:
    return list(
        db.scalars(
            select(ProtocolTodoAssignee.participant_id)
            .where(ProtocolTodoAssignee.protocol_todo_id == todo_id)
            .order_by(ProtocolTodoAssignee.sort_index, ProtocolTodoAssignee.participant_id)
        )
    )


def _sync_item(
    db: Session,
    item: TaskPackageItem,
    *,
    tenant_id: int,
    cycle_config: CycleConfig,
    cycle_year: int,
    open_status_id: int,
    closed_status_ids: set[int],
) -> tuple[int, int]:
    occurrences = occurrences_for(db, item, tenant_id=tenant_id, cycle_config=cycle_config, cycle_year=cycle_year)
    existing = {
        todo.occurrence_key: todo
        for todo in db.scalars(
            select(ProtocolTodo).where(
                ProtocolTodo.task_package_item_id == item.id,
                ProtocolTodo.cycle_config_id == cycle_config.id,
                ProtocolTodo.cycle_year == cycle_year,
            )
        )
    }
    assignees = resolve_assignee_ids(db, item, tenant_id=tenant_id)
    created = updated = 0
    for occurrence in occurrences:
        values: dict[str, Any] = {
            "task": item.task,
            "reference_link": item.reference_link,
            "tags": list(item.tags or []),
            "due_date": due_date_for(item, occurrence, cycle_config=cycle_config, cycle_year=cycle_year),
        }
        todo = existing.get(occurrence.key)
        if todo is None:
            todo = ProtocolTodo(
                tenant_id=tenant_id,
                protocol_element_block_id=None,
                sort_index=0,
                todo_status_id=open_status_id,
                task_package_item_id=item.id,
                cycle_config_id=cycle_config.id,
                cycle_year=cycle_year,
                occurrence_key=occurrence.key,
                overridden_fields=[],
                **values,
            )
            db.add(todo)
            db.flush()
            set_todo_assignees(db, todo, assignees)
            created += 1
            continue
        if todo.todo_status_id in closed_status_ids or todo.pending_delete:
            continue
        overridden = set(todo.overridden_fields or [])
        changed = False
        for field, value in values.items():
            if field in overridden or getattr(todo, field) == value:
                continue
            setattr(todo, field, value)
            changed = True
        if _clear_foreign_due(todo, overridden):
            changed = True
        if "assignees" not in overridden and todo_assignee_ids(db, todo.id) != assignees:
            set_todo_assignees(db, todo, assignees)
            changed = True
        if changed:
            db.add(todo)
            updated += 1
    return created, updated


def _clear_foreign_due(todo: ProtocolTodo, overridden: set[str]) -> bool:
    """Eine Paket-Instanz hat ihre Fälligkeit immer als Datum. Ein von Hand gesetzter Termin oder
    Sitzungsmarker gilt als Überschreibung der Fälligkeit (siehe mark_overrides); ohne diese
    Überschreibung werden Reste davon entfernt."""
    if "due_date" in overridden or (todo.due_event_id is None and todo.due_marker is None):
        return False
    todo.due_event_id = None
    todo.due_marker = None
    return True


def sync_package_cycle(db: Session, package: TaskPackage, package_cycle: TaskPackageCycle, *, today: date | None = None) -> tuple[int, int]:
    """Erzeugt/aktualisiert die Instanzen des laufenden Zyklus. Kein Commit."""
    if not package.is_active:
        return 0, 0
    cycle_config = db.get(CycleConfig, package_cycle.cycle_config_id)
    if cycle_config is None:
        return 0, 0
    cycle_year = current_cycle_year(cycle_config, today)
    if cycle_year < package_cycle.start_cycle_year:
        return 0, 0
    open_status_id, closed_status_ids = _status_ids(db)
    created = updated = 0
    for item in _items(db, package.id):
        c, u = _sync_item(
            db,
            item,
            tenant_id=package.tenant_id,
            cycle_config=cycle_config,
            cycle_year=cycle_year,
            open_status_id=open_status_id,
            closed_status_ids=closed_status_ids,
        )
        created += c
        updated += u
    return created, updated


def sync_package(db: Session, package: TaskPackage, *, today: date | None = None, commit: bool = True) -> tuple[int, int]:
    created = updated = 0
    for package_cycle in _package_cycles(db, package.id):
        c, u = sync_package_cycle(db, package, package_cycle, today=today)
        created += c
        updated += u
    if commit:
        db.commit()
    return created, updated


def sync_packages_for_list(db: Session, *, tenant_id: int, list_definition_id: int, today: date | None = None) -> int:
    """Nach einer Listenänderung: alle Pakete, deren Aufgaben diese Liste verwenden, für den
    laufenden Zyklus neu auflösen. Vergangene Zyklen bleiben unberührt."""
    packages = db.scalars(
        select(TaskPackage)
        .join(TaskPackageItem, TaskPackageItem.task_package_id == TaskPackage.id)
        .where(
            TaskPackage.tenant_id == tenant_id,
            TaskPackage.is_active.is_(True),
            TaskPackageItem.responsible_json.contains([{"list_definition_id": list_definition_id}]),
        )
        .distinct()
    ).all()
    for package in packages:
        sync_package(db, package, today=today, commit=False)
    db.commit()
    return len(packages)


def sync_packages_for_event_tag(db: Session, *, tenant_id: int, tag: str | None, today: date | None = None) -> None:
    """Nach Anlegen/Ändern eines Termins: Pakete mit Wiederholung "pro Termin" für diesen Tag
    nachführen, damit die Aufgabe für den neuen Termin sofort entsteht."""
    if not tag:
        return
    packages = db.scalars(
        select(TaskPackage)
        .join(TaskPackageItem, TaskPackageItem.task_package_id == TaskPackage.id)
        .where(
            TaskPackage.tenant_id == tenant_id,
            TaskPackage.is_active.is_(True),
            TaskPackageItem.recurrence_json.contains({"type": "events", "event_tag": tag}),
        )
        .distinct()
    ).all()
    for package in packages:
        sync_package(db, package, today=today, commit=False)
    db.commit()


def sync_packages_after_change(db: Session, *, tenant_id: int, list_definition_id: int | None = None, event_tag: str | None = None) -> None:
    """Best-Effort-Nachführen nach einer Listen- oder Terminänderung aus einer Route heraus.
    Die eigentliche Änderung ist dann bereits gespeichert und soll nicht scheitern, nur weil das
    Nachführen scheitert (der tägliche Job holt es nach) - der Fehler wird aber zentral erfasst."""
    try:
        if list_definition_id is not None:
            sync_packages_for_list(db, tenant_id=tenant_id, list_definition_id=list_definition_id)
        if event_tag:
            sync_packages_for_event_tag(db, tenant_id=tenant_id, tag=event_tag)
    except Exception as exc:
        db.rollback()
        record_system_error(db, exc=exc, tenant_id=tenant_id)


def run_due_task_packages(db: Session, *, today: date | None = None) -> dict[str, int]:
    """Täglicher Job task_package_rollover: legt beim Zykluswechsel die Instanzen des neuen
    Zyklus an und ergänzt neue Wiederholungen (z. B. neu erfasste Termine). Idempotent."""
    created = updated = packages = failed = 0
    # Nur Mandanten mit gebuchtem Feature; nach einem Downgrade (nur lesen) bleiben die
    # bestehenden Pendenzen, es entstehen aber keine neuen (permissions/features.json).
    booked = select(TenantFeature.tenant_id).where(TenantFeature.feature_code == F.TASK_PACKAGES, TenantFeature.access == "full")
    package_ids = list(db.execute(
        select(TaskPackage.id, TaskPackage.tenant_id)
        .where(TaskPackage.is_active.is_(True), TaskPackage.tenant_id.in_(booked))
        .order_by(TaskPackage.id)
    ))
    for package_id, tenant_id in package_ids:
        # Ein fehlerhaftes Paket darf die übrigen nicht blockieren - Fehler landet trotzdem
        # in system_error_log (der Loop selbst sähe ihn nicht mehr).
        try:
            package = db.get(TaskPackage, package_id)
            if package is None:
                continue
            c, u = sync_package(db, package, today=today, commit=True)
        except Exception as exc:
            db.rollback()
            record_system_error(db, exc=exc, tenant_id=tenant_id)
            failed += 1
            continue
        created += c
        updated += u
        packages += 1
    if failed:
        raise RuntimeError(f"{failed} Aufgabenpaket(e) konnten nicht nachgeführt werden")
    return {"packages": packages, "created": created, "updated": updated}


# ---------------------------------------------------------------------------
# Löschen / Lösen
# ---------------------------------------------------------------------------


def remove_todos(
    db: Session,
    package: TaskPackage,
    *,
    mode: str,
    cycle_config_id: int | None = None,
    today: date | None = None,
) -> tuple[int, int]:
    """Entfernt die Instanzen eines Pakets (optional nur eines Zyklus):
    - all: alle Instanzen löschen
    - future: nur Instanzen ab dem nächsten Zyklus löschen (laufender und vergangene bleiben)
    - none: nichts löschen
    Gibt (gelöscht, behalten) zurück. Kein Commit."""
    if mode not in ("all", "future", "none"):
        raise ValueError("Unbekannter Löschmodus")
    item_ids = select(TaskPackageItem.id).where(TaskPackageItem.task_package_id == package.id)
    conditions = [ProtocolTodo.task_package_item_id.in_(item_ids)]
    if cycle_config_id is not None:
        conditions.append(ProtocolTodo.cycle_config_id == cycle_config_id)
    todos = db.scalars(select(ProtocolTodo).where(*conditions)).all()
    current_years: dict[int, int] = {}
    deleted = 0
    for todo in todos:
        remove = mode == "all"
        if mode == "future" and todo.cycle_config_id is not None and todo.cycle_year is not None:
            if todo.cycle_config_id not in current_years:
                cycle_config = db.get(CycleConfig, todo.cycle_config_id)
                current_years[todo.cycle_config_id] = current_cycle_year(cycle_config, today) if cycle_config else 0
            remove = todo.cycle_year > current_years[todo.cycle_config_id]
        if remove:
            db.delete(todo)
            deleted += 1
    return deleted, len(todos) - deleted


def delete_package(db: Session, package: TaskPackage, *, mode: str, today: date | None = None) -> tuple[int, int]:
    deleted, kept = remove_todos(db, package, mode=mode, today=today)
    db.flush()
    # Behaltene Instanzen werden zu normalen Todos (FK ON DELETE SET NULL).
    db.delete(package)
    db.commit()
    return deleted, kept


def unassign_cycle(db: Session, package: TaskPackage, package_cycle: TaskPackageCycle, *, mode: str, today: date | None = None) -> tuple[int, int]:
    deleted, kept = remove_todos(db, package, mode=mode, cycle_config_id=package_cycle.cycle_config_id, today=today)
    # Behaltene Instanzen dieses Zyklus vom Paket lösen, sonst würden sie bei einer erneuten
    # Zuweisung wieder vom Paket überschrieben.
    item_ids = select(TaskPackageItem.id).where(TaskPackageItem.task_package_id == package.id)
    db.execute(
        update(ProtocolTodo)
        .where(ProtocolTodo.task_package_item_id.in_(item_ids), ProtocolTodo.cycle_config_id == package_cycle.cycle_config_id)
        .values(task_package_item_id=None)
        .execution_options(synchronize_session=False)
    )
    db.delete(package_cycle)
    db.commit()
    return deleted, kept


# ---------------------------------------------------------------------------
# Lesen
# ---------------------------------------------------------------------------


def _items(db: Session, package_id: int) -> list[TaskPackageItem]:
    return list(
        db.scalars(
            select(TaskPackageItem)
            .where(TaskPackageItem.task_package_id == package_id)
            .order_by(TaskPackageItem.sort_index, TaskPackageItem.id)
        )
    )


def _package_cycles(db: Session, package_id: int) -> list[TaskPackageCycle]:
    return list(
        db.scalars(select(TaskPackageCycle).where(TaskPackageCycle.task_package_id == package_id).order_by(TaskPackageCycle.id))
    )


def list_items(db: Session, package_id: int) -> list[TaskPackageItem]:
    return _items(db, package_id)


def list_package_cycles(db: Session, package_id: int) -> list[TaskPackageCycle]:
    return _package_cycles(db, package_id)


def todo_counts(db: Session, package_ids: Iterable[int]) -> dict[int, tuple[int, int]]:
    """{package_id: (offen, gesamt)} der verknüpften Instanzen."""
    ids = list(package_ids)
    if not ids:
        return {}
    _, closed = _status_ids(db)
    rows = db.execute(
        select(
            TaskPackageItem.task_package_id,
            func.count(ProtocolTodo.id),
            func.count(ProtocolTodo.id).filter(ProtocolTodo.todo_status_id.not_in(closed or {-1})),
        )
        .join(ProtocolTodo, ProtocolTodo.task_package_item_id == TaskPackageItem.id)
        .where(TaskPackageItem.task_package_id.in_(ids))
        .group_by(TaskPackageItem.task_package_id)
    ).all()
    return {row[0]: (row[2], row[1]) for row in rows}


def preview(
    db: Session, package: TaskPackage, *, cycle_config: CycleConfig, cycle_year: int
) -> list[dict[str, Any]]:
    """Was im angegebenen Zyklus entstehen würde - mit den Verantwortlichen, wie sie heute in
    der Liste stehen."""
    entries: list[dict[str, Any]] = []
    for item in _items(db, package.id):
        assignee_ids = resolve_assignee_ids(db, item, tenant_id=package.tenant_id)
        names_by_id = dict(
            db.execute(select(Participant.id, Participant.display_name).where(Participant.id.in_(assignee_ids or [-1]))).all()
        )
        existing_keys = set(
            db.scalars(
                select(ProtocolTodo.occurrence_key).where(
                    ProtocolTodo.task_package_item_id == item.id,
                    ProtocolTodo.cycle_config_id == cycle_config.id,
                    ProtocolTodo.cycle_year == cycle_year,
                )
            )
        )
        for occurrence in occurrences_for(db, item, tenant_id=package.tenant_id, cycle_config=cycle_config, cycle_year=cycle_year):
            entries.append(
                {
                    "item": item,
                    "occurrence": occurrence,
                    "due_date": due_date_for(item, occurrence, cycle_config=cycle_config, cycle_year=cycle_year),
                    "assignee_names": [names_by_id[pid] for pid in assignee_ids if pid in names_by_id],
                    "exists": occurrence.key in existing_keys,
                }
            )
    entries.sort(key=lambda entry: (entry["occurrence"].anchor, entry["item"].sort_index))
    return entries


# ---------------------------------------------------------------------------
# Überschreibungen aus der normalen Todo-Bearbeitung
# ---------------------------------------------------------------------------

_OVERRIDE_FIELD_MAP = {
    "task": "task",
    "reference_link": "reference_link",
    "tags": "tags",
    "due_date": "due_date",
    "due_event_id": "due_date",
    "due_marker": "due_date",
    "assigned_participant_id": "assignees",
}


def mark_overrides(todo: ProtocolTodo, changed_fields: Iterable[str]) -> None:
    """Merkt sich, welche Paket-Felder ein Mensch an dieser Instanz geändert hat."""
    if todo.task_package_item_id is None:
        return
    overridden = list(todo.overridden_fields or [])
    for field in changed_fields:
        managed = _OVERRIDE_FIELD_MAP.get(field)
        if managed and managed not in overridden:
            overridden.append(managed)
    todo.overridden_fields = overridden


def list_entry_belongs_to_tenant(db: Session, *, list_definition_id: int, list_entry_id: int, tenant_id: int) -> bool:
    return bool(
        db.scalar(
            select(func.count(ListEntry.id))
            .join(ListDefinition, ListDefinition.id == ListEntry.list_definition_id)
            .where(ListEntry.id == list_entry_id, ListDefinition.id == list_definition_id, ListDefinition.tenant_id == tenant_id)
        )
    )
