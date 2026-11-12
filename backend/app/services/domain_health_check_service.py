from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TenantDomain
from app.services import domain_verification_service, traefik_config_service


def run_health_check(db: Session) -> None:
    """Re-checks that every active custom domain still resolves to us and updates is_healthy /
    last_checked_at accordingly. Does NOT touch Traefik routing - a domain flagged unhealthy
    stays routed (a DNS check can be a transient false negative; auto-unrouting on that signal
    risks the exact kind of instability this is meant to guard against). The flag only feeds
    visibility (admin/self-service UI) and gates the "auto-redirect to custom domain" bridge -
    explicitly set unhealthy here (security-audit FEAT-01, audit 08), so a domain whose tenant lost
    `custom_domain` stops being reported healthy and stops being offered by the bridge, even before the next
    regenerate() physically removes its Traefik router."""
    booked_ids = set(
        db.scalars(
            select(TenantDomain.id).where(TenantDomain.status == "active", traefik_config_service.domain_feature_booked())
        )
    )
    rows = db.query(TenantDomain).filter(TenantDomain.status == "active").all()
    now = datetime.now(timezone.utc)
    for row in rows:
        if row.id not in booked_ids:
            # Nicht (mehr) im Abo: Traefik bedient die Domain nicht - nicht weiter als gesund
            # ausweisen (Audit 08, 2026-11: blieb nach einem Downgrade grün «Verifiziert»).
            row.is_healthy = False
            row.last_checked_at = now
            db.add(row)
            continue
        target_host = traefik_config_service.target_host_for_purpose(row.purpose)
        healthy = bool(target_host) and domain_verification_service.is_still_routable(row.domain, target_host)
        row.is_healthy = healthy
        row.last_checked_at = now
        db.add(row)
    db.commit()
