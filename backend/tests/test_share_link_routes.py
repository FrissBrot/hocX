"""Route-level tests for share_links.py (authenticated management) and public_share.py (the
token-authenticated public download page) - routes are called as plain callables, same
convention as test_files_overview.py."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.api.routes import public_share as public_share_routes
from app.api.routes import share_links as share_links_routes
from app.core.config import settings
from app.models.entities import GalleryImage, PhotoAlbum, PhotoAlbumItem, StoredFile
from app.schemas.files import ShareLinkCreate
from tests.factories import make_current_user, make_tenant


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "storage" / "uploads"))


def _make_file(db, tenant_id: int, name: str = "foto.png", content: bytes = b"fake-bytes") -> StoredFile:
    """A direct-upload ("gallery_upload") origin - create_share_link's file_ids validation
    goes through FileService.list_tenant_files, which only ever surfaces files joined to one
    of the four known origins (see StoredFileRepository._files_overview_branches); a bare
    StoredFile row with no such join would never validate."""
    (public_share_routes.Path(settings.storage_root)).mkdir(parents=True, exist_ok=True)
    (public_share_routes.Path(settings.storage_root) / name).write_bytes(content)
    stored_file = StoredFile(tenant_id=tenant_id, original_name=name, mime_type="image/png", storage_path=name)
    db.add(stored_file)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=stored_file.id))
    db.flush()
    return stored_file


class _FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host


class _FakeRequest:
    """Duck-typed fastapi.Request stand-in - public_share.py only reads .headers.get(...) and
    .client.host (see its _client_ip), matching test_auth_access.py's _FakeRequest."""

    def __init__(self) -> None:
        self.client = _FakeClient(f"198.51.100.{uuid.uuid4().hex[:6]}")
        self.headers: dict[str, str] = {}


# --- share_links.py (authenticated management) ------------------------------------------


