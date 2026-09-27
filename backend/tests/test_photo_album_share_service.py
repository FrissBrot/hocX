"""Tests for photo_album_share_service.py: mandantenuebergreifende Freigabe eines Fotoalbums
(manuell oder automatisch gefuehrt) an einen anderen Mandanten (invite -> pending ->
accepted/declined), und die daraus folgenden Zugriffsrechte
(accessible_tenant_ids_for_album/accessible_album_ids_for_tenant)."""

import uuid

import pytest

from app.models.entities import PhotoAlbum, PhotoAlbumItem
from app.services import photo_album_service, photo_album_share_service
from tests.factories import make_cycle_config, make_tenant


def _make_album(db, tenant_id: int, name: str = "Album", kind: str = "manual") -> PhotoAlbum:
    album = PhotoAlbum(tenant_id=tenant_id, name=name, kind=kind)
    db.add(album)
    db.flush()
    return album


def _make_cycle_album(db, tenant_id: int, name: str = "Zyklus-Album") -> PhotoAlbum:
    """kind='cycle' albums are auto-generated and DB-constrained (ck_photo_album_kind_fields)
    to always carry their cycle_config_id/cycle_year - unlike a "manual" album, which is the
    only kind _make_album's shortcut (no extra fields) may be used for."""
    cycle_config = make_cycle_config(db, tenant_id)
    album = PhotoAlbum(tenant_id=tenant_id, name=name, kind="cycle", cycle_config_id=cycle_config.id, cycle_year=2026)
    db.add(album)
    db.flush()
    return album


def test_invite_allows_automatically_managed_albums_too(db):
    """Sharing works on kind='cycle'/'submission'/'submission_element' albums exactly like on
    a manual one - the invite/accept mechanism doesn't care how an album's items got there."""
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_cycle_album(db, owner.id)

    share = photo_album_share_service.invite(db, album, target_tenant_id=partner.id, invited_by=None)

    assert share.status == "pending"


def test_photos_added_automatically_to_an_already_shared_album_wait_for_release(db):
    """The share covers the ALBUM, not a snapshot of its current items. A photo that the owner's
    normal upload/sync pipeline later files into an already-shared album (see
    photo_album_service.add_items) lands in the album right away but is only pre-marked
    (share_pending). The partner only sees it after it is released manually."""
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_cycle_album(db, owner.id)
    photo_album_share_service.invite(db, album, target_tenant_id=partner.id, invited_by=None)
    photo_album_share_service.respond(db, album_id=album.id, tenant_id=partner.id, accept=True, responded_by=None)

    new_photo_id = uuid.uuid4()
    photo_album_service.add_items(db, album, [new_photo_id])
    db.commit()

    assert db.get(PhotoAlbumItem, {"album_id": album.id, "file_id": new_photo_id}).share_pending is True
    assert photo_album_share_service.release_pending(db, album.id) == 1
    assert db.get(PhotoAlbumItem, {"album_id": album.id, "file_id": new_photo_id}).share_pending is False


def test_invite_rejects_the_owner_itself(db):
    owner = make_tenant(db)
    album = _make_album(db, owner.id)

    with pytest.raises(photo_album_share_service.AlbumShareError):
        photo_album_share_service.invite(db, album, target_tenant_id=owner.id, invited_by=None)


def test_invite_rejects_a_duplicate_invitation(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)
    photo_album_share_service.invite(db, album, target_tenant_id=partner.id, invited_by=None)

    with pytest.raises(photo_album_share_service.AlbumShareError):
        photo_album_share_service.invite(db, album, target_tenant_id=partner.id, invited_by=None)


def test_invite_creates_a_pending_share(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)

    share = photo_album_share_service.invite(db, album, target_tenant_id=partner.id, invited_by=None)

    assert share.status == "pending"
    assert share.album_id == album.id
    assert share.tenant_id == partner.id


