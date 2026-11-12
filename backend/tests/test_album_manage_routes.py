"""Albenverwaltung (Audit Dateien/Fotos): umbenennen, löschen (Fotos bleiben erhalten) und Fotos
aus einem Album nehmen - Besitzer darf alles, ein Partner eines geteilten Albums nur eigene Fotos
herausnehmen und das Album weder umbenennen noch löschen (E-7)."""

import pytest
from fastapi import HTTPException

from app.api.routes import files as files_routes
from app.models.entities import GalleryImage, PhotoAlbum, PhotoAlbumItem, PhotoAlbumTenantShare, StoredFile
from app.schemas.files import AlbumShareCreate, AlbumShareRespond, PhotoAlbumItemsUpdate, PhotoAlbumUpdate
from tests.factories import make_current_user, make_cycle_config, make_tenant


def _make_album(db, tenant_id: int, name: str = "Album") -> PhotoAlbum:
    album = PhotoAlbum(tenant_id=tenant_id, name=name, kind="manual")
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


def _shared_album(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)
    owner_user = make_current_user(owner.id, role="writer")
    partner_user = make_current_user(partner.id, role="writer")
    files_routes.create_album_share(album.id, AlbumShareCreate(target_tenant_public_id=partner.public_id), db, owner_user)
    files_routes.respond_album_share(album.id, AlbumShareRespond(accept=True), db, partner_user)
    return album, owner, partner, owner_user, partner_user


def _items(db, album) -> set:
    return {row.file_id for row in db.query(PhotoAlbumItem).filter_by(album_id=album.id)}


# --- umbenennen -----------------------------------------------------------------------------


def test_owner_can_rename_album_and_name_is_trimmed(db):
    tenant = make_tenant(db)
    album = _make_album(db, tenant.id, "Sommerlagr")
    user = make_current_user(tenant.id, role="writer")

    result = files_routes.rename_album(album.id, PhotoAlbumUpdate(name="  Sommerlager  "), db, user)

    assert result.name == "Sommerlager"
    db.refresh(album)
    assert album.name == "Sommerlager"


def test_rename_rejects_empty_name(db):
    tenant = make_tenant(db)
    album = _make_album(db, tenant.id)
    user = make_current_user(tenant.id, role="writer")

    with pytest.raises(HTTPException) as exc_info:
        files_routes.rename_album(album.id, PhotoAlbumUpdate(name="   "), db, user)
    assert exc_info.value.status_code == 422


def test_rename_requires_files_manage(db):
    tenant = make_tenant(db)
    album = _make_album(db, tenant.id)
    reader = make_current_user(tenant.id, role="reader")

    with pytest.raises(HTTPException) as exc_info:
        files_routes.rename_album(album.id, PhotoAlbumUpdate(name="Neu"), db, reader)
    assert exc_info.value.status_code == 403


def test_foreign_tenant_and_partner_cannot_rename(db):
    album, _owner, _partner, _owner_user, partner_user = _shared_album(db)
    stranger_user = make_current_user(make_tenant(db).id, role="writer")

    for user in (partner_user, stranger_user):
        with pytest.raises(HTTPException) as exc_info:
            files_routes.rename_album(album.id, PhotoAlbumUpdate(name="Übernommen"), db, user)
        assert exc_info.value.status_code == 404
    db.refresh(album)
    assert album.name == "Album"


# --- löschen --------------------------------------------------------------------------------


def test_delete_album_keeps_the_photos(db):
    album, owner, _partner, owner_user, _partner_user = _shared_album(db)
    photo = _make_gallery_file(db, owner.id)
    files_routes.add_album_items(album.id, PhotoAlbumItemsUpdate(file_ids=[photo.public_id]), db, owner_user)
    album_id = album.id

    files_routes.delete_album(album_id, db, owner_user)

    db.expire_all()
    assert db.get(PhotoAlbum, album_id) is None
    assert db.query(PhotoAlbumItem).filter_by(album_id=album_id).count() == 0
    assert db.query(PhotoAlbumTenantShare).filter_by(album_id=album_id).count() == 0
    assert db.get(StoredFile, photo.id) is not None


def test_partner_and_stranger_cannot_delete_album(db):
    album, _owner, _partner, _owner_user, partner_user = _shared_album(db)
    stranger_user = make_current_user(make_tenant(db).id, role="writer")

    for user in (partner_user, stranger_user):
        with pytest.raises(HTTPException) as exc_info:
            files_routes.delete_album(album.id, db, user)
        assert exc_info.value.status_code == 404
    assert db.get(PhotoAlbum, album.id) is not None


def test_automatic_album_cannot_be_deleted(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id)
    album = PhotoAlbum(tenant_id=tenant.id, name="Zyklus", kind="cycle", cycle_config_id=cycle_config.id, cycle_year=2026)
    db.add(album)
    db.flush()
    user = make_current_user(tenant.id, role="writer")

    with pytest.raises(HTTPException) as exc_info:
        files_routes.delete_album(album.id, db, user)
    assert exc_info.value.status_code == 422


# --- Fotos aus dem Album nehmen -------------------------------------------------------------


