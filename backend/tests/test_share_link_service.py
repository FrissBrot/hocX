"""Tests for share_link_service.py: token-based public download links, either a fixed file
selection (share_link_file) or a "live" link onto an album's current contents."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.entities import PhotoAlbum, PhotoAlbumItem, ShareLinkFile, StoredFile
from app.services import share_link_service
from tests.factories import make_tenant


def _make_file(db, tenant_id: int, name: str = "foto.png") -> StoredFile:
    stored_file = StoredFile(tenant_id=tenant_id, original_name=name, mime_type="image/png", storage_path=f"uploads/{name}")
    db.add(stored_file)
    db.flush()
    return stored_file


def test_create_for_files_rejects_empty_selection(db):
    tenant = make_tenant(db)
    with pytest.raises(share_link_service.ShareLinkError):
        share_link_service.create_for_files(db, tenant_id=tenant.id, name="Leer", file_ids=[], expires_at=None, created_by=None)


def test_create_for_files_rejects_more_than_200(db):
    tenant = make_tenant(db)
    files = [_make_file(db, tenant.id, f"f{i}.png") for i in range(201)]
    with pytest.raises(share_link_service.ShareLinkError):
        share_link_service.create_for_files(
            db, tenant_id=tenant.id, name="Zu viele", file_ids=[f.public_id for f in files], expires_at=None, created_by=None
        )


def test_create_for_files_persists_the_selection(db):
    tenant = make_tenant(db)
    a = _make_file(db, tenant.id, "a.png")
    b = _make_file(db, tenant.id, "b.png")

    link = share_link_service.create_for_files(
        db, tenant_id=tenant.id, name="Zwei Fotos", file_ids=[a.public_id, b.public_id], expires_at=None, created_by=None
    )

    assert link.tenant_id == tenant.id
    assert link.album_id is None
    assert link.token
    file_ids = {row.file_id for row in db.query(ShareLinkFile).filter_by(share_link_id=link.id)}
    assert file_ids == {a.public_id, b.public_id}


def test_create_for_album_is_live_and_carries_no_fixed_selection(db):
    tenant = make_tenant(db)
    album = PhotoAlbum(tenant_id=tenant.id, name="Album", kind="manual")
    db.add(album)
    db.flush()

    link = share_link_service.create_for_album(db, tenant_id=tenant.id, name="Album-Link", album=album, expires_at=None, created_by=None)

    assert link.album_id == album.id
    assert db.query(ShareLinkFile).filter_by(share_link_id=link.id).count() == 0


def test_file_ids_for_link_reflects_current_album_contents(db):
    """A live album link must show newly added items too, not just what was there at
    creation time - unlike the fixed file_ids case."""
    tenant = make_tenant(db)
    album = PhotoAlbum(tenant_id=tenant.id, name="Album", kind="manual")
    db.add(album)
    db.flush()
    link = share_link_service.create_for_album(db, tenant_id=tenant.id, name="Album-Link", album=album, expires_at=None, created_by=None)
    assert share_link_service.file_ids_for_link(db, link) == []

    photo = _make_file(db, tenant.id, "neu.png")
    db.add(PhotoAlbumItem(album_id=album.id, file_id=photo.public_id))
    db.commit()

    assert share_link_service.file_ids_for_link(db, link) == [photo.public_id]


def test_resolve_active_returns_none_for_unknown_token(db):
    assert share_link_service.resolve_active(db, "does-not-exist") is None


def test_resolve_active_returns_none_once_revoked(db):
    tenant = make_tenant(db)
    a = _make_file(db, tenant.id)
    link = share_link_service.create_for_files(db, tenant_id=tenant.id, name="X", file_ids=[a.public_id], expires_at=None, created_by=None)

    share_link_service.revoke(db, link)

    assert share_link_service.resolve_active(db, link.token) is None


def test_resolve_active_returns_none_once_expired(db):
    tenant = make_tenant(db)
    a = _make_file(db, tenant.id)
    link = share_link_service.create_for_files(
        db, tenant_id=tenant.id, name="X", file_ids=[a.public_id], expires_at=datetime.now(UTC) - timedelta(days=1), created_by=None
    )

    assert share_link_service.resolve_active(db, link.token) is None


def test_resolve_active_returns_the_link_before_expiry(db):
    tenant = make_tenant(db)
    a = _make_file(db, tenant.id)
    link = share_link_service.create_for_files(
        db, tenant_id=tenant.id, name="X", file_ids=[a.public_id], expires_at=datetime.now(UTC) + timedelta(days=1), created_by=None
    )

    resolved = share_link_service.resolve_active(db, link.token)

    assert resolved is not None
    assert resolved.id == link.id


def test_list_for_tenant_is_scoped_and_reports_counts(db):
    tenant_a = make_tenant(db)
    tenant_b = make_tenant(db)
    file_a = _make_file(db, tenant_a.id)
    file_b = _make_file(db, tenant_b.id)
    share_link_service.create_for_files(db, tenant_id=tenant_a.id, name="A-Link", file_ids=[file_a.public_id], expires_at=None, created_by=None)
    share_link_service.create_for_files(db, tenant_id=tenant_b.id, name="B-Link", file_ids=[file_b.public_id], expires_at=None, created_by=None)

    rows = share_link_service.list_for_tenant(db, tenant_a.id)

    assert len(rows) == 1
    assert rows[0].link.name == "A-Link"
    assert rows[0].file_count == 1
    assert rows[0].album_name is None


def test_status_for_reflects_active_expired_and_revoked(db):
    tenant = make_tenant(db)
    a = _make_file(db, tenant.id)
    active = share_link_service.create_for_files(db, tenant_id=tenant.id, name="Aktiv", file_ids=[a.public_id], expires_at=None, created_by=None)
    expired = share_link_service.create_for_files(
        db, tenant_id=tenant.id, name="Abgelaufen", file_ids=[a.public_id], expires_at=datetime.now(UTC) - timedelta(hours=1), created_by=None
    )
    revoked = share_link_service.create_for_files(db, tenant_id=tenant.id, name="Widerrufen", file_ids=[a.public_id], expires_at=None, created_by=None)
    share_link_service.revoke(db, revoked)

    assert share_link_service.status_for(active) == "active"
    assert share_link_service.status_for(expired) == "expired"
    assert share_link_service.status_for(revoked) == "revoked"
