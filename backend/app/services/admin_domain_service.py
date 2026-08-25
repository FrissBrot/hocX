from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import Tenant, TenantDomain
from app.schemas.admin import AdminDomainPage, AdminDomainRead
from app.services import traefik_config_service


class AdminDomainService:
    """Cross-tenant custom-domain overview for the platform-admin panel - unscoped by design."""

    def delete_domain(self, db: Session, domain_id: int) -> TenantDomain | None:
        """Removes a tenant's custom domain. Used by platform admins to clear a domain a
        tenant added but never got DNS-verified (see RUNBOOK.md ACME rate-limit warning) -
        tenants can otherwise only remove their own domains via the self-service flow, so
        an uncooperative/unreachable tenant would leave the platform stuck otherwise.
        Returns the deleted row (so the caller can log its domain/tenant before it's gone),
        or None if no such domain exists."""
        domain = db.get(TenantDomain, domain_id)
        if domain is None:
            return None
        # Mirrors TenantService.delete_domain's identical check (audit finding,
        # 2026-08-25) - this admin-panel path deleted the DB row but never regenerated
        # Traefik's config for an active domain, leaving its old route pointed at the
        # now-deleted tenant until some other, unrelated trigger happened to fix the file.
        # A different tenant claiming the freed-up domain in that window would have their
        # traffic routed to the wrong (stale) backend the whole time.
        was_active = domain.status == "active"
        db.delete(domain)
        db.commit()
        if was_active:
            traefik_config_service.regenerate(db)
        return domain

    def list_domains(self, db: Session, *, limit: int | None = None, offset: int = 0, q: str | None = None) -> AdminDomainPage:
        query = (
            db.query(TenantDomain, Tenant)
            .join(Tenant, TenantDomain.tenant_id == Tenant.id)
            .order_by(Tenant.name.asc(), TenantDomain.purpose.asc())
        )
        # Applied before the offset/limit slice (audit A1, 2026-08-16) - see the identical
        # fix in AdminTenantService.list_tenants/AdminUserService.list_users.
        if q and q.strip():
            like = f"%{q.strip()}%"
            query = query.filter(or_(TenantDomain.domain.ilike(like), Tenant.name.ilike(like)))
        total = query.count()
        query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        rows = query.all()
        items = [
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
        return AdminDomainPage(items=items, total=total)
