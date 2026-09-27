"""Mandantenuebergreifende Fotoalben: eine Einladung (photo_album_tenant_share) laedt einen
ANDEREN Mandanten in ein eigenes Album ein - egal ob manuell erstellt oder automatisch
gefuehrt (kind='cycle'/'submission'/'submission_element', siehe PhotoAlbum.kind). Der Besitzer
bleibt photo_album.tenant_id; diese Datei verwaltet nur die Einladungen und den daraus
resultierenden Zugriffs-Radius (accessible_tenant_ids_for_album), den files.py und
access_service.py fuer alle Lese-/Schreibpruefungen an einem Album/dessen Fotos konsultieren.

Die Freigabe wirkt auf das Album als Ganzes, nicht auf eine Foto-Momentaufnahme: Fotos, die der
Besitzer-Mandant spaeter ueber seine normale Upload-/Sync-Pipeline in ein bereits geteiltes
Album einordnet (auch automatisch, z.B. photo_album_service.assign_uploaded_files/
sync_submission_uploads), werden dem akzeptierten Partner-Mandanten automatisch mit sichtbar -
kein erneutes Teilen noetig. Dass ein Zyklus/eine Abgabe selbst nur im Besitzer-Mandanten
existiert, spielt dabei keine Rolle: der Partner sieht nur die Fotos, nicht die zugrunde
liegende Zyklus-/Abgabe-Struktur.

Ausnahme: Fotos, die AUTOMATISCH in ein bereits geteiltes Album fallen, werden dort nur
vorgemerkt (photo_album_item.share_pending) - der Besitzer sieht sie sofort, Partner und
Album-Links erst nach manueller Freigabe (release_pending). Manuell hinzugefuegte Fotos und
Galerie-Uploads mit bestaetigter Freigabe sind sofort geteilt."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.models.entities import PhotoAlbum, PhotoAlbumItem, PhotoAlbumTenantShare, ShareLink, Tenant
from app.services import tenant_trust_service
from app.services.tenant_service import build_tenant_profile_image_url


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


def shared_album_ids(db: Session, album_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Die Alben aus `album_ids`, die gerade geteilt sind: offene oder angenommene
    Mandanten-Freigabe oder ein aktiver (nicht widerrufener, nicht abgelaufener) Album-Link.
    Eine offene Einladung zaehlt mit, weil der Partner beim Annehmen alles Freigegebene sieht."""
    if not album_ids:
        return set()
    tenant_shared = db.scalars(
        select(PhotoAlbumTenantShare.album_id).where(
            PhotoAlbumTenantShare.album_id.in_(album_ids), PhotoAlbumTenantShare.status.in_(("pending", "accepted"))
        )
    )
    linked = db.scalars(
        select(ShareLink.album_id).where(
            ShareLink.album_id.in_(album_ids),
            ShareLink.revoked_at.is_(None),
            or_(ShareLink.expires_at.is_(None), ShareLink.expires_at > datetime.now(UTC)),
        )
    )
    return set(tenant_shared) | set(linked)


def is_album_shared(db: Session, album_id: uuid.UUID) -> bool:
    return album_id in shared_album_ids(db, [album_id])


def hides_pending_items(album: PhotoAlbum, viewer_tenant_id: int | None) -> bool:
    """Noch nicht freigegebene Fotos (share_pending) sieht nur der Besitzer-Mandant."""
    return viewer_tenant_id != album.tenant_id


def release_pending(db: Session, album_id: uuid.UUID, file_ids: list[uuid.UUID] | None = None) -> int:
    """Gibt vorgemerkte Fotos frei (alle des Albums oder nur `file_ids`) - danach sehen
    Partner und Album-Links sie. Gibt die Anzahl freigegebener Fotos zurueck."""
    statement = update(PhotoAlbumItem).where(PhotoAlbumItem.album_id == album_id, PhotoAlbumItem.share_pending.is_(True))
    if file_ids is not None:
        statement = statement.where(PhotoAlbumItem.file_id.in_(file_ids))
    released = db.execute(statement.values(share_pending=False)).rowcount or 0
    db.commit()
    return released


def release_stale_pending(db: Session, album_id: uuid.UUID) -> None:
    """Vor dem (erneuten) Teilen eines gerade NICHT geteilten Albums: Vormerkungen aus einer
    frueheren, inzwischen beendeten Freigabe sind bedeutungslos - wer das Album jetzt teilt,
    teilt es als Ganzes. Bleibt ungecommittet; der Aufrufer committet mit der neuen Freigabe."""
    if not is_album_shared(db, album_id):
        db.execute(
            update(PhotoAlbumItem)
            .where(PhotoAlbumItem.album_id == album_id, PhotoAlbumItem.share_pending.is_(True))
            .values(share_pending=False)
        )


