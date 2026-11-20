"""Papierkorb für Dateien und Fotos (Migration 0199, services/file_trash_service.py).

Gelöschte Dateien verschwinden aus jedem Lesepfad (Liste, Galerie, Zeitstrahl, Suche, Alben,
öffentliche Links, Pendenzen, Inhalt/Vorschau, Statistik, Abgabebox- und Foto-Worker-Rolle),
kommen mit «Wiederherstellen» samt Verknüpfungen zurück und werden erst von Hand oder nach der
Frist endgültig gelöscht. DSGVO-/Offboarding-/Aufbewahrungswege löschen weiterhin sofort und
schliessen den Papierkorb ein. Das Kontingent zählt den Papierkorb bis zum endgültigen Löschen."""

from __future__ import annotations

import hashlib
import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from app.api.routes import files as files_routes
from app.api.routes import public_share as public_share_routes
from app.api.routes import share_links as share_links_routes
from app.api.routes.search import search_files
from app.core.storage import MAIN, get_object_store
from app.core.trash_scope import TRASH_RETENTION, include_trashed
from app.models.entities import (
    GalleryImage,
    PhotoAlbum,
    PhotoAlbumItem,
    ProtocolTodoFile,
    ShareLinkFile,
    StoredFile,
    SubmissionLink,
)
from app.repositories.file_repository import StoredFileRepository
from app.schemas.files import FileBulkDelete, FileTrashAction, ShareLinkCreate, UploadPrecheckFile, UploadPrecheckRequest
from app.services import erasure_journal, file_trash_service, photo_album_service, tenant_retention_service
from app.services.admin_tenant_service import AdminTenantService
from app.services.file_service import FileService
from app.services.storage_service import StorageService
from tests.factories import make_app_user, make_current_user, make_event, make_tenant
from tests.test_share_link_routes import _FakeRequest, _isolated_storage_root, _make_file  # noqa: F401  (Fixture)
from tests.test_submission_links import _probe_as_abgabebox
from tests.test_submission_manual_elements import _create, org  # noqa: F401  (Fixture)

service = FileService()
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _user(db, tenant_id: int, role: str = "writer", **kwargs):
    account = make_app_user(db, email=f"trash-{uuid.uuid4().hex[:8]}@example.com", tenant_id=tenant_id, role_code=role)
    return make_current_user(tenant_id, role=role, user_id=account.id, **kwargs)


def _trash(db, user, *files):
    result = files_routes.move_to_trash(FileTrashAction(file_ids=[f.public_id for f in files]), db, user)
    _forget_files(db)
    return result


def _forget_files(db) -> None:
    """Geladene Dateien aus der Identity-Map nehmen: Session.get soll wirklich abfragen (der
    Papierkorb-Filter greift nur auf Abfragen, nicht auf schon geladene Objekte)."""
    for obj in list(db.identity_map.values()):
        if isinstance(obj, StoredFile):
            db.expunge(obj)


def _visible_ids(db, tenant_id: int, **filters) -> set[uuid.UUID]:
    return {item.id for item in service.list_tenant_files(db, tenant_id, limit=200, **filters)}


def _token(created) -> str:
    return created.url.removeprefix("/share/")


def _audit_actions(db, tenant_id: int) -> set[str]:
    return set(db.scalars(text("SELECT action FROM audit_log WHERE tenant_id = :t"), {"t": tenant_id}))


# ── Lesepfade ──────────────────────────────────────────────────────────────────────────────


def test_trashed_file_disappears_from_list_timeline_search_stats_and_content(db):
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    keep = _make_file(db, tenant.id, "bleibt.png")
    gone = _make_file(db, tenant.id, "papierkorb-foto.png")
    keep_id, gone_id, gone_pk = keep.public_id, gone.public_id, gone.id
    db.commit()
    stats_before = service.file_stats(db, tenant.id)

    result = _trash(db, user, gone)

    assert result.file_ids == [gone_id] and result.errors == []
    assert _visible_ids(db, tenant.id) == {keep_id}
    assert _visible_ids(db, tenant.id, only_images=True) == {keep_id}
    assert sum(day.count for day in service.tenant_files_timeline(db, tenant.id, only_images=True)) == 1
    assert [hit.id for hit in search_files(db, tenant.id, "papierkorb")] == []
    assert service.file_stats(db, tenant.id).photo_count == stats_before.photo_count - 1
    assert db.get(StoredFile, gone_pk) is None
    for route in (files_routes.get_stored_file_content, files_routes.get_stored_file_thumbnail):
        with pytest.raises(HTTPException) as exc_info:
            route(gone_id, db=db, user=user) if route is files_routes.get_stored_file_thumbnail else route(gone_id, None, db, user)
        assert exc_info.value.status_code == 404


