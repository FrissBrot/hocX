"""An upload window (Fotos/Dateien) that picks an Abgabe-Element as Bezug must obey that
Abgabe's file rules - allowed_file_types, max_file_size_mb, max_files_per_element - the same
way the public Abgabebox does (see submission_upload_rules.py)."""
import asyncio
import io
import uuid
import zipfile

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from starlette.datastructures import Headers

from app.api.routes import files as files_routes
from app.models.entities import GalleryImage, StoredFile, SubmissionAssignment, SubmissionUpload, SubmissionUploadFile
from app.services.file_service import FileService
from app.services.submission_service import _element_ref
from tests.factories import make_current_user, make_list_definition, make_list_entry, make_tenant

service = FileService()
PDF = b"%PDF-1.7\n%test\n"


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))


def _image_bytes(fmt="PNG", color=(10, 20, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (48, 48), color=color).save(buffer, format=fmt)
    return buffer.getvalue()


def _upload_file(content: bytes, filename: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=filename, headers=Headers({"content-type": "application/octet-stream"}))


def _make_assignment(db, tenant_id, *, allowed=(), max_files=None, max_mb=20):
    """A list-backed Abgabe with one element - returns (assignment, element_ref, upload)."""
    definition = make_list_definition(db, tenant_id, name=f"Liste {uuid.uuid4().hex[:8]}")
    entry = make_list_entry(db, definition.id, column_one_value={"text_value": "Gruppe Adler"})
    assignment = SubmissionAssignment(
        tenant_id=tenant_id, title="Sommerlager Abgabe", public_slug=f"abgabe-{entry.id}", source_type="list",
        list_definition_id=definition.id, allowed_file_types=list(allowed), max_files_per_element=max_files,
        max_file_size_mb=max_mb,
    )
    db.add(assignment)
    db.flush()
    upload = SubmissionUpload(assignment_id=assignment.id, event_id=None, list_entry_id=entry.id, status="submitted")
    db.add(upload)
    db.flush()
    return assignment, _element_ref(event_public_id=None, list_entry_public_id=entry.public_id), upload


def _add_abgabebox_file(db, tenant_id, upload):
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name="schon-da.pdf", mime_type="application/pdf",
        storage_path="abgabebox/schon-da.pdf", scan_status="clean",
    )
    db.add(stored_file)
    db.flush()
    db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=stored_file.id))
    db.flush()


def _upload_documents(db, user, assignment, element_ref, files):
    return asyncio.run(
        files_routes.upload_documents(
            files=files, tags=None, event_id=None, submission_assignment_id=assignment.public_id,
            submission_element_ref=element_ref, cycle_config_id=None, db=db, user=user,
        )
    )


def _upload_photos(db, user, assignment, element_ref, files):
    return asyncio.run(
        files_routes.upload_gallery_images(
            files=files, tags=None, event_id=None, submission_assignment_id=assignment.public_id,
            submission_element_ref=element_ref, cycle_config_id=None, db=db, user=user,
        )
    )


