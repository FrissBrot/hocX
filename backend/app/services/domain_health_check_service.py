from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import TenantDomain
from app.services import domain_verification_service


def run_health_check(db: Session) -> None:
    """Re-checks that every active custom domain still resolves to us and updates is_healthy /
    last_checked_at accordingly. Does NOT touch Traefik routing - a domain flagged unhealthy
    stays routed (a DNS check can be a transient false negative; auto-unrouting on that signal
    risks the exact kind of instability this is meant to guard against). The flag only feeds
    visibility (admin/self-service UI) and gates the "auto-redirect to custom domain" bridge."""
    rows = db.query(TenantDomain).filter(TenantDomain.status == "active").all()
    now = datetime.now(timezone.utc)
    for row in rows:
        target_host = settings.traefik_domain if row.purpose == "app" else settings.traefik_abgabebox_domain
        healthy = bool(target_host) and domain_verification_service.is_still_routable(row.domain, target_host)
        row.is_healthy = healthy
        row.last_checked_at = now
        db.add(row)
    db.commit()
