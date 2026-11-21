"""Pendenz-Dialog: Dateien per Drag-and-Drop (1.5.1).

- POST /files/duplicate-check meldet nur Dateien mit gleichem Inhalt, die die Person in der
  Dateisuche auch sehen würde (eigener Mandant, passende Leserechte, kein Papierkorb) - ein
  fremder oder unsichtbarer Treffer sieht aus wie ein unbekannter Hash (kein Existenz-Orakel).
- POST /files/document-uploads mit allow_duplicates speichert eine Kopie statt das Duplikat zu
  überspringen; allow_images nimmt Bilder an, aber nur mit photos.manage.
"""
import asyncio
import hashlib
import io
import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException, UploadFile
from pydantic import ValidationError
from starlette.datastructures import Headers

from app.api.routes import files as files_routes
from app.models.entities import GalleryImage, StoredFile, SubmissionAssignment
from app.schemas.files import FileDiscardUploadsRequest, FileDuplicateCheckRequest, UploadPrecheckRequest
from app.services.file_service import FileService
from tests.factories import make_current_user, make_tenant

service = FileService()

PDF = b"%PDF-1.7\n%pendenz\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00" + b"\x00" * 16


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _upload_file(content: bytes, filename: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=filename, headers=Headers({"content-type": "application/octet-stream"}))


def _upload(db, user, files, **form):
    kwargs = dict(tags=None, event_id=None, submission_assignment_id=None, submission_element_ref=None, cycle_config_id=None)
    kwargs.update(form)
    return asyncio.run(files_routes.upload_documents(files=files, db=db, user=user, **kwargs))


def _store_pdf(db, tenant_id: int, content: bytes = PDF, name: str = "budget.pdf") -> StoredFile:
    items, errors = asyncio.run(
        service.save_document_uploads(db, tenant_id=tenant_id, files=[(name, content)], tags=[], created_by=None)
    )
    assert errors == [] and len(items) == 1
    return db.query(StoredFile).filter_by(tenant_id=tenant_id, public_id=items[0].id).one()


def _assignment_id(db, tenant_id: int) -> int:
    assignment = SubmissionAssignment(tenant_id=tenant_id, title="Lagerbericht", public_slug=f"lager-{tenant_id}", source_type="manual")
    db.add(assignment)
    db.flush()
    return assignment.id


def _check(db, user, *hashes):
    return files_routes.check_file_duplicates(FileDuplicateCheckRequest(sha256=list(hashes)), db=db, user=user).matches


# --- Duplikatprüfung ------------------------------------------------------------------------


def test_duplicate_check_finds_visible_file_of_own_tenant(db):
    tenant = make_tenant(db)
    stored = _store_pdf(db, tenant.id)
    writer = make_current_user(tenant.id, role="writer")

    matches = _check(db, writer, _sha(PDF).upper(), "0" * 64)

    assert len(matches) == 1
    assert matches[0].sha256 == _sha(PDF)
    assert matches[0].file.id == stored.public_id
    assert matches[0].file.original_name == "budget.pdf"


def test_duplicate_check_never_reports_a_file_of_another_tenant(db):
    own = make_tenant(db)
    foreign = make_tenant(db)
    _store_pdf(db, foreign.id)
    writer = make_current_user(own.id, role="writer")

    assert _check(db, writer, _sha(PDF)) == []


def test_duplicate_check_hides_files_the_person_cannot_see(db):
    """Nur Foto-Leserecht: Dokumente der Ablage sind in der Dateisuche unsichtbar, also auch hier."""
    tenant = make_tenant(db)
    _store_pdf(db, tenant.id)
    photos_only = make_current_user(tenant.id, role="writer", permissions=frozenset({"photos.read", "meetings.read"}))

    assert _check(db, photos_only, _sha(PDF)) == []


def test_duplicate_check_ignores_trashed_files(db):
    tenant = make_tenant(db)
    stored = _store_pdf(db, tenant.id)
    stored.deleted_at = datetime.now(UTC)
    db.flush()
    writer = make_current_user(tenant.id, role="writer")

    assert _check(db, writer, _sha(PDF)) == []


def test_duplicate_check_requires_read_permission(db):
    tenant = make_tenant(db)
    nobody = make_current_user(tenant.id, role="reader", permissions=frozenset({"meetings.read"}))

    with pytest.raises(HTTPException) as exc_info:
        _check(db, nobody, _sha(PDF))
    assert exc_info.value.status_code == 403


