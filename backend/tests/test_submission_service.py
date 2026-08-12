"""Regression tests for SubmissionService (Abgabebox assignment/element/reopen logic in the
main backend) - previously zero test coverage.

Note on scope: the actual file upload endpoint used by not-logged-in external submitters
lives in the separate `abgabebox-backend` service (see submission_upload's docstring in
app/models/entities.py: "die restricted Postgres-Rolle des separaten abgabebox-backend-
Service darf auf dieser Tabelle nur INSERT"), not in this backend's submission_service.py -
so "upload succeeds within the window" / "upload rejected outside the window" is out of
reach here. What IS covered, and is the security/correctness-relevant part that lives in
*this* service:
- element status resolution (open / submitted) from the append-only submission_upload log
- reopen_element: refuses to reopen an element that was never submitted; on a legitimate
  reopen it deletes the old upload's files but - by explicit design, see the model
  docstring - leaves the old submission_upload row itself in place as an audit trail, and a
  subsequent fresh submission still resolves correctly as the new "latest" state.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.models.entities import StoredFile, SubmissionAssignment, SubmissionUpload, SubmissionUploadFile
from app.services.submission_service import SubmissionService
from tests.factories import make_list_definition, make_list_entry, make_tenant


def _make_list_assignment(db, tenant_id: int, list_definition_id: int) -> SubmissionAssignment:
    assignment = SubmissionAssignment(
        tenant_id=tenant_id,
        title="Fotos einreichen",
        public_slug="fotos",
        source_type="list",
        list_definition_id=list_definition_id,
        deadline=date(2026, 12, 31),
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


def _setup(db):
    tenant = make_tenant(db)
    list_definition = make_list_definition(db, tenant.id, column_one_value_type="text")
    entry = make_list_entry(db, list_definition.id, column_one_value={"text_value": "Gruppenfoto"})
    assignment = _make_list_assignment(db, tenant.id, list_definition.id)
    return tenant, assignment, entry


# --- element status resolution -----------------------------------------------------------


def test_element_is_open_when_nothing_uploaded_yet(db):
    tenant, assignment, entry = _setup(db)
    service = SubmissionService()

    elements = service.get_assignment_elements(db, assignment)

    assert len(elements) == 1
    assert elements[0].element_ref == f"entry-{entry.id}"
    assert elements[0].status == "open"
    assert elements[0].files == []


def test_element_is_submitted_with_files_after_upload(db):
    tenant, assignment, entry = _setup(db)
    upload = _make_submitted_upload(db, assignment_id=assignment.id, list_entry_id=entry.id, tenant_id=tenant.id, filename="foto.pdf")
    service = SubmissionService()

    elements = service.get_assignment_elements(db, assignment)

    assert elements[0].status == "submitted"
    assert elements[0].upload_id == upload.id
    assert len(elements[0].files) == 1
    assert elements[0].files[0].original_name == "foto.pdf"


# --- reopen_element -------------------------------------------------------------------


def test_reopen_element_fails_when_nothing_was_ever_submitted(db):
    tenant, assignment, entry = _setup(db)
    service = SubmissionService()

    with pytest.raises(ValueError, match="noch nicht abgegeben"):
        service.reopen_element(db, assignment, f"entry-{entry.id}")


def test_reopen_element_deletes_files_but_keeps_the_old_upload_row_as_audit_trail(db):
    tenant, assignment, entry = _setup(db)
    old_upload = _make_submitted_upload(db, assignment_id=assignment.id, list_entry_id=entry.id, tenant_id=tenant.id, filename="foto-v1.pdf")
    stored_file_id = db.scalar(select(SubmissionUploadFile.stored_file_id).where(SubmissionUploadFile.upload_id == old_upload.id))

    service = SubmissionService()
    element = service.reopen_element(db, assignment, f"entry-{entry.id}")

    assert element.status == "reopened"
    assert element.files == []

    # The old upload row is NOT deleted - submission_upload is an append-only audit log by
    # design (a compromised external abgabebox-backend process must never be able to erase
    # a prior submission's history, only add to it).
    still_there = db.get(SubmissionUpload, old_upload.id)
    assert still_there is not None
    assert still_there.status == "submitted"

    # Its files, however, ARE removed (the whole point of reopening).
    assert db.get(StoredFile, stored_file_id) is None
    assert db.scalar(select(SubmissionUploadFile).where(SubmissionUploadFile.upload_id == old_upload.id)) is None

    # A fresh "reopened" row now exists alongside the untouched old "submitted" one.
    all_uploads = db.scalars(
        select(SubmissionUpload).where(SubmissionUpload.assignment_id == assignment.id, SubmissionUpload.list_entry_id == entry.id)
    ).all()
    assert len(all_uploads) == 2
    assert {u.status for u in all_uploads} == {"submitted", "reopened"}


def test_element_resolves_correctly_after_reopen_then_fresh_resubmission(db):
    """The known "old row survives" characteristic must not corrupt subsequent state: once a
    NEW file is submitted after reopening, get_assignment_elements must resolve to that new
    upload (the highest id), not get confused by the older submitted/reopened rows."""
    tenant, assignment, entry = _setup(db)
    _make_submitted_upload(db, assignment_id=assignment.id, list_entry_id=entry.id, tenant_id=tenant.id, filename="foto-v1.pdf")
    service = SubmissionService()
    service.reopen_element(db, assignment, f"entry-{entry.id}")

    # Simulate the external abgabebox-backend service recording a fresh submission.
    new_upload = _make_submitted_upload(db, assignment_id=assignment.id, list_entry_id=entry.id, tenant_id=tenant.id, filename="foto-v2.pdf")

    elements = service.get_assignment_elements(db, assignment)

    assert len(elements) == 1
    assert elements[0].status == "submitted"
    assert elements[0].upload_id == new_upload.id
    assert len(elements[0].files) == 1
    assert elements[0].files[0].original_name == "foto-v2.pdf"


# --- source-field validation (create_assignment) -----------------------------------------


def test_create_assignment_rejects_list_type_without_deadline(db):
    from app.schemas.submission import SubmissionAssignmentCreate

    tenant = make_tenant(db)
    list_definition = make_list_definition(db, tenant.id)
    service = SubmissionService()
    payload = SubmissionAssignmentCreate(
        title="Ohne Deadline", public_slug="ohne-deadline", source_type="list",
        list_definition_id=list_definition.id, deadline=None,
    )

    with pytest.raises(ValueError, match="deadline"):
        service.create_assignment(db, payload, tenant_id=tenant.id)


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
