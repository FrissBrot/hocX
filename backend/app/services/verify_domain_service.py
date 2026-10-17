"""Prüf-Domain eines Mandanten (Feature 'verify_domain', tenant_domain.purpose = 'verify').

Neue PDFs tragen im Prüfvermerk, im QR-Code und im XMP die Prüfseite des Mandanten
(https://verify.verein.ch/verify?id=...), sobald seine Prüf-Domain nutzbar ist. Die Bedingungen
entsprechen der Spalte verify_domain der View document_verification_public (Migration
0126_verify_domain), damit QR-Code und Weiterleitung der zentralen Prüfseite übereinstimmen:
Domain aktiv und gesund, Feature gebucht, Name und Logo auf der Prüfseite freigegeben.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Tenant, TenantDomain
from app.services import traefik_config_service


def verify_domain_row(db: Session, tenant_id: int) -> TenantDomain | None:
    """Die Prüf-Domain des Mandanten, unabhängig von Status und Buchung (Einstellungsseite)."""
    return (
        db.query(TenantDomain)
        .filter(TenantDomain.tenant_id == tenant_id, TenantDomain.purpose == "verify")
        .one_or_none()
    )


def usable_verify_domain(db: Session, tenant_id: int) -> str | None:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or not tenant.verify_show_identity:
        return None
    row = (
        db.query(TenantDomain)
        .filter(
            TenantDomain.tenant_id == tenant_id,
            TenantDomain.purpose == "verify",
            TenantDomain.status == "active",
            TenantDomain.is_healthy.is_(True),
            traefik_config_service.domain_feature_booked(),
        )
        .one_or_none()
    )
    return row.domain if row is not None else None


def tenant_verify_base_url(db: Session, tenant_id: int) -> str:
    """Basis-URL der Prüfseite für neue Dokumente des Mandanten (ohne ?id=)."""
    domain = usable_verify_domain(db, tenant_id)
    return f"https://{domain}/verify" if domain else settings.verify_base_url
