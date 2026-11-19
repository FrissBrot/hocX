"""Einzelabgaben mit mehreren Abgabeelementen (Migration 0198, submission_manual_element).

- Migration: Backfill genau eines Standard-Elements je bestehender Einzelabgabe (Name = Titel, Ende =
  bisheriger Stichtag, Referenz «manual»), bestehende Einreichungen gehören weiter dazu; Downgrade
  schlägt zusätzliche Elemente dem einen Element zu.
- Anlegen/Ändern/Entfernen über die Routen (submissions.manage), Reihenfolge, stabile IDs.
- Mandantentrennung: fremde Personen, fremde Element-IDs, fremde Abgaben werden abgelehnt.
- Pendenzen je Element mit Verantwortlichen, Abgleich bei Änderung und Entfernen, Trigger bei
  geprüfter Datei, Fortschritt und Zählung je Element.
- Abgabebox-Lesepfad (Rolle hocx_abgabebox): nur Mandant des Links, nur freigegebene Spalten,
  Einreichung nur auf Elemente der eigenen Abgabe.
"""
from __future__ import annotations

import importlib.util
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text

from app.api.routes import submission_assignments as routes
from app.models import (
    GalleryImage,
    ProtocolTodo,
    StoredFile,
    SubmissionAssignment,
    SubmissionManualElement,
    SubmissionUpload,
    SubmissionUploadFile,
    TodoStatus,
)
from app.schemas.submission import (
    SubmissionAssignmentCreate,
    SubmissionAssignmentUpdate,
    SubmissionLinkCreate,
    SubmissionManualElementWrite,
)
from app.services.data_export.personal import collect
from app.services.submission_link_service import SubmissionLinkService
from app.services.submission_service import SubmissionService
from app.services.tenant_clone_service import TenantCloneService
from tests.factories import make_current_user, make_participant, make_tenant
from tests.test_submission_links import _probe_as_abgabebox
from tests.test_tenant_export_import import _export_import

BACKEND_ROOT = Path(__file__).resolve().parents[1]
service = SubmissionService()


@pytest.fixture
def org(db):
    tenant = make_tenant(db, "Pfadi Einzel")
    other = make_tenant(db, "Fremdverein")
    anna = make_participant(db, tenant.id, display_name="Anna Muster")
    ben = make_participant(db, tenant.id, display_name="Ben Beispiel")
    stranger = make_participant(db, other.id, display_name="Fremde Person")
    link = SubmissionLinkService().create_link(db, SubmissionLinkCreate(name="Eltern"), tenant_id=tenant.id)
    return {
        "tenant": tenant, "other": other, "anna": anna, "ben": ben, "stranger": stranger, "link": link,
        "user": make_current_user(tenant.id, role="admin"), "other_user": make_current_user(other.id, role="admin"),
    }


def _create(db, org, elements: list[dict] | None, **values):
    payload = SubmissionAssignmentCreate(
        title=values.pop("title", "Lager"), public_slug=values.pop("public_slug", "lager"), source_type="manual",
        link_ids=[org["link"].id],
        manual_elements=[SubmissionManualElementWrite(**element) for element in elements] if elements is not None else None,
        **values,
    )
    read = routes.create_assignment(payload, db=db, user=org["user"])
    return read, db.scalar(select(SubmissionAssignment).where(SubmissionAssignment.public_id == read.id))


def _patch(db, org, read, elements: list[dict], user=None):
    payload = SubmissionAssignmentUpdate(manual_elements=[SubmissionManualElementWrite(**element) for element in elements])
    return routes.patch_assignment(read.id, payload, db=db, user=user or org["user"])


def _todos(db, assignment) -> dict[str, ProtocolTodo]:
    db.expire_all()
    return {todo.element_ref: todo for todo in db.scalars(select(ProtocolTodo).where(ProtocolTodo.submission_assignment_id == assignment.id))}


def _status_code(db, todo) -> str:
    db.expire(todo)
    return db.scalar(select(TodoStatus.code).where(TodoStatus.id == todo.todo_status_id))


def _upload(db, tenant_id: int, assignment, *, manual_element_id=None, scan_status="clean", with_file=True):
    upload = SubmissionUpload(assignment_id=assignment.id, manual_element_id=manual_element_id, status="submitted", submitted_at=datetime.now(UTC))
    db.add(upload)
    db.flush()
    if with_file:
        stored = StoredFile(
            tenant_id=tenant_id, original_name="anmeldung.pdf", mime_type="application/pdf",
            storage_path=f"tenant-{tenant_id}/{uuid.uuid4().hex}.pdf", scan_status=scan_status,
        )
        db.add(stored)
        db.flush()
        db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=stored.id, sort_index=0))
        db.flush()
    return upload


