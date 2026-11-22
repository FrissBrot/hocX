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
from app.core.storage import MAIN, get_object_store
from app.models.document_entities import Document, DocumentExtraction, DocumentFile, DocumentVersion
from app.models.entities import GalleryImage, PhotoAlbum, PhotoAlbumItem, StoredFile
from app.schemas.files import ShareLinkCreate
from tests.factories import make_current_user, make_tenant
from tests.image_fixtures import response_bytes


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
    key = f"uploads/tenant-{tenant_id}/share/{name}"
    get_object_store().put_bytes(db, MAIN, key, _png_bytes() if content is None else content)
    stored_file = StoredFile(tenant_id=tenant_id, original_name=name, mime_type=mime_type, storage_path=key)
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


def test_create_share_link_without_a_name_gets_one(db):
    """Der Name ist freiwillig: eine Datei heisst wie sie selbst, mehrere werden gezählt, ein Album
    behält seinen Namen. Zu lang bleibt abgelehnt."""
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    a = _make_file(db, tenant.id, name="lager.png")
    b = _make_file(db, tenant.id, name="zelt.png")
    album = PhotoAlbum(tenant_id=tenant.id, name="Sommerlager", kind="manual")
    db.add(album)
    db.flush()

    assert share_links_routes.create_share_link(ShareLinkCreate(file_ids=[a.public_id]), db, user).name == "lager.png"
    assert share_links_routes.create_share_link(ShareLinkCreate(name="  ", file_ids=[a.public_id, b.public_id]), db, user).name == "2 Dateien"
    assert share_links_routes.create_share_link(ShareLinkCreate(album_id=album.id), db, user).name == "Sommerlager"
    with pytest.raises(HTTPException) as too_long:
        share_links_routes.create_share_link(ShareLinkCreate(name="x" * 121, file_ids=[a.public_id]), db, user)
    assert too_long.value.status_code == 422


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


def test_download_public_share_file_serves_the_stored_file(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    a = _make_file(db, tenant.id, "a.png")
    # Alle Metadaten geteilt -> das Original wird unveraendert ausgeliefert.
    created = share_links_routes.create_share_link(
        ShareLinkCreate(name="X", file_ids=[a.public_id], share_location=True, share_capture_date=True, share_camera=True), db, user
    )
    token = created.url.removeprefix("/share/")

    response = public_share_routes.download_public_share_file(token, a.public_id, _FakeRequest(), db)

    assert response_bytes(response) == _png_bytes()
    assert 'filename="a.png"' in response.headers["content-disposition"]


def test_download_public_share_all_builds_a_zip_for_multiple_files(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    a = _make_file(db, tenant.id, "a.png")
    b = _make_file(db, tenant.id, "b.png")
    created = share_links_routes.create_share_link(ShareLinkCreate(name="X", file_ids=[a.public_id, b.public_id]), db, user)
    token = created.url.removeprefix("/share/")

    response = public_share_routes.download_public_share_all(token, _FakeRequest(), db)

    assert response.media_type == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response_bytes(response))) as archive:
        assert sorted(archive.namelist()) == ["a.png", "b.png"]


def test_download_public_share_all_zips_even_a_single_file(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    a = _make_file(db, tenant.id, "a.png")
    created = share_links_routes.create_share_link(ShareLinkCreate(name="X", file_ids=[a.public_id]), db, user)
    token = created.url.removeprefix("/share/")

    response = public_share_routes.download_public_share_all(token, _FakeRequest(), db)

    assert response.media_type == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response_bytes(response))) as archive:
        assert archive.namelist() == ["a.png"]


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

    with zipfile.ZipFile(io.BytesIO(response_bytes(response))) as archive:
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
    assert Image.open(io.BytesIO(response_bytes(response))).size == (4, 3)
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


def _attach_document_preview(db, original: StoredFile, *, preview_tenant_id: int | None = None, pages: int | None = 3) -> StoredFile:
    """Wie nach der Dokument-Pipeline: Version mit Original, erzeugtem PNG der ersten Seite und
    gelesener Seitenzahl."""
    document = Document(tenant_id=original.tenant_id, source_kind="upload", display_name=original.original_name)
    db.add(document)
    db.flush()
    version = DocumentVersion(document_id=document.id, version_number=1)
    db.add(version)
    db.flush()
    document.current_version_id = version.id
    tenant_id = preview_tenant_id or original.tenant_id
    key = f"documents/tenant-{tenant_id}/{uuid.uuid4().hex}-vorschau.png"
    get_object_store().put_bytes(db, MAIN, key, _png_bytes())
    preview = StoredFile(tenant_id=tenant_id, original_name="vorschau.png", mime_type="image/png", storage_path=key)
    db.add(preview)
    db.flush()
    db.add(DocumentFile(document_version_id=version.id, stored_file_id=original.id, role="original"))
    db.add(DocumentFile(document_version_id=version.id, stored_file_id=preview.id, role="preview", is_generated=True))
    if pages is not None:
        db.add(DocumentExtraction(document_version_id=version.id, status="ready", page_count=pages))
    db.flush()
    return preview


