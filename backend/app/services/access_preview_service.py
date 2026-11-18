"""«Ansehen als …»: nur lesende Vorschau, was ein Konto sieht (Plan «Berechtigungen», Phase 7).

Sicherheitsentscheid: Es gibt **keine** Sitzung des anderen Kontos, keinen Token-Tausch und keinen
Schreibweg. Berechnet wird nur, was dasselbe ``build_current_user`` für jeden Request des Kontos
ergäbe (Rechte inkl. Implikationen, Reichweiten, Module des Mandanten, MFA-Pflicht) - die
Navigation leitet das Frontend daraus mit derselben Funktion ab wie für die echte Seitenleiste
(``app-shell-nav.ts::buildNav``). Inhalte anderer Personen liefert die Vorschau nicht; einzig die
Titel der Abgabe-Aufträge, die ein «nur zugewiesene»-Prüfer sieht, und davon nur die, die der
Akteur selbst lesen darf (hat er selbst nur «zugewiesene», die Schnittmenge mit seinen eigenen -
Schutzregel 1 vergleicht Rechte und Reichweiten, nicht einzelne Zuweisungen).

Schutzregeln (wie ``role_service.ensure_can_manage_account``):
- nur mit ``access.manage`` (verlangt MFA, Katalog) - prüft die Route;
- nur Konten des eigenen Mandanten (fremd oder unbekannt: 404, kein Existenz-Orakel);
- nur Konten, deren Rechte eine Teilmenge der eigenen sind (sonst 403 ``permission_not_held``);
- jeder Aufruf steht im Verlauf (``user.access_previewed``, abgelehnte mit ``outcome=failure``).
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.mfa_policy import account_requires_mfa
from app.core.permissions import CATALOG, SCOPE_ALL, SCOPE_ASSIGNED, SCOPED_PERMISSIONS, P
from app.core.security import CurrentUser, build_current_user
from app.models import AppUser, SubmissionAssignment, UserMfaFactor
from app.schemas.role import (
    AccessPreviewPermission,
    AccessPreviewRead,
    AccessPreviewSubmission,
    AccessPreviewSubmissions,
    RoleRef,
)
from app.services import public_id_service, role_service
from app.services import submission_reviewer_service as reviewers
from app.services.audit_service import AuditService

AUDIT_ACTION = "user.access_previewed"
# Begrenzt nur die Antwortgrösse (Titel der zugewiesenen Aufträge)
MAX_PREVIEW_SUBMISSIONS = 50

audit = AuditService()


def _feature_access(target: CurrentUser, permission: P) -> str:
    feature = CATALOG[permission].feature
    if feature is None or feature in target.current_tenant_features:
        return "full"
    if feature in target.current_tenant_read_only_features:
        return "read_only"
    return "none"


def _submissions(db: Session, actor: CurrentUser, target: CurrentUser) -> AccessPreviewSubmissions | None:
    if not target.can(P.SUBMISSIONS_READ):
        return None
    visible = reviewers.visible_assignment_ids(db, target)
    if visible is None:
        count = db.scalar(
            select(func.count()).select_from(SubmissionAssignment).where(SubmissionAssignment.tenant_id == target.current_tenant_id)
        )
        return AccessPreviewSubmissions(scope=SCOPE_ALL, visible_count=int(count or 0))
    # Titel nur von Aufträgen, die der Akteur selbst lesen darf (Anzahl bleibt die des Kontos)
    own_visible = reviewers.visible_assignment_ids(db, actor)
    titled = visible if own_visible is None else visible & own_visible
    rows = []
    if titled:
        rows = list(db.execute(
            select(SubmissionAssignment.public_id, SubmissionAssignment.title)
            .where(SubmissionAssignment.tenant_id == target.current_tenant_id, SubmissionAssignment.id.in_(titled))
            .order_by(SubmissionAssignment.title, SubmissionAssignment.id)
            .limit(MAX_PREVIEW_SUBMISSIONS)
        ))
    return AccessPreviewSubmissions(
        scope=SCOPE_ASSIGNED,
        visible_count=len(visible),
        assigned=[AccessPreviewSubmission(id=public_id, title=title) for public_id, title in rows],
    )


def preview(db: Session, actor: CurrentUser, user_public_id: uuid.UUID) -> AccessPreviewRead:
    """Vorschau für ein Konto des eigenen Mandanten. ``access.manage`` prüft die Route vorher."""
    target_row = public_id_service.get_by_public_id(db, AppUser, user_public_id, tenant_id=actor.current_tenant_id)
    if target_row is None or target_row.tenant_id != actor.current_tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    try:
        role_service.ensure_can_manage_account(db, actor, target_row.id)
    except HTTPException:
        # Abgelehnte Vorschau ebenfalls im Verlauf (wer hat es bei wem versucht)
        audit.log(db, action=AUDIT_ACTION, actor=actor, entity_type="user", entity_id=target_row.id,
                  details={"target": str(target_row.public_id)}, outcome="failure")
        raise

    target = build_current_user(db, target_row)
    permissions = [
        AccessPreviewPermission(
            key=key.value,
            scope=(SCOPE_ALL if target.sees_all(key) else SCOPE_ASSIGNED) if key in SCOPED_PERMISSIONS else None,
            feature_access=_feature_access(target, key),
            effective=target.can(key),
        )
        for key in CATALOG
        if key.value in target.permissions
    ]
    has_factor = db.scalar(select(UserMfaFactor.id).where(UserMfaFactor.user_id == target_row.id).limit(1)) is not None
    result = AccessPreviewRead(
        user_id=target_row.public_id,
        display_name=target_row.display_name,
        is_active=target_row.is_active,
        login_enabled=target_row.login_enabled,
        roles=[RoleRef(id=role.public_id, name=role.name, system_key=role.system_key) for role in target.roles],
        permissions=permissions,
        enabled_features=sorted(target.current_tenant_features),
        read_only_features=sorted(target.current_tenant_read_only_features),
        mfa_required=account_requires_mfa(db, target_row.id, permissions=target.permissions, tenant_id=target.current_tenant_id),
        mfa_active=has_factor,
        submissions=_submissions(db, actor, target),
    )
    audit.log(db, action=AUDIT_ACTION, actor=actor, entity_type="user", entity_id=target_row.id,
              details={"target": str(target_row.public_id), "permissions": [item.key for item in permissions]})
    return result