# --- Anlegen, Ändern, Entfernen ----------------------------------------------------------------


def test_new_single_submission_without_elements_gets_one_default_element_from_title_and_deadline(db, org):
    end = date.today() + timedelta(days=10)
    read, assignment = _create(db, org, None, deadline=end)

    assert assignment.deadline is None  # das Zeitfenster gehört seit 0198 zum Element
    [element] = read.manual_elements
    assert (element.name, element.window_end, element.is_default, element.element_ref) == ("Lager", end, True, "manual")
    assert [item.element_ref for item in service.get_assignment_elements(db, assignment)] == ["manual"]


def test_create_update_and_remove_elements_with_stable_ids(db, org):
    read, assignment = _create(db, org, [
        {"name": "Anmeldung", "window_end": date.today() + timedelta(days=5), "responsible_participant_ids": [org["anna"].public_id]},
        {"name": "Fotos", "window_start": date.today() - timedelta(days=1)},
    ])
    first, second = read.manual_elements
    assert first.is_default and first.element_ref == "manual"
    assert not second.is_default and second.element_ref == f"manual-{second.id}"
    assert first.responsible_participant_ids == [org["anna"].public_id]

    updated = _patch(db, org, read, [
        {"id": second.id, "name": "Fotos (Lager)", "responsible_participant_ids": [org["ben"].public_id, org["anna"].public_id]},
        {"name": "Abrechnung", "window_end": date.today() + timedelta(days=30)},
    ])
    names = [(item.name, item.id) for item in updated.manual_elements]
    assert names[0] == ("Fotos (Lager)", second.id)  # gleiche ID, neue Reihenfolge
    assert names[1][0] == "Abrechnung" and names[1][1] not in (first.id, second.id)
    assert updated.manual_elements[0].responsible_participant_ids == [org["ben"].public_id, org["anna"].public_id]
    # Das Standard-Element ist weg; kein anderes wird nachträglich zum Standard (Referenzen bleiben stabil)
    assert [item.element_ref for item in updated.manual_elements] == [f"manual-{second.id}", f"manual-{names[1][1]}"]
    assert db.scalar(select(func.count(SubmissionManualElement.id)).where(SubmissionManualElement.assignment_id == assignment.id)) == 2


def test_an_empty_list_and_a_window_ending_before_its_start_are_rejected(db, org):
    with pytest.raises(ValueError):
        SubmissionManualElementWrite(name="X", window_start=date(2026, 12, 2), window_end=date(2026, 12, 1))
    with pytest.raises(ValueError):
        SubmissionManualElementWrite(name="   ")
    read, _assignment = _create(db, org, [{"name": "Anmeldung"}])
    # Zuletzt: die Route rollt bei einem Fehler die (Test-)Transaktion zurück
    with pytest.raises(HTTPException) as excinfo:
        _patch(db, org, read, [])
    assert excinfo.value.status_code == 400 and excinfo.value.detail == "Eine Einzelabgabe braucht mindestens ein Element"


def test_removing_an_element_drops_its_submission_rows_and_app_links(db, org):
    read, assignment = _create(db, org, [{"name": "Anmeldung"}, {"name": "Fotos"}])
    extra = db.scalar(select(SubmissionManualElement).where(SubmissionManualElement.public_id == read.manual_elements[1].id))
    service.close_element(db, assignment, f"manual-{extra.public_id}")  # Zeile ohne Dateien
    gallery_file = StoredFile(tenant_id=org["tenant"].id, original_name="f.jpg", mime_type="image/jpeg", storage_path="main/f.jpg")
    db.add(gallery_file)
    db.flush()
    image = GalleryImage(
        tenant_id=org["tenant"].id, stored_file_id=gallery_file.id, submission_assignment_id=assignment.id,
        submission_element_ref=f"manual-{extra.public_id}",
    )
    db.add(image)
    db.flush()

    _patch(db, org, read, [{"id": read.manual_elements[0].id, "name": "Anmeldung"}])

    db.expire_all()
    assert db.scalar(select(func.count(SubmissionUpload.id)).where(SubmissionUpload.assignment_id == assignment.id)) == 0
    assert (image.submission_assignment_id, image.submission_element_ref) == (None, None)


