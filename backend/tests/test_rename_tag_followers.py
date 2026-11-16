"""POST /events/rename-tag: neben Terminen und Abgabe-Filtern ziehen auch die anderen Stellen mit,
die einen Termin-Tag als Text speichern - sonst verlieren sie nach dem Umbenennen alle Termine:
- Aufgabenpakete mit Wiederholung «pro Termin» (task_package_item.recurrence_json.event_tag,
  exakter Vergleich in task_package_service.occurrences_for): keine Aufgaben für neue Termine mehr.
- Vorlagen mit Fälligkeits-Tag (template.todo_due_event_tag): die Terminauswahl «fällig am»
  bleibt leer."""
from __future__ import annotations

from datetime import date

from app.api.routes import events as events_routes
from app.models.entities import TaskPackage, TaskPackageItem
from tests.factories import make_current_user, make_event, make_template, make_tenant


def _package_item(db, tenant_id: int, event_tag: str) -> TaskPackageItem:
    package = TaskPackage(tenant_id=tenant_id, name=f"Paket {event_tag}")
    db.add(package)
    db.flush()
    item = TaskPackageItem(task_package_id=package.id, task="Material", recurrence_json={"type": "events", "event_tag": event_tag})
    db.add(item)
    db.flush()
    return item


def test_rename_tag_moves_task_package_recurrence_and_template_due_tag(db):
    tenant = make_tenant(db, "Umbenennen")
    other = make_tenant(db, "Anderer")
    user = make_current_user(tenant.id, role="writer")
    event = make_event(db, tenant.id, title="Training", event_date=date(2026, 5, 1))
    event.tag = "Training"
    item = _package_item(db, tenant.id, "Training")
    unrelated = _package_item(db, tenant.id, "GV")
    foreign = _package_item(db, other.id, "Training")
    template = make_template(db, tenant.id)
    template.todo_due_event_tag = "Training"
    foreign_template = make_template(db, other.id)
    foreign_template.todo_due_event_tag = "Training"
    db.flush()

    events_routes.rename_tag(events_routes.RenameTagPayload(old_tag="Training", new_tag="Probe"), db=db, user=user)

    for row in (item, unrelated, foreign, template, foreign_template):
        db.refresh(row)
    assert item.recurrence_json == {"type": "events", "event_tag": "Probe"}
    assert unrelated.recurrence_json["event_tag"] == "GV"
    assert foreign.recurrence_json["event_tag"] == "Training"
    assert template.todo_due_event_tag == "Probe"
    assert foreign_template.todo_due_event_tag == "Training"
