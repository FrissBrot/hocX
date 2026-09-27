"""Oeffentliche Download-Links fuer Dateien/Fotos: der Token IST die Authentifizierung (Teil
der URL, siehe frontend's /share/[token] Seite), analog zu submission_link_service.py. Ein
Link zeigt entweder auf eine feste Dateiauswahl (share_link_file) oder "live" auf ein ganzes
Album (album_id gesetzt - zeigt immer den aktuellen Album-Inhalt, auch neu hinzugefuegte
Fotos)."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import AppUser, PhotoAlbum, PhotoAlbumItem, ShareLink, ShareLinkFile
from app.services import photo_album_share_service

# 24 Bytes = 192 Bit Entropie, als URL-safe Base64 (32 Zeichen) - nicht erratbar. Gleiches Mass
# wie submission_link_service.generate_token().
_TOKEN_BYTES = 24


def generate_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


class ShareLinkError(Exception):
    """Raised for create() preconditions - the route turns this into a 422."""


def create_for_files(
    db: Session, *, tenant_id: int, name: str, file_ids: list[uuid.UUID], expires_at: datetime | None, created_by: int | None
) -> ShareLink:
    if not file_ids or len(file_ids) > 200:
        raise ShareLinkError("Bitte 1 bis 200 Dateien auswählen.")
    link = ShareLink(tenant_id=tenant_id, name=name, token=generate_token(), expires_at=expires_at, created_by=created_by)
    db.add(link)
    db.flush()
    db.add_all([ShareLinkFile(share_link_id=link.id, file_id=file_id) for file_id in dict.fromkeys(file_ids)])
    db.commit()
    db.refresh(link)
    return link


def create_for_album(
    db: Session, *, tenant_id: int, name: str, album: PhotoAlbum, expires_at: datetime | None, created_by: int | None
) -> ShareLink:
    photo_album_share_service.release_stale_pending(db, album.id)
    link = ShareLink(tenant_id=tenant_id, name=name, token=generate_token(), album_id=album.id, expires_at=expires_at, created_by=created_by)
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def revoke(db: Session, link: ShareLink) -> None:
    link.revoked_at = datetime.now(UTC)
    db.commit()


def resolve_active(db: Session, token: str) -> ShareLink | None:
    """None for an unknown, revoked, or expired token - callers don't distinguish which, so a
    guesser can't learn whether a token ever existed."""
    link = db.scalar(select(ShareLink).where(ShareLink.token == token))
    if link is None or link.revoked_at is not None:
        return None
    if link.expires_at is not None and link.expires_at <= datetime.now(UTC):
        return None
    return link


def file_ids_for_link(db: Session, link: ShareLink) -> list[uuid.UUID]:
    if link.album_id is not None:
        # Noch nicht freigegebene Fotos (share_pending) gehoeren nicht in den oeffentlichen Link.
        return list(
            db.scalars(
                select(PhotoAlbumItem.file_id).where(PhotoAlbumItem.album_id == link.album_id, PhotoAlbumItem.share_pending.is_(False))
            )
        )
    return list(db.scalars(select(ShareLinkFile.file_id).where(ShareLinkFile.share_link_id == link.id)))


@dataclass
class ShareLinkOverviewRow:
    link: ShareLink
    album_name: str | None
    file_count: int
    created_by_name: str | None


def list_for_tenant(db: Session, tenant_id: int) -> list[ShareLinkOverviewRow]:
    links = list(db.scalars(select(ShareLink).where(ShareLink.tenant_id == tenant_id).order_by(ShareLink.created_at.desc())))
    if not links:
        return []

    album_ids = [link.album_id for link in links if link.album_id is not None]
    album_names = {}
    if album_ids:
        album_names = dict(db.execute(select(PhotoAlbum.id, PhotoAlbum.name).where(PhotoAlbum.id.in_(album_ids))).all())

    user_ids = [link.created_by for link in links if link.created_by is not None]
    user_names = {}
    if user_ids:
        user_names = dict(db.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(user_ids))).all())

    file_link_ids = [link.id for link in links if link.album_id is None]
    file_counts_by_link: dict[uuid.UUID, int] = {}
    if file_link_ids:
        rows = db.execute(
            select(ShareLinkFile.share_link_id, func.count())
            .where(ShareLinkFile.share_link_id.in_(file_link_ids))
            .group_by(ShareLinkFile.share_link_id)
        ).all()
        file_counts_by_link = dict(rows)

    album_item_counts: dict[uuid.UUID, int] = {}
    if album_ids:
        rows = db.execute(
            select(PhotoAlbumItem.album_id, func.count())
            .where(PhotoAlbumItem.album_id.in_(album_ids), PhotoAlbumItem.share_pending.is_(False))
            .group_by(PhotoAlbumItem.album_id)
        ).all()
        album_item_counts = dict(rows)

    results = []
    for link in links:
        if link.album_id is not None:
            file_count = album_item_counts.get(link.album_id, 0)
            album_name = album_names.get(link.album_id)
        else:
            file_count = file_counts_by_link.get(link.id, 0)
            album_name = None
        results.append(
            ShareLinkOverviewRow(
                link=link,
                album_name=album_name,
                file_count=file_count,
                created_by_name=user_names.get(link.created_by) if link.created_by is not None else None,
            )
        )
    return results


def status_for(link: ShareLink) -> str:
    if link.revoked_at is not None:
        return "revoked"
    if link.expires_at is not None and link.expires_at <= datetime.now(UTC):
        return "expired"
    return "active"
