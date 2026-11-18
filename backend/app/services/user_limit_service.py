"""Benutzerlimit des Abos: Konten mit Login (aktiv), höchstens ``user_limit_override`` bzw.
``plan.included_user_limit`` (None = unbegrenzt). Teilnehmende ohne Login zählen nicht; offene
Einladungen zählen schon beim Einladen mit (Entscheid 18.11.2026), damit niemand erst beim
Annehmen am Limit scheitert.

Durchgesetzt beim Aktivieren eines Logins (Anlegen, Login einschalten, Konto reaktivieren) im
Mandanten selbst; das Plattform-Admin-Panel darf bewusst darüber hinaus gehen (Override).
Bestehende Konten über dem Limit (z. B. nach einem Downgrade) bleiben nutzbar - es kommen nur
keine neuen dazu (docs/FEATURE_ENTITLEMENT_ARCHITECTURE.md, Abschnitt Nutzungslimits).
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import AppUser, Plan, Tenant


def login_account_count(db: Session, tenant_id: int) -> int:
    """Konten, die sich anmelden können - ohne ausgetretene Personen (AppUser.has_left)."""
    from app.services.todo_fine_service import today

    return int(db.scalar(
        select(func.count(AppUser.id)).where(
            AppUser.tenant_id == tenant_id, AppUser.login_enabled.is_(True), AppUser.is_active.is_(True),
            or_(AppUser.left_at.is_(None), AppUser.left_at >= today()),
        )
    ) or 0)


def effective_user_limit(db: Session, tenant: Tenant) -> int | None:
    if tenant.user_limit_override is not None:
        return tenant.user_limit_override
    plan = db.get(Plan, tenant.plan_code) if tenant.plan_code is not None else None
    return plan.included_user_limit if plan is not None else None


def pending_invite_count(db: Session, tenant_id: int, *, excluding_user_id: int | None = None) -> int:
    """Konten ohne Login mit offener, gültiger Einladung (ohne die Person selbst, wenn sie gerade
    eingeladen wird oder annimmt - ihre eigene Einladung belegt keinen zusätzlichen Platz)."""
    from datetime import UTC, datetime

    from app.models import AccountToken

    statement = (
        select(func.count(func.distinct(AccountToken.user_id)))
        .join(AppUser, AppUser.id == AccountToken.user_id)
        .where(
            AccountToken.tenant_id == tenant_id, AccountToken.purpose == "invite",
            AccountToken.used_at.is_(None), AccountToken.revoked_at.is_(None), AccountToken.expires_at > datetime.now(UTC),
            AppUser.login_enabled.is_(False), AppUser.is_active.is_(True),
        )
    )
    if excluding_user_id is not None:
        statement = statement.where(AccountToken.user_id != excluding_user_id)
    return int(db.scalar(statement) or 0)


def ensure_login_capacity(db: Session, tenant_id: int, *, for_user_id: int | None = None) -> None:
    """Vor dem Aktivieren eines weiteren Logins bzw. vor einer Einladung: 409, wenn aktive Logins
    plus offene Einladungen das Benutzerlimit erreichen. for_user_id: das Konto, um das es geht."""
    # Mandantenzeile sperren: parallele Aktivierungen zählen nacheinander (kein Überschreiten per Race)
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    if tenant is None:
        return
    limit = effective_user_limit(db, tenant)
    if limit is not None and login_account_count(db, tenant_id) + pending_invite_count(db, tenant_id, excluding_user_id=for_user_id) >= limit:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Das Benutzerlimit Ihres Abos ist erreicht ({limit} Konten mit Login inkl. offener Einladungen). Ziehen Sie eine Einladung zurück, deaktivieren Sie ein Konto oder erweitern Sie das Abo.",
        )
