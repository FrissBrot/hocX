"""Vorgemerkte Fotos in geteilten Alben (photo_album_item.share_pending): automatisch in ein
geteiltes Album einsortierte Fotos sieht nur der Besitzer, bis er sie freigibt; manuelles
Hinzufuegen und ein beim Upload bestaetigter Galerie-Upload teilen sofort."""

from datetime import date

import pytest
from fastapi import HTTPException

from app.api.routes import files as files_routes
from app.models.entities import GalleryImage, PhotoAlbum, PhotoAlbumItem, StoredFile
from app.schemas.files import AlbumReleaseRequest, AlbumShareCreate, AlbumShareRespond, PhotoAlbumItemsUpdate
from app.services import photo_album_service, share_link_service
from app.services.access_service import AccessService
from app.services.file_service import FileService
from tests.factories import make_current_user, make_cycle_config, make_tenant

service = FileService()


def _make_cycle_album(db, tenant_id: int, cycle_config=None, name: str = "Zyklus 2026") -> PhotoAlbum:
    cycle_config = cycle_config or make_cycle_config(db, tenant_id)
    album = PhotoAlbum(tenant_id=tenant_id, name=name, kind="cycle", cycle_config_id=cycle_config.id, cycle_year=2026)
    db.add(album)
    db.flush()
    return album


def _make_gallery_file(db, tenant_id: int, name: str = "foto.png") -> StoredFile:
    stored_file = StoredFile(tenant_id=tenant_id, original_name=name, mime_type="image/png", storage_path=f"uploads/{name}")
    db.add(stored_file)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=stored_file.id))
    db.flush()
    return stored_file


def _share(db, owner, partner, album, accept: bool = True):
    owner_user = make_current_user(owner.id, role="writer")
    files_routes.create_album_share(album.id, AlbumShareCreate(target_tenant_public_id=partner.public_id), db, owner_user)
    if accept:
        files_routes.respond_album_share(album.id, AlbumShareRespond(accept=True), db, make_current_user(partner.id, role="writer"))


def _pending(db, album, stored_file) -> bool:
    return db.get(PhotoAlbumItem, {"album_id": album.id, "file_id": stored_file.public_id}).share_pending


def _album_file_ids(db, user, album) -> list:
    items = files_routes.list_files(
        skip=0, limit=60, source=None, only_images=False, exclude_images=False, search=None, tags=None,
        sort_by="created_at", sort_dir="desc", db=db, user=user, album_id=album.id,
    )
    return [item.id for item in items]


def test_automatic_add_to_an_unshared_album_is_not_pending(db):
    owner = make_tenant(db)
    album = _make_cycle_album(db, owner.id)
    photo = _make_gallery_file(db, owner.id)

    photo_album_service.add_items(db, album, [photo.public_id])

    assert _pending(db, album, photo) is False