def test_trashed_photo_disappears_from_album_and_album_counts(db):
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    keep = _make_file(db, tenant.id, "a.png")
    gone = _make_file(db, tenant.id, "b.png")
    album = PhotoAlbum(tenant_id=tenant.id, name="Lager", kind="manual")
    db.add(album)
    db.flush()
    photo_album_service.add_items(db, album, [keep.public_id, gone.public_id], release=True)
    album_id, keep_id = album.id, keep.public_id
    db.commit()

    _trash(db, user, gone)

    assert _visible_ids(db, None, album_id=album_id) == {keep_id}
    [stats] = [row for row in photo_album_service.list_albums_with_stats(db, service, tenant.id) if row.album.id == album_id]
    assert stats.photo_count == 1


def test_public_file_link_to_trashed_file_is_404_and_album_link_hides_it(db):
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    only = _make_file(db, tenant.id, "nur.png")
    keep = _make_file(db, tenant.id, "album-bleibt.png")
    gone = _make_file(db, tenant.id, "album-weg.png")
    album = PhotoAlbum(tenant_id=tenant.id, name="Album", kind="manual")
    db.add(album)
    db.flush()
    photo_album_service.add_items(db, album, [keep.public_id, gone.public_id], release=True)
    db.commit()
    file_link = share_links_routes.create_share_link(ShareLinkCreate(name="Datei", file_ids=[only.public_id]), db, user)
    album_link = share_links_routes.create_share_link(ShareLinkCreate(name="Album", album_id=album.id), db, user)
    only_id, keep_id, gone_id = only.public_id, keep.public_id, gone.public_id

    _trash(db, user, only, gone)

    with pytest.raises(HTTPException) as exc_info:
        public_share_routes.get_public_share(_token(file_link), _FakeRequest(), db)
    assert exc_info.value.status_code == 404
    with pytest.raises(HTTPException) as exc_info:
        public_share_routes.download_public_share_file(_token(file_link), only_id, _FakeRequest(), db)
    assert exc_info.value.status_code == 404
    shared = public_share_routes.get_public_share(_token(album_link), _FakeRequest(), db)
    assert [f.id for f in shared.files] == [keep_id]
    with pytest.raises(HTTPException) as exc_info:
        public_share_routes.get_public_share_thumbnail(_token(album_link), gone_id, _FakeRequest(), db)
    assert exc_info.value.status_code == 404


def test_trashed_file_disappears_from_todo_files_but_link_survives_editing(db):
    from tests.factories import make_protocol_todo
    from app.models.entities import ProtocolTodo
    from app.schemas.protocol import TodoDetailsUpdate
    from app.services.protocol_todo_service import ProtocolTodoService

    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    keep = _make_file(db, tenant.id, "anhang.png")
    gone = _make_file(db, tenant.id, "anhang-weg.png")
    todo = make_protocol_todo(db, None, task="Aufgabe", tenant_id=tenant.id)
    todo_service = ProtocolTodoService()
    todo_service.update_details(db, todo, TodoDetailsUpdate(file_ids=[keep.public_id, gone.public_id]), tenant_id=tenant.id)
    todo_id, keep_id, gone_id, gone_pk = todo.id, keep.public_id, gone.public_id, gone.id

    _trash(db, user, gone)

    todo = db.get(ProtocolTodo, todo_id)
    assert [f.id for f in todo_service.get_details(db, todo).files] == [keep_id]
    # Der Client speichert nur die sichtbaren Dateien: die Verknüpfung zur Papierkorb-Datei bleibt.
    todo_service.update_details(db, todo, TodoDetailsUpdate(file_ids=[keep_id]), tenant_id=tenant.id)
    assert db.scalar(select(ProtocolTodoFile.stored_file_id).where(ProtocolTodoFile.stored_file_id == gone_pk)) == gone_pk
    file_trash_service.restore(db, user, [gone_id])
    _forget_files(db)
    todo = db.get(ProtocolTodo, todo_id)
    assert {f.id for f in todo_service.get_details(db, todo).files} == {keep_id, gone_id}


