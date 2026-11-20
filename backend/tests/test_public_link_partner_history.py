"""Verlauf der Partner-Organisationen (Zugangslinks, GET /api/public-links/partner-history):
nur Alben des eigenen Mandanten, Partner nur als Organisationsname, keine IP/E-Mail."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.api.routes import public_links as route
from app.models.entities import PhotoAlbum, PhotoAlbumTenantShare, ShareLink
from app.public_links import partner_history
from tests.factories import make_current_user, make_participant, make_tenant


@pytest.fixture
def world(db):
    own = make_tenant(db, "Eigenverein")
    partner = make_tenant(db, "Pfadi Partner")
    third = make_tenant(db, "Drittverein")
    anna = make_participant(db, own.id, "Anna Eigen")
    bruno = make_participant(db, partner.id, "Bruno Partner")
    now = datetime.now(UTC)

    own_album = PhotoAlbum(tenant_id=own.id, name="Sommerlager")
    partner_album = PhotoAlbum(tenant_id=partner.id, name="Fremdes Album")
    third_album = PhotoAlbum(tenant_id=third.id, name="Drittalbum")
    db.add_all([own_album, partner_album, third_album])
    db.flush()
    db.add_all([
        # eigenes Album mit dem Partner geteilt, angenommen
        PhotoAlbumTenantShare(album_id=own_album.id, tenant_id=partner.id, status="accepted", invited_by=anna.id,
                              responded_by=bruno.id, responded_at=now - timedelta(days=1)),
        # Album des Partners mit uns geteilt: gehört nicht in unseren Verlauf
        PhotoAlbumTenantShare(album_id=partner_album.id, tenant_id=own.id, status="accepted", invited_by=bruno.id,
                              responded_by=anna.id, responded_at=now),
        # fremdes Album, mit dem Partner geteilt: gar nicht unseres
        PhotoAlbumTenantShare(album_id=third_album.id, tenant_id=partner.id, status="pending"),
        # öffentlicher Link des Partners auf unser Album
        ShareLink(tenant_id=partner.id, name="Lager-Rückblick", token=uuid.uuid4().hex, album_id=own_album.id,
                  created_by=bruno.id, expires_at=now + timedelta(days=30)),
        # eigener Link auf eigenes Album: keine Partner-Aktion
        ShareLink(tenant_id=own.id, name="Eigener Link", token=uuid.uuid4().hex, album_id=own_album.id, created_by=anna.id),
        # Partner-Link auf fremdes Album
        ShareLink(tenant_id=partner.id, name="Fremder Link", token=uuid.uuid4().hex, album_id=third_album.id),
        # unser Link auf das Partner-Album: Aktion auf fremdem Album
        ShareLink(tenant_id=own.id, name="Link aufs Partneralbum", token=uuid.uuid4().hex, album_id=partner_album.id),
    ])
    db.flush()
    return {"own": own, "partner": partner, "third": third}


def test_history_lists_own_and_partner_actions_on_own_albums(db, world):
    entries = partner_history.collect(db, world["own"].id)
    events = {(entry.event, entry.actor, entry.partner, entry.album) for entry in entries}
    assert events == {
        ("invited", "own", "Pfadi Partner", "Sommerlager"),
        ("accepted", "partner", "Pfadi Partner", "Sommerlager"),
        ("public_link_created", "partner", "Pfadi Partner", "Sommerlager"),
    }
    invited = next(entry for entry in entries if entry.event == "invited")
    assert invited.person == "Anna Eigen"
    link = next(entry for entry in entries if entry.event == "public_link_created")
    assert link.link_name == "Lager-Rückblick" and link.expires_at is not None
    # Partner nur als Organisation: keine Person des Partners
    assert all(entry.person is None for entry in entries if entry.actor == "partner")
    # neueste zuerst
    assert [entry.at for entry in entries] == sorted((entry.at for entry in entries), reverse=True)


def test_history_never_shows_foreign_albums(db, world):
    own_entries = partner_history.collect(db, world["own"].id)
    assert not {"Fremdes Album", "Drittalbum"} & {entry.album for entry in own_entries}
    assert not {"Fremder Link", "Eigener Link", "Link aufs Partneralbum"} & {entry.link_name for entry in own_entries}
    # Der Partner sieht in seinem Verlauf nur Aktionen auf SEINEM Album, nie unser Sommerlager
    partner_entries = partner_history.collect(db, world["partner"].id)
    assert {entry.album for entry in partner_entries} == {"Fremdes Album"}
    assert {(entry.event, entry.partner, entry.link_name) for entry in partner_entries} == {
        ("invited", "Eigenverein", None), ("accepted", "Eigenverein", None),
        ("public_link_created", "Eigenverein", "Link aufs Partneralbum"),
    }
    # Dritter: offene Einladung an den Partner (ohne einladende Person) und ein Partner-Link
    third_entries = partner_history.collect(db, world["third"].id)
    assert {entry.album for entry in third_entries} == {"Drittalbum"}
    assert {(entry.event, entry.person) for entry in third_entries} == {("invited", None), ("public_link_created", None)}
    assert "Sommerlager" not in {entry.album for entry in third_entries}


def test_route_requires_settings_manage_and_returns_no_contact_data(db, world):
    admin = make_current_user(world["own"].id, role="admin")
    result = route.list_partner_history(db=db, user=admin)
    assert len(result) == 3
    dumped = [item.model_dump() for item in result]
    assert all(set(item) == {"at", "event", "actor", "partner", "person", "album", "link_name", "expires_at"} for item in dumped)
    writer = make_current_user(world["own"].id, role="writer")
    with pytest.raises(HTTPException) as exc:
        route.list_partner_history(db=db, user=writer)
    assert exc.value.status_code == 403
