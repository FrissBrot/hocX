"""Abgabebox und Pendenzen bleiben stimmig (Audit 2026-11-12):

- nur geprüfte Dateien erledigen die Pendenz (Trigger 0175), Quarantäne erst nach dem Scan
- der Trigger erledigt ohne Python: der Abgleich friert die Verspätungsbusse nach
- Schliessen ändert keine von Hand erledigte Pendenz, fremde Element-Referenzen schreiben nichts
- Fortschritt zählt jedes Element einmal und nur Elemente, die zur Abgabe gehören
- der ZIP-Download enthält alle Dateien aller Einreichungen, auch nach dem Schliessen
"""
from __future__ import annotations

import uuid
import zipfile
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.api.routes import submission_assignments as routes
from app.api.routes import todo_fines as fine_routes
from app.models import (
    GalleryImage,
    ProtocolTodo,
    StoredFile,
    SubmissionAssignment,
    SubmissionUpload,
    SubmissionUploadFile,
    TodoFine,
    TodoStatus,
)
from app.notifications import dispatch
from app.schemas.submission import SubmissionAssignmentCreate, SubmissionLinkCreate
from app.schemas.todo_fines import (
    FineTariffAssignment,
    FineTariffGroupWrite,
    TodoFineRuleFilter,
    TodoFineRuleRateWrite,
    TodoFineRuleWrite,
)
from app.services.submission_link_service import SubmissionLinkService
from app.services.submission_service import SubmissionService
from tests.factories import (
    DEFAULT_TEST_FEATURES,
    GRANDFATHERED_FEATURES,
    make_current_user,
    make_event,
    make_finance_account,
    make_participant,
    make_tenant,
)

service = SubmissionService()


@pytest.fixture
def box(db):
    tenant = make_tenant(db, "Pfadi Box", features=GRANDFATHERED_FEATURES + ("finance", "todo_fines"))
    other = make_tenant(db, "Fremd")
    anna = make_participant(db, tenant.id, display_name="Anna Muster")
    event = make_event(db, tenant.id, title="Badetag")
    event.tag = "lager"
    event.event_date = date.today() - timedelta(days=20)
    event.spezial1_ids = [anna.id]
    second = make_event(db, tenant.id, title="Wanderung")
    second.tag = "lager"
    second.event_date = date.today() - timedelta(days=20)
    db.flush()
    link = SubmissionLinkService().create_link(db, SubmissionLinkCreate(name="Leiter"), tenant_id=tenant.id)
    created = service.create_assignment(
        db,
        SubmissionAssignmentCreate(
            title="Berichte", public_slug="berichte", source_type="events", tag_filter="lager",
            offset_days_before=30, offset_days_after=7, link_ids=[link.id], responsible_participant_source="spezial1_ids",
        ),
        tenant_id=tenant.id,
    )
    assignment = db.scalar(select(SubmissionAssignment).where(SubmissionAssignment.public_id == created.id))
    [todo] = db.scalars(select(ProtocolTodo).where(ProtocolTodo.submission_assignment_id == assignment.id))
    return {"tenant": tenant, "other": other, "anna": anna, "event": event, "second": second, "assignment": assignment, "todo": todo}


def _code(db, todo) -> str:
    db.expire(todo)
    return db.scalar(select(TodoStatus.code).where(TodoStatus.id == todo.todo_status_id))


def _set_status(db, todo, code: str) -> None:
    todo.todo_status_id = db.scalar(select(TodoStatus.id).where(TodoStatus.code == code))
    todo.completed_at = datetime.now(UTC) if code in ("done", "cancelled") else None
    db.flush()


def _submit(db, box, *, event=None, scan_status="clean", name="bericht.pdf", submitted_at=None) -> StoredFile:
    upload = SubmissionUpload(
        assignment_id=box["assignment"].id, event_id=(event or box["event"]).id, status="submitted",
        submitted_at=submitted_at or datetime.now(UTC),
    )
    db.add(upload)
    db.flush()
    stored = StoredFile(
        tenant_id=box["tenant"].id, original_name=name, mime_type="application/pdf",
        storage_path=f"tenant-x/{uuid.uuid4().hex}.pdf", scan_status=scan_status,
    )
    db.add(stored)
    db.flush()
    db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=stored.id, sort_index=0))
    db.flush()
    return stored


# --- Quarantäne -------------------------------------------------------------------------


def test_file_in_quarantine_does_not_complete_the_task_until_it_is_clean(db, box):
    todo = box["todo"]
    stored = _submit(db, box, scan_status="pending")
    assert _code(db, todo) == "open"

    stored.scan_status = "clean"
    db.flush()
    service.sync_submission_todos(db, box["assignment"])
    assert _code(db, todo) == "done"


