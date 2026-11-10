"""Datenschutz-Audit PRIV-016: Gelöschte Fotos verschwinden aus Freigabelinks, und ein Dateilink
liefert nie eine Datei eines anderen Mandanten aus - auch nicht über einen verwaisten Eintrag in
share_link_file (kein Fremdschlüssel)."""
from __future__ import annotations

from sqlalchemy import select

from app.api.routes import files as files_routes
from app.api.routes import public_share as public_share_routes
from app.api.routes import share_links as share_links_routes
from app.models.entities import ShareLink, ShareLinkFile
from app.schemas.files import FileBulkDelete, ShareLinkCreate
from tests.factories import make_current_user, make_tenant
from tests.test_share_link_routes import _FakeRequest, _isolated_storage_root, _make_file  # noqa: F401  (Fixture)


def _token(created) -> str:
    return created.url.removeprefix("/share/")


def test_deleted_photo_disappears_from_file_link(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    keep = _make_file(db, tenant.id, "bleibt.png")
    gone = _make_file(db, tenant.id, "weg.png")
    created = share_links_routes.create_share_link(ShareLinkCreate(name="Lager", file_ids=[keep.public_id, gone.public_id]), db, user)

    files_routes.bulk_delete_files(FileBulkDelete(file_ids=[gone.public_id]), db, user)

    assert db.scalar(select(ShareLinkFile.file_id).where(ShareLinkFile.file_id == gone.public_id)) is None
    result = public_share_routes.get_public_share(_token(created), _FakeRequest(), db)
    assert [f.id for f in result.files] == [keep.public_id]


def test_file_link_never_serves_another_tenants_file(db):
    tenant = make_tenant(db)
    other = make_tenant(db, "Anderer Verein")
    user = make_current_user(tenant.id, role="writer")
    own = _make_file(db, tenant.id, "eigen.png")
    foreign = _make_file(db, other.id, "fremd.png")
    created = share_links_routes.create_share_link(ShareLinkCreate(name="Eigene", file_ids=[own.public_id]), db, user)
    link_id = db.scalar(select(ShareLink.id).where(ShareLink.token == _token(created)))
    # Verwaister/manipulierter Eintrag: zeigt auf die public_id einer fremden Datei.
    db.add(ShareLinkFile(share_link_id=link_id, file_id=foreign.public_id))
    db.flush()

    result = public_share_routes.get_public_share(_token(created), _FakeRequest(), db)

    assert [f.id for f in result.files] == [own.public_id]
