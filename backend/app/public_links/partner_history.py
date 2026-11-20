"""Verlauf der Partner-Organisationen (Zugangslinks › Reiter Partner-Organisationen).

Zeigt, was Partner mit den geteilten Alben DIESES Mandanten gemacht haben und was der Mandant
selbst freigegeben hat. Quelle sind ausschliesslich bestehende Daten, kein neues Protokoll:

- ``photo_album_tenant_share``: Einladung (``created_at``, eigene Person ``invited_by``) und
  Antwort des Partners (``responded_at``, ``status`` angenommen/abgelehnt).
- ``share_link`` auf eigene Alben, angelegt von einem Partner (``tenant_id`` ≠ eigener Mandant):
  öffentlicher Link erstellt (Name, Ablauf).

Nicht enthalten, weil hocX es nicht festhält: Downloads und Ansichten (weder durch Partner noch
über öffentliche Links), wann ein Partner Fotos ins Album gelegt hat (``photo_album_item`` hat
keinen Zeitpunkt), wer einen Partner-Link widerrufen hat, und beendete Freigaben (die Zeile wird
gelöscht).

Datenschutz: nur Alben dieses Mandanten; Partner erscheinen nur als Organisationsname (keine
Personen des Partners), eigene Personen mit Anzeigenamen; keine IP- oder E-Mail-Adressen.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import AppUser, PhotoAlbum, PhotoAlbumTenantShare, ShareLink, Tenant

PartnerEvent = Literal["invited", "accepted", "declined", "public_link_created"]

# Obergrenze der Einträge (neueste zuerst) - der vollständige Verlauf steht unter Organisation › Verlauf.
HISTORY_LIMIT = 200


@dataclass(frozen=True)
class PartnerHistoryEntry:
    at: datetime
    event: PartnerEvent
    # «partner»: Aktion der Partner-Organisation · «own»: Aktion einer eigenen Person
    actor: Literal["partner", "own"]
    partner: str
    # Nur bei eigenen Aktionen: Anzeigename der eigenen Person (None: Person gelöscht/unbekannt)
    person: str | None
    album: str
    link_name: str | None = None
    expires_at: datetime | None = None


def collect(db: Session, tenant_id: int, *, limit: int = HISTORY_LIMIT) -> list[PartnerHistoryEntry]:
    entries: list[PartnerHistoryEntry] = []

    shares = db.execute(
        select(PhotoAlbumTenantShare, PhotoAlbum.name.label("album"), Tenant.name.label("partner"))
        .join(PhotoAlbum, PhotoAlbum.id == PhotoAlbumTenantShare.album_id)
        .join(Tenant, Tenant.id == PhotoAlbumTenantShare.tenant_id)
        .where(PhotoAlbum.tenant_id == tenant_id, PhotoAlbumTenantShare.tenant_id != tenant_id)
    ).all()
    inviter_ids = {row.PhotoAlbumTenantShare.invited_by for row in shares if row.PhotoAlbumTenantShare.invited_by is not None}
    # Nur eigene Personen: invited_by ist immer jemand des Besitzer-Mandanten
    names = dict(
        db.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(inviter_ids), AppUser.tenant_id == tenant_id)).all()
    ) if inviter_ids else {}
    for row in shares:
        share = row.PhotoAlbumTenantShare
        entries.append(PartnerHistoryEntry(
            at=share.created_at, event="invited", actor="own", partner=row.partner,
            person=names.get(share.invited_by) if share.invited_by is not None else None, album=row.album,
        ))
        if share.responded_at is not None and share.status in ("accepted", "declined"):
            entries.append(PartnerHistoryEntry(
                at=share.responded_at, event="accepted" if share.status == "accepted" else "declined",
                actor="partner", partner=row.partner, person=None, album=row.album,
            ))

    partner_links = db.execute(
        select(ShareLink.name, ShareLink.created_at, ShareLink.expires_at, PhotoAlbum.name.label("album"), Tenant.name.label("partner"))
        .join(PhotoAlbum, PhotoAlbum.id == ShareLink.album_id)
        .join(Tenant, Tenant.id == ShareLink.tenant_id)
        .where(PhotoAlbum.tenant_id == tenant_id, ShareLink.tenant_id != tenant_id)
    ).all()
    for row in partner_links:
        entries.append(PartnerHistoryEntry(
            at=row.created_at, event="public_link_created", actor="partner", partner=row.partner, person=None,
            album=row.album, link_name=row.name, expires_at=row.expires_at,
        ))

    entries.sort(key=lambda entry: entry.at, reverse=True)
    return entries[:limit]
