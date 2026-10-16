"""IMGMETA-007 (Entscheidung): Standort beim Teilen eines Albums an einen Partner-Mandanten
schaltbar, Standard an; Freigabe-Links teilen den Standort standardmässig nicht."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.routes import files as files_routes
from app.core.config import settings
from app.models.entities import GalleryImage, PhotoAlbum, PhotoAlbumItem, PhotoAlbumTenantShare, StoredFile
from app.schemas.files import AlbumShareCreate, AlbumShareRespond, AlbumShareUpdate
from app.services import photo_album_share_service, share_link_service
from tests.factories import make_current_user, make_tenant
from tests.image_fixtures import jpeg, read_exif

LATITUDE, LONGITUDE = 47.3769, 8.5417


@pytest.fixture(autouse=True)
def _isolated_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))


def _photo(db, tenant_id: int, content: bytes, *, name: str = "foto.jpg", mime: str = "image/jpeg") -> StoredFile:
    key = f"uploads/test/{name}"
    path = Path(settings.storage_root) / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name=name, mime_type=mime, storage_path=key, scan_status="clean",
        file_size_bytes=len(content),
    )
    db.add(stored_file)
    db.flush()
    return stored_file


def _shared_album(db, *, share_location: bool | None = None):
    owner, partner = make_tenant(db), make_tenant(db)
    album = PhotoAlbum(tenant_id=owner.id, name="Ausflug", kind="manual")
    db.add(album)
    db.flush()
    owner_user = make_current_user(owner.id, role="writer")
    payload = AlbumShareCreate(target_tenant_public_id=partner.public_id)
    if share_location is not None:
        payload = AlbumShareCreate(target_tenant_public_id=partner.public_id, share_location=share_location)
    files_routes.create_album_share(album.id, payload, db, owner_user)
    partner_user = make_current_user(partner.id, role="writer")
    files_routes.respond_album_share(album.id, AlbumShareRespond(accept=True), db, partner_user)
    return owner, partner, album, owner_user, partner_user


def _add(db, album: PhotoAlbum, stored_file: StoredFile, *, live_video: StoredFile | None = None) -> None:
    db.add(GalleryImage(tenant_id=stored_file.tenant_id, stored_file_id=stored_file.id,
                        live_video_stored_file_id=live_video.id if live_video is not None else None))
    db.add(PhotoAlbumItem(album_id=album.id, file_id=stored_file.public_id))
    db.flush()


def _gps_of(response) -> dict:
    return read_exif(Path(response.path).read_bytes())[2]


def test_album_share_shares_location_by_default_and_links_do_not(db):
    _owner, partner, album, _owner_user, _partner_user = _shared_album(db)
    share = db.get(PhotoAlbumTenantShare, {"album_id": album.id, "tenant_id": partner.id})
    assert share.share_location is True
    assert share_link_service.DEFAULT_METADATA_POLICY.location is False


def test_partner_gets_gps_when_the_share_includes_the_location(db):
    owner, _partner, album, _owner_user, partner_user = _shared_album(db)
    photo = _photo(db, owner.id, jpeg(latitude=LATITUDE, longitude=LONGITUDE))
    _add(db, album, photo)

    assert _gps_of(files_routes.get_stored_file_content(photo.public_id, db, partner_user))
    assert _gps_of(files_routes.download_stored_file(photo.public_id, "image", db, partner_user))


def test_partner_gets_no_location_when_the_owner_switched_it_off(db):
    owner, partner, album, owner_user, partner_user = _shared_album(db, share_location=False)
    photo = _photo(db, owner.id, jpeg(latitude=LATITUDE, longitude=LONGITUDE, make="Kamera"))
    _add(db, album, photo)

    content = files_routes.get_stored_file_content(photo.public_id, db, partner_user)
    assert _gps_of(content) == {}
    ifd0, _exif, _gps = read_exif(Path(content.path).read_bytes())
    assert ifd0.get(0x010F) == "Kamera"  # nur der Standort fällt weg
    assert _gps_of(files_routes.download_stored_file(photo.public_id, "image", db, partner_user)) == {}
    # Der Besitzer selbst bekommt weiter das Original.
    assert _gps_of(files_routes.get_stored_file_content(photo.public_id, db, owner_user))

    # Wieder eingeschaltet: Partner bekommt den Standort.
    files_routes.update_album_share(album.id, partner.public_id, AlbumShareUpdate(share_location=True), db, owner_user)
    assert _gps_of(files_routes.get_stored_file_content(photo.public_id, db, partner_user))


def test_database_only_gps_is_not_written_into_the_partner_copy(db):
    """Die Exportfassung trägt GPS aus der Datenbank ein - ohne Standortfreigabe darf das nicht
    in der Kopie des Partners landen."""
    owner, _partner, album, _owner_user, partner_user = _shared_album(db, share_location=False)
    photo = _photo(db, owner.id, jpeg())
    photo.gps_latitude, photo.gps_longitude, photo.gps_source = LATITUDE, LONGITUDE, "client"
    db.flush()
    _add(db, album, photo)

    assert _gps_of(files_routes.download_stored_file(photo.public_id, "image", db, partner_user)) == {}


def test_partner_photos_seen_by_the_owner_follow_the_same_switch(db):
    """Legt der Partner eigene Fotos in das Album, gilt der Schalter seiner Freigabe auch für
    den Besitzer."""
    _owner, partner, album, owner_user, _partner_user = _shared_album(db, share_location=False)
    photo = _photo(db, partner.id, jpeg(latitude=LATITUDE, longitude=LONGITUDE), name="partner.jpg")
    _add(db, album, photo)

    assert _gps_of(files_routes.get_stored_file_content(photo.public_id, db, owner_user)) == {}
    assert photo_album_share_service.location_shared_with(db, partner.id, photo.id, partner.id) is True


def test_only_the_owner_can_switch_the_location(db):
    _owner, partner, album, _owner_user, partner_user = _shared_album(db)
    with pytest.raises(HTTPException) as exc_info:
        files_routes.update_album_share(album.id, partner.public_id, AlbumShareUpdate(share_location=False), db, partner_user)
    assert exc_info.value.status_code == 404
    assert db.get(PhotoAlbumTenantShare, {"album_id": album.id, "tenant_id": partner.id}).share_location is True


def test_shares_list_reports_the_location_switch(db):
    owner, _partner, album, owner_user, _partner_user = _shared_album(db, share_location=False)
    albums = files_routes.list_albums(db, owner_user)
    entry = next(item for item in albums if item.id == album.id)
    assert [share.share_location for share in entry.shared_with] == [False]
    assert owner.id == album.tenant_id


def _ffprobe_tags(path: Path) -> dict:
    output = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format_tags", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(output).get("format", {}).get("tags", {})


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg nicht installiert")
def test_live_photo_video_loses_its_location_for_partners_without_the_location(db, tmp_path):
    owner, _partner, album, _owner_user, partner_user = _shared_album(db, share_location=False)
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=32x32:d=1",
         "-metadata", "location=+47.3769+008.5417/", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(clip)],
        check=True, capture_output=True,
    )
    assert "location" in _ffprobe_tags(clip)
    video = _photo(db, owner.id, clip.read_bytes(), name="clip.mp4", mime="video/mp4")
    photo = _photo(db, owner.id, jpeg(latitude=LATITUDE, longitude=LONGITUDE))
    _add(db, album, photo, live_video=video)

    # Partner erhalten den Clip nur über den Download des Fotos (die Inhalts-Route des Clips
    # selbst ist für sie gesperrt).
    downloaded = files_routes.download_stored_file(photo.public_id, "video", db, partner_user)
    assert "location" not in _ffprobe_tags(Path(downloaded.path))