def test_elements_only_for_single_submissions(db, org):
    tenant = org["tenant"]
    with pytest.raises(HTTPException) as excinfo:
        routes.create_assignment(
            SubmissionAssignmentCreate(
                title="Berichte", public_slug="berichte", source_type="events", tag_filter="lager",
                manual_elements=[SubmissionManualElementWrite(name="X")],
            ),
            db=db, user=make_current_user(tenant.id, role="admin"),
        )
    assert excinfo.value.status_code == 400 and excinfo.value.detail == "Elemente gibt es nur bei Einzelabgaben"


def test_writing_elements_needs_submissions_manage(db, org):
    read, _assignment = _create(db, org, [{"name": "Anmeldung"}])
    reader = make_current_user(org["tenant"].id, role="reader")
    with pytest.raises(HTTPException) as excinfo:
        _patch(db, org, read, [{"name": "Eingeschleust"}], user=reader)
    assert excinfo.value.status_code == 403


# --- Fremder Mandant ---------------------------------------------------------------------------


def _update_elements(db, assignment, elements: list[dict]):
    return service.update_assignment(
        db, assignment.id, SubmissionAssignmentUpdate(manual_elements=[SubmissionManualElementWrite(**element) for element in elements])
    )


def test_responsible_person_of_another_tenant_is_rejected(db, org):
    read, assignment = _create(db, org, [{"name": "Anmeldung", "responsible_participant_ids": [org["anna"].public_id]}])
    element_id = read.manual_elements[0].id
    # Geprüft wird vor jeder Änderung: nichts geschrieben
    with pytest.raises(ValueError) as foreign:
        _update_elements(db, assignment, [{"id": element_id, "name": "Neu", "responsible_participant_ids": [org["stranger"].public_id]}])
    # Unbekannte ID: dieselbe Antwort (kein Existenz-Orakel)
    with pytest.raises(ValueError) as unknown:
        _update_elements(db, assignment, [{"id": element_id, "name": "Neu", "responsible_participant_ids": [uuid.uuid4()]}])
    assert str(foreign.value) == str(unknown.value) == "Verantwortliche Person nicht gefunden"
    db.expire_all()
    element = db.scalar(select(SubmissionManualElement).where(SubmissionManualElement.assignment_id == assignment.id))
    assert (element.name, element.responsible_participant_ids) == ("Anmeldung", [org["anna"].id])

    # Anlegen über die Route: 400 mit derselben Meldung (zuletzt, die Route rollt zurück)
    with pytest.raises(HTTPException) as excinfo:
        _create(db, org, [{"name": "Anmeldung", "responsible_participant_ids": [org["stranger"].public_id]}], public_slug="lager-2")
    assert excinfo.value.status_code == 400 and excinfo.value.detail == "Verantwortliche Person nicht gefunden"


def test_element_ids_of_another_assignment_or_tenant_are_rejected(db, org):
    read, _assignment = _create(db, org, [{"name": "Anmeldung"}])
    other_read, _other = _create(db, org, [{"name": "Fremd"}], title="Andere", public_slug="andere")
    with pytest.raises(ValueError, match="Element nicht gefunden"):
        _update_elements(db, _assignment, [{"id": other_read.manual_elements[0].id, "name": "Gestohlen"}])
    db.expire_all()
    assert db.scalar(select(SubmissionManualElement.name).where(SubmissionManualElement.public_id == other_read.manual_elements[0].id)) == "Fremd"

    # Eine Abgabe des anderen Mandanten ist für ihn 404, seine Personen bleiben unsichtbar
    with pytest.raises(HTTPException) as foreign:
        routes.patch_assignment(read.id, SubmissionAssignmentUpdate(manual_elements=[SubmissionManualElementWrite(name="X")]), db=db, user=org["other_user"])
    assert foreign.value.status_code == 404


def test_stored_foreign_ids_never_surface_as_responsible(db, org):
    """Defense in depth: eine am Dienst vorbei gespeicherte fremde Personen-ID wird weder
    angezeigt noch bekommt sie eine Pendenz."""
    read, assignment = _create(db, org, [{"name": "Anmeldung"}])
    element = db.scalar(select(SubmissionManualElement).where(SubmissionManualElement.assignment_id == assignment.id))
    element.responsible_participant_ids = [org["stranger"].id]
    db.flush()
    assert service.manual_elements_read(db, assignment)[0].responsible_participant_ids == []
    service.sync_submission_todos(db, assignment)
    assert _todos(db, assignment) == {}


