"""Anbieter der Zugangslinks-Übersicht (app/public_links/__init__.py). Jede Funktion liefert nur
Links, die gerade gelten: widerrufene, abgelaufene und benutzte erscheinen nicht."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.entities import (
    AccountToken,
    AppUser,
    CalendarFeed,
    PhotoAlbum,
    PhotoAlbumTenantShare,
    ShareLink,
    SubmissionAccessToken,
    SubmissionAssignment,
    SubmissionLink,
    Tenant,
    submission_assignment_link_table,
)
from app.public_links import Provider, PublicLink, register


def _names(db: Session, user_ids: set[int | None]) -> dict[int, str]:
    ids = [uid for uid in user_ids if uid is not None]
    if not ids:
        return {}
    return dict(db.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(ids))).all())


# ── Freigabelinks für Dateien und Alben ─────────────────────────────


def _share_links(db: Session, tenant_id: int) -> list[PublicLink]:
    from app.services import share_link_service

    rows = [row for row in share_link_service.list_for_tenant(db, tenant_id) if share_link_service.status_for(row.link) == "active"]
    links = []
    for row in rows:
        link = row.link
        album = link.album_id is not None
        # Partner-Link auf ein eigenes Album: der Partner verwaltet ihn, wir sehen ihn trotzdem
        partner = link.tenant_id != tenant_id
        params: dict[str, str | int] = {"count": row.file_count}
        if album:
            params["album"] = row.album_name or ""
        if partner:
            params["partner"] = db.scalar(select(Tenant.name).where(Tenant.id == link.tenant_id)) or ""
        links.append(PublicLink(
            kind="share_album_partner" if partner else ("share_album" if album else "share_files"),
            id=str(link.id), label=link.name, params=params, created_at=link.created_at,
            created_by=None if partner else row.created_by_name,
            expiry="date" if link.expires_at else "never", expires_at=link.expires_at,
            manage_href=None if partner else "/shared-links",
        ))
    return links


register(Provider(
    kind="share_link", token_columns=("share_link.token",), public_routes=("/api/public/share/",), collect=_share_links,
))


# ── Abgabebox ────────────────────────────────────────────────────────


def _submission_links(db: Session, tenant_id: int) -> list[PublicLink]:
    links = db.scalars(select(SubmissionLink).where(SubmissionLink.tenant_id == tenant_id).order_by(SubmissionLink.name)).all()
    if not links:
        return []
    titles: dict[int, list[str]] = {}
    for link_id, title in db.execute(
        select(submission_assignment_link_table.c.link_id, SubmissionAssignment.title)
        .join(SubmissionAssignment, SubmissionAssignment.id == submission_assignment_link_table.c.assignment_id)
        .where(
            submission_assignment_link_table.c.link_id.in_([link.id for link in links]),
            SubmissionAssignment.tenant_id == tenant_id, SubmissionAssignment.is_active.is_(True),
        )
        .order_by(SubmissionAssignment.title)
    ):
        titles.setdefault(link_id, []).append(title)
    return [
        PublicLink(
            kind="submission_link", id=str(link.public_id), label=link.name,
            params={"count": len(titles.get(link.id, [])), "assignments": ", ".join(titles.get(link.id, []))},
            created_at=link.created_at, expiry="window", manage_href="/submission-assignments",
        )
        for link in links
    ]


register(Provider(
    kind="submission_link", token_columns=("submission_link.token",), public_routes=(), collect=_submission_links,
    services=("abgabebox-backend: /api/public/{link_token}/…",),
))


# ── Kalender-Abos (ICS) ──────────────────────────────────────────────


def _calendar_feeds(db: Session, tenant_id: int) -> list[PublicLink]:
    feeds = db.scalars(select(CalendarFeed).where(CalendarFeed.tenant_id == tenant_id).order_by(CalendarFeed.created_at)).all()
    names = _names(db, {feed.user_id for feed in feeds})
    return [
        PublicLink(
            kind=f"calendar_{feed.kind}", id=str(feed.public_id), label=feed.calendar_name,
            params={"person": names.get(feed.user_id, ""), "scope": feed.todo_scope if feed.kind == "todos" else ""},
            created_at=feed.token_created_at, created_by=names.get(feed.user_id), expiry="never",
            last_used_at=feed.last_accessed_at, manage_href=None,
        )
        for feed in feeds
    ]


register(Provider(
    kind="calendar_feed", token_columns=("calendar_feed.token_hash", "calendar_feed.token_encrypted"),
    public_routes=("/api/public/calendar/",), collect=_calendar_feeds,
))


# ── Einladung und Passwort-Links ─────────────────────────────────────


def _account_links(db: Session, tenant_id: int) -> list[PublicLink]:
    now = datetime.now(UTC)
    tokens = db.scalars(
        select(AccountToken).where(
            AccountToken.tenant_id == tenant_id, AccountToken.used_at.is_(None), AccountToken.revoked_at.is_(None),
            or_(AccountToken.expires_at.is_(None), AccountToken.expires_at > now),
        ).order_by(AccountToken.created_at)
    ).all()
    names = _names(db, {token.user_id for token in tokens} | {token.created_by_user_id for token in tokens})
    people = dict(db.execute(select(AppUser.id, AppUser.public_id).where(AppUser.id.in_([token.user_id for token in tokens] or [-1]))).all())
    return [
        PublicLink(
            kind=f"account_{token.purpose}", id=str(token.id), label=names.get(token.user_id, ""),
            params={"person": names.get(token.user_id, ""), "sent": 1 if token.sent_at else 0},
            created_at=token.created_at, created_by=names.get(token.created_by_user_id) if token.created_by_user_id else None,
            expiry="single_use", expires_at=token.expires_at,
            manage_href=f"/participants?open={people[token.user_id]}" if token.user_id in people else None,
        )
        for token in tokens
    ]


register(Provider(
    kind="account_link", token_columns=("account_token.token_hash",),
    # Einlösen über /api/auth/account-link/… (Anmeldebereich, siehe EXEMPT_PUBLIC_ROUTES)
    public_routes=("/api/auth/account-link/",), collect=_account_links,
))


# ── Alben, die mit anderen Vereinen geteilt sind ─────────────────────


def _album_partners(db: Session, tenant_id: int) -> list[PublicLink]:
    rows = db.execute(
        select(PhotoAlbumTenantShare, PhotoAlbum.name, Tenant.name.label("partner"))
        .join(PhotoAlbum, PhotoAlbum.id == PhotoAlbumTenantShare.album_id)
        .join(Tenant, Tenant.id == PhotoAlbumTenantShare.tenant_id)
        .where(PhotoAlbum.tenant_id == tenant_id, PhotoAlbumTenantShare.tenant_id != tenant_id, PhotoAlbumTenantShare.status.in_(("pending", "accepted")))
        .order_by(PhotoAlbum.name)
    ).all()
    names = _names(db, {row.PhotoAlbumTenantShare.invited_by for row in rows})
    return [
        PublicLink(
            kind="album_partner", id=f"{row.PhotoAlbumTenantShare.album_id}:{row.PhotoAlbumTenantShare.tenant_id}", label=row.name,
            params={"partner": row.partner, "status": row.PhotoAlbumTenantShare.status,
                    "publicLinks": 1 if row.PhotoAlbumTenantShare.partner_public_links else 0},
            created_at=getattr(row.PhotoAlbumTenantShare, "created_at", None),
            created_by=names.get(row.PhotoAlbumTenantShare.invited_by), expiry="never", manage_href="/photos",
        )
        for row in rows
    ]


register(Provider(kind="album_partner", token_columns=(), public_routes=(), collect=_album_partners))



# ── Persönliche Abgabe-Links (Verantwortliche ohne Login) ────────────


def _submission_access(db: Session, tenant_id: int) -> list[PublicLink]:
    now = datetime.now(UTC)
    rows = db.execute(
        select(SubmissionAccessToken, SubmissionAssignment.title, SubmissionAssignment.owner_access)
        .join(SubmissionAssignment, SubmissionAssignment.id == SubmissionAccessToken.assignment_id)
        .where(
            SubmissionAccessToken.tenant_id == tenant_id, SubmissionAssignment.tenant_id == tenant_id,
            SubmissionAccessToken.revoked_at.is_(None), SubmissionAccessToken.expires_at > now,
            SubmissionAssignment.owner_access != "off",
        )
        .order_by(SubmissionAccessToken.created_at.desc())
    ).all()
    names = _names(db, {row.SubmissionAccessToken.participant_id for row in rows})
    return [
        PublicLink(
            kind="submission_access", id=str(row.SubmissionAccessToken.id), label=row.title,
            params={"person": names.get(row.SubmissionAccessToken.participant_id, ""), "assignment": row.title, "level": row.owner_access},
            created_at=row.SubmissionAccessToken.created_at, created_by=None, expiry="date",
            expires_at=row.SubmissionAccessToken.expires_at, last_used_at=row.SubmissionAccessToken.last_used_at,
            manage_href="/submission-assignments",
        )
        for row in rows
    ]


register(Provider(
    kind="submission_access", token_columns=("submission_access_token.token_hash",),
    public_routes=("/api/public/submission-access/",), collect=_submission_access,
))
