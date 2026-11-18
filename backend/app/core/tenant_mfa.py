"""MFA-Pflicht des Mandanten (tenant.require_mfa, Migration 0188).

Einzige Stelle, die beantwortet «verlangt dieser Mandant MFA für alle Logins?». Die Pflicht eines
Kontos ergibt sich daraus ODER aus Administrations-Berechtigungen (permissions.requires_mfa);
beides verbinden security._requires_mfa (laufende Sessions, collaboration_ws) und
MfaService.user_requires_mfa (Login, UserMfaRead.required, letzter Faktor).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Tenant


def tenant_requires_mfa(db: Session, tenant_id: int | None) -> bool:
    if tenant_id is None:
        return False
    # db.get nutzt die Identity-Map: in build_current_user ist der Mandant schon geladen.
    tenant = db.get(Tenant, tenant_id)
    return bool(tenant is not None and tenant.require_mfa)