# --- Pendenzen, Fortschritt ---------------------------------------------------------------------


def test_todos_per_element_follow_changes_and_removal(db, org):
    end = date.today() + timedelta(days=7)
    read, assignment = _create(db, org, [
        {"name": "Lager", "responsible_participant_ids": [org["anna"].public_id]},
        {"name": "Fotos", "window_end": end, "responsible_participant_ids": [org["ben"].public_id]},
        {"name": "Ohne Person"},
    ])
    extra_ref = read.manual_elements[1].element_ref
    todos = _todos(db, assignment)
    assert set(todos) == {"manual", extra_ref}
    assert todos["manual"].task == "Lager"  # Standard-Element heisst wie die Abgabe: nicht doppelt
    assert todos[extra_ref].task == "Lager: Fotos"
    assert todos[extra_ref].due_date == end
    assert todos[extra_ref].assigned_participant_id == org["ben"].id
    assert todos[extra_ref].reference_link.endswith(f"/lager/{extra_ref}")

    later = end + timedelta(days=3)
    _patch(db, org, read, [
        {"id": read.manual_elements[1].id, "name": "Fotos", "window_end": later, "responsible_participant_ids": [org["anna"].public_id]},
        {"id": read.manual_elements[2].id, "name": "Ohne Person"},
    ])
    todos = _todos(db, assignment)
    assert set(todos) == {extra_ref}  # Element entfernt: Pendenz weg
    assert todos[extra_ref].due_date == later and todos[extra_ref].assigned_participant_id == org["anna"].id


def test_clean_file_on_an_extra_element_completes_only_its_todo_and_counts_once(db, org):
    read, assignment = _create(db, org, [
        {"name": "Anmeldung", "responsible_participant_ids": [org["anna"].public_id]},
        {"name": "Fotos", "responsible_participant_ids": [org["ben"].public_id]},
    ])
    extra = db.scalar(select(SubmissionManualElement).where(SubmissionManualElement.public_id == read.manual_elements[1].id))
    extra_ref = f"manual-{extra.public_id}"

    _upload(db, org["tenant"].id, assignment, manual_element_id=extra.id)  # Trigger 0175/0198
    todos = _todos(db, assignment)
    assert _status_code(db, todos[extra_ref]) == "done"
    assert _status_code(db, todos["manual"]) == "open"

    elements = {element.element_ref: element for element in service.get_assignment_elements(db, assignment)}
    assert elements[extra_ref].status == "submitted" and len(elements[extra_ref].files) == 1
    assert elements["manual"].status == "open" and elements["manual"].files == []
    summary = service.summaries(db, [assignment])[assignment.id]
    assert summary == {"submitted": 1, "quarantine": 0, "infected": 0, "closed": 0, "total": 2}

    # Schliessen/Öffnen je Element; abgeschlossen erst, wenn alle erledigt sind
    service.close_element(db, assignment, "manual")
    assert service.assignment_completion(db, assignment) is True
    service.reopen_element(db, assignment, "manual")
    assert service.assignment_completion(db, assignment) is False
    with pytest.raises(ValueError):
        service.close_element(db, assignment, f"manual-{uuid.uuid4()}")


def test_personal_data_export_lists_the_elements_a_person_is_responsible_for(db, org):
    _create(db, org, [{"name": "Anmeldung", "window_end": date(2026, 12, 31), "responsible_participant_ids": [org["anna"].public_id]}])
    data = collect(db, org["anna"])
    assert data["submission_elements"] == [{"title": "Lager", "name": "Anmeldung", "due_date": date(2026, 12, 31)}]
    assert collect(db, org["ben"])["submission_elements"] == []


# --- Abgabebox-Lesepfad -------------------------------------------------------------------------


