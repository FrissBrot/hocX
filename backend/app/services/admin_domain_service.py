from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Tenant, TenantDomain
from app.schemas.admin import AdminDomainRead


class AdminDomainService:
    """Cross-tenant custom-domain overview for the platform-admin panel - unscoped by design."""

    def list_domains(self, db: Session) -> list[AdminDomainRead]:
        rows = (
            db.query(TenantDomain, Tenant)
            .join(Tenant, TenantDomain.tenant_id == Tenant.id)
            .order_by(Tenant.name.asc(), TenantDomain.purpose.asc())
            .all()
        )
        return [
            AdminDomainRead(
                id=domain.id,
                tenant_id=tenant.id,
                tenant_name=tenant.name,
                purpose=domain.purpose,
                domain=domain.domain,
                status=domain.status,
                is_healthy=domain.is_healthy,
                last_checked_at=domain.last_checked_at,
                verified_at=domain.verified_at,
                created_at=domain.created_at,
            )
            for domain, tenant in rows
        ]
