"""Rollenverwaltung je Mandant (RBAC) und ihre Schutzregeln.

Eine Rolle bündelt systemseitig definierte Berechtigungen (permissions/catalog.json); ein Konto
kann mehrere Rollen haben, seine Rechte sind die Vereinigungsmenge (core/security.py lädt sie bei
jedem Request). Architektur: docs/RBAC_ARCHITECTURE_PROPOSAL.md, Abschnitt E.4.

Schutzregeln - für den Mandanten-Admin wie für den Plattform-Admin-Pfad (actor=None):

1. Keine Rechteausweitung: Ein Akteur vergibt, entzieht, erstellt, ändert oder löscht nur Rollen,
   deren Berechtigungen er selbst hat, und verwaltet nur Konten, deren Berechtigungen er selbst hat
   (kein Passwort-/Login-/MFA-Zugriff auf Höherberechtigte). Der Plattform-Admin ist ausgenommen.
2. Mindestens ein handlungsfähiger Administrator: ein aktives Konto mit Login und access.manage.
   Jede Änderung, die diese Menge verkleinern kann, wird danach geprüft (409).
3. Kein Selbstentzug von access.manage (E-2) - das macht ein anderer Administrator.
4. Nebenläufigkeit: alle diese Änderungen sperren zuerst die Mandantenzeile (FOR UPDATE), damit
   zwei Admins sich nicht gleichzeitig gegenseitig herabstufen (RBAC-Analyse S-6).
5. Die Standardrolle admin ist fest (immer alle Berechtigungen, nicht änderbar, nicht löschbar);
   Standardrollen sind nicht löschbar.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

from fastapi import HTTPException, status
from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.orm import Session

from app.core.permissions import ADMIN_ROLE_KEY, CATALOG, DEFAULT_ROLE_KEY, P, effective_permissions, expand
from app.core.security import CurrentUser, load_role_permissions, require_permission
from app.models import AppUser, Tenant, TenantRole, TenantRolePermission, UserRole
from app.schemas.role import RoleCreate, RoleRead, RoleRef, RoleUpdate

# Rollen-Namen sind frei; die Länge begrenzt nur Missbrauch (Anzeige in Tabellen und PDFs).
MAX_ROLES_PER_TENANT = 50


class RoleConflict(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


# ── Laden ────────────────────────────────────────────────────────────────────────────────────


def _role_permissions(db: Session, role_ids: Iterable[int]) -> dict[int, frozenset[str]]:
    """Effektive Berechtigungen je Rolle (admin = alle, sonst Zeilen + Implikationen)."""
    ids = list(set(role_ids))
    if not ids:
        return {}
    roles = {row.id: row.system_key for row in db.execute(select(TenantRole.id, TenantRole.system_key).where(TenantRole.id.in_(ids)))}
    raw: dict[int, list[str]] = {role_id: [] for role_id in roles}
    for role_id, key in db.execute(
        select(TenantRolePermission.role_id, TenantRolePermission.permission_key).where(TenantRolePermission.role_id.in_(ids))
    ):
        raw[role_id].append(key)
    return {
        role_id: frozenset(str(key) for key in effective_permissions(raw[role_id], [system_key]))
        for role_id, system_key in roles.items()
    }


def role_ref(role: TenantRole) -> RoleRef:
    return RoleRef(id=role.public_id, name=role.name, system_key=role.system_key)


def roles_by_user(db: Session, user_ids: Iterable[int]) -> dict[int, list[TenantRole]]:
    ids = list(set(user_ids))
    if not ids:
        return {}
    result: dict[int, list[TenantRole]] = {user_id: [] for user_id in ids}
    rows = db.execute(
        select(UserRole.user_id, TenantRole)
        .join(TenantRole, TenantRole.id == UserRole.role_id)
        .where(UserRole.user_id.in_(ids))
        .order_by(TenantRole.id)
    )
    for user_id, role in rows:
        result[user_id].append(role)
    return result


def role_labels(db: Session, tenant_id: int, user_ids: Iterable[int], language: str | None) -> dict[int, str]:
    """Rollen je Konto als Text für PDFs und Exporte: eigener Name oder - bei unbenannten
    Standardrollen - die übersetzte Bezeichnung (Dokument-Texte role.<system_key>)."""
    from app.documents.providers.common import sort_key
    from app.documents.strings import text

    ids = list(set(user_ids))
    if not ids:
        return {}
    rows = db.execute(
        select(UserRole.user_id, TenantRole.name, TenantRole.system_key)
        .join(TenantRole, TenantRole.id == UserRole.role_id)
        .where(UserRole.user_id.in_(ids), TenantRole.tenant_id == tenant_id)
    ).all()
    labels: dict[int, list[str]] = {}
    for user_id, name, system_key in rows:
        label = name or (text(language, f"role.{system_key}") if system_key else "")
        if label:
            labels.setdefault(user_id, []).append(label)
    return {user_id: ", ".join(sorted(values, key=sort_key)) for user_id, values in labels.items()}


def system_role(db: Session, tenant_id: int, system_key: str) -> TenantRole:
    role = db.scalar(select(TenantRole).where(TenantRole.tenant_id == tenant_id, TenantRole.system_key == system_key))
    if role is None:
        # Jeder Mandant bekommt die Standardrollen per Trigger (Migration 0156_rbac) - fehlt eine,
        # ist das ein Datenfehler, kein Benutzerfehler.
        raise RuntimeError(f"Standardrolle {system_key!r} fehlt für Mandant {tenant_id}")
    return role


def resolve_roles(db: Session, tenant_id: int, role_ids: Iterable[uuid.UUID]) -> list[TenantRole]:
    """Rollen per public_id - nur des angegebenen Mandanten; fremde/unbekannte IDs sind ein 400
    (gleiche Antwort für beide, kein Existenz-Orakel)."""
    wanted = list(dict.fromkeys(role_ids))
    if not wanted:
        return []
    roles = list(db.scalars(select(TenantRole).where(TenantRole.tenant_id == tenant_id, TenantRole.public_id.in_(wanted))))
    if len(roles) != len(wanted):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unbekannte Rolle")
    return roles


def list_roles(db: Session, tenant_id: int) -> list[RoleRead]:
    roles = list(db.scalars(select(TenantRole).where(TenantRole.tenant_id == tenant_id).order_by(TenantRole.id)))
    permissions = _role_permissions(db, [role.id for role in roles])
    counts = dict(
        db.execute(
            select(UserRole.role_id, func.count()).where(UserRole.tenant_id == tenant_id).group_by(UserRole.role_id)
        ).all()
    )
    return [_read(role, permissions.get(role.id, frozenset()), int(counts.get(role.id, 0))) for role in roles]


def _read(role: TenantRole, permissions: frozenset[str], user_count: int) -> RoleRead:
    return RoleRead(
        id=role.public_id,
        name=role.name,
        description=role.description,
        system_key=role.system_key,
        permissions=sorted(permissions, key=_catalog_order),
        user_count=user_count,
        locked=role.system_key == ADMIN_ROLE_KEY,
    )


def _catalog_order(key: str) -> int:
    return list(CATALOG).index(P(key))


# ── Schutzregeln ─────────────────────────────────────────────────────────────────────────────


def lock_tenant(db: Session, tenant_id: int) -> int:
    """Serialisiert alle Rechteänderungen eines Mandanten (Schutzregel 4) und liefert die Zahl
    der handlungsfähigen Administratoren vor der Änderung (für ensure_admin_remains)."""
    db.execute(select(Tenant.id).where(Tenant.id == tenant_id).with_for_update())
    return count_capable_admins(db, tenant_id)


def _ensure_subset(actor: CurrentUser | None, permissions: Iterable[str]) -> None:
    if actor is None:
        return
    missing = set(permissions) - set(actor.permissions)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nur Berechtigungen, die man selbst hat, können vergeben oder verwaltet werden",
        )


def ensure_can_manage_account(db: Session, actor: CurrentUser | None, user_id: int) -> None:
    """Konto eines anderen verwalten (Passwort, Login, E-Mail, Aktiv, MFA, Rollen, Löschen):
    nur, wenn dessen Berechtigungen eine Teilmenge der eigenen sind (Schutzregel 1)."""
    if actor is None:
        return
    target_permissions, _ = load_role_permissions(db, user_id)
    _ensure_subset(actor, target_permissions)


def count_capable_admins(db: Session, tenant_id: int, *, excluding: set[int] | None = None) -> int:
    """Aktive Konten mit Login, die access.manage haben (über die Standardrolle admin oder eine
    eigene Rolle mit access.manage)."""
    grants_access = or_(
        TenantRole.system_key == ADMIN_ROLE_KEY,
        exists(
            select(TenantRolePermission.role_id).where(
                TenantRolePermission.role_id == TenantRole.id,
                TenantRolePermission.permission_key == P.ACCESS_MANAGE.value,
            )
        ),
    )
    statement = (
        select(func.count(func.distinct(AppUser.id)))
        .select_from(AppUser)
        .join(UserRole, UserRole.user_id == AppUser.id)
        .join(TenantRole, TenantRole.id == UserRole.role_id)
        .where(AppUser.tenant_id == tenant_id, AppUser.is_active.is_(True), AppUser.login_enabled.is_(True), grants_access)
    )
    if excluding:
        statement = statement.where(AppUser.id.not_in(excluding))
    return int(db.scalar(statement) or 0)


def ensure_admin_remains(db: Session, tenant_id: int, actor: CurrentUser | None, *, before: int, affects_actor: bool = False) -> None:
    """Nach einer Änderung (bereits geflusht, noch nicht committet): die Änderung hat den letzten
    handlungsfähigen Administrator nicht entfernt (Schutzregel 2; ``before`` aus lock_tenant) und -
    wenn sie das eigene Konto oder eine eigene Rolle betrifft - kein Selbstentzug (Schutzregel 3).
    Bei Verstoss 409; der Aufrufer committet dann nicht (die Request-Session verwirft alles)."""
    db.flush()
    if before > 0 and count_capable_admins(db, tenant_id) == 0:
        raise RoleConflict("Der letzte Administrator eines Mandanten kann nicht entfernt oder herabgestuft werden")
    if affects_actor and actor is not None and P.ACCESS_MANAGE.value in actor.permissions:
        own, _ = load_role_permissions(db, actor.user_id)
        still_active = db.scalar(select(AppUser.is_active).where(AppUser.id == actor.user_id))
        if P.ACCESS_MANAGE.value not in own or not still_active:
            raise RoleConflict("Die eigene Benutzerverwaltung kann man sich nicht selbst entziehen")


@contextmanager
def admin_guard(db: Session, tenant_id: int, actor: CurrentUser | None, *, affects_actor: bool = False) -> Iterator[None]:
    """Rahmen für jede Änderung, die Administratoren treffen kann (Rollen setzen, Rolle ändern,
    deaktivieren, Login entziehen): sperrt den Mandanten, führt die Änderung in einem Savepoint aus
    und prüft danach die Schutzregeln 2 und 3. Bei einem Verstoss wird nur der Savepoint
    zurückgerollt (409) - die Session bleibt im Zustand vor der Änderung. Innerhalb des Blocks
    darf nicht committet werden."""
    before = lock_tenant(db, tenant_id)
    savepoint = db.begin_nested()
    try:
        yield
        ensure_admin_remains(db, tenant_id, actor, before=before, affects_actor=affects_actor)
    except BaseException:
        savepoint.rollback()
        raise
    savepoint.commit()


def ensure_not_last_admin_removed(db: Session, tenant_id: int, user_ids: Iterable[int]) -> None:
    """Vor dem Löschen von Konten: es bleibt mindestens ein handlungsfähiger Administrator, sofern
    es vorher einen gab (Schutzregel 2). Sperrt den Mandanten bis zum Ende der Transaktion."""
    removed = set(user_ids)
    if lock_tenant(db, tenant_id) == 0 or not removed:
        return
    if count_capable_admins(db, tenant_id, excluding=removed) == 0:
        raise RoleConflict("Der letzte Administrator eines Mandanten kann nicht entfernt oder herabgestuft werden")


# ── Zuweisung ────────────────────────────────────────────────────────────────────────────────


def assign_default_role(db: Session, user: AppUser) -> None:
    """Neue Konten/Teilnehmende bekommen die Standardrolle reader ("Mitglied"), wie bisher."""
    role = system_role(db, user.tenant_id, DEFAULT_ROLE_KEY)
    db.add(UserRole(tenant_id=user.tenant_id, user_id=user.id, role_id=role.id))
    db.flush()


def set_user_roles(db: Session, actor: CurrentUser | None, user: AppUser, roles: list[TenantRole]) -> bool:
    """Setzt die Rollen eines Kontos vollständig. Prüft die Schutzregeln, committet nicht.
    Gibt zurück, ob sich etwas geändert hat."""
    current = set(db.scalars(select(UserRole.role_id).where(UserRole.user_id == user.id)))
    wanted = {role.id for role in roles}
    if current == wanted:
        return False
    if actor is not None:
        if user.id != actor.user_id:
            ensure_can_manage_account(db, actor, user.id)
        changed = (current ^ wanted)
        permissions = _role_permissions(db, changed)
        _ensure_subset(actor, set().union(*permissions.values()) if permissions else set())
    with admin_guard(db, user.tenant_id, actor, affects_actor=actor is not None and user.id == actor.user_id):
        if current - wanted:
            db.execute(delete(UserRole).where(UserRole.user_id == user.id, UserRole.role_id.in_(current - wanted)))
        for role_id in wanted - current:
            db.add(UserRole(tenant_id=user.tenant_id, user_id=user.id, role_id=role_id))
    return True


# ── Rollen anlegen, ändern, löschen ─────────────────────────────────────────────────────────


def _validated_permissions(keys: Iterable[str]) -> frozenset[str]:
    unknown = [key for key in keys if key not in {permission.value for permission in P}]
    if unknown:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unbekannte Berechtigung")
    # Gespeichert wird die vollständige Menge inkl. Implikationen - dann zeigt die Oberfläche
    # genau das, was wirkt.
    return frozenset(str(key) for key in expand(keys))


def _clean_name(name: str | None) -> str | None:
    if name is None:
        return None
    cleaned = " ".join(name.split())
    return cleaned or None


def _ensure_unique_name(db: Session, tenant_id: int, name: str | None, *, excluding_id: int | None = None) -> None:
    if name is None:
        return
    statement = select(TenantRole.id).where(TenantRole.tenant_id == tenant_id, func.lower(TenantRole.name) == name.lower())
    if excluding_id is not None:
        statement = statement.where(TenantRole.id != excluding_id)
    if db.scalar(statement) is not None:
        raise RoleConflict("Eine Rolle mit diesem Namen gibt es bereits")


def _replace_permissions(db: Session, role: TenantRole, keys: frozenset[str]) -> None:
    db.execute(delete(TenantRolePermission).where(TenantRolePermission.role_id == role.id))
    for key in sorted(keys):
        db.add(TenantRolePermission(role_id=role.id, permission_key=key))


def get_role(db: Session, tenant_id: int, role_id: uuid.UUID) -> TenantRole:
    role = db.scalar(select(TenantRole).where(TenantRole.tenant_id == tenant_id, TenantRole.public_id == role_id))
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rolle nicht gefunden")
    return role


def read_role(db: Session, role: TenantRole) -> RoleRead:
    permissions = _role_permissions(db, [role.id]).get(role.id, frozenset())
    count = int(db.scalar(select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id)) or 0)
    return _read(role, permissions, count)


def create_role(db: Session, actor: CurrentUser, payload: RoleCreate) -> TenantRole:
    require_permission(actor, P.ACCESS_MANAGE)
    tenant_id = actor.current_tenant_id
    lock_tenant(db, tenant_id)
    if (db.scalar(select(func.count()).select_from(TenantRole).where(TenantRole.tenant_id == tenant_id)) or 0) >= MAX_ROLES_PER_TENANT:
        raise RoleConflict("Zu viele Rollen")
    name = _clean_name(payload.name)
    if name is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name fehlt")
    _ensure_unique_name(db, tenant_id, name)
    permissions = _validated_permissions(payload.permissions)
    _ensure_subset(actor, permissions)
    role = TenantRole(tenant_id=tenant_id, name=name, description=_clean_description(payload.description))
    db.add(role)
    db.flush()
    _replace_permissions(db, role, permissions)
    db.flush()
    return role


def _clean_description(description: str | None) -> str | None:
    if description is None:
        return None
    cleaned = description.strip()
    return cleaned or None


def update_role(db: Session, actor: CurrentUser, role: TenantRole, payload: RoleUpdate) -> tuple[frozenset[str], frozenset[str]]:
    """Gibt (alte, neue) Berechtigungen zurück (für das Audit-Log)."""
    require_permission(actor, P.ACCESS_MANAGE)
    if role.system_key == ADMIN_ROLE_KEY:
        raise RoleConflict("Die Rolle Administrator ist fest und kann nicht geändert werden")
    before = _role_permissions(db, [role.id]).get(role.id, frozenset())
    _ensure_subset(actor, before)
    fields = payload.model_fields_set
    name = role.name
    if "name" in fields:
        name = _clean_name(payload.name)
        if name is None and role.system_key is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name fehlt")
        _ensure_unique_name(db, role.tenant_id, name, excluding_id=role.id)
    after = before
    if "permissions" in fields and payload.permissions is not None:
        after = _validated_permissions(payload.permissions)
        _ensure_subset(actor, after)
    with admin_guard(db, role.tenant_id, actor, affects_actor=role.id in actor.role_ids):
        role.name = name
        if "description" in fields:
            role.description = _clean_description(payload.description)
        if after != before:
            _replace_permissions(db, role, after)
        db.add(role)
    return before, after


def delete_role(db: Session, actor: CurrentUser, role: TenantRole) -> None:
    require_permission(actor, P.ACCESS_MANAGE)
    lock_tenant(db, role.tenant_id)
    if role.system_key is not None:
        raise RoleConflict("Standardrollen können nicht gelöscht werden")
    _ensure_subset(actor, _role_permissions(db, [role.id]).get(role.id, frozenset()))
    if db.scalar(select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id)):
        raise RoleConflict("Die Rolle ist noch Benutzern zugewiesen")
    # Eine Rolle ohne Zuweisungen kann niemandem Rechte nehmen - Schutzregeln 2/3 greifen hier nicht.
    db.delete(role)
    db.flush()
