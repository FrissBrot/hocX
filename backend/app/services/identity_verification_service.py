"""Bestätigung der Organisation durch hocX («Verifizierte Organisation» auf der Prüfseite).

Ablauf: Ein Mandanten-Admin beantragt die Verifizierung (identity_verification_request, höchstens
ein offener Antrag je Mandant). Ein Plattform-Admin bestätigt (setzt tenant.identity_verified_*)
oder lehnt mit Begründung ab und kann eine bestehende Bestätigung entziehen. Bestätigt wird der
Name zum Antragszeitpunkt: ändert sich der Name, wird die Bestätigung automatisch aufgehoben und
ein offener Antrag zurückgezogen (verhindert, dass ein verifiziertes Konto in einen anderen Namen
umbenannt wird). Logo-Änderungen werden nur protokolliert.

Das Abzeichen erscheint auf der Prüfseite nur, wenn der Mandant zusätzlich die Anzeige von Name
und Logo freigegeben hat - diese Logik steckt in der View document_verification_public
(Migration 0117), nicht hier.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import CurrentUser
from app.models import IdentityVerificationRequest, Tenant
from app.services.audit_service import AuditService

audit = AuditService()

REVOKED_NAME_CHANGED = "name_changed"
REVOKED_BY_ADMIN = "admin"


class VerificationStateError(ValueError):
    """Kuratierter Zustandsfehler (z. B. schon verifiziert, kein offener Antrag)."""


def pending_request(db: Session, tenant_id: int) -> IdentityVerificationRequest | None:
    return db.scalar(
        select(IdentityVerificationRequest).where(
            IdentityVerificationRequest.tenant_id == tenant_id, IdentityVerificationRequest.status == "pending"
        )
    )


def latest_request(db: Session, tenant_id: int) -> IdentityVerificationRequest | None:
    return db.scalar(
        select(IdentityVerificationRequest)
        .where(IdentityVerificationRequest.tenant_id == tenant_id)
        .order_by(IdentityVerificationRequest.requested_at.desc(), IdentityVerificationRequest.id.desc())
        .limit(1)
    )


def request_verification(db: Session, tenant: Tenant, *, actor: CurrentUser, message: str | None) -> IdentityVerificationRequest:
    if tenant.identity_verified_at is not None:
        raise VerificationStateError("apiError.verificationAlreadyVerified")
    if pending_request(db, tenant.id) is not None:
        raise VerificationStateError("apiError.verificationAlreadyPending")
    row = IdentityVerificationRequest(
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        message=(message or "").strip()[:2000] or None,
        requested_by=actor.user_id,
    )
    db.add(row)
    db.flush()
    audit.log(db, action="identity_verification.requested", actor=actor, tenant_id=tenant.id, entity_type="identity_verification_request", entity_id=row.id)
    return row


def withdraw_request(db: Session, tenant: Tenant, *, actor: CurrentUser) -> None:
    row = pending_request(db, tenant.id)
    if row is None:
        raise VerificationStateError("apiError.verificationNoPending")
    row.status = "withdrawn"
    row.decided_at = datetime.now(UTC)
    audit.log(db, action="identity_verification.withdrawn", actor=actor, tenant_id=tenant.id, entity_type="identity_verification_request", entity_id=row.id)


def approve(db: Session, tenant: Tenant, *, admin_id: int, admin_email: str, note: str | None) -> None:
    """Bestätigt die Organisation. Mit offenem Antrag wird dieser abgeschlossen; ohne Antrag
    kann ein Plattform-Admin auch direkt bestätigen (z. B. nach telefonischer Prüfung)."""
    now = datetime.now(UTC)
    row = pending_request(db, tenant.id)
    if row is not None:
        if row.tenant_name != tenant.name:
            # Sollte nie vorkommen (Umbenennung zieht den Antrag zurück) - lieber ablehnen als
            # einen anderen Namen bestätigen.
            raise VerificationStateError("apiError.verificationNameChanged")
        row.status = "approved"
        row.decided_at = now
        row.decided_by_admin_id = admin_id
        row.decision_note = (note or "").strip()[:2000] or None
    tenant.identity_verified_at = now
    tenant.identity_verified_by_admin_id = admin_id
    tenant.identity_verification_note = (note or "").strip()[:2000] or None
    tenant.identity_verification_revoked_at = None
    tenant.identity_verification_revoked_reason = None
    db.add(tenant)
    audit.log(db, action="admin.identity_verification_approved", actor_email=admin_email, entity_type="tenant", entity_id=tenant.id, details={"name": tenant.name})


def reject(db: Session, tenant: Tenant, *, admin_id: int, admin_email: str, note: str) -> None:
    row = pending_request(db, tenant.id)
    if row is None:
        raise VerificationStateError("apiError.verificationNoPending")
    if not (note or "").strip():
        raise VerificationStateError("apiError.verificationReasonRequired")
    row.status = "rejected"
    row.decided_at = datetime.now(UTC)
    row.decided_by_admin_id = admin_id
    row.decision_note = note.strip()[:2000]
    audit.log(db, action="admin.identity_verification_rejected", actor_email=admin_email, entity_type="tenant", entity_id=tenant.id)


def revoke(db: Session, tenant: Tenant, *, admin_email: str | None, reason: str, note: str | None = None, actor_email: str | None = None) -> bool:
    """Hebt eine bestehende Bestätigung auf. False, wenn der Mandant nicht verifiziert war."""
    if tenant.identity_verified_at is None:
        return False
    tenant.identity_verified_at = None
    tenant.identity_verified_by_admin_id = None
    tenant.identity_verification_note = (note or "").strip()[:2000] or None
    tenant.identity_verification_revoked_at = datetime.now(UTC)
    tenant.identity_verification_revoked_reason = reason
    db.add(tenant)
    if reason == REVOKED_BY_ADMIN:
        audit.log(db, action="admin.identity_verification_revoked", actor_email=admin_email, entity_type="tenant", entity_id=tenant.id)
    else:
        audit.log(db, action="identity_verification.revoked", actor_email=actor_email or admin_email, tenant_id=tenant.id, details={"reason": reason})
    return True


def handle_rename(db: Session, tenant: Tenant, old_name: str, *, actor_email: str | None) -> bool:
    """Vor dem Commit einer Namensänderung aufrufen. Hebt die Bestätigung auf und zieht einen
    offenen Antrag zurück. True, wenn eine Bestätigung aufgehoben wurde (Hinweis im UI)."""
    if tenant.name == old_name:
        return False
    row = pending_request(db, tenant.id)
    if row is not None:
        row.status = "withdrawn"
        row.decided_at = datetime.now(UTC)
        row.decision_note = REVOKED_NAME_CHANGED
    return revoke(db, tenant, admin_email=None, reason=REVOKED_NAME_CHANGED, actor_email=actor_email)