def test_document_upload_rejects_a_file_type_the_abgabe_does_not_allow(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    assignment, ref, _ = _make_assignment(db, tenant.id, allowed=["pdf"])

    with pytest.raises(HTTPException) as exc_info:
        _upload_documents(db, writer, assignment, ref, [_upload_file(PDF, "ok.pdf"), _upload_file(b"a;b\n", "liste.csv")])

    assert exc_info.value.status_code == 400
    assert "'.csv' nicht erlaubt" in exc_info.value.detail
    assert db.query(StoredFile).filter_by(tenant_id=tenant.id).count() == 0  # all-or-nothing, like the Abgabebox


def test_document_upload_accepts_an_allowed_type_and_links_it_to_the_element(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    assignment, ref, _ = _make_assignment(db, tenant.id, allowed=[".PDF"])  # dot/case are normalised

    result = _upload_documents(db, writer, assignment, ref, [_upload_file(PDF, "ok.pdf")])

    assert result.errors == []
    assert result.items[0].ref_label == "Sommerlager Abgabe · Gruppe Adler"
    row = db.query(GalleryImage).filter_by(tenant_id=tenant.id).one()
    assert (row.submission_assignment_id, row.submission_element_ref) == (assignment.id, ref)


def test_document_upload_with_no_type_restriction_takes_any_supported_document(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    assignment, ref, _ = _make_assignment(db, tenant.id, allowed=[])

    result = _upload_documents(db, writer, assignment, ref, [_upload_file(PDF, "a.pdf")])

    assert [item.original_name for item in result.items] == ["a.pdf"]


def test_document_upload_enforces_the_abgabes_max_file_size(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    assignment, ref, _ = _make_assignment(db, tenant.id, max_mb=1)

    with pytest.raises(HTTPException) as exc_info:
        _upload_documents(db, writer, assignment, ref, [_upload_file(PDF + b"x" * (1024 * 1024), "gross.pdf")])

    assert exc_info.value.status_code == 413
    assert "maximal 1 MB" in exc_info.value.detail


def test_document_upload_counts_abgabebox_files_and_earlier_in_app_uploads_against_max_files(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    assignment, ref, upload = _make_assignment(db, tenant.id, max_files=3)
    _add_abgabebox_file(db, tenant.id, upload)  # 1 of 3 used through the public Abgabebox

    with pytest.raises(HTTPException) as exc_info:
        _upload_documents(db, writer, assignment, ref, [_upload_file(PDF, f"{n}.pdf") for n in range(3)])
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Maximal 3 Dateien insgesamt erlaubt (2 noch möglich)"

    _upload_documents(db, writer, assignment, ref, [_upload_file(PDF, "a.pdf"), _upload_file(PDF, "b.pdf")])  # fills it

    with pytest.raises(HTTPException) as exc_info:
        _upload_documents(db, writer, assignment, ref, [_upload_file(PDF, "c.pdf")])
    assert exc_info.value.detail == "Maximal 3 Dateien insgesamt erlaubt (0 noch möglich)"


def test_document_service_rechecks_capacity_under_the_lock(db):
    """The route's early check can race; save_document_uploads must refuse on its own."""
    tenant = make_tenant(db)
    assignment, ref, upload = _make_assignment(db, tenant.id, max_files=1)
    _add_abgabebox_file(db, tenant.id, upload)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            service.save_document_uploads(
                db, tenant_id=tenant.id, files=[("a.pdf", PDF)], tags=[], created_by=None,
                upload_assignment=assignment, upload_element_ref=ref,
            )
        )
    assert exc_info.value.status_code == 400


def test_other_abgaben_and_elements_do_not_share_the_count(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    full, full_ref, full_upload = _make_assignment(db, tenant.id, max_files=1)
    _add_abgabebox_file(db, tenant.id, full_upload)
    other, other_ref, _ = _make_assignment(db, tenant.id, max_files=1)

    result = _upload_documents(db, writer, other, other_ref, [_upload_file(PDF, "a.pdf")])

    assert len(result.items) == 1


def test_photo_upload_rejects_a_direct_image_the_abgabe_does_not_allow(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    assignment, ref, _ = _make_assignment(db, tenant.id, allowed=["png"])

    with pytest.raises(HTTPException) as exc_info:
        _upload_photos(db, writer, assignment, ref, [_upload_file(_image_bytes("JPEG"), "foto.jpg")])

    assert exc_info.value.status_code == 400
    assert "'.jpg' nicht erlaubt" in exc_info.value.detail


def test_photo_upload_rejects_more_direct_images_than_the_abgabe_has_room_for(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    assignment, ref, _ = _make_assignment(db, tenant.id, max_files=1)

    with pytest.raises(HTTPException) as exc_info:
        _upload_photos(db, writer, assignment, ref, [_upload_file(_image_bytes(), "a.png"), _upload_file(_image_bytes(color=(1, 2, 3)), "b.png")])

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Maximal 1 Dateien insgesamt erlaubt (1 noch möglich)"


def test_photo_zip_entries_are_judged_by_the_job_per_file(db):
    """A ZIP's entries are only known once the ingest job opens it - the job keeps what the
    rules allow and reports every rejected entry, instead of failing the whole ZIP."""
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    assignment, ref, upload = _make_assignment(db, tenant.id, allowed=["png", "jpg"], max_files=3)
    _add_abgabebox_file(db, tenant.id, upload)  # room for 2 more
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("a.png", _image_bytes(color=(200, 10, 10)))
        archive.writestr("b.gif", _image_bytes("GIF", color=(10, 200, 10)))  # type not allowed
        archive.writestr("c.jpg", _image_bytes("JPEG", color=(10, 10, 200)))
        archive.writestr("d.png", _image_bytes(color=(90, 90, 90)))  # over the limit

    queued = _upload_photos(db, writer, assignment, ref, [_upload_file(buffer.getvalue(), "fotos.zip")])
    service.process_pending_gallery_upload_jobs(db)

    detail = files_routes.get_gallery_upload_job(queued.id, db=db, user=writer)
    assert detail.status == "done"
    assert detail.processed_files == detail.total_files == 4
    assert {item.original_name for item in detail.imported_items} == {"a.png", "c.jpg"}
    problems = [error for error in detail.errors if "ähnelt" not in error]
    assert any(error.startswith("b.gif:") and "'.gif' nicht erlaubt" in error for error in problems)
    assert any(error.startswith("d.png:") and "Limit der Abgabe erreicht" in error for error in problems)
    # The photos that made it are counted toward the element from now on.
    assert db.query(GalleryImage).filter_by(submission_assignment_id=assignment.id, submission_element_ref=ref).count() == 2


@pytest.mark.parametrize("image", [False, True])
@pytest.mark.parametrize("closed", [False, True])
@pytest.mark.parametrize("scan_status", ["clean", "pending"])
def test_linked_upload_counts_as_submission(db, monkeypatch, image, closed, scan_status):
    from app.services.submission_service import SubmissionService
    from app.services.submission_upload_rules import load_rules
    from app.services import file_service as file_service_module

    async def clean_scan(contents, **kwargs):
        return [scan_status] * len(contents)

    monkeypatch.setattr(file_service_module.scanner, "scan_many", clean_scan)
    tenant = make_tenant(db)
    assignment, ref, empty_upload = _make_assignment(db, tenant.id, max_files=3)
    if closed:
        empty_upload.status = "closed"
    else:
        db.delete(empty_upload)
    db.flush()
    upload = service.save_gallery_uploads if image else service.save_document_uploads
    items, errors = asyncio.run(upload(
        db, tenant_id=tenant.id, files=[("bild.png", _image_bytes())] if image else [("datei.pdf", PDF)],
        tags=[], created_by=None, upload_assignment=assignment, upload_element_ref=ref,
    ))
    assert errors == []
    submissions = SubmissionService()
    element = submissions.get_assignment_elements(db, assignment)[0]
    assert element.status == ("closed" if closed else "submitted")
    assert element.submitted_at is not None
    assert [file.id for file in element.files] == [items[0].id]
    assert element.files[0].content_url == service.build_content_url(items[0].id)
    assert submissions.repository.count_submissions_summary(db, assignment_id=assignment.id) == {
        "submitted": 1, "clean": int(scan_status == "clean"),
        "quarantine": int(scan_status == "pending"), "infected": 0,
    }
    assert load_rules(db, assignment, ref).remaining == 2

    # A public submission for the same element adds a file, not another completed element.
    from app.services.submission_service import _parse_element_ref
    event_id, entry_id = _parse_element_ref(db, ref)
    public_upload = SubmissionUpload(
        assignment_id=assignment.id, event_id=event_id, list_entry_id=entry_id, status="submitted",
    )
    db.add(public_upload)
    db.flush()
    _add_abgabebox_file(db, tenant.id, public_upload)
    assert len(submissions.get_assignment_elements(db, assignment)[0].files) == 2
    counts = submissions.repository.count_submissions_summary(db, assignment_id=assignment.id)
    assert counts["submitted"] == counts["clean"] == 1
    assert load_rules(db, assignment, ref).remaining == 1