def test_automatic_add_to_a_shared_album_is_pending_and_hidden_from_the_partner(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_cycle_album(db, owner.id)
    _share(db, owner, partner, album)
    photo = _make_gallery_file(db, owner.id)

    photo_album_service.add_items(db, album, [photo.public_id])
    db.commit()

    assert _pending(db, album, photo) is True
    owner_user = make_current_user(owner.id, role="writer")
    partner_user = make_current_user(partner.id, role="writer")
    assert _album_file_ids(db, owner_user, album) == [photo.public_id]
    assert _album_file_ids(db, partner_user, album) == []

    owner_view = next(row for row in files_routes.list_albums(db, owner_user) if row.id == album.id)
    assert (owner_view.photo_count, owner_view.pending_share_count, owner_view.is_shared) == (1, 1, True)
    partner_view = next(row for row in files_routes.list_albums(db, partner_user) if row.id == album.id)
    assert (partner_view.photo_count, partner_view.cover_thumbnail_urls) == (0, [])

    with pytest.raises(HTTPException):
        AccessService().ensure_can_read_stored_file(db, partner_user, photo.id)


def test_a_pending_invitation_already_counts_as_shared(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_cycle_album(db, owner.id)
    _share(db, owner, partner, album, accept=False)
    photo = _make_gallery_file(db, owner.id)

    photo_album_service.add_items(db, album, [photo.public_id])

    assert _pending(db, album, photo) is True


def test_release_makes_pending_photos_visible_to_the_partner(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_cycle_album(db, owner.id, name="Sommerlager")
    _share(db, owner, partner, album)
    first = _make_gallery_file(db, owner.id, "a.png")
    second = _make_gallery_file(db, owner.id, "b.png")
    photo_album_service.add_items(db, album, [first.public_id, second.public_id])
    db.commit()
    owner_user = make_current_user(owner.id, role="writer")

    [row] = files_routes.list_album_pending_releases(db, owner_user)
    assert (row.album_name, row.pending_count) == ("Sommerlager", 2)
    pending_items = files_routes.list_files(
        skip=0, limit=60, source=None, only_images=False, exclude_images=False, search=None, tags=None,
        sort_by="created_at", sort_dir="desc", db=db, user=owner_user, album_id=album.id, share_pending=True,
    )
    assert len(pending_items) == 2 and all(item.share_pending for item in pending_items)

    result = files_routes.release_album_items(album.id, AlbumReleaseRequest(file_ids=[first.public_id]), db, owner_user)
    assert result.released == 1
    assert (_pending(db, album, first), _pending(db, album, second)) == (False, True)

    files_routes.release_album_items(album.id, AlbumReleaseRequest(), db, owner_user)
    assert files_routes.list_album_pending_releases(db, owner_user) == []
    partner_user = make_current_user(partner.id, role="writer")
    assert set(_album_file_ids(db, partner_user, album)) == {first.public_id, second.public_id}


def test_only_the_owner_can_release(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_cycle_album(db, owner.id)
    _share(db, owner, partner, album)

    with pytest.raises(HTTPException) as exc_info:
        files_routes.release_album_items(album.id, AlbumReleaseRequest(), db, make_current_user(partner.id, role="writer"))
    assert exc_info.value.status_code == 404


def test_manual_add_shares_immediately_and_releases_a_pending_photo(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_cycle_album(db, owner.id)
    _share(db, owner, partner, album)
    pending_photo = _make_gallery_file(db, owner.id, "auto.png")
    new_photo = _make_gallery_file(db, owner.id, "manuell.png")
    photo_album_service.add_items(db, album, [pending_photo.public_id])
    db.commit()

    files_routes.add_album_items(
        album.id,
        PhotoAlbumItemsUpdate(file_ids=[pending_photo.public_id, new_photo.public_id]),
        db,
        make_current_user(owner.id, role="writer"),
    )

    assert (_pending(db, album, pending_photo), _pending(db, album, new_photo)) == (False, False)


def test_assign_uploaded_files_with_confirmed_release_is_not_pending(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    cycle_config = make_cycle_config(db, owner.id)
    album = _make_cycle_album(db, owner.id, cycle_config)
    _share(db, owner, partner, album)
    photo = _make_gallery_file(db, owner.id)

    photo_album_service.assign_uploaded_files(
        db, service, tenant_id=owner.id, stored_file_public_ids=[photo.public_id], cycle_config=cycle_config,
        fallback_date=date(2026, 6, 1), release_shared=True,
    )

    assert _pending(db, album, photo) is False


def test_album_share_link_leaves_out_pending_photos(db):
    owner = make_tenant(db)
    album = _make_cycle_album(db, owner.id)
    link = share_link_service.create_for_album(db, tenant_id=owner.id, name="Link", album=album, expires_at=None, created_by=None)
    released = _make_gallery_file(db, owner.id, "frei.png")
    pending = _make_gallery_file(db, owner.id, "offen.png")
    photo_album_service.add_items(db, album, [released.public_id], release=True)
    photo_album_service.add_items(db, album, [pending.public_id])
    db.commit()

    assert share_link_service.file_ids_for_link(db, link) == [released.public_id]


def test_resharing_an_unshared_album_releases_stale_pending_photos(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_cycle_album(db, owner.id)
    _share(db, owner, partner, album)
    photo = _make_gallery_file(db, owner.id)
    photo_album_service.add_items(db, album, [photo.public_id])
    db.commit()
    owner_user = make_current_user(owner.id, role="writer")
    files_routes.delete_album_share(album.id, partner.public_id, db, owner_user)
    assert files_routes.list_album_pending_releases(db, owner_user) == []

    _share(db, owner, partner, album, accept=False)

    assert _pending(db, album, photo) is False


def test_upload_target_shared_albums_lists_only_shared_existing_albums(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    cycle_config = make_cycle_config(db, owner.id)
    album = _make_cycle_album(db, owner.id, cycle_config, name="Zyklus geteilt")
    owner_user = make_current_user(owner.id, role="writer")

    def shared_names():
        return [
            row.album_name
            for row in files_routes.list_upload_target_shared_albums(
                event_id=None, submission_assignment_id=None, submission_element_ref=None,
                cycle_config_id=cycle_config.public_id, db=db, user=owner_user,
            )
        ]

    assert shared_names() == []
    _share(db, owner, partner, album)
    assert shared_names() == ["Zyklus geteilt"]
