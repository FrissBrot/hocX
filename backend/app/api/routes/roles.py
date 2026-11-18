"""Rollenverwaltung des Mandanten (RBAC): Rollen anlegen, ändern, löschen und Konten zuweisen.

Alles nur mit access.manage; die Schutzregeln (keine Rechteausweitung, letzter Administrator,
kein Selbstentzug, Mandantensperre) liegen in services/role_service.py. Hintergrund:
docs/RBAC_ARCHITECTURE_PROPOSAL.md.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.permissions import CATALOG, P
from app.core.features_generated import F
from app.core.security import CurrentUser, get_current_user, require_feature, require_permission
from app.models import AppUser
from app.schemas.role import AccessPreviewRead, PermissionInfo, RoleCreate, RoleRead, RoleRef, RoleUpdate, UserRolesUpdate
from app.services import access_preview_service, public_id_service, role_service
from app.services.audit_service import AuditService

router = APIRouter()
audit = AuditService()


@router.get("/roles", response_model=list[RoleRead])
def list_roles(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.ACCESS_MANAGE)
    return role_service.list_roles(db, user.current_tenant_id)


@router.get("/roles/catalog", response_model=list[PermissionInfo])
def get_permission_catalog(user: CurrentUser = Depends(get_current_user)):
    """Systemseitig definierte Berechtigungen (Bezeichnungen sind i18n-Keys im Frontend)."""
    require_permission(user, P.ACCESS_MANAGE)
    return [
        PermissionInfo(
            key=key.value,
            area=definition.area,
            feature=definition.feature,
            requires_mfa=definition.requires_mfa,
            implies=[implied.value for implied in definition.implies],
            scopes=list(definition.scopes),
        )
        for key, definition in CATALOG.items()
    ]


@router.post("/roles", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
def create_role(payload: RoleCreate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.ACCESS_MANAGE)
    require_feature(user, F.CUSTOM_ROLES, write=True)
    try:
        role = role_service.create_role(db, user, payload)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Rolle konnte nicht angelegt werden") from exc
    result = role_service.read_role(db, role)
    audit.log(db, action="role.created", actor=user, entity_type="tenant_role", entity_id=role.id,
              details={"name": role.name, "permissions": result.permissions, "scopes": result.scopes, "require_mfa": role.require_mfa})
    return result


@router.patch("/roles/{role_id}", response_model=RoleRead)
def update_role(role_id: uuid.UUID, payload: RoleUpdate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.ACCESS_MANAGE)
    require_feature(user, F.CUSTOM_ROLES, write=True)
    role = role_service.get_role(db, user.current_tenant_id, role_id)
    mfa_before = role.require_mfa
    scopes_before = role_service.role_scopes(db, role)
    try:
        before, after = role_service.update_role(db, user, role, payload)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Rolle konnte nicht geändert werden") from exc
    result = role_service.read_role(db, role)
    audit.log(db, action="role.updated", actor=user, entity_type="tenant_role", entity_id=role.id,
              details={"name": role.name, "system_key": role.system_key,
                       "permissions_before": sorted(before), "permissions_after": sorted(after),
                       "scopes_before": scopes_before, "scopes_after": result.scopes,
                       "require_mfa_before": mfa_before, "require_mfa_after": role.require_mfa})
    return result


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(role_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.ACCESS_MANAGE)
    role = role_service.get_role(db, user.current_tenant_id, role_id)
    role_internal_id, role_name = role.id, role.name
    try:
        role_service.delete_role(db, user, role)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Rolle konnte nicht gelöscht werden") from exc
    audit.log(db, action="role.deleted", actor=user, entity_type="tenant_role", entity_id=role_internal_id, details={"name": role_name})


@router.put("/users/{user_id}/roles", response_model=list[RoleRef])
def set_user_roles(user_id: uuid.UUID, payload: UserRolesUpdate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.ACCESS_MANAGE)
    target = public_id_service.get_by_public_id(db, AppUser, user_id, tenant_id=user.current_tenant_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    roles = role_service.resolve_roles(db, user.current_tenant_id, payload.role_ids)
    try:
        role_service.set_user_roles(db, user, target, roles)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Rollen konnten nicht gesetzt werden") from exc
    # Audit «user.roles_changed» (vorher/nachher) schreibt role_service.set_user_roles selbst
    return [role_service.role_ref(role) for role in role_service.roles_by_user(db, [target.id]).get(target.id, [])]


@router.get("/users/{user_id}/access-preview", response_model=AccessPreviewRead)
def get_access_preview(user_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """«Ansehen als …» (Plan «Berechtigungen», Phase 7): nur lesend, keine Sitzung des Kontos.
    access.manage (verlangt MFA), nur eigener Mandant, nur Konten ohne mehr Rechte als man selbst;
    jeder Aufruf steht im Verlauf (user.access_previewed) - siehe services/access_preview_service.py."""
    require_permission(user, P.ACCESS_MANAGE)
    return access_preview_service.preview(db, user, user_id)
