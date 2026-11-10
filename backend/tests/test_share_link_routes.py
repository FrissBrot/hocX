"""Route-level tests for share_links.py (authenticated management) and public_share.py (the
token-authenticated public download page) - routes are called as plain callables, same
convention as test_files_overview.py."""

import io
import uuid
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from PIL import Image

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


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 3), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _make_file(db, tenant_id: int, name: str = "foto.png", content: bytes | None = None, mime_type: str = "image/png") -> StoredFile:
    """A direct-upload ("gallery_upload") origin - create_share_link's file_ids validation
    goes through FileService.list_tenant_files, which only ever surfaces files joined to one
    of the four known origins (see StoredFileRepository._files_overview_branches); a bare
    StoredFile row with no such join would never validate."""
    (public_share_routes.Path(settings.storage_root)).mkdir(parents=True, exist_ok=True)
    (public_share_routes.Path(settings.storage_root) / name).write_bytes(_png_bytes() if content is None else content)
    stored_file = StoredFile(tenant_id=tenant_id, original_name=name, mime_type=mime_type, storage_path=name)
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
    assert result.tenant_name == tenant.name
    assert [f.id for f in result.files] == [a.public_id]
    assert result.files[0].is_image is True
    assert result.files[0].view_url.endswith(f"/files/{a.public_id}/view")
    # "Alle herunterladen" ist immer ein ZIP, auch bei nur einer Datei.
    assert result.download_all_url == f"/api/public/share/{token}/download"


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
    a = _make_file(db, tenant.id, "a.png")
    # Alle Metadaten geteilt -> das Original wird unveraendert ausgeliefert.
    created = share_links_routes.create_share_link(
        ShareLinkCreate(name="X", file_ids=[a.public_id], share_location=True, share_capture_date=True, share_camera=True), db, user
    )
    token = created.url.removeprefix("/share/")

    response = public_share_routes.download_public_share_file(token, a.public_id, _FakeRequest(), db)

    assert response.path.name == "a.png"
    assert 'filename="a.png"' in response.headers["content-disposition"]


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