def test_abgabebox_reads_only_the_elements_of_its_link_tenant_and_only_granted_columns(db, org):
    read, assignment = _create(db, org, [{"name": "Anmeldung", "responsible_participant_ids": [org["anna"].public_id]}, {"name": "Fotos"}])
    other_link = SubmissionLinkService().create_link(db, SubmissionLinkCreate(name="Fremd"), tenant_id=org["other"].id)
    routes.create_assignment(
        SubmissionAssignmentCreate(title="Fremd", public_slug="fremd", source_type="manual", link_ids=[other_link.id]),
        db=db, user=org["other_user"],
    )
    sql = "SELECT name, is_default, window_start, window_end, sort_index, public_id FROM submission_manual_element ORDER BY assignment_id, sort_index"

    rows, error = _probe_as_abgabebox(db, sql, link_token=org["link"].token)
    assert error is None and [row[0] for row in rows] == ["Anmeldung", "Fotos"]
    rows, error = _probe_as_abgabebox(db, sql, link_token=other_link.token)
    assert error is None and [row[0] for row in rows] == ["Fremd"]
    rows, error = _probe_as_abgabebox(db, sql)
    assert error is None and rows == []
    # Verantwortliche sind für die öffentliche Rolle nicht lesbar, schreiben darf sie gar nicht
    _rows, error = _probe_as_abgabebox(db, "SELECT responsible_participant_ids FROM submission_manual_element", link_token=org["link"].token)
    assert error is not None and "permission denied" in error
    _rows, error = _probe_as_abgabebox(
        db, "UPDATE submission_manual_element SET name = 'x' WHERE assignment_id = :id", {"id": assignment.id}, link_token=org["link"].token,
    )
    assert error is not None and "permission denied" in error


def test_abgabebox_can_submit_only_to_elements_of_the_same_assignment(db, org):
    read, assignment = _create(db, org, [{"name": "Anmeldung"}, {"name": "Fotos"}])
    other_read, other_assignment = _create(db, org, [{"name": "Andere"}, {"name": "Andere 2"}], title="Andere", public_slug="andere")
    own = db.scalar(select(SubmissionManualElement.id).where(SubmissionManualElement.public_id == read.manual_elements[1].id))
    foreign = db.scalar(select(SubmissionManualElement.id).where(SubmissionManualElement.public_id == other_read.manual_elements[1].id))
    insert = (
        "INSERT INTO submission_upload (assignment_id, manual_element_id, status, submitted_at) "
        "VALUES (:assignment_id, :element_id, 'submitted', now())"
    )
    _rows, error = _probe_as_abgabebox(db, insert, {"assignment_id": assignment.id, "element_id": own}, link_token=org["link"].token)
    assert error is None
    _rows, error = _probe_as_abgabebox(db, insert, {"assignment_id": assignment.id, "element_id": foreign}, link_token=org["link"].token)
    assert error is not None and "fk_submission_upload_manual_element" in error


def test_abgabebox_functions_count_files_per_manual_element(db, org):
    read, assignment = _create(db, org, [{"name": "Anmeldung"}, {"name": "Fotos"}])
    extra = db.scalar(select(SubmissionManualElement).where(SubmissionManualElement.public_id == read.manual_elements[1].id))
    for ref in ("manual", f"manual-{extra.public_id}", f"manual-{extra.public_id}"):
        stored = StoredFile(tenant_id=org["tenant"].id, original_name="f.jpg", mime_type="image/jpeg", storage_path=f"main/{uuid.uuid4().hex}.jpg")
        db.add(stored)
        db.flush()
        db.add(GalleryImage(tenant_id=org["tenant"].id, stored_file_id=stored.id, submission_assignment_id=assignment.id, submission_element_ref=ref))
    db.flush()
    sql = "SELECT event_id, list_entry_id, manual_element_id, file_count FROM public.submission_linked_file_counts(:id) ORDER BY 3 NULLS FIRST"
    rows, error = _probe_as_abgabebox(db, sql, {"id": assignment.id}, link_token=org["link"].token)
    assert error is None and [tuple(row) for row in rows] == [(None, None, None, 1), (None, None, extra.id, 2)]

    db.execute(text("UPDATE gallery_image SET submission_withdrawn_at = now() WHERE submission_element_ref = :ref"), {"ref": f"manual-{extra.public_id}"})
    rows, error = _probe_as_abgabebox(
        db, "SELECT event_id, list_entry_id, manual_element_id FROM public.submission_withdrawn_elements(:id)", {"id": assignment.id},
        link_token=org["link"].token,
    )
    assert error is None and [tuple(row) for row in rows] == [(None, None, extra.id)]


# --- Mandanten-Export/-Import, Klon --------------------------------------------------------------


