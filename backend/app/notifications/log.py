"""Versandprotokoll der E-Mails für das Plattform-Admin-Portal (/admin/notifications).

Die Tabelle notification ist Warteschlange und Protokoll zugleich (90 Tage, dann gelöscht, siehe
dispatch.run). Hier wird sie mandantenübergreifend gelesen - nur für Admin-Owner, und jeder Abruf
wird im Audit-Log festgehalten (wie das Fehlerprotokoll, PRIV-013). Der Mailinhalt selbst wird nie
gespeichert und erscheint deshalb auch hier nicht: nur wer, was, wann und mit welchem Ergebnis."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import AppUser, Notification, Tenant
from app.schemas.admin import NotificationLogEntry, NotificationLogPage
from app.core.sql_like import LIKE_ESCAPE, contains_pattern

STATUSES = ("pending", "sent", "skipped", "failed")


def list_log(db: Session, *, status: str | None = None, search: str | None = None, limit: int = 50, offset: int = 0) -> NotificationLogPage:
    conditions = []
    if status:
        conditions.append(Notification.status == status)
    needle = (search or "").strip()
    if needle:
        # % und _ sind Text (vorher entfernt: «max_muster@…» fand die Adresse nicht mehr)
        pattern = contains_pattern(needle)
        conditions.append(or_(*(column.ilike(pattern, escape=LIKE_ESCAPE) for column in (Tenant.name, AppUser.display_name, AppUser.email))))
    base = (
        select(Notification, Tenant.name.label("tenant_name"), AppUser.display_name.label("recipient_name"), AppUser.email.label("recipient_email"))
        .join(Tenant, Tenant.id == Notification.tenant_id)
        .join(AppUser, AppUser.id == Notification.recipient_id)
        .where(*conditions)
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(
        base.order_by(func.coalesce(Notification.sent_at, Notification.deliver_after).desc(), Notification.id.desc()).limit(limit).offset(offset)
    ).all()
    items = [
        NotificationLogEntry(
            id=row.Notification.public_id,
            created_at=row.Notification.created_at,
            deliver_after=row.Notification.deliver_after,
            sent_at=row.Notification.sent_at,
            tenant_name=row.tenant_name,
            recipient_name=row.recipient_name,
            # Sicherheitshinweis «E-Mail geändert» geht an die alte Adresse
            recipient_email=(row.Notification.payload or {}).get("old_email") if row.Notification.kind == "security.email_changed" else row.recipient_email,
            kind=row.Notification.kind,
            status=row.Notification.status,
            skip_reason=row.Notification.skip_reason,
            attempts=row.Notification.attempts,
            last_error=row.Notification.last_error,
        )
        for row in rows
    ]
    return NotificationLogPage(items=items, total=int(total))