def test_respond_raises_when_there_is_no_pending_invitation(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)

    with pytest.raises(photo_album_share_service.AlbumShareError):
        photo_album_share_service.respond(db, album_id=album.id, tenant_id=partner.id, accept=True, responded_by=None)


def test_respond_accept_marks_the_share_accepted(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)
    photo_album_share_service.invite(db, album, target_tenant_id=partner.id, invited_by=None)

    share = photo_album_share_service.respond(db, album_id=album.id, tenant_id=partner.id, accept=True, responded_by=None)

    assert share.status == "accepted"
    assert share.responded_at is not None


def test_respond_decline_marks_the_share_declined(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)
    photo_album_share_service.invite(db, album, target_tenant_id=partner.id, invited_by=None)

    share = photo_album_share_service.respond(db, album_id=album.id, tenant_id=partner.id, accept=False, responded_by=None)

    assert share.status == "declined"


def test_respond_cannot_be_repeated_once_settled(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)
    photo_album_share_service.invite(db, album, target_tenant_id=partner.id, invited_by=None)
    photo_album_share_service.respond(db, album_id=album.id, tenant_id=partner.id, accept=True, responded_by=None)

    with pytest.raises(photo_album_share_service.AlbumShareError):
        photo_album_share_service.respond(db, album_id=album.id, tenant_id=partner.id, accept=False, responded_by=None)


def test_revoke_allows_the_owner(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)
    photo_album_share_service.invite(db, album, target_tenant_id=partner.id, invited_by=None)
    photo_album_share_service.respond(db, album_id=album.id, tenant_id=partner.id, accept=True, responded_by=None)

    photo_album_share_service.revoke(db, album_id=album.id, tenant_id=partner.id, acting_tenant_id=owner.id, album_owner_tenant_id=owner.id)

    assert partner.id not in photo_album_share_service.accessible_tenant_ids_for_album(db, album.id)


def test_revoke_allows_the_partner_to_leave(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)
    photo_album_share_service.invite(db, album, target_tenant_id=partner.id, invited_by=None)
    photo_album_share_service.respond(db, album_id=album.id, tenant_id=partner.id, accept=True, responded_by=None)

    photo_album_share_service.revoke(db, album_id=album.id, tenant_id=partner.id, acting_tenant_id=partner.id, album_owner_tenant_id=owner.id)

    assert partner.id not in photo_album_share_service.accessible_tenant_ids_for_album(db, album.id)