def test_export_import_and_clone_keep_elements_responsible_and_refs(db, org):
    read, assignment = _create(db, org, [
        {"name": "Anmeldung", "responsible_participant_ids": [org["anna"].public_id]},
        {"name": "Fotos", "window_end": date(2026, 12, 31), "responsible_participant_ids": [org["ben"].public_id]},
    ])
    extra = db.scalar(select(SubmissionManualElement).where(SubmissionManualElement.public_id == read.manual_elements[1].id))
    service.close_element(db, assignment, f"manual-{extra.public_id}")

    def check(tenant_id: int) -> None:
        copy = db.scalar(select(SubmissionAssignment).where(SubmissionAssignment.tenant_id == tenant_id))
        elements = db.scalars(
            select(SubmissionManualElement).where(SubmissionManualElement.assignment_id == copy.id).order_by(SubmissionManualElement.sort_index)
        ).all()
        assert [(e.name, e.is_default, e.window_end, e.tenant_id) for e in elements] == [
            ("Anmeldung", True, None, tenant_id), ("Fotos", False, date(2026, 12, 31), tenant_id),
        ]
        # Verantwortliche zeigen auf die Personen des neuen Mandanten
        for element in elements:
            for pid in element.responsible_participant_ids:
                assert db.scalar(text("SELECT tenant_id FROM app_user WHERE id = :id"), {"id": pid}) == tenant_id
        # Die Schliessung gehört weiter zum zusätzlichen Element
        states = {e.element_ref: e.status for e in service.get_assignment_elements(db, copy)}
        assert states == {"manual": "open", f"manual-{elements[1].public_id}": "closed"}

    # Einzige Warnung: der Link-Token ist hier schon vergeben (Quell-Mandant existiert noch)
    new_tenant, warnings = _export_import(db, org["tenant"].id, "full_abgabebox")
    assert all("Abgabebox-Link" in warning for warning in warnings)
    check(new_tenant.id)
    cloned = TenantCloneService().clone_full(db, org["tenant"].id, "Pfadi Einzel (Kopie)")
    check(cloned.id)


# --- Migration ----------------------------------------------------------------------------------


@pytest.fixture
def migration(db, monkeypatch):
    spec = importlib.util.spec_from_file_location("migration_0198", BACKEND_ROOT / "alembic/versions/0198_submission_manual_elements.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.op, "get_bind", lambda: db.connection(), raising=False)
    monkeypatch.setattr(module.op, "execute", lambda sql: db.connection().execute(text(sql)), raising=False)
    return module


def test_migration_backfills_one_default_element_per_single_submission_and_downgrades(db, org, migration):
    read, assignment = _create(db, org, [{"name": "Lager", "window_end": date(2026, 12, 24)}, {"name": "Fotos"}])
    extra = db.scalar(select(SubmissionManualElement).where(SubmissionManualElement.public_id == read.manual_elements[1].id))
    _upload(db, org["tenant"].id, assignment, with_file=False)
    _upload(db, org["tenant"].id, assignment, manual_element_id=extra.id, with_file=False)
    assignment_id, title = assignment.id, assignment.title
    db.flush()

    migration.downgrade()
    connection = db.connection()
    assert connection.exec_driver_sql("SELECT to_regclass('public.submission_manual_element')").scalar() is None
    # Stichtag zurück vom Standard-Element, beide Einreichungen jetzt beim einen Element
    assert connection.exec_driver_sql(f"SELECT deadline FROM submission_assignment WHERE id = {assignment_id}").scalar() == date(2026, 12, 24)  # sql-ok: Test-ID
    assert connection.exec_driver_sql(
        f"SELECT count(*) FROM submission_upload WHERE assignment_id = {assignment_id} AND event_id IS NULL AND list_entry_id IS NULL"  # sql-ok: Test-ID
    ).scalar() == 2

    # Zustand vor 0198: Einzelabgabe mit Stichtag, ohne Elemente
    connection.exec_driver_sql(f"UPDATE submission_assignment SET deadline = DATE '2027-01-15' WHERE id = {assignment_id}")  # sql-ok: Test-ID
    migration.upgrade()
    migration.backfill_default_elements(migration.op.execute)  # idempotent
    db.expire_all()

    [element] = db.scalars(select(SubmissionManualElement).where(SubmissionManualElement.assignment_id == assignment_id)).all()
    assert (element.name, element.window_end, element.is_default, element.tenant_id) == (title, date(2027, 1, 15), True, org["tenant"].id)
    reloaded = db.get(SubmissionAssignment, assignment_id)
    assert reloaded.deadline is None
    # Bestehende Einreichungen gehören weiter zum Element «manual»
    [state] = service.get_assignment_elements(db, reloaded)
    assert state.element_ref == "manual" and state.upload_id is not None
    assert db.scalar(select(func.count(SubmissionUpload.id)).where(SubmissionUpload.manual_element_id.is_not(None))) == 0
