"""Regression tests for SubmissionService (Abgabebox assignment/element/close/reopen logic in
the main backend) - previously zero test coverage.

Note on scope: the actual file upload endpoint used by not-logged-in external submitters
lives in the separate `abgabebox-backend` service (see submission_upload's docstring in
app/models/entities.py: "die restricted Postgres-Rolle des separaten abgabebox-backend-
Service darf auf dieser Tabelle nur INSERT"), not in this backend's submission_service.py -
so "upload succeeds within the window" / "upload rejected outside the window" is out of
reach here. What IS covered, and is the security/correctness-relevant part that lives in
*this* service:
- element status resolution (open / submitted / closed) from the append-only submission_upload
  log, now cumulative: an element with files stays 'submitted' (still open for more uploads)
  until explicitly closed - see the 2026-08-17 change described in close_element/reopen_element's
  docstrings.
- close_element / reopen_element: the only way an element still transitions between "accepting
  uploads" and "not accepting uploads" now that offset_days_before/after and deadline are
  optional (no forced time window).
- sort_order (alphabetical / date / proximity) applied to resolved elements.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models.entities import StoredFile, SubmissionAssignment, SubmissionUpload, SubmissionUploadFile
from app.services.submission_service import SubmissionService
from tests.factories import make_event, make_list_definition, make_list_entry, make_tenant


def _make_tagged_event(db, tenant_id: int, title: str, event_date: date, tag: str = "lager"):
    event = make_event(db, tenant_id, title=title, event_date=event_date)
    event.tag = tag
    db.flush()
    return event


def _make_list_assignment(db, tenant_id: int, list_definition_id: int, *, deadline: date | None = date(2026, 12, 31), sort_order: str = "date") -> SubmissionAssignment:
    assignment = SubmissionAssignment(
        tenant_id=tenant_id,
        title="Fotos einreichen",
        public_slug="fotos",
        source_type="list",
        list_definition_id=list_definition_id,
        deadline=deadline,
        sort_order=sort_order,
    )
    db.add(assignment)
    db.flush()
    return assignment


def _make_submitted_upload(db, *, assignment_id: int, list_entry_id: int, tenant_id: int, filename: str) -> SubmissionUpload:
    upload = SubmissionUpload(assignment_id=assignment_id, list_entry_id=list_entry_id, status="submitted", submitted_at=None)
    db.add(upload)
    db.flush()
    stored_file = StoredFile(tenant_id=tenant_id, original_name=filename, mime_type="application/pdf", storage_path=f"abgabebox/{filename}")
    db.add(stored_file)
    db.flush()
    db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=stored_file.id))
    db.commit()
    db.refresh(upload)
    return upload


def _setup(db, **assignment_kwargs):
    tenant = make_tenant(db)
    list_definition = make_list_definition(db, tenant.id, column_one_value_type="text")
    entry = make_list_entry(db, list_definition.id, column_one_value={"text_value": "Gruppenfoto"})
    assignment = _make_list_assignment(db, tenant.id, list_definition.id, **assignment_kwargs)
    return tenant, assignment, entry


# --- element status resolution -----------------------------------------------------------


def test_element_is_open_when_nothing_uploaded_yet(db):
    tenant, assignment, entry = _setup(db)
    service = SubmissionService()

    elements = service.get_assignment_elements(db, assignment)

    assert len(elements) == 1
    assert elements[0].element_ref == f"entry-{entry.public_id}"
    assert elements[0].status == "open"
    assert elements[0].files == []


def test_element_is_submitted_with_files_after_upload(db):
    tenant, assignment, entry = _setup(db)
    upload = _make_submitted_upload(db, assignment_id=assignment.id, list_entry_id=entry.id, tenant_id=tenant.id, filename="foto.pdf")
    service = SubmissionService()

    elements = service.get_assignment_elements(db, assignment)

    assert elements[0].status == "submitted"
    assert elements[0].upload_id == upload.public_id
    assert len(elements[0].files) == 1
    assert elements[0].files[0].original_name == "foto.pdf"


def test_element_stays_open_for_further_uploads_without_being_closed(db):
    """Kumulatives Modell: ein Element mit bereits eingegangenen Dateien bleibt 'submitted',
    nicht automatisch geschlossen - im Unterschied zum alten Verhalten vor 2026-08-17, wo eine
    Abgabe die Box implizit fuer weitere Uploads sperrte."""
    tenant, assignment, entry = _setup(db)
    _make_submitted_upload(db, assignment_id=assignment.id, list_entry_id=entry.id, tenant_id=tenant.id, filename="foto-v1.pdf")
    second = _make_submitted_upload(db, assignment_id=assignment.id, list_entry_id=entry.id, tenant_id=tenant.id, filename="foto-v2.pdf")
    service = SubmissionService()

    elements = service.get_assignment_elements(db, assignment)

    assert elements[0].status == "submitted"
    assert elements[0].upload_id == second.public_id
    names = {f.original_name for f in elements[0].files}
    assert names == {"foto-v1.pdf", "foto-v2.pdf"}


# --- close_element / reopen_element -------------------------------------------------------


def test_close_element_marks_it_closed_and_keeps_existing_files(db):
    tenant, assignment, entry = _setup(db)
    _make_submitted_upload(db, assignment_id=assignment.id, list_entry_id=entry.id, tenant_id=tenant.id, filename="foto.pdf")
    service = SubmissionService()

    element = service.close_element(db, assignment, f"entry-{entry.public_id}")

    assert element.status == "closed"
    assert len(element.files) == 1
    assert element.files[0].original_name == "foto.pdf"


def test_close_element_works_even_when_nothing_was_ever_submitted(db):
    """Admin kann ein Element praeventiv schliessen, bevor je etwas eingereicht wurde -
    z.B. um einen irrelevant gewordenen Termin aus der oeffentlichen Liste zu nehmen."""
    tenant, assignment, entry = _setup(db)
    service = SubmissionService()

    element = service.close_element(db, assignment, f"entry-{entry.public_id}")

    assert element.status == "closed"
    assert element.files == []


def test_close_element_fails_when_already_closed(db):
    tenant, assignment, entry = _setup(db)
    service = SubmissionService()
    service.close_element(db, assignment, f"entry-{entry.public_id}")

    with pytest.raises(ValueError, match="bereits geschlossen"):
        service.close_element(db, assignment, f"entry-{entry.public_id}")


def test_reopen_element_fails_when_not_closed(db):
    tenant, assignment, entry = _setup(db)
    service = SubmissionService()

    with pytest.raises(ValueError, match="nicht geschlossen"):
        service.reopen_element(db, assignment, f"entry-{entry.public_id}")


def test_reopen_element_keeps_files_unlike_pre_2026_08_17_behavior(db):
    tenant, assignment, entry = _setup(db)
    old_upload = _make_submitted_upload(db, assignment_id=assignment.id, list_entry_id=entry.id, tenant_id=tenant.id, filename="foto-v1.pdf")
    stored_file_id = db.scalar(select(SubmissionUploadFile.stored_file_id).where(SubmissionUploadFile.upload_id == old_upload.id))
    service = SubmissionService()
    service.close_element(db, assignment, f"entry-{entry.public_id}")

    element = service.reopen_element(db, assignment, f"entry-{entry.public_id}")

    assert element.status == "submitted"
    assert len(element.files) == 1
    assert element.files[0].original_name == "foto-v1.pdf"
    # Die Datei aus der geschlossenen Abgabe existiert unveraendert weiter (kein Loeschen mehr).
    assert db.get(StoredFile, stored_file_id) is not None

    # Ein neuer Upload danach kommt kumulativ dazu, ersetzt die alte Datei nicht.
    _make_submitted_upload(db, assignment_id=assignment.id, list_entry_id=entry.id, tenant_id=tenant.id, filename="foto-v2.pdf")
    elements = service.get_assignment_elements(db, assignment)
    names = {f.original_name for f in elements[0].files}
    assert names == {"foto-v1.pdf", "foto-v2.pdf"}


# --- sort_order -----------------------------------------------------------------------


def test_sort_order_alphabetical_orders_events_by_title(db):
    tenant = make_tenant(db)
    assignment = SubmissionAssignment(
        tenant_id=tenant.id, title="Fotos", public_slug="fotos-events", source_type="events",
        tag_filter="lager", sort_order="alphabetical",
    )
    db.add(assignment)
    db.flush()
    today = date.today()
    for title, offset in (("Zebra-Lager", 10), ("Anfang-Lager", -10), ("Mitte-Lager", 0)):
        _make_tagged_event(db, tenant.id, title, today + timedelta(days=offset))
    service = SubmissionService()

    elements = service.get_assignment_elements(db, assignment)

    assert [e.label for e in elements] == ["Anfang-Lager", "Mitte-Lager", "Zebra-Lager"]


def test_sort_order_proximity_orders_events_closest_to_today_first(db):
    tenant = make_tenant(db)
    assignment = SubmissionAssignment(
        tenant_id=tenant.id, title="Fotos", public_slug="fotos-proximity", source_type="events",
        tag_filter="lager", sort_order="proximity",
    )
    db.add(assignment)
    db.flush()
    today = date.today()
    _make_tagged_event(db, tenant.id, "Weit weg", today + timedelta(days=30))
    _make_tagged_event(db, tenant.id, "Naechste Woche", today + timedelta(days=7))
    _make_tagged_event(db, tenant.id, "Heute", today)
    service = SubmissionService()

    elements = service.get_assignment_elements(db, assignment)

    assert [e.label for e in elements] == ["Heute", "Naechste Woche", "Weit weg"]


def test_sort_order_date_orders_events_chronologically(db):
    tenant = make_tenant(db)
    assignment = SubmissionAssignment(
        tenant_id=tenant.id, title="Fotos", public_slug="fotos-date", source_type="events",
        tag_filter="lager", sort_order="date",
    )
    db.add(assignment)
    db.flush()
    today = date.today()
    _make_tagged_event(db, tenant.id, "Spaeter", today + timedelta(days=30))
    _make_tagged_event(db, tenant.id, "Frueher", today - timedelta(days=30))
    service = SubmissionService()

    elements = service.get_assignment_elements(db, assignment)

    assert [e.label for e in elements] == ["Frueher", "Spaeter"]


# --- optional time window (no forced offset_days_*/deadline) ----------------------------


def test_events_assignment_without_offsets_has_no_window_and_is_always_open(db):
    tenant = make_tenant(db)
    assignment = SubmissionAssignment(
        tenant_id=tenant.id, title="Immer offen", public_slug="immer-offen", source_type="events",
        tag_filter="lager",
    )
    db.add(assignment)
    db.flush()
    _make_tagged_event(db, tenant.id, "Lager 2020", date(2020, 1, 1))
    service = SubmissionService()

    elements = service.get_assignment_elements(db, assignment)

    assert len(elements) == 1
    assert elements[0].window_start is None
    assert elements[0].window_end is None
    assert elements[0].status == "open"


def test_list_assignment_without_deadline_is_accepted(db):
    from app.schemas.submission import SubmissionAssignmentCreate

    tenant = make_tenant(db)
    list_definition = make_list_definition(db, tenant.id)
    service = SubmissionService()
    payload = SubmissionAssignmentCreate(
        title="Ohne Deadline", public_slug="ohne-deadline", source_type="list",
        list_definition_id=list_definition.public_id, deadline=None,
    )

    created = service.create_assignment(db, payload, tenant_id=tenant.id)

    assert created.deadline is None


def test_create_assignment_rejects_events_type_with_list_fields_set(db):
    from app.schemas.submission import SubmissionAssignmentCreate

    tenant = make_tenant(db)
    service = SubmissionService()
    payload = SubmissionAssignmentCreate(
        title="Falsch konfiguriert", public_slug="falsch", source_type="events",
        tag_filter="lager", offset_days_before=1, offset_days_after=1,
        deadline=date(2026, 1, 1),
    )

    with pytest.raises(ValueError):
        service.create_assignment(db, payload, tenant_id=tenant.id)


# --- count_submissions_summary -----------------------------------------------------------


def test_count_submissions_summary_ignores_closed_element_with_no_files(db):
    """A preemptively closed element (no file ever uploaded, see close_element) must not count
    as 'submitted' in the assignment summary bar - only elements with an actual file do."""
    tenant, assignment, entry = _setup(db)
    service = SubmissionService()
    service.close_element(db, assignment, f"entry-{entry.public_id}")

    counts = service.repository.count_submissions_summary(db, assignment_id=assignment.id)

    assert counts["submitted"] == 0


def test_count_submissions_summary_counts_element_with_files(db):
    tenant, assignment, entry = _setup(db)
    _make_submitted_upload(db, assignment_id=assignment.id, list_entry_id=entry.id, tenant_id=tenant.id, filename="foto.pdf")
    service = SubmissionService()

    counts = service.repository.count_submissions_summary(db, assignment_id=assignment.id)

    assert counts["submitted"] == 1


def test_create_assignment_rejects_list_type_without_list_definition(db):
    from app.schemas.submission import SubmissionAssignmentCreate

    tenant = make_tenant(db)
    service = SubmissionService()
    payload = SubmissionAssignmentCreate(
        title="Ohne Liste", public_slug="ohne-liste", source_type="list",
        list_definition_id=None,
    )

    with pytest.raises(ValueError, match="list_definition_id"):
        service.create_assignment(db, payload, tenant_id=tenant.id)
