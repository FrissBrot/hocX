"""Datei-Detail: bei Abgabe-Uploads steht neben dem Bezug (Abgabe) das Element, aus dem die Datei
stammt - Termin mit Datum bzw. Listeneintrag."""
import uuid
from datetime import date

from app.models import StoredFile
from app.models.entities import SubmissionAssignment, SubmissionUpload, SubmissionUploadFile
from app.services.file_service import FileService
from tests.factories import make_event, make_tenant


def _upload(db, assignment, *, event_id=None, name="bericht.pdf"):
    upload = SubmissionUpload(assignment_id=assignment.id, status="submitted", event_id=event_id)
    db.add(upload)
    db.flush()
    stored = StoredFile(tenant_id=assignment.tenant_id, original_name=name, mime_type="application/pdf",
                        storage_path=f"abgabebox/{uuid.uuid4().hex}.pdf", scan_status="clean")
    db.add(stored)
    db.flush()
    db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=stored.id, sort_index=0))
    db.flush()
    return stored


def test_submission_file_shows_its_event_element(db):
    tenant = make_tenant(db)
    event = make_event(db, tenant.id, title="Scharanlass", event_date=date(2026, 10, 25))
    assignment = SubmissionAssignment(tenant_id=tenant.id, title="Gliähwurm Berichte", public_slug=f"a-{uuid.uuid4().hex[:8]}", source_type="events", tag_filter="hock", offset_days_before=7, offset_days_after=7)
    db.add(assignment)
    db.flush()
    with_event = _upload(db, assignment, event_id=event.id, name="aufnahme.pdf")
    manual = _upload(db, assignment, name="ohne-element.pdf")

    items = {item.id: item for item in FileService().list_tenant_files(db, tenant.id, limit=50)}
    item = items[with_event.public_id]
    assert item.ref_label == "Gliähwurm Berichte"
    assert item.element_label == "Scharanlass"
    assert item.element_date == date(2026, 10, 25)
    assert items[manual.public_id].element_label is None
