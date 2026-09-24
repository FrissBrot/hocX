"""Tests for the mandantenuebergreifende Album-Freigabe route layer in files.py
(create_album_share/respond_album_share/delete_album_share/list_album_share_requests,
list_albums' owner/shared visibility) and the resulting cross-tenant photo access via
access_service.ensure_can_read_stored_file."""

import pytest
from fastapi import HTTPException

from app.api.routes import files as files_routes
from app.models.entities import GalleryImage, PhotoAlbum, PhotoAlbumItem, StoredFile
from app.schemas.files import AlbumShareCreate, AlbumShareRespond, FileBulkDelete, PhotoAlbumItemsUpdate
from app.services.access_service import AccessService
from tests.factories import make_current_user, make_cycle_config, make_tenant


def _make_album(db, tenant_id: int, name: str = "Album", kind: str = "manual") -> PhotoAlbum:
    album = PhotoAlbum(tenant_id=tenant_id, name=name, kind=kind)
    db.add(album)
    db.flush()
    return album


def _make_cycle_album(db, tenant_id: int, name: str = "Zyklus-Album") -> PhotoAlbum:
    """kind='cycle' albums are DB-constrained (ck_photo_album_kind_fields) to always carry
    their cycle_config_id/cycle_year, unlike the "manual" shortcut _make_album covers."""
    cycle_config = make_cycle_config(db, tenant_id)
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


def _invite_and_accept(db, owner_tenant, partner_tenant, album):
    owner_user = make_current_user(owner_tenant.id, role="writer")
    files_routes.create_album_share(album.id, AlbumShareCreate(target_tenant_public_id=partner_tenant.public_id), db, owner_user)
    partner_user = make_current_user(partner_tenant.id, role="writer")
    files_routes.respond_album_share(album.id, AlbumShareRespond(accept=True), db, partner_user)


# --- create_album_share --------------------------------------------------------------------


