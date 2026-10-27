"""Benutzerlimit des Abos: Konten mit Login (aktiv), höchstens ``user_limit_override`` bzw.
``plan.included_user_limit`` (None = unbegrenzt). Teilnehmende ohne Login zählen nicht.

Durchgesetzt beim Aktivieren eines Logins (Anlegen, Login einschalten, Konto reaktivieren) im
Mandanten selbst; das Plattform-Admin-Panel darf bewusst darüber hinaus gehen (Override).
Bestehende Konten über dem Limit (z. B. nach einem Downgrade) bleiben nutzbar - es kommen nur
keine neuen dazu (docs/FEATURE_ENTITLEMENT_ARCHITECTURE.md, Abschnitt Nutzungslimits).
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AppUser, Plan, Tenant


def login_account_count(db: Session, tenant_id: int) -> int:
    return int(db.scalar(
        select(func.count(AppUser.id)).where(AppUser.tenant_id == tenant_id, AppUser.login_enabled.is_(True), AppUser.is_active.is_(True))
    ) or 0)


def effective_user_limit(db: Session, tenant: Tenant) -> int | None:
    if tenant.user_limit_override is not None:
        return tenant.user_limit_override
    plan = db.get(Plan, tenant.plan_code) if tenant.plan_code is not None else None
    return plan.included_user_limit if plan is not None else None


def ensure_login_capacity(db: Session, tenant_id: int) -> None:
    """Vor dem Aktivieren eines weiteren Logins: 409, wenn das Benutzerlimit erreicht ist."""
    # Mandantenzeile sperren: parallele Aktivierungen zählen nacheinander (kein Überschreiten per Race)
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    if tenant is None:
        return
    limit = effective_user_limit(db, tenant)
    if limit is not None and login_account_count(db, tenant_id) >= limit:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Das Benutzerlimit Ihres Abos ist erreicht ({limit} Konten mit Login). Deaktivieren Sie ein Konto oder erweitern Sie das Abo.",
        )
