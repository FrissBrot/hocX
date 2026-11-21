"""Sicherheit & Anmeldungen der eigenen Organisation (Vereins-Ansicht, Admin-Redesign Phase E).

Lesen: Recht ``security.read`` (Standardrolle «admin»; bis 1.5.0 genügte ``access.manage`` - jetzt
eigenes Recht, damit Verlauf/Zugänge und Sicherheitswarnungen getrennt vergeben werden können).
Nur eigene Konten (tenant_id-Filter und RLS), datensparsam: keine IP, keine Netz-/Geräte-Pseudonyme,
Risiko nur als Klasse.

Sitzungen eines Kontos beenden: ``access.manage`` plus frische Anmeldung (``require_recent_auth``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth_security import events, read_service
from app.auth_security import sessions as session_register
from app.auth_security.step_up import ADMIN, require_recent_auth
from app.core.db import get_db
from app.core.permissions import P
from app.core.security import CurrentUser, get_current_user, require_permission
from app.models.entities import AppUser
from app.services import public_id_service
from app.services.audit_service import AuditService

router = APIRouter()
audit = AuditService()


@router.get("/auth-security/activity")
def tenant_login_activity(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.SECURITY_READ)
    return {
        "summary": read_service.tenant_summary(db, user.current_tenant_id),
        "warnings": read_service.tenant_warnings(db, user.current_tenant_id),
        "accounts": read_service.tenant_accounts(db, user.current_tenant_id),
        "events": read_service.tenant_events(db, user.current_tenant_id, limit=limit),
    }


@router.post("/auth-security/accounts/{user_id}/revoke-sessions")
def revoke_account_sessions(user_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Alle Sitzungen eines Kontos der eigenen Organisation beenden (fremde/unbekannte: 404)."""
    require_permission(user, P.ACCESS_MANAGE)
    target = public_id_service.get_by_public_id(db, AppUser, user_id, tenant_id=user.current_tenant_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    require_recent_auth(user, kind=ADMIN, action="sessions.revoke_user")
    revoked = session_register.revoke_all(db, target.id, reason="tenant_admin_revoked")
    # Sessions von vor dem Session-Register (stateless Cookies) über session_revoke_at mit beenden
    target.session_revoke_at = datetime.now(UTC)
    audit.log(db, action="user.sessions_revoked", actor=user, entity_type="user", entity_id=target.id, details={"revoked": revoked})
    db.commit()
    events.record(event_type="session.revoke", outcome="success", user_id=target.id, tenant_id=user.current_tenant_id,
                  details={"scope": "all", "revoked": revoked})
    return {"revoked": revoked}