def test_abgabebox_and_photo_worker_roles_do_not_see_trashed_rows(db):
    from app.schemas.submission import SubmissionLinkCreate
    from app.services.submission_link_service import SubmissionLinkService

    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    keep = _make_file(db, tenant.id, "rolle-a.png")
    gone = _make_file(db, tenant.id, "rolle-b.png")
    for stored_file in (keep, gone):
        stored_file.checksum_sha256 = hashlib.sha256(stored_file.original_name.encode()).hexdigest()
    SubmissionLinkService().create_link(db, SubmissionLinkCreate(name="Trash-Test"), tenant_id=tenant.id)
    token = db.scalar(select(SubmissionLink.token).where(SubmissionLink.tenant_id == tenant.id))
    keep_pk, gone_pk, tenant_id = keep.id, gone.id, tenant.id
    db.commit()
    _trash(db, user, gone)

    nested = db.begin_nested()
    try:
        db.execute(text("SET LOCAL ROLE hocx_abgabebox"))
        db.execute(text("SELECT set_config('app.abgabebox_link', :token, true)"), {"token": token})
        seen = set(db.scalars(text("SELECT id FROM stored_file WHERE tenant_id = :t"), {"t": tenant_id}))
        assert keep_pk in seen and gone_pk not in seen
    finally:
        nested.rollback()

    nested = db.begin_nested()
    try:
        db.execute(text("SET LOCAL ROLE hocx_photo_worker"))
        seen = set(db.scalars(text("SELECT id FROM stored_file WHERE id = ANY(:ids)"), {"ids": [keep_pk, gone_pk]}))
        assert seen == {keep_pk}
        updated = db.execute(text("UPDATE stored_file SET face_quality_score = 1, face_analyzed_at = NOW() WHERE id = :id"), {"id": gone_pk})
        assert updated.rowcount == 0
    finally:
        nested.rollback()


# ── Wiederherstellen, endgültig löschen, Frist ───────────────────────────────────────────────


def test_restore_brings_back_album_tags_event_and_share_link(db):
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    photo = _make_file(db, tenant.id, "zurueck.png")
    photo.tags = ["Sommerlager"]
    event = make_event(db, tenant.id, title="Lager")
    db.execute(GalleryImage.__table__.update().where(GalleryImage.stored_file_id == photo.id).values(event_id=event.id))
    album = PhotoAlbum(tenant_id=tenant.id, name="Album", kind="manual")
    db.add(album)
    db.flush()
    photo_album_service.add_items(db, album, [photo.public_id], release=True)
    db.commit()
    link = share_links_routes.create_share_link(ShareLinkCreate(name="Link", file_ids=[photo.public_id]), db, user)
    photo_id, album_id = photo.public_id, album.id

    _trash(db, user, photo)
    listing = files_routes.list_trash(db, user)
    assert [item.id for item in listing.items] == [photo_id]
    assert listing.items[0].days_left == TRASH_RETENTION.days
    assert listing.items[0].deleted_by_name

    restored = files_routes.restore_from_trash(FileTrashAction(file_ids=[photo_id]), db, user)
    _forget_files(db)

    assert restored.file_ids == [photo_id]
    [item] = service.list_tenant_files(db, None, album_id=album_id, limit=10)
    assert item.id == photo_id and item.tags == ["Sommerlager"] and item.ref_label == "Lager"
    shared = public_share_routes.get_public_share(_token(link), _FakeRequest(), db)
    assert [f.id for f in shared.files] == [photo_id]
    assert files_routes.list_trash(db, user).items == []


def test_purge_deletes_object_row_album_and_link_entries_and_journals(db):
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    photo = _make_file(db, tenant.id, "endgueltig.png")
    album = PhotoAlbum(tenant_id=tenant.id, name="Album", kind="manual")
    db.add(album)
    db.flush()
    photo_album_service.add_items(db, album, [photo.public_id], release=True)
    db.commit()
    share_links_routes.create_share_link(ShareLinkCreate(name="Link", file_ids=[photo.public_id]), db, user)
    photo_id, photo_pk, key = photo.public_id, photo.id, photo.storage_path
    _trash(db, user, photo)

    result = files_routes.purge_from_trash(FileTrashAction(file_ids=[photo_id]), db, user)
    get_object_store().purge_deleted(db)

    assert result.file_ids == [photo_id]
    with include_trashed(db):
        assert db.get(StoredFile, photo_pk) is None
    assert get_object_store().active_backend().head(MAIN, key) is None
    assert db.scalar(select(PhotoAlbumItem.file_id).where(PhotoAlbumItem.file_id == photo_id)) is None
    assert db.scalar(select(ShareLinkFile.file_id).where(ShareLinkFile.file_id == photo_id)) is None
    assert db.scalar(text("SELECT count(*) FROM erasure_journal WHERE subject_public_id = :id"), {"id": photo_id}) == 1
    assert {"file.trashed", "file.purged"} <= _audit_actions(db, tenant.id)