def test_public_share_shows_the_first_page_of_processed_documents(db):
    """Dokumente bekommen auf der öffentlichen Seite die Vorschau der ersten Seite und ihre
    Seitenzahl; eine Datei ohne Pipeline-Ergebnis bleibt ohne Vorschau (Typ-Kachel)."""
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    pdf = _make_file(db, tenant.id, "bericht.pdf", content=b"%PDF-1.4 test", mime_type="application/pdf")
    plain = _make_file(db, tenant.id, "liste.csv", content=b"a;b\n", mime_type="text/csv")
    _attach_document_preview(db, pdf, pages=3)
    created = share_links_routes.create_share_link(ShareLinkCreate(name="Dokumente", file_ids=[pdf.public_id, plain.public_id]), db, user)
    token = created.url.removeprefix("/share/")

    result = public_share_routes.get_public_share(token, _FakeRequest(), db)
    by_name = {f.original_name: f for f in result.files}
    assert by_name["bericht.pdf"].thumbnail_url == f"/api/public/share/{token}/files/{pdf.public_id}/thumbnail"
    assert by_name["bericht.pdf"].page_count == 3
    # Keine Lightbox-Grossansicht für Nicht-Bilder - die Vorschau ist kein "view".
    assert by_name["bericht.pdf"].view_url is None
    assert by_name["liste.csv"].thumbnail_url is None and by_name["liste.csv"].page_count is None

    response = public_share_routes.get_public_share_thumbnail(token, pdf.public_id, _FakeRequest(), db)
    assert response.media_type == "image/png"
    assert response_bytes(response) == _png_bytes()

    with pytest.raises(HTTPException) as exc_info:
        public_share_routes.get_public_share_thumbnail(token, plain.public_id, _FakeRequest(), db)
    assert exc_info.value.status_code == 404


def test_public_share_ignores_a_document_preview_of_another_tenant(db):
    """Zeigt eine (fehlerhafte) Vorschau-Zuordnung auf eine Datei eines fremden Mandanten,
    liefert der öffentliche Link sie nicht aus."""
    tenant = make_tenant(db)
    other_tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    pdf = _make_file(db, tenant.id, "bericht.pdf", content=b"%PDF-1.4 test", mime_type="application/pdf")
    _attach_document_preview(db, pdf, preview_tenant_id=other_tenant.id)
    created = share_links_routes.create_share_link(ShareLinkCreate(name="X", file_ids=[pdf.public_id]), db, user)
    token = created.url.removeprefix("/share/")

    result = public_share_routes.get_public_share(token, _FakeRequest(), db)
    assert result.files[0].thumbnail_url is None
    with pytest.raises(HTTPException) as exc_info:
        public_share_routes.get_public_share_thumbnail(token, pdf.public_id, _FakeRequest(), db)
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
    with zipfile.ZipFile(io.BytesIO(response_bytes(archive_response))) as archive:
        zipped = archive.read("foto.jpg")

    for content in (response_bytes(single), response_bytes(view), zipped):
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


# --- Audit Dateien/Fotos ------------------------------------------------------------------