def test_create_share_link_requires_exactly_one_of_files_or_album(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")

    with pytest.raises(HTTPException) as exc_info:
        share_links_routes.create_share_link(ShareLinkCreate(name="X"), db, user)
    assert exc_info.value.status_code == 422

    a = _make_file(db, tenant.id)
    album = PhotoAlbum(tenant_id=tenant.id, name="Album", kind="manual")
    db.add(album)
    db.flush()
    with pytest.raises(HTTPException) as exc_info:
        share_links_routes.create_share_link(ShareLinkCreate(name="X", file_ids=[a.public_id], album_id=album.id), db, user)
    assert exc_info.value.status_code == 422


def test_create_share_link_rejects_a_foreign_file_id(db):
    tenant = make_tenant(db)
    other_tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    foreign_file = _make_file(db, other_tenant.id)

    with pytest.raises(HTTPException) as exc_info:
        share_links_routes.create_share_link(ShareLinkCreate(name="X", file_ids=[foreign_file.public_id]), db, user)
    assert exc_info.value.status_code == 404


def test_create_share_link_for_files_returns_the_relative_share_url(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    a = _make_file(db, tenant.id)

    result = share_links_routes.create_share_link(ShareLinkCreate(name="Mein Link", file_ids=[a.public_id]), db, user)

    assert result.file_count == 1
    assert result.album_name is None
    assert result.status == "active"
    assert result.url.startswith("/share/")


def test_create_share_link_rejects_an_album_the_tenant_cannot_see(db):
    owner = make_tenant(db)
    other = make_tenant(db)
    user = make_current_user(other.id, role="writer")
    album = PhotoAlbum(tenant_id=owner.id, name="Fremdes Album", kind="manual")
    db.add(album)
    db.flush()

    with pytest.raises(HTTPException) as exc_info:
        share_links_routes.create_share_link(ShareLinkCreate(name="X", album_id=album.id), db, user)
    assert exc_info.value.status_code == 404


def test_list_share_links_is_scoped_to_the_current_tenant(db):
    tenant_a = make_tenant(db)
    tenant_b = make_tenant(db)
    user_a = make_current_user(tenant_a.id, role="writer")
    user_b = make_current_user(tenant_b.id, role="writer")
    share_links_routes.create_share_link(ShareLinkCreate(name="A-Link", file_ids=[_make_file(db, tenant_a.id).public_id]), db, user_a)
    share_links_routes.create_share_link(ShareLinkCreate(name="B-Link", file_ids=[_make_file(db, tenant_b.id).public_id]), db, user_b)

    result = share_links_routes.list_share_links(db, user_a)

    assert [row.name for row in result] == ["A-Link"]


def test_revoke_share_link_of_another_tenant_is_not_found(db):
    tenant = make_tenant(db)
    other_tenant = make_tenant(db)
    owner = make_current_user(tenant.id, role="writer")
    other_user = make_current_user(other_tenant.id, role="writer")
    created = share_links_routes.create_share_link(ShareLinkCreate(name="X", file_ids=[_make_file(db, tenant.id).public_id]), db, owner)

    with pytest.raises(HTTPException) as exc_info:
        share_links_routes.revoke_share_link(created.id, db, other_user)
    assert exc_info.value.status_code == 404


def test_revoke_share_link_marks_it_revoked_and_removes_public_access(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    created = share_links_routes.create_share_link(ShareLinkCreate(name="X", file_ids=[_make_file(db, tenant.id).public_id]), db, user)
    token = created.url.removeprefix("/share/")

    share_links_routes.revoke_share_link(created.id, db, user)

    updated = next(row for row in share_links_routes.list_share_links(db, user) if row.id == created.id)
    assert updated.status == "revoked"
    with pytest.raises(HTTPException) as exc_info:
        public_share_routes.get_public_share(token, _FakeRequest(), db)
    assert exc_info.value.status_code == 404


# --- public_share.py (public, token-authenticated) ---------------------------------------


def test_get_public_share_404s_for_an_unknown_token(db):
    with pytest.raises(HTTPException) as exc_info:
        public_share_routes.get_public_share("no-such-token", _FakeRequest(), db)
    assert exc_info.value.status_code == 404


def test_get_public_share_lists_the_linked_files(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    a = _make_file(db, tenant.id, "a.png")
    created = share_links_routes.create_share_link(ShareLinkCreate(name="Zwei Fotos", file_ids=[a.public_id]), db, user)
    token = created.url.removeprefix("/share/")

    result = public_share_routes.get_public_share(token, _FakeRequest(), db)

    assert result.name == "Zwei Fotos"
    assert [f.id for f in result.files] == [a.public_id]
    assert result.files[0].is_image is True
    assert result.download_all_url is None  # only one file


def test_get_public_share_excludes_files_infected_after_the_link_was_created(db):
    """A file can only be added to a link while still clean (create_share_link validates
    against list_tenant_files, which already excludes infected rows) - but a later re-scan
    can still flag it infected afterwards, and the public page must stop serving it."""
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    clean = _make_file(db, tenant.id, "clean.png")
    later_infected = _make_file(db, tenant.id, "infected.png")
    created = share_links_routes.create_share_link(
        ShareLinkCreate(name="Gemischt", file_ids=[clean.public_id, later_infected.public_id]), db, user
    )
    token = created.url.removeprefix("/share/")

    later_infected.scan_status = "infected"
    db.commit()

    result = public_share_routes.get_public_share(token, _FakeRequest(), db)

    assert [f.id for f in result.files] == [clean.public_id]


def test_get_public_share_for_an_album_link_reflects_live_contents(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    album = PhotoAlbum(tenant_id=tenant.id, name="Album", kind="manual")
    db.add(album)
    db.flush()
    created = share_links_routes.create_share_link(ShareLinkCreate(name="Album-Link", album_id=album.id), db, user)
    token = created.url.removeprefix("/share/")

    assert public_share_routes.get_public_share(token, _FakeRequest(), db).files == []

    photo = _make_file(db, tenant.id, "neu.png")
    db.add(PhotoAlbumItem(album_id=album.id, file_id=photo.public_id))
    db.commit()

    result = public_share_routes.get_public_share(token, _FakeRequest(), db)
    assert [f.id for f in result.files] == [photo.public_id]


def test_download_public_share_file_rejects_a_file_outside_the_link(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    a = _make_file(db, tenant.id, "a.png")
    outsider = _make_file(db, tenant.id, "b.png")
    created = share_links_routes.create_share_link(ShareLinkCreate(name="X", file_ids=[a.public_id]), db, user)
    token = created.url.removeprefix("/share/")

    with pytest.raises(HTTPException) as exc_info:
        public_share_routes.download_public_share_file(token, outsider.public_id, _FakeRequest(), db)
    assert exc_info.value.status_code == 404


def test_download_public_share_file_serves_the_file_on_disk(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    a = _make_file(db, tenant.id, "a.png", content=b"echte-bytes")
    created = share_links_routes.create_share_link(ShareLinkCreate(name="X", file_ids=[a.public_id]), db, user)
    token = created.url.removeprefix("/share/")

    response = public_share_routes.download_public_share_file(token, a.public_id, _FakeRequest(), db)

    assert response.path.name == "a.png"


def test_download_public_share_all_builds_a_zip_for_multiple_files(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    a = _make_file(db, tenant.id, "a.png")
    b = _make_file(db, tenant.id, "b.png")
    created = share_links_routes.create_share_link(ShareLinkCreate(name="X", file_ids=[a.public_id, b.public_id]), db, user)
    token = created.url.removeprefix("/share/")

    response = public_share_routes.download_public_share_all(token, _FakeRequest(), db)

    assert response.path.suffix == ".zip"
    assert response.path.exists()


def test_public_share_endpoints_reject_an_expired_link(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    a = _make_file(db, tenant.id)
    created = share_links_routes.create_share_link(
        ShareLinkCreate(name="X", file_ids=[a.public_id], expires_at=datetime.now(UTC) - timedelta(days=1)), db, user
    )
    token = created.url.removeprefix("/share/")

    with pytest.raises(HTTPException) as exc_info:
        public_share_routes.get_public_share(token, _FakeRequest(), db)
    assert exc_info.value.status_code == 404