def test_owner_can_remove_any_photo_and_it_stays_in_the_gallery(db):
    album, owner, partner, owner_user, partner_user = _shared_album(db)
    owner_photo = _make_gallery_file(db, owner.id, "owner.png")
    partner_photo = _make_gallery_file(db, partner.id, "partner.png")
    files_routes.add_album_items(album.id, PhotoAlbumItemsUpdate(file_ids=[owner_photo.public_id]), db, owner_user)
    files_routes.add_album_items(album.id, PhotoAlbumItemsUpdate(file_ids=[partner_photo.public_id]), db, partner_user)

    result = files_routes.remove_album_items(
        album.id, PhotoAlbumItemsUpdate(file_ids=[owner_photo.public_id, partner_photo.public_id]), db, owner_user
    )

    assert result.removed == 2
    assert _items(db, album) == set()
    assert db.get(StoredFile, owner_photo.id) is not None
    assert db.get(StoredFile, partner_photo.id) is not None


def test_partner_can_remove_only_own_photos(db):
    album, owner, partner, owner_user, partner_user = _shared_album(db)
    owner_photo = _make_gallery_file(db, owner.id, "owner.png")
    partner_photo = _make_gallery_file(db, partner.id, "partner.png")
    files_routes.add_album_items(album.id, PhotoAlbumItemsUpdate(file_ids=[owner_photo.public_id]), db, owner_user)
    files_routes.add_album_items(album.id, PhotoAlbumItemsUpdate(file_ids=[partner_photo.public_id]), db, partner_user)

    with pytest.raises(HTTPException) as exc_info:
        files_routes.remove_album_items(album.id, PhotoAlbumItemsUpdate(file_ids=[owner_photo.public_id]), db, partner_user)
    assert exc_info.value.status_code == 404
    assert _items(db, album) == {owner_photo.public_id, partner_photo.public_id}

    result = files_routes.remove_album_items(album.id, PhotoAlbumItemsUpdate(file_ids=[partner_photo.public_id]), db, partner_user)
    assert result.removed == 1
    assert _items(db, album) == {owner_photo.public_id}


def test_remove_rejects_photo_not_in_album_and_foreign_album(db):
    tenant = make_tenant(db)
    album = _make_album(db, tenant.id)
    user = make_current_user(tenant.id, role="writer")
    photo = _make_gallery_file(db, tenant.id)

    with pytest.raises(HTTPException) as exc_info:
        files_routes.remove_album_items(album.id, PhotoAlbumItemsUpdate(file_ids=[photo.public_id]), db, user)
    assert exc_info.value.status_code == 404

    stranger_user = make_current_user(make_tenant(db).id, role="writer")
    with pytest.raises(HTTPException) as exc_info:
        files_routes.remove_album_items(album.id, PhotoAlbumItemsUpdate(file_ids=[photo.public_id]), db, stranger_user)
    assert exc_info.value.status_code == 404


# --- Protokollbild im geteilten Album (Audit Dateien/Fotos) ---------------------------------


def _make_protocol_image(db, tenant_id: int, number: str = "1/2026") -> StoredFile:
    from datetime import date

    from app.models.entities import ProtocolImage
    from tests.factories import make_protocol, make_protocol_element, make_protocol_element_block, make_template

    template = make_template(db, tenant_id)
    protocol = make_protocol(db, tenant_id, template.id, protocol_number=number, protocol_date=date(2026, 1, 1))
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={})
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name="protokoll-bild.png", mime_type="image/png",
        storage_path="uploads/tenant-x/block-x/protokoll-bild.png", scan_status="clean",
    )
    db.add(stored_file)
    db.flush()
    db.add(ProtocolImage(protocol_element_block_id=block.id, stored_file_id=stored_file.id, sort_index=0))
    db.flush()
    return stored_file


def test_partner_can_read_protocol_image_in_shared_album_but_not_outside(db):
    from app.services.access_service import AccessService

    album, owner, _partner, _owner_user, partner_user = _shared_album(db)
    in_album = _make_protocol_image(db, owner.id)
    db.add(PhotoAlbumItem(album_id=album.id, file_id=in_album.public_id))
    db.commit()

    AccessService().ensure_can_read_stored_file(db, partner_user, in_album.id)  # darf nicht werfen

    other = _make_protocol_image(db, owner.id, "2/2026")
    db.commit()
    with pytest.raises(HTTPException):
        AccessService().ensure_can_read_stored_file(db, partner_user, other.id)


def test_blocked_photo_cannot_be_added_to_album(db):
    tenant = make_tenant(db)
    album = _make_album(db, tenant.id)
    user = make_current_user(tenant.id, role="writer")
    photo = _make_gallery_file(db, tenant.id)
    photo.scan_status = "error"
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        files_routes.add_album_items(album.id, PhotoAlbumItemsUpdate(file_ids=[photo.public_id]), db, user)
    assert exc_info.value.status_code == 422


def test_accepting_a_share_requires_the_photo_sharing_feature_but_declining_does_not(db):
    from tests.factories import DEFAULT_TEST_FEATURES

    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)
    owner_user = make_current_user(owner.id, role="writer")
    files_routes.create_album_share(album.id, AlbumShareCreate(target_tenant_public_id=partner.public_id), db, owner_user)
    without_sharing = make_current_user(
        partner.id, role="writer", features=frozenset(DEFAULT_TEST_FEATURES) - {"photo_sharing"}
    )

    with pytest.raises(HTTPException) as exc_info:
        files_routes.respond_album_share(album.id, AlbumShareRespond(accept=True), db, without_sharing)
    assert exc_info.value.status_code == 403

    files_routes.respond_album_share(album.id, AlbumShareRespond(accept=False), db, without_sharing)