def test_revoke_rejects_an_unrelated_third_tenant(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    stranger = make_tenant(db)
    album = _make_album(db, owner.id)
    photo_album_share_service.invite(db, album, target_tenant_id=partner.id, invited_by=None)
    photo_album_share_service.respond(db, album_id=album.id, tenant_id=partner.id, accept=True, responded_by=None)

    with pytest.raises(photo_album_share_service.AlbumShareError):
        photo_album_share_service.revoke(db, album_id=album.id, tenant_id=partner.id, acting_tenant_id=stranger.id, album_owner_tenant_id=owner.id)


def test_accessible_tenant_ids_for_album_includes_owner_and_only_accepted_partners(db):
    owner = make_tenant(db)
    accepted_partner = make_tenant(db)
    pending_partner = make_tenant(db)
    album = _make_album(db, owner.id)
    photo_album_share_service.invite(db, album, target_tenant_id=accepted_partner.id, invited_by=None)
    photo_album_share_service.respond(db, album_id=album.id, tenant_id=accepted_partner.id, accept=True, responded_by=None)
    photo_album_share_service.invite(db, album, target_tenant_id=pending_partner.id, invited_by=None)

    accessible = photo_album_share_service.accessible_tenant_ids_for_album(db, album.id)

    assert accessible == {owner.id, accepted_partner.id}


def test_accessible_album_ids_for_tenant_excludes_owned_albums(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)
    photo_album_share_service.invite(db, album, target_tenant_id=partner.id, invited_by=None)
    photo_album_share_service.respond(db, album_id=album.id, tenant_id=partner.id, accept=True, responded_by=None)

    assert photo_album_share_service.accessible_album_ids_for_tenant(db, partner.id) == [album.id]
    assert photo_album_share_service.accessible_album_ids_for_tenant(db, owner.id) == []


def test_get_accessible_album_returns_none_before_acceptance(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)
    photo_album_share_service.invite(db, album, target_tenant_id=partner.id, invited_by=None)

    assert photo_album_share_service.get_accessible_album(db, album.id, partner.id) is None
    assert photo_album_share_service.get_accessible_album(db, album.id, owner.id) is not None


def test_get_accessible_album_returns_it_once_accepted(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    album = _make_album(db, owner.id)
    photo_album_share_service.invite(db, album, target_tenant_id=partner.id, invited_by=None)
    photo_album_share_service.respond(db, album_id=album.id, tenant_id=partner.id, accept=True, responded_by=None)

    found = photo_album_share_service.get_accessible_album(db, album.id, partner.id)

    assert found is not None
    assert found.id == album.id


def test_list_pending_for_tenant_only_returns_open_invitations(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    pending_album = _make_album(db, owner.id, name="Offen")
    accepted_album = _make_album(db, owner.id, name="Angenommen")
    photo_album_share_service.invite(db, pending_album, target_tenant_id=partner.id, invited_by=None)
    photo_album_share_service.invite(db, accepted_album, target_tenant_id=partner.id, invited_by=None)
    photo_album_share_service.respond(db, album_id=accepted_album.id, tenant_id=partner.id, accept=True, responded_by=None)

    pending = photo_album_share_service.list_pending_for_tenant(db, partner.id)

    assert [row.album_name for row in pending] == ["Offen"]
    assert pending[0].owner_tenant_name == owner.name


def test_list_shares_for_album_reports_every_status(db):
    owner = make_tenant(db)
    accepted = make_tenant(db, "Akzeptiert AG")
    declined = make_tenant(db, "Abgelehnt AG")
    album = _make_album(db, owner.id)
    photo_album_share_service.invite(db, album, target_tenant_id=accepted.id, invited_by=None)
    photo_album_share_service.respond(db, album_id=album.id, tenant_id=accepted.id, accept=True, responded_by=None)
    photo_album_share_service.invite(db, album, target_tenant_id=declined.id, invited_by=None)
    photo_album_share_service.respond(db, album_id=album.id, tenant_id=declined.id, accept=False, responded_by=None)

    rows = {row.tenant_public_id: row for row in photo_album_share_service.list_shares_for_album(db, album.id)}

    assert {key: row.status for key, row in rows.items()} == {accepted.public_id: "accepted", declined.public_id: "declined"}
    # Name nur mit Trust: Annehmen begruendet ihn, Ablehnen nicht.
    assert rows[accepted.public_id].tenant_name == "Akzeptiert AG"
    assert rows[declined.public_id].tenant_name is None


def test_list_shares_for_album_reports_invited_and_responded_dates(db):
    owner = make_tenant(db)
    accepted = make_tenant(db, "Akzeptiert AG")
    pending = make_tenant(db, "Offen AG")
    album = _make_album(db, owner.id)
    photo_album_share_service.invite(db, album, target_tenant_id=accepted.id, invited_by=None)
    photo_album_share_service.respond(db, album_id=album.id, tenant_id=accepted.id, accept=True, responded_by=None)
    photo_album_share_service.invite(db, album, target_tenant_id=pending.id, invited_by=None)

    rows = {row.tenant_public_id: row for row in photo_album_share_service.list_shares_for_album(db, album.id)}

    assert rows[accepted.public_id].invited_at is not None
    assert rows[accepted.public_id].responded_at is not None
    assert rows[pending.public_id].invited_at is not None
    assert rows[pending.public_id].responded_at is None
