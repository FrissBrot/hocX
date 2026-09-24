"""Mandantenuebergreifende Fotoalben: eine Einladung (photo_album_tenant_share) laedt einen
ANDEREN Mandanten in ein eigenes "manual"-Album ein. Der Besitzer bleibt photo_album.tenant_id;
diese Datei verwaltet nur die Einladungen und den daraus resultierenden Zugriffs-Radius
(accessible_tenant_ids_for_album), den files.py und access_service.py fuer alle Lese-/
Schreibpruefungen an einem Album/dessen Fotos konsultieren.

Nur "manual"-Alben sind teilbar - die drei automatisch gefuehrten Kinds (cycle/submission/
submission_element, siehe PhotoAlbum.kind) haengen an einer Quelle, die selbst nur im
Besitzer-Mandanten existiert (ein Zyklus/eine Abgabe eines anderen Mandanten waere fuer den
eingeladenen Mandanten ohnehin bedeutungslos)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import PhotoAlbum, PhotoAlbumTenantShare, Tenant


class AlbumShareError(Exception):
    """Raised for invite/respond/revoke preconditions - routes turn this into a 4xx response."""


def accessible_tenant_ids_for_album(db: Session, album_id: uuid.UUID) -> set[int]:
    """Owner tenant plus every tenant with an ACCEPTED share - the full set allowed to see
    this album and add/remove their own photos in it."""
    album = db.get(PhotoAlbum, album_id)
    if album is None:
        return set()
    accepted = db.scalars(
        select(PhotoAlbumTenantShare.tenant_id).where(
            PhotoAlbumTenantShare.album_id == album_id,
            PhotoAlbumTenantShare.status == "accepted",
        )
    )
    return {album.tenant_id, *accepted}


def get_accessible_album(db: Session, album_id: uuid.UUID, tenant_id: int) -> PhotoAlbum | None:
    """The album if `tenant_id` may see it (owner or accepted share partner), else None - the
    single access check every album/album-item/share-link route should go through."""
    album = db.get(PhotoAlbum, album_id)
    if album is None or tenant_id not in accessible_tenant_ids_for_album(db, album_id):
        return None
    return album


def accessible_album_ids_for_tenant(db: Session, tenant_id: int) -> list[uuid.UUID]:
    """Albums NOT owned by `tenant_id` that it can nonetheless see via an accepted share -
    the counterpart list_albums_with_stats unions with the tenant's own albums."""
    return list(
        db.scalars(
            select(PhotoAlbumTenantShare.album_id).where(
                PhotoAlbumTenantShare.tenant_id == tenant_id,
                PhotoAlbumTenantShare.status == "accepted",
            )
        )
    )


@dataclass
class AlbumShareRow:
    tenant_public_id: uuid.UUID
    tenant_name: str
    status: str


def list_shares_for_album(db: Session, album_id: uuid.UUID) -> list[AlbumShareRow]:
    rows = db.execute(
        select(PhotoAlbumTenantShare.status, Tenant.public_id, Tenant.name)
        .join(Tenant, Tenant.id == PhotoAlbumTenantShare.tenant_id)
        .where(PhotoAlbumTenantShare.album_id == album_id)
        .order_by(Tenant.name)
    ).all()
    return [AlbumShareRow(tenant_public_id=row.public_id, tenant_name=row.name, status=row.status) for row in rows]


def invite(db: Session, album: PhotoAlbum, *, target_tenant_id: int, invited_by: int | None) -> PhotoAlbumTenantShare:
    if album.kind != "manual":
        raise AlbumShareError("Nur manuell erstellte Alben können mit anderen Mandanten geteilt werden.")
    if target_tenant_id == album.tenant_id:
        raise AlbumShareError("Dieser Mandant besitzt das Album bereits.")
    existing = db.get(PhotoAlbumTenantShare, {"album_id": album.id, "tenant_id": target_tenant_id})
    if existing is not None:
        raise AlbumShareError("Für diesen Mandanten besteht bereits eine Freigabe oder Anfrage.")
    share = PhotoAlbumTenantShare(album_id=album.id, tenant_id=target_tenant_id, status="pending", invited_by=invited_by)
    db.add(share)
    db.commit()
    db.refresh(share)
    return share


def respond(db: Session, *, album_id: uuid.UUID, tenant_id: int, accept: bool, responded_by: int | None) -> PhotoAlbumTenantShare:
    share = db.get(PhotoAlbumTenantShare, {"album_id": album_id, "tenant_id": tenant_id})
    if share is None or share.status != "pending":
        raise AlbumShareError("Keine offene Anfrage für dieses Album gefunden.")
    share.status = "accepted" if accept else "declined"
    share.responded_by = responded_by
    share.responded_at = datetime.now(UTC)
    db.commit()
    db.refresh(share)
    return share


def revoke(db: Session, *, album_id: uuid.UUID, tenant_id: int, acting_tenant_id: int, album_owner_tenant_id: int) -> None:
    """Either side can end a share: the owner revokes it, or the shared-with tenant leaves it -
    both are the same operation (delete the row), just from different actors."""
    if acting_tenant_id not in (album_owner_tenant_id, tenant_id):
        raise AlbumShareError("Nur der Besitzer oder der geteilte Mandant kann diese Freigabe beenden.")
    share = db.get(PhotoAlbumTenantShare, {"album_id": album_id, "tenant_id": tenant_id})
    if share is None:
        raise AlbumShareError("Keine Freigabe für diesen Mandanten gefunden.")
    db.delete(share)
    db.commit()


@dataclass
class PendingShareRequest:
    album_id: uuid.UUID
    album_name: str
    owner_tenant_name: str
    created_at: datetime


def list_pending_for_tenant(db: Session, tenant_id: int) -> list[PendingShareRequest]:
    rows = db.execute(
        select(PhotoAlbumTenantShare.album_id, PhotoAlbum.name, Tenant.name, PhotoAlbumTenantShare.created_at)
        .join(PhotoAlbum, PhotoAlbum.id == PhotoAlbumTenantShare.album_id)
        .join(Tenant, Tenant.id == PhotoAlbum.tenant_id)
        .where(PhotoAlbumTenantShare.tenant_id == tenant_id, PhotoAlbumTenantShare.status == "pending")
        .order_by(PhotoAlbumTenantShare.created_at.desc())
    ).all()
    return [
        PendingShareRequest(album_id=row[0], album_name=row[1], owner_tenant_name=row[2], created_at=row[3])
        for row in rows
    ]