@dataclass
class PendingReleaseRow:
    album_id: uuid.UUID
    album_name: str
    album_kind: str
    pending_count: int


def list_pending_releases(db: Session, tenant_id: int) -> list[PendingReleaseRow]:
    """Eigene, aktuell geteilte Alben mit noch nicht freigegebenen Fotos - fuer den Hinweis
    auf der Fotos-Seite."""
    rows = db.execute(
        select(PhotoAlbum.id, PhotoAlbum.name, PhotoAlbum.kind, func.count())
        .join(PhotoAlbumItem, PhotoAlbumItem.album_id == PhotoAlbum.id)
        .where(PhotoAlbum.tenant_id == tenant_id, PhotoAlbumItem.share_pending.is_(True))
        .group_by(PhotoAlbum.id, PhotoAlbum.name, PhotoAlbum.kind)
        .order_by(PhotoAlbum.name)
    ).all()
    shared = shared_album_ids(db, [row[0] for row in rows])
    return [
        PendingReleaseRow(album_id=row[0], album_name=row[1], album_kind=row[2], pending_count=row[3])
        for row in rows
        if row[0] in shared
    ]


@dataclass
class AlbumShareRow:
    tenant_public_id: uuid.UUID
    # Name/Profilbild nur bei Trust zwischen Besitzer und Partner (tenant_trust_service) -
    # eine offene/abgelehnte Einladung an einen fremden Mandanten verraet sonst dessen Namen.
    tenant_name: str | None
    tenant_profile_image_url: str | None
    status: str
    # "eingeladen am" (created_at) bzw. "seit" (responded_at, beim Annehmen/Ablehnen gesetzt)
    # im Teilen-Dialog.
    invited_at: datetime
    responded_at: datetime | None


def list_shares_for_album(db: Session, album_id: uuid.UUID) -> list[AlbumShareRow]:
    owner_tenant_id = db.scalar(select(PhotoAlbum.tenant_id).where(PhotoAlbum.id == album_id))
    trusted = tenant_trust_service.trusted_tenant_ids(db, owner_tenant_id) if owner_tenant_id is not None else set()
    rows = db.execute(
        select(
            PhotoAlbumTenantShare.status,
            PhotoAlbumTenantShare.created_at,
            PhotoAlbumTenantShare.responded_at,
            Tenant.id,
            Tenant.public_id,
            Tenant.name,
            Tenant.profile_image_path,
        )
        .join(Tenant, Tenant.id == PhotoAlbumTenantShare.tenant_id)
        .where(PhotoAlbumTenantShare.album_id == album_id)
        .order_by(PhotoAlbumTenantShare.created_at)
    ).all()
    return [
        AlbumShareRow(
            tenant_public_id=row.public_id,
            tenant_name=row.name if row.id in trusted else None,
            tenant_profile_image_url=build_tenant_profile_image_url(row.public_id, row.profile_image_path) if row.id in trusted else None,
            status=row.status,
            invited_at=row.created_at,
            responded_at=row.responded_at,
        )
        for row in rows
    ]


def invite(db: Session, album: PhotoAlbum, *, target_tenant_id: int, invited_by: int | None) -> PhotoAlbumTenantShare:
    """Jedes Album ist teilbar, auch automatisch gefuehrte (kind='cycle'/'submission'/
    'submission_element'): die Freigabe wirkt auf das Album als Ganzes, nicht auf eine
    Foto-Momentaufnahme. Alles, was beim Teilen im Album liegt, ist freigegeben; Fotos, die
    spaeter automatisch ueber die Upload-/Sync-Pipeline des Besitzers hineinfallen, sind bis
    zur manuellen Freigabe nur vorgemerkt (share_pending, siehe release_pending)."""
    if target_tenant_id == album.tenant_id:
        raise AlbumShareError("Dieser Mandant besitzt das Album bereits.")
    existing = db.get(PhotoAlbumTenantShare, {"album_id": album.id, "tenant_id": target_tenant_id})
    if existing is not None:
        raise AlbumShareError("Für diesen Mandanten besteht bereits eine Freigabe oder Anfrage.")
    release_stale_pending(db, album.id)
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
    if accept:
        # Erstes Annehmen begruendet den Trust zwischen beiden Mandanten (bleibt bestehen).
        owner_tenant_id = db.scalar(select(PhotoAlbum.tenant_id).where(PhotoAlbum.id == album_id))
        if owner_tenant_id is not None:
            tenant_trust_service.establish(db, owner_tenant_id, tenant_id)
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