def test_empty_trash_purges_everything_visible(db):
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    files = [_make_file(db, tenant.id, f"leer-{i}.png") for i in range(3)]
    db.commit()
    _trash(db, user, *files)

    result = files_routes.empty_trash(db, user)

    assert result.purged == 3
    assert files_routes.list_trash(db, user).items == []
    assert "file.trash_emptied" in _audit_actions(db, tenant.id)


def test_purge_expired_only_removes_files_past_the_retention(db):
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    old = _make_file(db, tenant.id, "alt.png")
    fresh = _make_file(db, tenant.id, "neu.png")
    old_pk, fresh_pk = old.id, fresh.id
    db.commit()
    _trash(db, user, old, fresh)
    db.execute(
        StoredFile.__table__.update().where(StoredFile.id == old_pk).values(deleted_at=datetime.now(UTC) - TRASH_RETENTION - timedelta(hours=1))
    )
    db.commit()

    result = file_trash_service.purge_expired(db)

    assert result["purged"] >= 1 and result["failed"] == 0
    with include_trashed(db):
        assert db.get(StoredFile, old_pk) is None
        assert db.get(StoredFile, fresh_pk) is not None


def test_job_is_registered_with_lock_id():
    from app.core.background_loops import BACKGROUND_LOCK_IDS
    from app.core.job_registry import JOB_DEFINITIONS
    from app.core.loops import JOB_WORKER_LOOPS, file_trash_purge_loop

    assert "file_trash_purge" in BACKGROUND_LOCK_IDS
    assert any(job.name == "file_trash_purge" for job in JOB_DEFINITIONS)
    assert file_trash_purge_loop in JOB_WORKER_LOOPS


# ── Rechte und Mandanten ─────────────────────────────────────────────────────────────────────


def test_other_tenant_cannot_trash_list_restore_or_purge(db):
    tenant = make_tenant(db)
    other = make_tenant(db, "Fremder Verein")
    user = _user(db, tenant.id)
    stranger = _user(db, other.id)
    photo = _make_file(db, tenant.id, "fremd.png")
    photo_id = photo.public_id
    db.commit()

    attempt = _trash(db, stranger, photo)
    assert attempt.file_ids == [] and attempt.errors
    _trash(db, user, db.scalar(select(StoredFile).where(StoredFile.public_id == photo_id)))

    assert files_routes.list_trash(db, stranger).items == []
    assert files_routes.restore_from_trash(FileTrashAction(file_ids=[photo_id]), db, stranger).file_ids == []
    assert files_routes.purge_from_trash(FileTrashAction(file_ids=[photo_id]), db, stranger).file_ids == []
    assert files_routes.empty_trash(db, stranger).purged == 0
    with pytest.raises(HTTPException) as exc_info:
        files_routes.get_trash_thumbnail(photo_id, db, stranger)
    assert exc_info.value.status_code == 404
    assert [item.id for item in files_routes.list_trash(db, user).items] == [photo_id]


def test_reader_has_no_trash_access(db):
    tenant = make_tenant(db)
    reader = _user(db, tenant.id, role="reader")
    for call in (
        lambda: files_routes.list_trash(db, reader),
        lambda: files_routes.move_to_trash(FileTrashAction(file_ids=[uuid.uuid4()]), db, reader),
        lambda: files_routes.restore_from_trash(FileTrashAction(file_ids=[uuid.uuid4()]), db, reader),
        lambda: files_routes.purge_from_trash(FileTrashAction(file_ids=[uuid.uuid4()]), db, reader),
        lambda: files_routes.empty_trash(db, reader),
    ):
        with pytest.raises(HTTPException) as exc_info:
            call()
        assert exc_info.value.status_code == 403


