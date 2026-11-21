"""Exakte Duplikate verraten keine Dateien, die die Person nicht sehen darf (Folge zum
Security-Review V-1/V-2, 1.5.1):

- persönlicher Abgabe-Link (ohne Anmeldung): jede Einreichung wird gespeichert, nie
  «übersprungen» mit fremder ID oder Duplikat-Text;
- Galerie-Upload-Job: Sichtbarkeit wie beim Auftraggeber, unsichtbare Duplikate werden Kopien;
- Protokollbild und Word-Import: 409 nur für sichtbare Duplikate, sonst eigene Kopie.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
from datetime import datetime

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.models.entities import GalleryUploadJob, StoredFile
from app.services import file_service as file_service_module
from app.services.file_service import FileService, _gallery_job_viewer, _NoVisibility
from tests.factories import make_app_user, make_current_user, make_tenant

service = FileService()

PDF = b"%PDF-1.7\n%duplikat-orakel\n%%EOF\n"


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _store_document(db, tenant_id: int, content: bytes = PDF, name: str = "vorstand.pdf") -> StoredFile:
    items, errors = asyncio.run(service.save_document_uploads(db, tenant_id=tenant_id, files=[(name, content)], tags=[], created_by=None))
    assert errors == [] and items
    return db.query(StoredFile).filter_by(public_id=items[0].id).one()


def _png(color=(30, 60, 90)) -> bytes:
    from tests.image_fixtures import png

    return png(color=color)


def _without_files_read(tenant_id: int):
    """Sieht Fotos, aber keine Dokumente der Ablage."""
    return make_current_user(
        tenant_id, role="writer", permissions=frozenset({"photos.read", "photos.manage", "meetings.read", "meetings.edit", "files.manage"})
    )


def _without_photos_read(tenant_id: int):
    """Sieht Dokumente, aber keine Fotos."""
    return make_current_user(
        tenant_id, role="writer", permissions=frozenset({"files.read", "files.manage", "meetings.read", "meetings.edit"})
    )


# --- Persönlicher Abgabe-Link (ohne Anmeldung) -----------------------------------------------

from tests.test_submission_done_notifications import box, sent  # noqa: E402,F401 (Fixtures)
from tests.test_submission_owner_access import _client, _issue, _manage, _no_rate_limit  # noqa: E402,F401
from app.api.routes import public_submission_access as access_route  # noqa: E402


def test_personal_link_never_reveals_an_existing_file(db, box, monkeypatch):
    async def clean_scan(contents, **kwargs):
        return ["clean"] * len(contents)

    monkeypatch.setattr(file_service_module.scanner, "scan_many", clean_scan)
    from app.services.submission_service import local_today

    hidden = _store_document(db, box["tenant"].id)
    box["event"].event_date = local_today()
    _manage(box)
    token = _issue(db, box)

    response = _client(db).post(
        "/api/public/submission-access/upload",
        headers={access_route.TOKEN_HEADER: token},
        files=[("files", ("bericht.pdf", PDF, "application/pdf"))],
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["errors"] == []
    assert [entry["status"] for entry in body["file_results"]] == ["uploaded"]
    assert all(entry.get("file_id") != str(hidden.public_id) for entry in body["file_results"])
    assert "Duplikat" not in response.text
    assert db.query(StoredFile).filter_by(tenant_id=box["tenant"].id, checksum_sha256=_sha(PDF)).count() == 2


# --- Galerie-Upload ---------------------------------------------------------------------------


def test_gallery_upload_stores_copy_of_invisible_duplicate_without_metadata(db):
    tenant = make_tenant(db)
    content = _png()
    first, _ = asyncio.run(service.save_gallery_uploads(db, tenant_id=tenant.id, files=[("a.png", content)], tags=[], created_by=None))
    hidden_id = first[0].id
    results: list[dict] = []

    items, _errors = asyncio.run(
        service.save_gallery_uploads(
            db, tenant_id=tenant.id, files=[("b.png", content)], tags=[], created_by=None, file_results=results,
            viewer=_without_photos_read(tenant.id),
        )
    )

    assert len(items) == 1 and items[0].id != hidden_id
    assert all(entry.get("file_id") != str(hidden_id) for entry in results)
    assert db.query(StoredFile).filter_by(tenant_id=tenant.id, checksum_sha256=_sha(content)).count() == 2


def test_gallery_upload_still_skips_visible_duplicate(db):
    tenant = make_tenant(db)
    content = _png((5, 6, 7))
    first, _ = asyncio.run(service.save_gallery_uploads(db, tenant_id=tenant.id, files=[("a.png", content)], tags=[], created_by=None))
    results: list[dict] = []

    items, _errors = asyncio.run(
        service.save_gallery_uploads(
            db, tenant_id=tenant.id, files=[("b.png", content)], tags=[], created_by=None, file_results=results,
            viewer=make_current_user(tenant.id, role="writer"),
        )
    )

    assert items == []
    assert [(entry["status"], entry["file_id"]) for entry in results] == [("skipped", str(first[0].id))]


def _job(db, tenant_id: int, requested_by: int | None) -> GalleryUploadJob:
    job = GalleryUploadJob(tenant_id=tenant_id, staged_paths=[], original_filenames=[], requested_by=requested_by)
    db.add(job)
    db.flush()
    db.refresh(job)
    return job


def test_gallery_job_viewer_follows_the_requesting_account(db):
    tenant, other = make_tenant(db), make_tenant(db)
    writer = make_app_user(db, email=f"g{tenant.id}-{datetime.now().timestamp()}@example.com", tenant_id=tenant.id, role_code="writer")
    foreign = make_app_user(db, email=f"f{other.id}-{datetime.now().timestamp()}@example.com", tenant_id=other.id, role_code="writer")

    viewer = _gallery_job_viewer(db, _job(db, tenant.id, writer.id))
    assert not isinstance(viewer, _NoVisibility) and viewer.current_tenant_id == tenant.id

    # Konto eines anderen Mandanten, gelöschtes Konto oder gesperrtes Konto: sieht nichts
    assert isinstance(_gallery_job_viewer(db, _job(db, tenant.id, foreign.id)), _NoVisibility)
    assert isinstance(_gallery_job_viewer(db, _job(db, tenant.id, None)), _NoVisibility)
    writer.is_active = False
    db.flush()
    assert isinstance(_gallery_job_viewer(db, _job(db, tenant.id, writer.id)), _NoVisibility)


def test_gallery_job_without_visibility_stores_copies(db):
    tenant = make_tenant(db)
    content = _png((9, 9, 9))
    first, _ = asyncio.run(service.save_gallery_uploads(db, tenant_id=tenant.id, files=[("a.png", content)], tags=[], created_by=None))
    results: list[dict] = []

    items, _errors = asyncio.run(
        service.save_gallery_uploads(
            db, tenant_id=tenant.id, files=[("b.png", content)], tags=[], created_by=None, file_results=results,
            viewer=_NoVisibility(tenant.id),
        )
    )

    assert len(items) == 1 and items[0].id != first[0].id
    assert all(entry.get("file_id") is None or entry["status"] == "uploaded" for entry in results)


# --- Protokollbild ----------------------------------------------------------------------------


def _upload_file(content: bytes, filename: str = "bild.png", content_type: str = "image/png") -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=filename, headers=Headers({"content-type": content_type}))


def test_protocol_image_409_only_for_visible_duplicates(db):
    from tests.test_protocol_image_duplicate_check import _make_block, _make_tenant_with_protocol

    tenant, protocol = _make_tenant_with_protocol(db)
    block_a, block_b, block_c = (_make_block(db, protocol.id) for _ in range(3))
    content = _png((40, 41, 42))
    asyncio.run(service.save_protocol_image(db, protocol_element_block=block_a, file=_upload_file(content)))

    # Sieht keine Fotos: eigene Kopie statt 409
    stored = asyncio.run(
        service.save_protocol_image(db, protocol_element_block=block_b, file=_upload_file(content), viewer=_without_photos_read(tenant.id))
    )
    assert stored is not None

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            service.save_protocol_image(db, protocol_element_block=block_c, file=_upload_file(content), viewer=make_current_user(tenant.id))
        )
    assert exc_info.value.status_code == 409


def test_protocol_image_ignores_foreign_tenant_duplicate(db):
    from tests.test_protocol_image_duplicate_check import _make_block, _make_tenant_with_protocol

    foreign = make_tenant(db)
    content = _png((70, 71, 72))
    asyncio.run(service.save_gallery_uploads(db, tenant_id=foreign.id, files=[("a.png", content)], tags=[], created_by=None))
    tenant, protocol = _make_tenant_with_protocol(db)

    stored = asyncio.run(
        service.save_protocol_image(db, protocol_element_block=_make_block(db, protocol.id), file=_upload_file(content), viewer=make_current_user(tenant.id))
    )
    assert stored is not None


# --- Word-Import ------------------------------------------------------------------------------


def test_word_import_409_only_for_visible_duplicates(db, monkeypatch):
    monkeypatch.setattr(file_service_module.scanner, "scan_bytes", lambda *args, **kwargs: "clean")
    tenant = make_tenant(db)
    hidden = _store_document(db, tenant.id)

    copy = service.save_word_import_document(db, tenant_id=tenant.id, filename="import.pdf", content=PDF, viewer=_without_files_read(tenant.id))
    assert copy.id != hidden.id

    with pytest.raises(HTTPException) as exc_info:
        service.save_word_import_document(db, tenant_id=tenant.id, filename="import2.pdf", content=PDF, viewer=make_current_user(tenant.id))
    assert exc_info.value.status_code == 409


def test_personal_link_silently_skips_duplicate_within_the_same_element(db, box, monkeypatch):
    async def clean_scan(contents, **kwargs):
        return ["clean"] * len(contents)

    monkeypatch.setattr(file_service_module.scanner, "scan_many", clean_scan)
    from app.services.submission_service import local_today

    box["event"].event_date = local_today()
    _manage(box)
    token = _issue(db, box)
    client = _client(db)
    content = b"%PDF-1.7\n%element-duplikat\n%%EOF\n"

    def upload():
        return client.post(
            "/api/public/submission-access/upload",
            headers={access_route.TOKEN_HEADER: token},
            files=[("files", ("bericht.pdf", content, "application/pdf"))],
        )

    first, second = upload(), upload()

    assert first.status_code == second.status_code == 200
    a, b = first.json(), second.json()
    # Gleiche Antwort wie ein normaler Upload: keine Fehler, Status «uploaded», kein Duplikat-Text
    assert a["errors"] == b["errors"] == []
    assert [entry["status"] for entry in b["file_results"]] == ["uploaded"]
    assert b["file_results"][0]["file_id"] == a["file_results"][0]["file_id"]
    assert "Duplikat" not in second.text
    assert db.query(StoredFile).filter_by(tenant_id=box["tenant"].id, checksum_sha256=_sha(content)).count() == 1


# --- Ähnlichkeitshinweis nur für sichtbare Bilder ---------------------------------------------


def _similar_pair():
    from tests.test_protocol_image_duplicate_check import _circle_png_bytes

    return _circle_png_bytes((200, 150), 100, 75, 50), _circle_png_bytes((196, 148), 98, 74, 49)


def _circle_variant() -> bytes:
    from tests.test_protocol_image_duplicate_check import _circle_png_bytes

    return _circle_png_bytes((198, 149), 99, 74, 50)


def test_gallery_similarity_hint_only_for_visible_images(db):
    tenant = make_tenant(db)
    original, similar = _similar_pair()
    asyncio.run(service.save_gallery_uploads(db, tenant_id=tenant.id, files=[("a.png", original)], tags=[], created_by=None))

    _items, hidden_errors = asyncio.run(
        service.save_gallery_uploads(db, tenant_id=tenant.id, files=[("b.png", similar)], tags=[], created_by=None, viewer=_without_photos_read(tenant.id))
    )
    _items, visible_errors = asyncio.run(
        service.save_gallery_uploads(
            db, tenant_id=tenant.id, files=[("c.png", _circle_variant())], tags=[], created_by=None,
            viewer=make_current_user(tenant.id, role="writer"),
        )
    )

    assert not any("ähnelt" in error for error in hidden_errors)
    assert any("ähnelt" in error for error in visible_errors)


def test_protocol_image_similarity_hint_only_for_visible_images(db):
    from tests.test_protocol_image_duplicate_check import _make_block, _make_tenant_with_protocol

    tenant, protocol = _make_tenant_with_protocol(db)
    original, similar = _similar_pair()
    asyncio.run(service.save_protocol_image(db, protocol_element_block=_make_block(db, protocol.id), file=_upload_file(original, "a.png")))

    hidden = asyncio.run(
        service.save_protocol_image(
            db, protocol_element_block=_make_block(db, protocol.id), file=_upload_file(similar, "b.png"), viewer=_without_photos_read(tenant.id)
        )
    )
    assert hidden.duplicate_warning is None

    from tests.test_protocol_image_duplicate_check import _circle_png_bytes

    visible = asyncio.run(
        service.save_protocol_image(
            db, protocol_element_block=_make_block(db, protocol.id), file=_upload_file(_circle_png_bytes((198, 149), 99, 74, 50), "c.png"),
            viewer=make_current_user(tenant.id),
        )
    )
    assert visible.duplicate_warning is not None


def test_similarity_visibility_query_runs_without_similar_images(db, monkeypatch):
    tenant = make_tenant(db)
    calls = []
    original = FileService.visible_overview_items
    monkeypatch.setattr(FileService, "visible_overview_items", lambda self, *args: calls.append(args) or original(self, *args))

    asyncio.run(
        service.save_gallery_uploads(db, tenant_id=tenant.id, files=[("a.png", _png((1, 99, 200)))], tags=[], created_by=None, viewer=make_current_user(tenant.id))
    )

    assert any(args[2] == [] for args in calls)


# --- Galerie-Job: RLS an den Mandanten des Auftrags gebunden ---------------------------------


def test_gallery_job_runs_bound_to_its_tenant(db, monkeypatch):
    from app.core.tenant_scope import bound_tenant_id

    tenant = make_tenant(db)
    job = _job(db, tenant.id, None)
    db.commit()
    seen = []

    async def fake_run(self, session, running_job):
        seen.append((running_job.id, bound_tenant_id(session)))

    monkeypatch.setattr(FileService, "_run_gallery_upload_job", fake_run)
    monkeypatch.setattr(FileService, "cleanup_gallery_staging", lambda self, session: None)

    service.process_pending_gallery_upload_jobs(db)

    assert (job.id, tenant.id) in seen
    assert bound_tenant_id(db) is None