def test_duplicate_check_prefers_visible_copy_over_older_hidden_one(db, monkeypatch):
    """Ältere Kopie ausserhalb der Abgabe-Reichweite, neuere sichtbare: gemeldet wird nur die sichtbare."""
    from app.services import context_visibility_service

    tenant = make_tenant(db)
    hidden = _store_pdf(db, tenant.id, name="abgabe.pdf")
    # Zweite Kopie mit gleichem Inhalt (allow_duplicates wie im Pendenz-Dialog)
    items, _errors = asyncio.run(
        service.save_document_uploads(db, tenant_id=tenant.id, files=[("ablage.pdf", PDF)], tags=[], created_by=None, allow_duplicates=True)
    )
    visible_id = items[0].id
    # Die ältere Kopie hängt an einem Auftrag, den die Person nicht sehen darf
    hidden_gallery = db.query(GalleryImage).filter_by(stored_file_id=hidden.id).one()
    hidden_gallery.submission_assignment_id = _assignment_id(db, tenant.id)
    db.flush()
    monkeypatch.setattr(context_visibility_service, "readable_assignment_ids", lambda _db, _user: set())
    writer = make_current_user(tenant.id, role="writer")

    matches = _check(db, writer, _sha(PDF))

    assert [match.file.id for match in matches] == [visible_id]


@pytest.mark.parametrize("hashes", [[], ["abc"], ["g" * 64], ["0" * 64] * 21])
def test_duplicate_check_validates_hashes(hashes):
    with pytest.raises(ValidationError):
        FileDuplicateCheckRequest(sha256=hashes)


# --- Upload aus dem Pendenz-Dialog ----------------------------------------------------------


def test_document_upload_skips_exact_duplicate_by_default(db):
    tenant = make_tenant(db)
    _store_pdf(db, tenant.id)
    writer = make_current_user(tenant.id, role="writer")

    result = _upload(db, writer, [_upload_file(PDF, "nochmal.pdf")])

    assert result.items == []
    assert [entry.status for entry in result.file_results] == ["skipped"]
    assert db.query(StoredFile).filter_by(tenant_id=tenant.id).count() == 1


def test_document_upload_with_allow_duplicates_stores_a_copy(db):
    tenant = make_tenant(db)
    original = _store_pdf(db, tenant.id)
    writer = make_current_user(tenant.id, role="writer")

    result = _upload(db, writer, [_upload_file(PDF, "kopie.pdf")], allow_duplicates=True)

    assert len(result.items) == 1
    assert result.items[0].id != original.public_id
    assert result.items[0].original_name == "kopie.pdf"
    assert db.query(StoredFile).filter_by(tenant_id=tenant.id, checksum_sha256=_sha(PDF)).count() == 2


def test_document_upload_with_allow_duplicates_does_not_reveal_hidden_duplicate(db):
    """Mit allow_duplicates meldet der Upload nie «übersprungen» samt ID einer vorhandenen Datei (die
    für die Person unsichtbar sein könnte) - die Kopie wird normal gespeichert."""
    tenant = make_tenant(db)
    hidden = _store_pdf(db, tenant.id)
    writer = make_current_user(tenant.id, role="writer")

    result = _upload(db, writer, [_upload_file(PDF, "neu.pdf")], allow_duplicates=True)

    assert all(entry.file_id != str(hidden.public_id) for entry in result.file_results)
    assert all(entry.status == "uploaded" for entry in result.file_results)