def test_clean_file_completes_the_task_at_submission_time(db, box):
    submitted = datetime.now(UTC) - timedelta(minutes=5)
    _submit(db, box, submitted_at=submitted)
    assert _code(db, box["todo"]) == "done"
    assert box["todo"].completed_at == submitted


def test_infected_file_leaves_the_task_open_and_closing_cancels_it(db, box):
    todo = box["todo"]
    _submit(db, box, scan_status="infected")
    assert _code(db, todo) == "open"
    service.close_element(db, box["assignment"], todo.element_ref)
    assert _code(db, todo) == "cancelled"


# --- Bussen auf dem Trigger-Weg -----------------------------------------------------------


def _fine_rule(db, box):
    manager = make_current_user(box["tenant"].id, role="admin", features=DEFAULT_TEST_FEATURES | {"todo_fines"})
    account = make_finance_account(db, box["tenant"].id, "Bussenkasse")
    tariff = fine_routes.create_tariff(FineTariffGroupWrite(name="Leitende"), db=db, user=manager)
    fine_routes.assign_tariff(box["anna"].public_id, FineTariffAssignment(tariff_group_id=tariff.id), db=db, user=manager)
    fine_routes.create_rule(
        TodoFineRuleWrite(
            name="Abgaben", applies_from=date(2020, 1, 1), interval_days=1, split_mode="each", account_id=account.public_id,
            filter=TodoFineRuleFilter(tags=[]),
            rates=[TodoFineRuleRateWrite(tariff_group_id=tariff.id, base_amount=Decimal("5"), interval_amount=Decimal("1"))],
        ),
        db=db, user=manager,
    )


def test_late_submission_through_the_box_gets_its_fine_from_the_sync(db, box):
    _fine_rule(db, box)
    todo = box["todo"]
    _submit(db, box)
    assert _code(db, todo) == "done"
    assert db.scalar(select(func.count(TodoFine.id)).where(TodoFine.protocol_todo_id == todo.id)) == 0  # Trigger ohne Busse

    service.sync_submission_todos(db, box["assignment"])
    [fine] = db.scalars(select(TodoFine).where(TodoFine.protocol_todo_id == todo.id)).all()
    assert fine.days_late == 13 and fine.status == "pending"

    service.sync_submission_todos(db, box["assignment"])  # nichts doppelt
    assert db.scalar(select(func.count(TodoFine.id)).where(TodoFine.protocol_todo_id == todo.id)) == 1


def test_old_completions_are_not_fined_afterwards(db, box):
    _fine_rule(db, box)
    _submit(db, box, submitted_at=datetime.now(UTC) - timedelta(days=5))
    service.sync_submission_todos(db, box["assignment"])
    assert db.scalar(select(func.count(TodoFine.id)).where(TodoFine.protocol_todo_id == box["todo"].id)) == 0


# --- Schliessen ---------------------------------------------------------------------------


def test_closing_keeps_a_task_done_by_hand(db, box):
    todo = box["todo"]
    _set_status(db, todo, "done")
    service.close_element(db, box["assignment"], todo.element_ref)
    assert _code(db, todo) == "done"
    service.reopen_element(db, box["assignment"], todo.element_ref)
    assert _code(db, todo) == "done"


@pytest.mark.parametrize("kind", ["foreign", "unknown", "garbage"])
def test_close_and_reopen_reject_refs_outside_the_assignment_without_writing(db, box, kind):
    foreign = make_event(db, box["other"].id, title="Fremd")
    ref = {
        "foreign": f"event-{foreign.public_id}",
        "unknown": f"event-{uuid.uuid4()}",
        "garbage": "event-kein-uuid",
    }[kind]
    rows = db.scalar(select(func.count(SubmissionUpload.id)))
    for action in (service.close_element, service.reopen_element):
        with pytest.raises(ValueError):
            action(db, box["assignment"], ref)
    assert db.scalar(select(func.count(SubmissionUpload.id))) == rows


# --- Fortschritt --------------------------------------------------------------------------


def test_summary_counts_each_element_once_and_only_current_ones(db, box):
    _submit(db, box, name="a.pdf")
    _submit(db, box, name="b.pdf", scan_status="infected")
    service.close_element(db, box["assignment"], f"event-{box['event'].public_id}")
    service.close_element(db, box["assignment"], f"event-{box['second'].public_id}")
    summary = service.summaries(db, [box["assignment"]])[box["assignment"].id]
    assert summary == {"submitted": 1, "quarantine": 0, "infected": 0, "closed": 1, "total": 2}

    box["event"].tag = "anderes"  # Termin gehört nicht mehr dazu
    db.flush()
    summary = service.summaries(db, [box["assignment"]])[box["assignment"].id]
    assert summary == {"submitted": 0, "quarantine": 0, "infected": 0, "closed": 1, "total": 1}