def test_create_share_link_rejects_more_than_200_files_with_422_not_404(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    ids = [uuid.uuid4() for _ in range(201)]

    with pytest.raises(HTTPException) as exc_info:
        share_links_routes.create_share_link(ShareLinkCreate(name="Zu viele", file_ids=ids), db, user)
    assert exc_info.value.status_code == 422


def test_create_share_link_rejects_blocked_file(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    blocked = _make_file(db, tenant.id, "gesperrt.png")
    blocked.scan_status = "error"
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        share_links_routes.create_share_link(ShareLinkCreate(name="Gesperrt", file_ids=[blocked.public_id]), db, user)
    assert exc_info.value.status_code == 422


def test_share_link_overview_counts_only_clean_files(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    clean = _make_file(db, tenant.id, "a.png")
    pending = _make_file(db, tenant.id, "b.png")
    pending.scan_status = "pending"
    album = PhotoAlbum(tenant_id=tenant.id, name="Album", kind="manual")
    db.add(album)
    db.flush()
    db.add_all([PhotoAlbumItem(album_id=album.id, file_id=clean.public_id), PhotoAlbumItem(album_id=album.id, file_id=pending.public_id)])
    db.commit()
    share_links_routes.create_share_link(ShareLinkCreate(name="Dateien", file_ids=[clean.public_id, pending.public_id]), db, user)
    share_links_routes.create_share_link(ShareLinkCreate(name="Album", album_id=album.id), db, user)

    counts = {row.name: row.file_count for row in share_links_routes.list_share_links(db, user)}

    assert counts == {"Dateien": 1, "Album": 1}


def test_public_album_thumbnail_resolves_single_file_and_respects_pending_release(db):
    """Gezielte Einzelauflösung (statt ganzes Album je Thumbnail): ein Foto im Album wird
    gefunden, ein vorgemerktes (share_pending) nicht."""
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    released = _make_file(db, tenant.id, "frei.png")
    held_back = _make_file(db, tenant.id, "vorgemerkt.png")
    album = PhotoAlbum(tenant_id=tenant.id, name="Album", kind="manual")
    db.add(album)
    db.flush()
    db.add_all([
        PhotoAlbumItem(album_id=album.id, file_id=released.public_id),
        PhotoAlbumItem(album_id=album.id, file_id=held_back.public_id),
    ])
    db.commit()
    created = share_links_routes.create_share_link(ShareLinkCreate(name="Album", album_id=album.id), db, user)
    token = created.url.removeprefix("/share/")
    # Erst nach dem Anlegen vormerken (das Anlegen gibt alte Vormerkungen frei).
    db.get(PhotoAlbumItem, {"album_id": album.id, "file_id": held_back.public_id}).share_pending = True
    db.commit()
    link = public_share_routes._resolve_link_or_404(db, token)

    assert public_share_routes._resolve_file_or_404(db, link, released.public_id).id == released.id
    with pytest.raises(HTTPException) as exc_info:
        public_share_routes._resolve_file_or_404(db, link, held_back.public_id)
    assert exc_info.value.status_code == 404


def test_share_links_respect_the_split_between_documents_and_photos(db):
    """Security-Review Phase 3: öffentlich teilen nur, was man selbst sehen darf - Bilder mit
    photos.read, Dokumente mit files.read; die Linkliste zeigt nur solche Links."""
    import dataclasses

    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    photos_only = dataclasses.replace(writer, permissions=frozenset({"sharing.public", "photos.read"}))
    pdf = _make_file(db, tenant.id, name="vertraulich.pdf", content=b"%PDF-1.4 test", mime_type="application/pdf")
    photo = _make_file(db, tenant.id)

    with pytest.raises(HTTPException) as denied:
        share_links_routes.create_share_link(ShareLinkCreate(name="PDF", file_ids=[pdf.public_id]), db, photos_only)
    assert denied.value.status_code == 403
    share_links_routes.create_share_link(ShareLinkCreate(name="Foto", file_ids=[photo.public_id]), db, photos_only)
    document_link = share_links_routes.create_share_link(ShareLinkCreate(name="Dokument", file_ids=[pdf.public_id]), db, writer)

    assert [row.name for row in share_links_routes.list_share_links(db, photos_only)] == ["Foto"]
    assert {row.name for row in share_links_routes.list_share_links(db, writer)} == {"Foto", "Dokument"}
    with pytest.raises(HTTPException) as hidden:
        share_links_routes.revoke_share_link(document_link.id, db, photos_only)
    assert hidden.value.status_code == 404


def test_expiry_date_from_the_date_field_keeps_the_link_open_through_that_swiss_day(db):
    """Das Freigabe-Modal schickt das Ablaufdatum aus dem DateInput als reines Datum
    ("JJJJ-MM-TT"); die öffentliche Seite zeigt «Link gültig bis <Datum>». Der Link muss also bis
    zum Ende dieses Tages (Schweizer Zeit) offen bleiben, nicht schon um 00:00 UTC (= 01:00/02:00
    Schweizer Zeit) desselben Tages ablaufen (Nachtlauf 2026-11-20)."""
    from datetime import date
    from zoneinfo import ZoneInfo

    zurich = ZoneInfo("Europe/Zurich")
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    a = _make_file(db, tenant.id)

    payload = ShareLinkCreate.model_validate_json(f'{{"name": "Sommerfest", "file_ids": ["{a.public_id}"], "expires_at": "2030-11-30"}}')
    created = share_links_routes.create_share_link(payload, db, user)
    expires_local = created.expires_at.astimezone(zurich)
    assert expires_local.date() == date(2030, 11, 30)
    assert expires_local >= datetime(2030, 11, 30, 23, 59, tzinfo=zurich)

    # Heute als Ablaufdatum gewählt: der Link funktioniert heute noch.
    today = datetime.now(zurich).date().isoformat()
    payload = ShareLinkCreate.model_validate_json(f'{{"name": "Heute", "file_ids": ["{a.public_id}"], "expires_at": "{today}"}}')
    created = share_links_routes.create_share_link(payload, db, user)
    assert created.status == "active"
    token = created.url.removeprefix("/share/")
    assert public_share_routes.get_public_share(token, _FakeRequest(), db).name == "Heute"

    # Ein vollständiger Zeitpunkt (andere Clients) bleibt unverändert.
    moment = datetime(2030, 11, 30, 18, 0, tzinfo=UTC)
    created = share_links_routes.create_share_link(ShareLinkCreate(name="Y", file_ids=[a.public_id], expires_at=moment), db, user)
    assert created.expires_at == moment


def _make_draft_protocol_image(db, tenant_id: int) -> StoredFile:
    """Bild in einem Protokollentwurf (Status «geplant») - erscheint in der Dateiübersicht als
    Quelle «protocol_image», lesen darf es nur, wer den Entwurf lesen darf."""
    from datetime import date

    from app.models.entities import ProtocolImage
    from tests.factories import make_protocol, make_protocol_element, make_protocol_element_block, make_template

    template = make_template(db, tenant_id)
    protocol = make_protocol(db, tenant_id, template.id, protocol_number="7/2026", protocol_date=date(2026, 3, 1))
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={})
    stored_file = _make_file(db, tenant_id, name="entwurf-bild.png")
    db.execute(GalleryImage.__table__.delete().where(GalleryImage.stored_file_id == stored_file.id))
    db.add(ProtocolImage(protocol_element_block_id=block.id, stored_file_id=stored_file.id, sort_index=0))
    db.flush()
    return stored_file


def test_create_share_link_rejects_images_of_protocols_the_account_cannot_read(db):
    """Nachtlauf 2026-11-22 (dateien-fotos/rechte): der Link machte Bilder aus Protokollentwürfen
    öffentlich, die das Konto selbst nicht öffnen darf (Einzelabruf 404) - wie beim Album
    (add_album_items) zählt je Datei das Leserecht des Einzelabrufs."""
    import dataclasses

    from app.services.access_service import AccessService

    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    # Eigene Rolle «Fotos & Links»: Fotos lesen und öffentlich teilen, Protokolle nur abgeschlossene
    photographer = dataclasses.replace(writer, permissions=frozenset({"meetings.read", "photos.read", "photos.manage", "sharing.public"}))
    draft_image = _make_draft_protocol_image(db, tenant.id)
    db.commit()

    with pytest.raises(HTTPException):
        AccessService().ensure_can_read_stored_file(db, photographer, draft_image.id)

    with pytest.raises(HTTPException) as denied:
        share_links_routes.create_share_link(ShareLinkCreate(name="Entwurf", file_ids=[draft_image.public_id]), db, photographer)
    assert denied.value.status_code == 404
    # Wer den Entwurf lesen darf, teilt ihn weiterhin
    share_links_routes.create_share_link(ShareLinkCreate(name="Entwurf", file_ids=[draft_image.public_id]), db, writer)


def test_share_link_list_hides_links_to_files_the_account_cannot_read(db):
    """Nachtlauf 2026-11-22: die Linkliste zeigte die Token-URL eines Links auf ein Entwurfsbild
    auch Konten, die das Bild selbst nicht öffnen dürfen (nur Dateiart geprüft)."""
    import dataclasses

    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    photographer = dataclasses.replace(writer, user_id=2, permissions=frozenset({"meetings.read", "photos.read", "photos.manage", "sharing.public"}))
    draft_image = _make_draft_protocol_image(db, tenant.id)
    photo = _make_file(db, tenant.id)
    draft_link = share_links_routes.create_share_link(ShareLinkCreate(name="Entwurf", file_ids=[draft_image.public_id]), db, writer)
    share_links_routes.create_share_link(ShareLinkCreate(name="Foto", file_ids=[photo.public_id]), db, writer)

    assert {row.name for row in share_links_routes.list_share_links(db, writer)} == {"Entwurf", "Foto"}
    assert [row.name for row in share_links_routes.list_share_links(db, photographer)] == ["Foto"]
    with pytest.raises(HTTPException) as hidden:
        share_links_routes.revoke_share_link(draft_link.id, db, photographer)
    assert hidden.value.status_code == 404