def test_photos_manage_alone_neither_trashes_nor_sees_documents(db):
    tenant = make_tenant(db)
    writer = _user(db, tenant.id)
    photos_only = _user(db, tenant.id, permissions=frozenset({"photos.read", "photos.manage", "meetings.read"}))
    document = _make_file(db, tenant.id, "bericht.pdf", content=b"%PDF-1.4 test", mime_type="application/pdf")
    photo = _make_file(db, tenant.id, "foto-recht.png")
    document_id, photo_id = document.public_id, photo.public_id
    db.commit()

    attempt = _trash(db, photos_only, document)
    assert attempt.file_ids == [] and attempt.errors
    _trash(db, writer, db.scalar(select(StoredFile).where(StoredFile.public_id == document_id)))
    _trash(db, photos_only, db.scalar(select(StoredFile).where(StoredFile.public_id == photo_id)))

    assert [item.id for item in files_routes.list_trash(db, photos_only).items] == [photo_id]
    assert {item.id for item in files_routes.list_trash(db, writer).items} == {photo_id, document_id}


def test_only_direct_uploads_go_to_the_trash(db):
    from tests.test_photo_bulk_delete import _make_protocol_image

    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    protocol_file = _make_protocol_image(db, tenant.id)
    protocol_file_id = protocol_file.public_id
    db.commit()

    result = _trash(db, user, protocol_file)

    assert result.file_ids == [] and result.errors
    assert db.scalar(select(StoredFile.id).where(StoredFile.public_id == protocol_file_id)) is not None


def test_bulk_delete_route_moves_to_trash(db):
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    photo = _make_file(db, tenant.id, "mehrfach.png")
    photo_id = photo.public_id
    db.commit()

    result = files_routes.bulk_delete_files(FileBulkDelete(file_ids=[photo_id]), db, user)
    _forget_files(db)

    assert result.deleted_ids == [photo_id]
    assert [item.id for item in files_routes.list_trash(db, user).items] == [photo_id]


# ── Kontingent, Duplikate, DSGVO-Wege ────────────────────────────────────────────────────────


def test_trash_counts_towards_quota_and_has_its_own_storage_category(db):
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    photo = _make_file(db, tenant.id, "kontingent.png")
    photo.file_size_bytes = 5000
    db.commit()
    before = StoredFileRepository().total_bytes_for_tenant(db, tenant.id)

    _trash(db, user, photo)

    assert StoredFileRepository().total_bytes_for_tenant(db, tenant.id) == before
    breakdown = StorageService().breakdown_for_tenant(db, tenant.id)
    assert {c.key: c.bytes for c in breakdown.categories}["trash"] == 5000
    assert breakdown.total_bytes == before
    assert files_routes.list_trash(db, user).total_bytes == 5000


def test_reupload_of_trashed_file_is_stored_again_not_rejected_as_duplicate(db):
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    content = b"\x89PNG\r\n\x1a\n" + b"trash-duplicate"
    photo = _make_file(db, tenant.id, "doppelt.png", content=content)
    checksum = hashlib.sha256(content).hexdigest()
    photo.checksum_sha256 = checksum
    db.commit()
    request = UploadPrecheckRequest(files=[UploadPrecheckFile(client_id="a", sha256=checksum, size=len(content))])
    assert service.precheck_uploads(db, tenant_id=tenant.id, request=request, user_id=user.user_id)[0].status == "already_exists"

    _trash(db, user, photo)

    [result] = service.precheck_uploads(db, tenant_id=tenant.id, request=request, user_id=user.user_id)
    assert result.status == "upload_required"
    kept, skipped = service._filter_exact_duplicates(db, tenant.id, [("doppelt.png", content)])
    assert [name for name, _ in kept] == ["doppelt.png"] and skipped == []


def test_tenant_deletion_removes_trashed_objects(db):
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    photo = _make_file(db, tenant.id, "offboarding.png")
    key = photo.storage_path
    db.commit()
    _trash(db, user, photo)

    AdminTenantService().delete_tenant(db, tenant.id)
    db.commit()
    get_object_store().purge_deleted(db)

    assert get_object_store().active_backend().head(MAIN, key) is None


def test_erasure_journal_replay_finds_trashed_file(db):
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    photo = _make_file(db, tenant.id, "journal.png")
    photo_id, photo_pk = photo.public_id, photo.id
    db.commit()
    _trash(db, user, photo)

    result = erasure_journal.apply(
        db, [erasure_journal.ErasureEntry(kind="stored_file", subject_public_id=photo_id, tenant_public_id=None, created_at=datetime.now(UTC))]
    )

    assert result["applied"] == 1
    with include_trashed(db):
        assert db.get(StoredFile, photo_pk) is None


