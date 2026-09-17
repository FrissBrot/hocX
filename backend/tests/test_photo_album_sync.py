"""Tests for photo_album_service.sync_submission_uploads - the periodic loop that folds
abgabebox submission-upload photos into their auto-generated albums (see main.py's
photo_album_sync_loop). Covers the album_synced_at bounding added in the 2026-09-17 audit
fix: only rows not yet reflected in albums get scanned/processed each tick, instead of
every clean image submission ever uploaded, every tick, forever."""
from __future__ import annotations

from app.models.entities import (
    PhotoAlbum,
    PhotoAlbumItem,
    StoredFile,
    SubmissionAssignment,
    SubmissionUpload,
    SubmissionUploadFile,
)
from app.services import photo_album_service
from app.services.file_service import FileService
from tests.factories import make_list_definition, make_list_entry, make_tenant

service = FileService()


def _make_list_backed_assignment(db, tenant_id: int, *, title: str = "Fotos Sommerlager") -> SubmissionAssignment:
    list_definition = make_list_definition(db, tenant_id)
    entry = make_list_entry(db, list_definition.id)
    assignment = SubmissionAssignment(
        tenant_id=tenant_id, title=title, public_slug=f"{title.lower().replace(' ', '-')}-{entry.id}",
        source_type="list", list_definition_id=list_definition.id,
    )
    db.add(assignment)
    db.flush()
    upload = SubmissionUpload(assignment_id=assignment.id, event_id=None, list_entry_id=entry.id, status="submitted")
    db.add(upload)
    db.flush()
    return assignment, upload


def _make_submission_image(db, tenant_id, upload_id, *, filename="foto.png", delete_comment=None) -> SubmissionUploadFile:
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name=filename, mime_type="image/png",
        storage_path=f"abgabebox/{filename}", scan_status="clean",
    )
    db.add(stored_file)
    db.flush()
    upload_file = SubmissionUploadFile(upload_id=upload_id, stored_file_id=stored_file.id, delete_comment=delete_comment)
    db.add(upload_file)
    db.flush()
    return stored_file, upload_file


def test_sync_files_a_new_submission_photo_into_its_albums_and_marks_it_synced(db):
    tenant = make_tenant(db)
    assignment, upload = _make_list_backed_assignment(db, tenant.id)
    stored_file, upload_file = _make_submission_image(db, tenant.id, upload.id)

    photo_album_service.sync_submission_uploads(db, service)

    db.refresh(upload_file)
    assert upload_file.album_synced_at is not None

    items = db.query(PhotoAlbumItem).filter_by(file_id=stored_file.public_id).all()
    # Lands in both the submission-wide album and the element-scoped album (see
    # assign_uploaded_files' docstring on the two very different call sites feeding the
    # same album-creation functions).
    assert len(items) == 2
    for item in items:
        album = db.get(PhotoAlbum, item.album_id)
        assert album.tenant_id == tenant.id


def test_sync_does_not_reprocess_an_already_synced_row(db, monkeypatch):
    """Regression test (2026-09-17 audit fix): previously every clean image
    submission_upload_file was re-selected and re-scanned on every tick, forever. Now a
    row with album_synced_at already set is excluded from the query entirely - verified
    here by spying on get_or_create_submission_album's call count across two ticks with no
    new files in between."""
    tenant = make_tenant(db)
    assignment, upload = _make_list_backed_assignment(db, tenant.id)
    _make_submission_image(db, tenant.id, upload.id)

    photo_album_service.sync_submission_uploads(db, service)

    call_count = {"n": 0}
    original = photo_album_service.get_or_create_submission_album

    def _counting(*args, **kwargs):
        call_count["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(photo_album_service, "get_or_create_submission_album", _counting)

    photo_album_service.sync_submission_uploads(db, service)

    assert call_count["n"] == 0


def test_sync_removes_a_soft_deleted_photo_from_its_albums_and_marks_it_synced(db):
    tenant = make_tenant(db)
    assignment, upload = _make_list_backed_assignment(db, tenant.id)
    stored_file, upload_file = _make_submission_image(db, tenant.id, upload.id)

    photo_album_service.sync_submission_uploads(db, service)
    assert db.query(PhotoAlbumItem).filter_by(file_id=stored_file.public_id).count() > 0

    upload_file.delete_comment = "Falsches Foto"
    upload_file.album_synced_at = None
    db.add(upload_file)
    db.commit()

    photo_album_service.sync_submission_uploads(db, service)

    db.refresh(upload_file)
    assert upload_file.album_synced_at is not None
    assert db.query(PhotoAlbumItem).filter_by(file_id=stored_file.public_id).count() == 0


def test_sync_ignores_a_non_image_or_unscanned_file(db):
    tenant = make_tenant(db)
    assignment, upload = _make_list_backed_assignment(db, tenant.id)
    stored_file = StoredFile(
        tenant_id=tenant.id, original_name="beleg.pdf", mime_type="application/pdf",
        storage_path="abgabebox/beleg.pdf", scan_status="clean",
    )
    db.add(stored_file)
    db.flush()
    upload_file = SubmissionUploadFile(upload_id=upload.id, stored_file_id=stored_file.id)
    db.add(upload_file)
    db.commit()

    photo_album_service.sync_submission_uploads(db, service)

    db.refresh(upload_file)
    assert upload_file.album_synced_at is None
    assert db.query(PhotoAlbumItem).filter_by(file_id=stored_file.public_id).count() == 0
