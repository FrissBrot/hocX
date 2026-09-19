"""Tests for the "Dateien" page's document upload window: _sniff_document_mime (extension picks
the signature check, content must agree), FileService.save_document_uploads (gallery_image row +
Bezug columns, per-file errors, virus verdict) and the POST /files/document-uploads route
(role gating, Bezug validation/tenant scoping, and the overview's ref_label/ref_href)."""
import asyncio
import io

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.api.routes import files as files_routes
from app.models.entities import GalleryImage, StoredFile
from app.services import file_service as file_service_module
from app.services import public_id_service
from app.services.file_service import FileService
from app.services.upload_pipeline import _sniff_document_mime
from tests.factories import make_current_user, make_cycle_config, make_event, make_tenant

service = FileService()

PDF = b"%PDF-1.7\n%test\n"
DOCX = b"PK\x03\x04" + b"\x00" * 32


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))


def _upload_file(content: bytes, filename: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=filename, headers=Headers({"content-type": "application/octet-stream"}))


def _upload(db, user, files, **form):
    kwargs = dict(
        tags=None, event_id=None, submission_assignment_id=None, submission_element_ref=None, cycle_config_id=None
    )
    kwargs.update(form)
    return asyncio.run(files_routes.upload_documents(files=files, db=db, user=user, **kwargs))


