"""Geteilte Alben: der Partner-Mandant sieht nur die Fotos, nicht die Struktur dahinter
(photo_album_share_service, Moduldoku) - keine Termin-/Abgabe-/Zyklus-Titel, keine Tags und
keine Links in die Bereiche des Besitzers. Eigene Fotos des Partners behalten ihren Kontext."""
from app.api.routes import files as files_routes
from app.models.entities import GalleryImage, PhotoAlbumItem, StoredFile
from tests.factories import make_current_user, make_event, make_tenant
from tests.test_album_share_routes import _invite_and_accept, _make_album


def _list(db, user, album, *, search=None, tags=None):
    return files_routes.list_files(
        skip=0, limit=60, source=None, only_images=False, exclude_images=False, search=search, tags=tags,
        sort_by="created_at", sort_dir="desc", db=db, user=user, album_id=album.id,
        exclude_album_id=None, share_pending=None, date_from=None, date_to=None,
    )


def _photo(db, tenant_id: int, name: str, *, event_id: int | None = None, tags: list[str] | None = None) -> StoredFile:
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name=name, mime_type="image/png", storage_path=f"uploads/{name}", tags=tags or [], scan_status="clean",
    )
    db.add(stored_file)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=stored_file.id, event_id=event_id))
    db.flush()
    return stored_file


def test_partner_does_not_see_the_owners_context_of_shared_photos(db):
    owner = make_tenant(db)
    partner = make_tenant(db, "Partnerverein")
    event = make_event(db, owner.id, title="Elternabend Familie Muster")
    owner_photo = _photo(db, owner.id, "owner.png", event_id=event.id, tags=["Anna Muster"])
    album = _make_album(db, owner.id)
    db.add(PhotoAlbumItem(album_id=album.id, file_id=owner_photo.public_id, is_best=False))
    db.flush()
    _invite_and_accept(db, owner, partner, album)

    owner_view = {item.id: item for item in _list(db, make_current_user(owner.id, role="writer"), album)}
    partner_view = {item.id: item for item in _list(db, make_current_user(partner.id, role="writer"), album)}

    assert owner_view[owner_photo.public_id].ref_label == "Elternabend Familie Muster"
    assert owner_view[owner_photo.public_id].tags == ["Anna Muster"]
    seen = partner_view[owner_photo.public_id]
    assert "Muster" not in f"{seen.ref_label} {seen.context_label} {seen.origin_tag} {seen.ref_href}"
    assert seen.tags == []


def test_partner_cannot_probe_the_owners_tags_or_titles_by_searching(db):
    owner = make_tenant(db)
    partner = make_tenant(db, "Partnerverein")
    event = make_event(db, owner.id, title="Elternabend Familie Muster")
    owner_photo = _photo(db, owner.id, "owner.png", event_id=event.id, tags=["Anna Muster"])
    album = _make_album(db, owner.id)
    db.add(PhotoAlbumItem(album_id=album.id, file_id=owner_photo.public_id, is_best=False))
    db.flush()
    _invite_and_accept(db, owner, partner, album)
    owner_user = make_current_user(owner.id, role="writer")
    partner_user = make_current_user(partner.id, role="writer")

    assert [i.id for i in _list(db, owner_user, album, search="Muster")] == [owner_photo.public_id]
    assert [i.id for i in _list(db, owner_user, album, tags=["Anna Muster"])] == [owner_photo.public_id]
    assert _list(db, partner_user, album, search="Muster") == []
    assert _list(db, partner_user, album, tags=["Anna Muster"]) == []
    assert [i.id for i in _list(db, partner_user, album, search="owner")] == [owner_photo.public_id]


def test_partner_keeps_the_context_of_its_own_photos(db):
    owner = make_tenant(db)
    partner = make_tenant(db, "Partnerverein")
    album = _make_album(db, owner.id)
    _invite_and_accept(db, owner, partner, album)
    own = _photo(db, partner.id, "eigen.png", tags=["Sommer"])
    db.add(PhotoAlbumItem(album_id=album.id, file_id=own.public_id, is_best=False))
    db.flush()

    seen = {i.id: i for i in _list(db, make_current_user(partner.id, role="writer"), album, tags=["Sommer"])}

    assert seen[own.public_id].tags == ["Sommer"]
