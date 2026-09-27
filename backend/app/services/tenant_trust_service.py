"""Vertrauen zwischen Mandanten (tenant_trust): entsteht beim ersten Annehmen einer
Album-Freigabe und bleibt bestehen. Ohne Trust ist ein anderer Mandant nur ueber seine ID
auffindbar und bleibt anonym (kein Name, kein Profilbild); mit Trust sehen sich beide Seiten
mit Namen/Profilbild und koennen sich gegenseitig per Namen suchen."""

from __future__ import annotations

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.entities import Tenant, TenantTrust


def _pair(tenant_a_id: int, tenant_b_id: int) -> tuple[int, int]:
    return (tenant_a_id, tenant_b_id) if tenant_a_id < tenant_b_id else (tenant_b_id, tenant_a_id)


def establish(db: Session, tenant_a_id: int, tenant_b_id: int) -> None:
    """Idempotent; committet nicht selbst (laeuft in der Transaktion des Aufrufers)."""
    if tenant_a_id == tenant_b_id:
        return
    low, high = _pair(tenant_a_id, tenant_b_id)
    db.execute(insert(TenantTrust).values(tenant_low_id=low, tenant_high_id=high).on_conflict_do_nothing())


def is_trusted(db: Session, tenant_a_id: int, tenant_b_id: int) -> bool:
    if tenant_a_id == tenant_b_id:
        return True
    low, high = _pair(tenant_a_id, tenant_b_id)
    return db.get(TenantTrust, {"tenant_low_id": low, "tenant_high_id": high}) is not None


def trusted_tenant_ids(db: Session, tenant_id: int) -> set[int]:
    rows = db.execute(
        select(TenantTrust.tenant_low_id, TenantTrust.tenant_high_id).where(
            or_(TenantTrust.tenant_low_id == tenant_id, TenantTrust.tenant_high_id == tenant_id)
        )
    ).all()
    return {row.tenant_high_id if row.tenant_low_id == tenant_id else row.tenant_low_id for row in rows}


def search_trusted(db: Session, tenant_id: int, query: str, *, limit: int = 10) -> list[Tenant]:
    """Vertraute Mandanten, deren Name (oder Slug) `query` enthaelt - die einzige Stelle, an
    der ein anderer Mandant per Namen gefunden werden kann."""
    pattern = f"%{query.strip()}%"
    partner_id = func.coalesce(
        func.nullif(TenantTrust.tenant_low_id, tenant_id), TenantTrust.tenant_high_id
    )
    stmt = (
        select(Tenant)
        .join(TenantTrust, Tenant.id == partner_id)
        .where(
            or_(TenantTrust.tenant_low_id == tenant_id, TenantTrust.tenant_high_id == tenant_id),
            Tenant.id != tenant_id,
            or_(Tenant.name.ilike(pattern), and_(Tenant.public_slug.is_not(None), Tenant.public_slug.ilike(pattern))),
        )
        .order_by(Tenant.name)
        .limit(limit)
    )
    return list(db.scalars(stmt))