@pytest.mark.parametrize(
    ("filename", "content", "expected"),
    [
        ("protokoll.pdf", PDF, "application/pdf"),
        ("Protokoll.PDF", PDF, "application/pdf"),
        ("bericht.docx", DOCX, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("kasse.xlsx", DOCX, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("alt.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 8, "application/msword"),
        ("brief.rtf", b"{\\rtf1\\ansi hallo}", "application/rtf"),
        ("liste.csv", "name;alter\nAnna;12\n".encode(), "text/csv"),
        ("archiv.zip", DOCX, "application/zip"),
    ],
)
def test_sniff_document_mime_accepts_matching_content(filename, content, expected):
    assert _sniff_document_mime(content, filename) == expected


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("virus.pdf", b"MZ\x90\x00 not a pdf"),  # extension claims PDF, bytes say otherwise
        ("virus.docx", PDF),
        ("programm.exe", b"MZ\x90\x00"),  # extension not on the allow-list at all
        ("bild.png", b"\x89PNG\r\n\x1a\n"),  # images belong on the Fotos page
        ("binaer.txt", b"abc\x00def"),  # "text" that is really binary
        ("ohne-endung", PDF),
    ],
)
def test_sniff_document_mime_rejects_mismatch_and_unlisted_types(filename, content):
    assert _sniff_document_mime(content, filename) is None


def test_save_document_uploads_stores_file_with_tags_and_gallery_row(db):
    tenant = make_tenant(db)

    items, errors = asyncio.run(
        service.save_document_uploads(
            db, tenant_id=tenant.id, files=[("protokoll.pdf", PDF)], tags=["Lager", " Lager ", ""], created_by=None
        )
    )

    assert errors == []
    assert len(items) == 1
    item = items[0]
    assert item.source == "gallery_upload"
    assert item.is_image is False
    assert item.thumbnail_url is None
    assert item.tags == ["Lager"]
    assert item.ref_label == ""
    assert item.ref_href is None
    stored_file = public_id_service.get_by_public_id(db, StoredFile, item.id)
    assert stored_file.mime_type == "application/pdf"
    assert db.query(GalleryImage).filter_by(stored_file_id=stored_file.id).one().tenant_id == tenant.id


def test_save_document_uploads_does_not_abort_batch_on_one_bad_file(db):
    tenant = make_tenant(db)

    items, errors = asyncio.run(
        service.save_document_uploads(
            db,
            tenant_id=tenant.id,
            files=[("gut.pdf", PDF), ("boese.pdf", b"MZ not a pdf"), ("bild.png", b"\x89PNG\r\n\x1a\n")],
            tags=[],
            created_by=None,
        )
    )

    assert [item.original_name for item in items] == ["gut.pdf"]
    assert len(errors) == 2
    assert errors[0].startswith("boese.pdf:")
    assert errors[1].startswith("bild.png:")


def test_save_document_uploads_rejects_infected_file_without_storing_it(db, monkeypatch):
    tenant = make_tenant(db)
    monkeypatch.setattr(file_service_module.scanner, "scan_bytes", lambda content, host, port: "infected")

    items, errors = asyncio.run(
        service.save_document_uploads(db, tenant_id=tenant.id, files=[("x.pdf", PDF)], tags=[], created_by=None)
    )

    assert items == []
    assert "infiziert" in errors[0]
    assert db.query(StoredFile).filter_by(tenant_id=tenant.id).count() == 0


def test_upload_documents_route_requires_writer_role(db):
    tenant = make_tenant(db)
    reader = make_current_user(tenant.id, role="reader")

    with pytest.raises(HTTPException) as exc_info:
        _upload(db, reader, [_upload_file(PDF, "a.pdf")])
    assert exc_info.value.status_code == 403


def test_upload_documents_route_with_event_bezug_shows_up_in_overview(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    event = make_event(db, tenant.id, title="Sommerlager")

    result = _upload(db, writer, [_upload_file(PDF, "anmeldung.pdf")], tags="Lager", event_id=event.public_id)

    assert result.errors == []
    assert [item.original_name for item in result.items] == ["anmeldung.pdf"]
    listed = service.list_tenant_files(db, tenant.id, exclude_images=True)
    assert [item.original_name for item in listed] == ["anmeldung.pdf"]
    assert listed[0].ref_label == "Sommerlager"
    assert listed[0].ref_date == event.event_date
    assert listed[0].ref_href == "/events"


def test_upload_documents_route_with_cycle_bezug(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    cycle_config = make_cycle_config(db, tenant.id, name="Pfadijahr")

    result = _upload(db, writer, [_upload_file(PDF, "plan.pdf")], cycle_config_id=cycle_config.public_id)

    assert result.items[0].ref_label == "Pfadijahr"
    assert result.items[0].ref_href == "/cycles"


def test_upload_documents_route_rejects_bezug_of_another_tenant(db):
    tenant = make_tenant(db)
    other_tenant = make_tenant(db, name="Fremder Mandant")
    writer = make_current_user(tenant.id, role="writer")
    foreign_event = make_event(db, other_tenant.id)
    foreign_cycle = make_cycle_config(db, other_tenant.id)

    for form in ({"event_id": foreign_event.public_id}, {"cycle_config_id": foreign_cycle.public_id}):
        with pytest.raises(HTTPException) as exc_info:
            _upload(db, writer, [_upload_file(PDF, "a.pdf")], **form)
        assert exc_info.value.status_code == 404
    assert db.query(StoredFile).filter_by(tenant_id=tenant.id).count() == 0


def test_upload_documents_route_rejects_more_than_one_bezug(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    event = make_event(db, tenant.id)
    cycle_config = make_cycle_config(db, tenant.id)

    with pytest.raises(HTTPException) as exc_info:
        _upload(db, writer, [_upload_file(PDF, "a.pdf")], event_id=event.public_id, cycle_config_id=cycle_config.public_id)
    assert exc_info.value.status_code == 422


def test_upload_documents_route_rejects_oversized_file_and_leaves_no_staging_file(db, monkeypatch, tmp_path):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    monkeypatch.setattr(files_routes, "MAX_UPLOAD_BYTES", 10)

    with pytest.raises(HTTPException) as exc_info:
        _upload(db, writer, [_upload_file(PDF * 4, "gross.pdf")])

    assert exc_info.value.status_code == 413
    staging = tmp_path / "uploads" / "_staging" / "documents"
    assert not staging.exists() or list(staging.iterdir()) == []


def test_upload_documents_route_rejects_too_many_files(db, monkeypatch):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    monkeypatch.setattr(files_routes, "MAX_DOCUMENT_UPLOAD_BATCH_FILES", 1)

    with pytest.raises(HTTPException) as exc_info:
        _upload(db, writer, [_upload_file(PDF, "a.pdf"), _upload_file(PDF, "b.pdf")])
    assert exc_info.value.status_code == 413