def test_retention_apply_deletes_a_trashed_file_immediately(db):
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    photo = _make_file(db, tenant.id, "aufbewahrung.png")
    photo_pk = photo.id
    db.commit()
    _trash(db, user, photo)

    with include_trashed(db):
        tenant_retention_service._apply(db, tenant.id, "gallery_image", photo_pk)
    db.commit()

    with include_trashed(db):
        assert db.get(StoredFile, photo_pk) is None


def test_personal_export_lists_trashed_files_with_date(db):
    from app.services.data_export import personal

    tenant = make_tenant(db)
    account = make_app_user(db, email=f"export-{uuid.uuid4().hex[:6]}@example.com", tenant_id=tenant.id, role_code="writer")
    user = make_current_user(tenant.id, role="writer", user_id=account.id)
    photo = _make_file(db, tenant.id, "auskunft.png")
    photo.created_by = account.id
    db.commit()
    _trash(db, user, photo)

    data = personal.collect(db, db.get(type(account), account.id))

    [row] = [row for row in data["files"] if row["name"] == "auskunft.png"]
    assert row["trashed_at"] is not None


# ── Migration ────────────────────────────────────────────────────────────────────────────────


def _migration(filename: str = "0199_stored_file_soft_delete.py"):
    spec = importlib.util.spec_from_file_location(f"migration_{filename[:4]}", BACKEND_ROOT / "alembic/versions" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_downgrade_restores_trash_and_upgrade_recreates_policy():
    """Downgrade holt Papierkorb-Dateien zurück (Spalten fallen weg), Upgrade legt Spalten,
    Index und die RESTRICTIVE-Policy für Abgabebox/Foto-Worker wieder an. In einer Transaktion,
    die am Ende zurückgerollt wird."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    from app.core.db import engine

    module = _migration()
    above = _migration("0200_photo_capture_override.py")
    assert len(module.revision) <= 32 and module.down_revision == "0198_submission_manual_elements"
    assert above.down_revision == module.revision
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            tenant_id = conn.scalar(text("INSERT INTO tenant (name) VALUES ('Migration 0199') RETURNING id"))
            file_id = conn.scalar(
                text(
                    "INSERT INTO stored_file (tenant_id, original_name, storage_path, deleted_at) "
                    "VALUES (:t, 'm.png', 'uploads/m.png', now()) RETURNING id"
                ),
                {"t": tenant_id},
            )
            # Kette wie alembic: erst 0200 zurück, dann 0199; danach in umgekehrter Reihenfolge hoch
            with Operations.context(MigrationContext.configure(conn)):
                above.downgrade()
                module.downgrade()
            columns = {column["name"] for column in inspect(conn).get_columns("stored_file")}
            assert "deleted_at" not in columns and "deleted_by" not in columns
            assert conn.scalar(text("SELECT count(*) FROM pg_policies WHERE policyname = 'stored_file_hide_trash'")) == 0
            assert conn.scalar(text("SELECT id FROM stored_file WHERE id = :id"), {"id": file_id}) == file_id
            assert not any("deleted_at" in source for source in _abgabebox_function_sources(conn))
            _assert_abgabebox_function_rights(conn)

            with Operations.context(MigrationContext.configure(conn)):
                module.upgrade()
                above.upgrade()
            assert conn.scalar(text("SELECT deleted_at FROM stored_file WHERE id = :id"), {"id": file_id}) is None
            roles = set(conn.scalars(text("SELECT unnest(roles)::text FROM pg_policies WHERE policyname = 'stored_file_hide_trash'")))
            assert roles == {"hocx_abgabebox", "hocx_photo_worker"}
            assert conn.scalar(text("SELECT permissive FROM pg_policies WHERE policyname = 'stored_file_hide_trash'")) == "RESTRICTIVE"
            sources = _abgabebox_function_sources(conn)
            assert len(sources) == 2 and all("s.deleted_at IS NOT NULL" in source for source in sources)
            _assert_abgabebox_function_rights(conn)
        finally:
            transaction.rollback()


def _abgabebox_function_sources(conn) -> list[str]:
    return list(conn.scalars(text(
        "SELECT prosrc FROM pg_proc WHERE proname IN ('submission_linked_file_counts', 'submission_withdrawn_elements') ORDER BY proname"
    )))


def _assert_abgabebox_function_rights(conn) -> None:
    """Wie 0198: SECURITY DEFINER mit festem search_path, nur hocx_abgabebox darf ausführen."""
    rows = conn.execute(text(
        "SELECT proname, prosecdef, proconfig, "
        "has_function_privilege('hocx_abgabebox', p.oid, 'EXECUTE') AS box, "
        "has_function_privilege('hocx_app', p.oid, 'EXECUTE') AS app "
        "FROM pg_proc p WHERE proname IN ('submission_linked_file_counts', 'submission_withdrawn_elements')"
    )).all()
    assert len(rows) == 2
    for row in rows:
        assert row.prosecdef and row.proconfig == ["search_path=pg_catalog, public"]
        assert row.box and not row.app


# ── Nachbesserungen aus dem Security-Review des Papierkorbs ──────────────────────────────────


def test_trashed_submission_photo_frees_capacity_in_backend_and_abgabebox(db, org):
    """Eine verknüpfte Galerie-Datei einer Abgabe im Papierkorb belegt weder im Backend
    (submission_upload_rules) noch in der Abgabebox (SECURITY-DEFINER-Funktionen, als Rolle
    hocx_abgabebox) Platz und sperrt das Element nicht als «zurückgezogen»."""
    from app.services import submission_upload_rules
    from app.services.submission_service import SubmissionService

    tenant_id = org["tenant"].id
    user = _user(db, tenant_id, role="admin")
    _read, assignment = _create(db, org, None, max_files_per_element=2)
    keep = _make_file(db, tenant_id, "abgabe-bleibt.png")
    gone = _make_file(db, tenant_id, "abgabe-papierkorb.png")
    withdrawn = _make_file(db, tenant_id, "abgabe-zurueckgezogen.png")
    for stored_file in (keep, gone, withdrawn):
        db.execute(
            GalleryImage.__table__.update().where(GalleryImage.stored_file_id == stored_file.id)
            .values(submission_assignment_id=assignment.id, submission_element_ref="manual")
        )
    db.execute(GalleryImage.__table__.update().where(GalleryImage.stored_file_id == withdrawn.id).values(submission_withdrawn_at=datetime.now(UTC)))
    db.commit()
    counts_sql = "SELECT event_id, list_entry_id, manual_element_id, file_count FROM public.submission_linked_file_counts(:id)"
    withdrawn_sql = "SELECT event_id, list_entry_id, manual_element_id FROM public.submission_withdrawn_elements(:id)"
    token = org["link"].token

    def state():
        counts, error = _probe_as_abgabebox(db, counts_sql, {"id": assignment.id}, link_token=token)
        assert error is None
        locked, error = _probe_as_abgabebox(db, withdrawn_sql, {"id": assignment.id}, link_token=token)
        assert error is None
        [element] = SubmissionService().get_assignment_elements(db, assignment)
        return (
            submission_upload_rules.load_rules(db, assignment, "manual").remaining,
            [tuple(row) for row in counts], [tuple(row) for row in locked], element.withdrawn_count,
        )

    assert state() == (0, [(None, None, None, 2)], [(None, None, None)], 1)

    _trash(db, user, gone, withdrawn)

    assert state() == (1, [(None, None, None, 1)], [], 0)


def test_trash_errors_name_no_file_the_account_may_not_manage(db):
    """Fehlertexte ohne Dateinamen: ohne Löschrecht derselbe Text wie für eine unbekannte ID."""
    from tests.test_photo_bulk_delete import _make_protocol_image

    tenant = make_tenant(db)
    photos_only = _user(db, tenant.id, permissions=frozenset({"photos.read", "photos.manage", "meetings.read"}))
    document = _make_file(db, tenant.id, "geheimer-bericht.pdf", content=b"%PDF-1.4 test", mime_type="application/pdf")
    protocol_file = _make_protocol_image(db, tenant.id)
    protocol_name = protocol_file.original_name
    db.commit()

    result = _trash(db, photos_only, document, protocol_file)
    unknown = files_routes.move_to_trash(FileTrashAction(file_ids=[uuid.uuid4()]), db, photos_only)

    assert result.file_ids == []
    assert result.errors[0] == unknown.errors[0] == file_trash_service.NOT_FOUND
    assert result.errors[1] == file_trash_service.NOT_DELETABLE_HERE
    assert not any("geheimer-bericht" in error or protocol_name in error for error in result.errors)


def test_release_all_pending_skips_trashed_photos(db):
    from app.services import photo_album_share_service

    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    keep = _make_file(db, tenant.id, "frei.png")
    gone = _make_file(db, tenant.id, "vorgemerkt-papierkorb.png")
    album = PhotoAlbum(tenant_id=tenant.id, name="Geteilt", kind="manual")
    db.add(album)
    db.flush()
    photo_album_service.add_items(db, album, [keep.public_id, gone.public_id], release=True)
    db.execute(PhotoAlbumItem.__table__.update().where(PhotoAlbumItem.album_id == album.id).values(share_pending=True))
    album_id, keep_id, gone_id = album.id, keep.public_id, gone.public_id
    db.commit()
    _trash(db, user, gone)

    assert photo_album_share_service.release_pending(db, album_id) == 1

    pending = dict(db.execute(select(PhotoAlbumItem.file_id, PhotoAlbumItem.share_pending).where(PhotoAlbumItem.album_id == album_id)).all())
    assert pending == {keep_id: False, gone_id: True}


def test_trashed_album_photo_behaves_like_an_unknown_id_for_best_and_remove(db):
    from app.schemas.files import PhotoAlbumItemBestUpdate, PhotoAlbumItemsUpdate

    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    gone = _make_file(db, tenant.id, "stern-papierkorb.png")
    album = PhotoAlbum(tenant_id=tenant.id, name="Sterne", kind="manual")
    db.add(album)
    db.flush()
    photo_album_service.add_items(db, album, [gone.public_id], release=True)
    album_id, gone_id = album.id, gone.public_id
    db.commit()
    _trash(db, user, gone)

    for call, status in (
        (lambda: files_routes.set_file_best_everywhere(gone_id, PhotoAlbumItemBestUpdate(best_override="include"), db, user), 422),
        (lambda: files_routes.set_album_item_best(album_id, gone_id, PhotoAlbumItemBestUpdate(best_override="include"), db, user), 404),
        (lambda: files_routes.remove_album_items(album_id, PhotoAlbumItemsUpdate(file_ids=[gone_id]), db, user), 404),
    ):
        with pytest.raises(HTTPException) as exc_info:
            call()
        assert exc_info.value.status_code == status

    assert photo_album_service.remove_items(db, db.get(PhotoAlbum, album_id), [gone_id]) == 0
    assert photo_album_service.set_best_override_everywhere(db, service, tenant.id, gone_id, "include") == 0
    [item] = db.scalars(select(PhotoAlbumItem).where(PhotoAlbumItem.album_id == album_id))
    assert item.file_id == gone_id and item.best_override is None


def _capture_errors(monkeypatch) -> list[int | None]:
    """Fehlerprotokoll-Aufrufe mitschreiben (tenant_id je Aufruf). Nicht über system_error_log:
    das Rollback im Fehlerzweig verwirft in der Test-Session auch die Testdaten (Mandant)."""
    from app.core import error_log

    calls: list[int | None] = []
    monkeypatch.setattr(error_log, "record_system_error", lambda db, *, exc, tenant_id=None, **kwargs: calls.append(tenant_id))
    return calls


def test_purge_job_counts_a_deleted_file_as_purged_when_after_commit_fails(db, monkeypatch):
    from app.services.file_eraser import FileEraser

    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    old = _make_file(db, tenant.id, "nacharbeit.png")
    old_pk, tenant_id = old.id, tenant.id
    db.commit()
    _trash(db, user, old)
    db.execute(StoredFile.__table__.update().where(StoredFile.id == old_pk).values(deleted_at=datetime.now(UTC) - TRASH_RETENTION - timedelta(hours=1)))
    db.commit()

    def broken(self, session):
        raise RuntimeError("Vorschaubild weg")

    monkeypatch.setattr(FileEraser, "after_commit", broken)
    errors = _capture_errors(monkeypatch)
    result = file_trash_service.purge_expired(db)

    assert result["purged"] >= 1 and result["failed"] == 0
    assert tenant_id in errors


def test_purge_of_expired_orphans_logs_errors_with_the_tenant(db, monkeypatch):
    from app.services.file_eraser import FileEraser

    tenant = make_tenant(db)
    tenant_id = tenant.id
    orphan = StoredFile(
        tenant_id=tenant.id, original_name="clip.mov", mime_type="video/quicktime", storage_path=f"uploads/{uuid.uuid4().hex}.mov",
        deleted_at=datetime.now(UTC) - TRASH_RETENTION - timedelta(hours=1),
    )
    db.add(orphan)
    db.commit()

    def broken(self, session, stored_file, **kwargs):
        raise RuntimeError("Speicher nicht erreichbar")

    monkeypatch.setattr(FileEraser, "erase", broken)
    errors = _capture_errors(monkeypatch)
    result = file_trash_service.purge_expired(db)

    assert result["orphans"] == 0
    assert errors == [tenant_id]