def test_summaries_route_returns_all_assignments_of_the_tenant(db, box):
    _submit(db, box)
    user = make_current_user(box["tenant"].id, role="admin")
    result = routes.get_assignment_summaries(db=db, user=user)
    assert result == {str(box["assignment"].public_id): {"submitted": 1, "quarantine": 0, "infected": 0, "closed": 0, "total": 2}}
    assert routes.get_assignment_summaries(db=db, user=make_current_user(box["other"].id, role="admin")) == {}


# --- ZIP ----------------------------------------------------------------------------------


def test_zip_contains_all_submissions_and_linked_files_even_after_closing(db, box, monkeypatch, tmp_path):
    written: list[tuple[str, str]] = []
    monkeypatch.setattr(routes.settings, "upload_root", str(tmp_path))
    monkeypatch.setattr(routes, "get_object_store", lambda: SimpleNamespace(exists=lambda namespace, key: True))
    monkeypatch.setattr(
        routes, "write_object_to_zip",
        lambda archive, namespace, key, name: (written.append((namespace, name)), archive.writestr(name, b"x")),
    )
    _submit(db, box, name="erste.pdf")
    _submit(db, box, name="zweite.pdf")
    _submit(db, box, name="virus.pdf", scan_status="infected")
    linked = StoredFile(tenant_id=box["tenant"].id, original_name="foto.jpg", mime_type="image/jpeg", storage_path="main/foto.jpg")
    db.add(linked)
    db.flush()
    db.add(GalleryImage(
        tenant_id=box["tenant"].id, stored_file_id=linked.id, submission_assignment_id=box["assignment"].id,
        submission_element_ref=f"event-{box['second'].public_id}",
    ))
    db.flush()
    service.close_element(db, box["assignment"], f"event-{box['event'].public_id}")

    response = routes.download_all_files_zip(box["assignment"].public_id, db=db, user=make_current_user(box["tenant"].id, role="admin"))
    with zipfile.ZipFile(response.path) as archive:
        names = sorted(archive.namelist())
    assert names == ["Badetag/erste.pdf", "Badetag/zweite.pdf", "Wanderung/foto.jpg"]
    assert dict((name, namespace) for namespace, name in written)["Wanderung/foto.jpg"] == "main"
    assert dict((name, namespace) for namespace, name in written)["Badetag/erste.pdf"] == "abgabebox"


def test_unique_arcname_and_segment():
    used: set[str] = set()
    assert routes._unique_arcname("a/b.pdf", used) == "a/b.pdf"
    assert routes._unique_arcname("a/b.pdf", used) == "a/b_1.pdf"
    assert routes._zip_segment("../Lager: 1/2") == "_Lager_ 1_2"
    assert routes._zip_segment("") == "element"
    assert routes._zip_segment("..") == "element"


# --- Versand-Loop -------------------------------------------------------------------------


def test_failing_submission_scan_does_not_stop_the_mail_loop(db, monkeypatch):
    from app.notifications import todos

    monkeypatch.setattr(dispatch.email_transport, "load_config", lambda db: object())

    def boom(db, now=None):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(todos, "scan_submission_done", boom)
    counts = dispatch.run(db)
    assert counts["error"] == 1


# --- Höchstzahl: App-Dateien zählen auch in der Abgabebox (Funktion aus 0175) ------------------


def test_abgabebox_role_counts_linked_files_only_for_its_own_link(db, box):
    from tests.test_submission_links import _probe_as_abgabebox

    link = box["assignment"].links[0]
    linked = StoredFile(tenant_id=box["tenant"].id, original_name="foto.jpg", mime_type="image/jpeg", storage_path="main/f.jpg")
    db.add(linked)
    db.flush()
    db.add(GalleryImage(
        tenant_id=box["tenant"].id, stored_file_id=linked.id, submission_assignment_id=box["assignment"].id,
        submission_element_ref=f"event-{box['event'].public_id}",
    ))
    db.flush()
    sql = "SELECT event_id, list_entry_id, file_count FROM public.submission_linked_file_counts(:id)"
    rows, error = _probe_as_abgabebox(db, sql, {"id": box["assignment"].id}, link_token=link.token)
    assert error is None and [tuple(row) for row in rows] == [(box["event"].id, None, 1)]

    foreign = SubmissionLinkService().create_link(db, SubmissionLinkCreate(name="Fremd"), tenant_id=box["other"].id)
    rows, error = _probe_as_abgabebox(db, sql, {"id": box["assignment"].id}, link_token=foreign.token)
    assert error is None and rows == []
    rows, error = _probe_as_abgabebox(db, sql, {"id": box["assignment"].id})
    assert error is None and rows == []