def test_create_album_share_requires_the_owner_tenant(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    stranger = make_tenant(db)
    album = _make_album(db, owner.id)
    stranger_user = make_current_user(stranger.id, role="writer")

    with pytest.raises(HTTPException) as exc_info:
        files_routes.create_album_share(album.id, AlbumShareCreate(target_tenant_public_id=partner.public_id), db, stranger_user)
    assert exc_info.value.status_code == 404


def test_create_album_share_rejects_an_unknown_target_public_id(db):
    import uuid

    owner = make_tenant(db)
    album = _make_album(db, owner.id)
    owner_user = make_current_user(owner.id, role="writer")

    with pytest.raises(HTTPException) as exc_info:
        files_routes.create_album_share(album.id, AlbumShareCreate(target_tenant_public_id=uuid.uuid4()), db, owner_user)
    assert exc_info.value.status_code == 404


def test_create_album_share_rejects_a_non_manual_album(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_cycle_album(db, owner.id)
    owner_user = make_current_user(owner.id, role="writer")

    with pytest.raises(HTTPException) as exc_info:
        files_routes.create_album_share(album.id, AlbumShareCreate(target_tenant_public_id=partner.public_id), db, owner_user)
    assert exc_info.value.status_code == 422


def test_create_album_share_rejects_a_duplicate_invitation(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)
    owner_user = make_current_user(owner.id, role="writer")
    files_routes.create_album_share(album.id, AlbumShareCreate(target_tenant_public_id=partner.public_id), db, owner_user)

    with pytest.raises(HTTPException) as exc_info:
        files_routes.create_album_share(album.id, AlbumShareCreate(target_tenant_public_id=partner.public_id), db, owner_user)
    assert exc_info.value.status_code == 422


# --- respond_album_share / list_album_share_requests ----------------------------------------


def test_list_album_share_requests_only_shows_pending_invitations_for_the_current_tenant(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    other = make_tenant(db)
    album = _make_album(db, owner.id, name="Sommerlager")
    owner_user = make_current_user(owner.id, role="writer")
    files_routes.create_album_share(album.id, AlbumShareCreate(target_tenant_public_id=partner.public_id), db, owner_user)

    partner_user = make_current_user(partner.id, role="writer")
    other_user = make_current_user(other.id, role="writer")

    requests = files_routes.list_album_share_requests(db, partner_user)
    assert [r.album_name for r in requests] == ["Sommerlager"]
    assert requests[0].owner_tenant_name == owner.name
    assert files_routes.list_album_share_requests(db, other_user) == []


def test_respond_album_share_rejects_when_there_is_no_pending_invitation(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)
    partner_user = make_current_user(partner.id, role="writer")

    with pytest.raises(HTTPException) as exc_info:
        files_routes.respond_album_share(album.id, AlbumShareRespond(accept=True), db, partner_user)
    assert exc_info.value.status_code == 404


def test_respond_album_share_accept_removes_it_from_pending_requests(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)
    owner_user = make_current_user(owner.id, role="writer")
    files_routes.create_album_share(album.id, AlbumShareCreate(target_tenant_public_id=partner.public_id), db, owner_user)
    partner_user = make_current_user(partner.id, role="writer")

    files_routes.respond_album_share(album.id, AlbumShareRespond(accept=True), db, partner_user)

    assert files_routes.list_album_share_requests(db, partner_user) == []


# --- delete_album_share ----------------------------------------------------------------------


def test_delete_album_share_rejects_an_unrelated_tenant(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    stranger = make_tenant(db)
    album = _make_album(db, owner.id)
    _invite_and_accept(db, owner, partner, album)
    stranger_user = make_current_user(stranger.id, role="writer")

    with pytest.raises(HTTPException) as exc_info:
        files_routes.delete_album_share(album.id, partner.public_id, db, stranger_user)
    assert exc_info.value.status_code == 403


def test_delete_album_share_lets_the_partner_leave(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)
    _invite_and_accept(db, owner, partner, album)
    partner_user = make_current_user(partner.id, role="writer")

    files_routes.delete_album_share(album.id, partner.public_id, db, partner_user)

    albums = {row.id for row in files_routes.list_albums(db, partner_user)}
    assert album.id not in albums


# --- list_albums: owner/shared visibility -----------------------------------------------------


def test_list_albums_shows_owner_name_to_the_partner_and_shares_to_the_owner(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id, name="Sommerlager")
    _invite_and_accept(db, owner, partner, album)

    owner_user = make_current_user(owner.id, role="writer")
    partner_user = make_current_user(partner.id, role="writer")

    owner_view = next(row for row in files_routes.list_albums(db, owner_user) if row.id == album.id)
    assert owner_view.owner_tenant_name is None
    assert [s.tenant_name for s in owner_view.shared_with] == [partner.name]

    partner_view = next(row for row in files_routes.list_albums(db, partner_user) if row.id == album.id)
    assert partner_view.owner_tenant_name == owner.name
    assert partner_view.shared_with == []


def test_list_albums_does_not_show_the_album_before_acceptance(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)
    owner_user = make_current_user(owner.id, role="writer")
    files_routes.create_album_share(album.id, AlbumShareCreate(target_tenant_public_id=partner.public_id), db, owner_user)
    partner_user = make_current_user(partner.id, role="writer")

    assert album.id not in {row.id for row in files_routes.list_albums(db, partner_user)}


# --- add/delete items across tenants once shared ----------------------------------------------


def test_add_album_items_is_rejected_for_the_partner_before_acceptance(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)
    owner_user = make_current_user(owner.id, role="writer")
    files_routes.create_album_share(album.id, AlbumShareCreate(target_tenant_public_id=partner.public_id), db, owner_user)
    partner_user = make_current_user(partner.id, role="writer")
    own_photo = _make_gallery_file(db, partner.id)

    with pytest.raises(HTTPException) as exc_info:
        files_routes.add_album_items(album.id, PhotoAlbumItemsUpdate(file_ids=[own_photo.public_id]), db, partner_user)
    assert exc_info.value.status_code == 404


def test_partner_can_add_and_delete_their_own_photos_once_accepted(db):
    """Core promise of the feature: after acceptance, each tenant adds/removes its OWN
    photos - add_album_items/bulk_delete_files already validate ownership against the
    ACTING tenant, not the album's owner, so no further change was needed there."""
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)
    _invite_and_accept(db, owner, partner, album)
    partner_user = make_current_user(partner.id, role="writer")
    partner_photo = _make_gallery_file(db, partner.id, "partner.png")

    files_routes.add_album_items(album.id, PhotoAlbumItemsUpdate(file_ids=[partner_photo.public_id]), db, partner_user)

    items = {row.file_id for row in db.query(PhotoAlbumItem).filter_by(album_id=album.id)}
    assert partner_photo.public_id in items

    result = files_routes.bulk_delete_files(FileBulkDelete(file_ids=[partner_photo.public_id]), db, partner_user)
    assert partner_photo.public_id in result.deleted_ids


def test_partner_cannot_add_a_file_it_does_not_own(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)
    _invite_and_accept(db, owner, partner, album)
    partner_user = make_current_user(partner.id, role="writer")
    owner_photo = _make_gallery_file(db, owner.id, "owner.png")

    with pytest.raises(HTTPException) as exc_info:
        files_routes.add_album_items(album.id, PhotoAlbumItemsUpdate(file_ids=[owner_photo.public_id]), db, partner_user)
    assert exc_info.value.status_code == 404


def test_partner_cannot_delete_the_owners_photo(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)
    _invite_and_accept(db, owner, partner, album)
    owner_user = make_current_user(owner.id, role="writer")
    partner_user = make_current_user(partner.id, role="writer")
    owner_photo = _make_gallery_file(db, owner.id, "owner.png")
    files_routes.add_album_items(album.id, PhotoAlbumItemsUpdate(file_ids=[owner_photo.public_id]), db, owner_user)

    result = files_routes.bulk_delete_files(FileBulkDelete(file_ids=[owner_photo.public_id]), db, partner_user)

    assert owner_photo.public_id not in result.deleted_ids
    assert result.errors
    items = {row.file_id for row in db.query(PhotoAlbumItem).filter_by(album_id=album.id)}
    assert owner_photo.public_id in items


# --- cross-tenant read access (access_service.ensure_can_read_stored_file) --------------------


def test_ensure_can_read_stored_file_denies_the_partner_before_acceptance(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)
    owner_user = make_current_user(owner.id, role="writer")
    files_routes.create_album_share(album.id, AlbumShareCreate(target_tenant_public_id=partner.public_id), db, owner_user)
    owner_photo = _make_gallery_file(db, owner.id)
    db.add(PhotoAlbumItem(album_id=album.id, file_id=owner_photo.public_id))
    db.commit()
    partner_user = make_current_user(partner.id, role="writer")

    with pytest.raises(HTTPException) as exc_info:
        AccessService().ensure_can_read_stored_file(db, partner_user, owner_photo.id)
    assert exc_info.value.status_code == 403


def test_ensure_can_read_stored_file_allows_the_partner_once_accepted(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)
    _invite_and_accept(db, owner, partner, album)
    owner_photo = _make_gallery_file(db, owner.id)
    db.add(PhotoAlbumItem(album_id=album.id, file_id=owner_photo.public_id))
    db.commit()
    partner_user = make_current_user(partner.id, role="writer")

    # Must not raise.
    AccessService().ensure_can_read_stored_file(db, partner_user, owner_photo.id)


def test_ensure_can_read_stored_file_still_denies_photos_outside_any_shared_album(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)
    _invite_and_accept(db, owner, partner, album)
    unrelated_photo = _make_gallery_file(db, owner.id, "unrelated.png")  # never added to the shared album
    partner_user = make_current_user(partner.id, role="writer")

    with pytest.raises(HTTPException) as exc_info:
        AccessService().ensure_can_read_stored_file(db, partner_user, unrelated_photo.id)
    assert exc_info.value.status_code == 403
