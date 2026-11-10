"""Audit MAIN-SEC-003: Öffentliche Album-Links eines Partner-Mandanten enden mit der
Album-Freigabe; der Album-Besitzer sieht sie und kann sie widerrufen."""

from app.api.routes import files as files_routes
from app.api.routes import share_links as share_links_routes
from app.models.entities import ShareLink
from app.services import share_link_service
from tests.factories import make_current_user, make_tenant
from tests.test_album_share_pending import _make_cycle_album, _share


def _partner_link(db):
    owner = make_tenant(db, name="Besitzer")
    partner = make_tenant(db, name="Partner")
    album = _make_cycle_album(db, owner.id)
    _share(db, owner, partner, album)
    link = share_link_service.create_for_album(
        db, tenant_id=partner.id, name="Partner-Link", album=album, expires_at=None, created_by=None
    )
    return owner, partner, album, link


def test_partner_album_link_dies_with_share_revocation(db):
    owner, partner, album, link = _partner_link(db)
    assert share_link_service.resolve_active(db, link.token) is not None

    files_routes.delete_album_share(album.id, partner.public_id, db=db, user=make_current_user(owner.id, role="writer"))

    assert share_link_service.resolve_active(db, link.token) is None
    assert db.get(ShareLink, link.id).revoked_at is not None


def test_partner_album_link_inactive_when_share_row_gone_without_revoke(db):
    """Auch ohne gesetztes revoked_at (z. B. Altbestand) prüft der Abruf den Zugriff."""
    from app.models.entities import PhotoAlbumTenantShare

    _, partner, album, link = _partner_link(db)
    db.delete(db.get(PhotoAlbumTenantShare, {"album_id": album.id, "tenant_id": partner.id}))
    db.flush()

    assert share_link_service.resolve_active(db, link.token) is None


def test_album_owner_sees_and_revokes_partner_link(db):
    owner, _, _, link = _partner_link(db)
    other = make_tenant(db, name="Fremd")

    owner_rows = share_link_service.list_for_tenant(db, owner.id)
    assert [row.link.id for row in owner_rows] == [link.id]
    assert share_link_service.list_for_tenant(db, other.id) == []
    assert share_link_service.can_manage(db, link, other.id) is False

    share_links_routes.revoke_share_link(link.id, db=db, user=make_current_user(owner.id, role="writer"))

    assert share_link_service.resolve_active(db, link.token) is None