def test_download_public_share_all_zips_even_a_single_file(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    a = _make_file(db, tenant.id, "a.png")
    created = share_links_routes.create_share_link(ShareLinkCreate(name="X", file_ids=[a.public_id]), db, user)
    token = created.url.removeprefix("/share/")

    response = public_share_routes.download_public_share_all(token, _FakeRequest(), db)

    assert response.path.suffix == ".zip"
    assert response.media_type == "application/zip"


def test_download_public_share_all_is_not_used_up_by_loading_the_gallery_thumbnails(db):
    """Regression: alle Endpunkte teilten sich einen Zaehler pro IP - eine Galerie mit mehr als
    20 Vorschaubildern brauchte das ZIP-Limit schon beim Seitenaufruf auf, und "Alle
    herunterladen" lieferte ein 429-JSON (vom Browser als fehlgeschlagene download.json
    angezeigt) statt des ZIPs."""
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    a = _make_file(db, tenant.id, "a.png")
    created = share_links_routes.create_share_link(ShareLinkCreate(name="X", file_ids=[a.public_id]), db, user)
    token = created.url.removeprefix("/share/")
    request = _FakeRequest()

    public_share_routes.get_public_share(token, request, db)
    for _ in range(30):
        public_share_routes.get_public_share_thumbnail(token, a.public_id, request, db)
    response = public_share_routes.download_public_share_all(token, request, db)

    assert response.media_type == "application/zip"


def test_public_share_thumbnails_cover_an_album_with_several_hundred_photos(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    a = _make_file(db, tenant.id, "a.png")
    created = share_links_routes.create_share_link(ShareLinkCreate(name="X", file_ids=[a.public_id]), db, user)
    token = created.url.removeprefix("/share/")
    request = _FakeRequest()

    for _ in range(500):
        public_share_routes.get_public_share_thumbnail(token, a.public_id, request, db)


def test_download_public_share_all_limits_the_zip_to_the_selection(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    a = _make_file(db, tenant.id, "a.png")
    b = _make_file(db, tenant.id, "b.png")
    outsider = _make_file(db, tenant.id, "c.png")
    created = share_links_routes.create_share_link(ShareLinkCreate(name="X", file_ids=[a.public_id, b.public_id]), db, user)
    token = created.url.removeprefix("/share/")

    response = public_share_routes.download_public_share_all(token, _FakeRequest(), db, ids=f"{b.public_id},{outsider.public_id}")

    with zipfile.ZipFile(response.path) as archive:
        assert archive.namelist() == ["b.png"]

    with pytest.raises(HTTPException) as exc_info:
        public_share_routes.download_public_share_all(token, _FakeRequest(), db, ids="kein-uuid")
    assert exc_info.value.status_code == 422


def test_view_public_share_file_serves_only_browser_safe_images_inline(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    png = _make_file(db, tenant.id, "a.png")
    svg = _make_file(db, tenant.id, "b.svg")
    svg.mime_type = "image/svg+xml"
    db.flush()
    created = share_links_routes.create_share_link(ShareLinkCreate(name="X", file_ids=[png.public_id, svg.public_id]), db, user)
    token = created.url.removeprefix("/share/")

    response = public_share_routes.view_public_share_file(token, png.public_id, _FakeRequest(), db)
    assert response.media_type == "image/png"
    assert Image.open(response.path).size == (4, 3)
    assert "attachment" not in response.headers.get("content-disposition", "")

    with pytest.raises(HTTPException) as exc_info:
        public_share_routes.view_public_share_file(token, svg.public_id, _FakeRequest(), db)
    assert exc_info.value.status_code == 404


def test_get_public_share_reports_total_size_and_date_range(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    a = _make_file(db, tenant.id, "a.png")
    b = _make_file(db, tenant.id, "b.png")
    a.file_size_bytes, b.file_size_bytes = 100, 250
    a.exif_taken_at = datetime(2026, 7, 14, 10, tzinfo=UTC)
    b.exif_taken_at = datetime(2026, 7, 28, 18, tzinfo=UTC)
    db.flush()
    created = share_links_routes.create_share_link(ShareLinkCreate(name="X", file_ids=[a.public_id, b.public_id]), db, user)
    token = created.url.removeprefix("/share/")

    result = public_share_routes.get_public_share(token, _FakeRequest(), db)

    assert result.total_size_bytes == 350
    assert result.date_from == a.exif_taken_at
    assert result.date_to == b.exif_taken_at


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


@pytest.mark.parametrize("endpoint", ["thumbnail", "view", "download"])
def test_public_share_file_endpoints_reject_files_of_other_links_and_tenants(db, endpoint):
    """Ein Token oeffnet nur die eigenen Dateien - weder Dateien eines anderen Links desselben
    Mandanten noch Dateien eines fremden Mandanten, auch wenn deren ID bekannt ist."""
    tenant = make_tenant(db)
    other_tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    other_user = make_current_user(other_tenant.id, role="writer")
    mine = _make_file(db, tenant.id, "mine.png")
    sibling = _make_file(db, tenant.id, "sibling.png")
    foreign = _make_file(db, other_tenant.id, "foreign.png")
    created = share_links_routes.create_share_link(ShareLinkCreate(name="X", file_ids=[mine.public_id]), db, user)
    share_links_routes.create_share_link(ShareLinkCreate(name="Y", file_ids=[sibling.public_id]), db, user)
    share_links_routes.create_share_link(ShareLinkCreate(name="Z", file_ids=[foreign.public_id]), db, other_user)
    token = created.url.removeprefix("/share/")
    route = {
        "thumbnail": public_share_routes.get_public_share_thumbnail,
        "view": public_share_routes.view_public_share_file,
        "download": public_share_routes.download_public_share_file,
    }[endpoint]

    for outsider in (sibling, foreign):
        with pytest.raises(HTTPException) as exc_info:
            route(token, outsider.public_id, _FakeRequest(), db)
        assert exc_info.value.status_code == 404

    with pytest.raises(HTTPException) as exc_info:
        public_share_routes.download_public_share_all(token, _FakeRequest(), db, ids=f"{sibling.public_id},{foreign.public_id}")
    assert exc_info.value.status_code == 404


# --- Foto-Metadaten (share_location / share_capture_date / share_camera) -------------------


def _jpeg_with_metadata() -> bytes:
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation
    exif[0x010F] = "Canon"
    exif[0x0132] = "2026:07:14 10:00:00"
    exif[0x8825] = {1: "N", 2: (47.0, 3.0, 0.0), 3: "E", 4: (8.0, 15.0, 0.0)}
    exif[0x8769] = {0x9003: "2026:07:14 10:00:00", 0xA431: "SERIAL123"}
    buffer = io.BytesIO()
    Image.new("RGB", (8, 6), "white").save(buffer, format="JPEG", exif=exif.tobytes())
    return buffer.getvalue()


def test_create_share_link_stores_the_metadata_choice_with_private_defaults(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    a = _make_file(db, tenant.id, "a.png")

    default = share_links_routes.create_share_link(ShareLinkCreate(name="X", file_ids=[a.public_id]), db, user)
    custom = share_links_routes.create_share_link(
        ShareLinkCreate(name="Y", file_ids=[a.public_id], share_location=True, share_capture_date=False), db, user
    )

    assert (default.share_location, default.share_capture_date, default.share_camera) == (False, True, False)
    assert (custom.share_location, custom.share_capture_date, custom.share_camera) == (True, False, False)


def test_public_downloads_strip_the_metadata_the_link_does_not_share(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    photo = _make_file(db, tenant.id, "foto.jpg", content=_jpeg_with_metadata(), mime_type="image/jpeg")
    other = _make_file(db, tenant.id, "b.png")
    created = share_links_routes.create_share_link(ShareLinkCreate(name="X", file_ids=[photo.public_id, other.public_id]), db, user)
    token = created.url.removeprefix("/share/")

    single = public_share_routes.download_public_share_file(token, photo.public_id, _FakeRequest(), db)
    view = public_share_routes.view_public_share_file(token, photo.public_id, _FakeRequest(), db)
    archive_response = public_share_routes.download_public_share_all(token, _FakeRequest(), db)
    with zipfile.ZipFile(archive_response.path) as archive:
        zipped = archive.read("foto.jpg")

    for content in (single.path.read_bytes(), view.path.read_bytes(), zipped):
        exif = Image.open(io.BytesIO(content)).getexif()
        assert 0x8825 not in exif  # kein Standort
        assert 0x010F not in exif  # keine Kamera
        assert exif.get(0x0132) == "2026:07:14 10:00:00"  # Datum ist standardmaessig geteilt
        assert exif.get(0x0112) == 6  # Ausrichtung bleibt immer
        assert 0xA431 not in exif.get_ifd(0x8769)
    assert 'filename="foto.jpg"' in single.headers["content-disposition"]


def test_public_share_hides_capture_dates_when_the_link_does_not_share_them(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    a = _make_file(db, tenant.id, "a.png")
    a.exif_taken_at = datetime(2026, 7, 14, 10, tzinfo=UTC)
    db.flush()
    created = share_links_routes.create_share_link(ShareLinkCreate(name="X", file_ids=[a.public_id], share_capture_date=False), db, user)
    token = created.url.removeprefix("/share/")

    result = public_share_routes.get_public_share(token, _FakeRequest(), db)

    assert result.date_from is None and result.date_to is None
    assert result.files[0].taken_at is None