def test_document_upload_still_checks_magic_bytes_with_allow_duplicates(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")

    result = _upload(db, writer, [_upload_file(b"MZ\x90\x00 kein pdf", "virus.pdf")], allow_duplicates=True)

    assert result.items == []
    assert result.errors and "virus.pdf" in result.errors[0]


def test_document_upload_rejects_images_without_allow_images(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")

    result = _upload(db, writer, [_upload_file(PNG, "screenshot.png")])

    assert result.items == []
    assert result.errors


def test_document_upload_allow_images_requires_photos_manage(db):
    tenant = make_tenant(db)
    files_only = make_current_user(
        tenant.id, role="writer", permissions=frozenset({"files.read", "files.manage", "meetings.read", "meetings.edit"})
    )

    with pytest.raises(HTTPException) as exc_info:
        _upload(db, files_only, [_upload_file(PNG, "screenshot.png")], allow_images=True)
    assert exc_info.value.status_code == 403
    assert db.query(StoredFile).filter_by(tenant_id=tenant.id).count() == 0


def test_document_upload_allow_images_stores_image(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")

    result = _upload(db, writer, [_upload_file(PNG, "screenshot.png")], allow_images=True)

    assert len(result.items) == 1
    assert result.items[0].mime_type == "image/png"


# --- V-1/V-2: Duplikate, die die Person nicht sehen darf, gelten als unbekannt --------------

def _photos_manager(tenant_id: int):
    """Darf Fotos verwalten, sieht aber keine Dokumente der Ablage."""
    return make_current_user(
        tenant_id, role="writer", permissions=frozenset({"photos.read", "photos.manage", "files.manage", "meetings.read"})
    )


def test_precheck_treats_invisible_duplicate_as_unknown(db):
    tenant = make_tenant(db)
    _store_pdf(db, tenant.id)
    entry = {"client_id": "a", "sha256": _sha(PDF), "name": "x.pdf", "size": len(PDF)}

    hidden = files_routes.precheck_uploads(
        UploadPrecheckRequest(context="document", files=[entry]), db=db, user=_photos_manager(tenant.id)
    ).results
    visible = files_routes.precheck_uploads(
        UploadPrecheckRequest(context="document", files=[entry]), db=db, user=make_current_user(tenant.id, role="writer")
    ).results

    assert hidden[0].status == "upload_required" and hidden[0].file_id is None
    assert visible[0].status == "already_exists" and visible[0].file_id is not None


def test_precheck_never_reports_foreign_tenant_file(db):
    own, foreign = make_tenant(db), make_tenant(db)
    _store_pdf(db, foreign.id)
    entry = {"client_id": "a", "sha256": _sha(PDF), "name": "x.pdf", "size": len(PDF)}
    result = files_routes.precheck_uploads(
        UploadPrecheckRequest(context="document", files=[entry]), db=db, user=make_current_user(own.id, role="writer")
    ).results
    assert result[0].status == "upload_required" and result[0].file_id is None


def test_document_upload_stores_copy_of_invisible_duplicate(db):
    tenant = make_tenant(db)
    hidden = _store_pdf(db, tenant.id)

    result = _upload(db, _photos_manager(tenant.id), [_upload_file(PDF, "kopie.pdf")])

    assert len(result.items) == 1 and result.errors == []
    assert all(entry.file_id != str(hidden.public_id) for entry in result.file_results)
    assert db.query(StoredFile).filter_by(tenant_id=tenant.id, checksum_sha256=_sha(PDF)).count() == 2


def test_document_upload_still_skips_visible_duplicate_with_its_id(db):
    tenant = make_tenant(db)
    stored = _store_pdf(db, tenant.id)

    result = _upload(db, make_current_user(tenant.id, role="writer"), [_upload_file(PDF, "nochmal.pdf")])

    assert result.items == []
    assert [(entry.status, entry.file_id) for entry in result.file_results] == [("skipped", str(stored.public_id))]


def test_visibility_query_runs_even_without_candidates(db, monkeypatch):
    """Gleiche Antwortzeit-Logik: ohne Treffer im Mandanten läuft die Sichtbarkeitsabfrage trotzdem."""
    tenant = make_tenant(db)
    calls = []
    original = FileService.visible_overview_items
    monkeypatch.setattr(FileService, "visible_overview_items", lambda self, *args: calls.append(args) or original(self, *args))
    entry = {"client_id": "a", "sha256": "0" * 64, "name": "x.pdf", "size": 1}

    files_routes.precheck_uploads(UploadPrecheckRequest(context="document", files=[entry]), db=db, user=make_current_user(tenant.id))
    _upload(db, make_current_user(tenant.id), [_upload_file(b"%PDF-1.7\n%neu\n", "neu.pdf")])

    assert len(calls) >= 2


# --- GPS wie beim Galerie-Upload ------------------------------------------------------------

def _stored_bytes(db, stored: StoredFile) -> bytes:
    from app.core.storage import get_object_store
    from app.services.stored_file_location import namespace_for_stored_file

    return get_object_store().get_bytes(namespace_for_stored_file(db, stored), stored.storage_path)


def test_document_upload_strips_gps_from_images_when_asked(db):
    from tests.image_fixtures import jpeg, read_exif

    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    photo = jpeg(latitude=47.37, longitude=8.54)
    assert read_exif(photo)[2]

    stripped = _upload(db, writer, [_upload_file(photo, "ort.jpg")], allow_images=True, allow_duplicates=True, include_gps=False)
    kept = _upload(db, writer, [_upload_file(photo, "ort2.jpg")], allow_images=True, allow_duplicates=True)

    stripped_row = db.query(StoredFile).filter_by(public_id=stripped.items[0].id).one()
    kept_row = db.query(StoredFile).filter_by(public_id=kept.items[0].id).one()
    assert read_exif(_stored_bytes(db, stripped_row))[2] == {}
    assert read_exif(_stored_bytes(db, kept_row))[2]


# --- Abbrechen: frisch hochgeladene, unverknüpfte Dateien in den Papierkorb -----------------

def _discard(db, user, *ids):
    return files_routes.discard_unlinked_uploads(FileDiscardUploadsRequest(file_ids=list(ids)), db=db, user=user).discarded


def _own_upload(db, user, name="neu.pdf", marker=b"neu"):
    result = _upload(db, user, [_upload_file(b"%PDF-1.7\n%" + marker + b"\n", name)], allow_duplicates=True)
    return db.query(StoredFile).filter_by(public_id=result.items[0].id).one()


def test_discard_trashes_own_fresh_unlinked_upload(db):
    tenant = make_tenant(db)
    from tests.factories import make_app_user

    account = make_app_user(db, email=f"d{tenant.id}@example.com", tenant_id=tenant.id, role_code="writer")
    writer = make_current_user(tenant.id, role="writer", user_id=account.id)
    stored = _own_upload(db, writer)

    assert _discard(db, writer, stored.public_id) == [stored.public_id]
    db.refresh(stored)
    assert stored.deleted_at is not None  # Papierkorb, wiederherstellbar


def test_discard_never_touches_foreign_linked_old_or_other_peoples_files(db):
    from app.models.entities import ProtocolTodoFile
    from app.schemas.protocol import ProtocolTodoCreate
    from app.services.protocol_todo_service import ProtocolTodoService
    from tests.factories import make_app_user

    tenant, foreign = make_tenant(db), make_tenant(db)
    me = make_app_user(db, email=f"me{tenant.id}@example.com", tenant_id=tenant.id, role_code="writer")
    other = make_app_user(db, email=f"other{tenant.id}@example.com", tenant_id=tenant.id, role_code="writer")
    writer = make_current_user(tenant.id, role="writer", user_id=me.id)

    linked = _own_upload(db, writer, "verknuepft.pdf", b"a")
    todo = ProtocolTodoService().create_standalone_todo(db, tenant.id, ProtocolTodoCreate(task="Mit Datei", todo_status_id=1))
    db.flush()
    db.add(ProtocolTodoFile(protocol_todo_id=todo.id, stored_file_id=linked.id, sort_index=0))
    old = _own_upload(db, writer, "alt.pdf", b"b")
    old.created_at = datetime(2020, 1, 1, tzinfo=UTC)
    someone_else = _own_upload(db, make_current_user(tenant.id, role="writer", user_id=other.id), "fremd.pdf", b"c")
    foreign_file = _own_upload(db, make_current_user(foreign.id, role="writer", user_id=me.id), "mandant.pdf", b"d")
    with_bezug = _own_upload(db, writer, "bezug.pdf", b"e")
    gallery = db.query(GalleryImage).filter_by(stored_file_id=with_bezug.id).one()
    gallery.submission_assignment_id = _assignment_id(db, tenant.id)
    db.flush()

    ids = [linked.public_id, old.public_id, someone_else.public_id, foreign_file.public_id, with_bezug.public_id]
    assert _discard(db, writer, *ids) == []
    for row in (linked, old, someone_else, foreign_file, with_bezug):
        db.refresh(row)
        assert row.deleted_at is None


def test_discard_requires_manage_permission(db):
    tenant = make_tenant(db)
    reader = make_current_user(tenant.id, role="reader", permissions=frozenset({"files.read", "meetings.read"}))
    with pytest.raises(HTTPException) as exc_info:
        _discard(db, reader, uuid.uuid4())
    assert exc_info.value.status_code == 403
