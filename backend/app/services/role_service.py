"""Rollenverwaltung je Mandant (RBAC) und ihre Schutzregeln.

Eine Rolle bündelt systemseitig definierte Berechtigungen (permissions/catalog.json); ein Konto
kann mehrere Rollen haben, seine Rechte sind die Vereinigungsmenge (core/security.py lädt sie bei
jedem Request). Architektur: docs/RBAC_ARCHITECTURE_PROPOSAL.md, Abschnitt E.4.

Schutzregeln - für den Mandanten-Admin wie für den Plattform-Admin-Pfad (actor=None):

1. Keine Rechteausweitung: Ein Akteur vergibt, entzieht, erstellt, ändert oder löscht nur Rollen,
   deren Berechtigungen er selbst hat, und verwaltet nur Konten, deren Berechtigungen er selbst hat
   (kein Passwort-/Login-/MFA-Zugriff auf Höherberechtigte). Der Plattform-Admin ist ausgenommen.
   Das gilt auch für die Reichweite (Migration 0195): wer ein Recht nur für zugewiesene Objekte
   hat, vergibt es nicht für alle.
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

from app.core.permissions import (
    ADMIN_ROLE_KEY,
    CATALOG,
    DEFAULT_ROLE_KEY,
    SCOPE_ALL,
    SCOPE_ASSIGNED,
    SCOPED_PERMISSIONS,
    P,
    effective_permissions,
    expand,
    resolve_scopes,
)
from app.core.security import CurrentUser, load_role_permissions, load_role_scopes, require_permission
from app.models import AppUser, Tenant, TenantRole, TenantRolePermission, UserRole
from app.schemas.role import RoleCreate, RoleRead, RoleRef, RoleUpdate

# Rollen-Namen sind frei; die Länge begrenzt nur Missbrauch (Anzeige in Tabellen und PDFs).
MAX_ROLES_PER_TENANT = 50


class RoleConflict(HTTPException):
    """409 mit stabilem Code; die Oberfläche übersetzt `code`, `message` bleibt der deutsche
    Fallback (lib/api/client.ts liest detail.message)."""

    def __init__(self, detail: str, code: str) -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail={"code": code, "message": detail})


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


def _role_scopes(db: Session, role_ids: Iterable[int]) -> dict[int, dict[str, str]]:
    """Reichweite je Recht mit Reichweite und Rolle (admin: alles für alle). Gespeichert ist die
    aufgelöste Menge; NULL in tenant_role_permission.scope bedeutet «alle»."""
    ids = list(set(role_ids))
    if not ids:
        return {}
    roles = {row.id: row.system_key for row in db.execute(select(TenantRole.id, TenantRole.system_key).where(TenantRole.id.in_(ids)))}
    rows: dict[int, dict[str, str | None]] = {role_id: {} for role_id in roles}
    for role_id, key, scope in db.execute(
        select(TenantRolePermission.role_id, TenantRolePermission.permission_key, TenantRolePermission.scope)
        .where(TenantRolePermission.role_id.in_(ids))
    ):
        rows[role_id][key] = scope or SCOPE_ALL
    result: dict[int, dict[str, str]] = {}
    for role_id, system_key in roles.items():
        if system_key == ADMIN_ROLE_KEY:
            result[role_id] = {key.value: SCOPE_ALL for key in SCOPED_PERMISSIONS}
        else:
            result[role_id] = {key.value: scope for key, scope in resolve_scopes(rows[role_id], rows[role_id]).items()}
    return result


def role_scopes(db: Session, role: TenantRole) -> dict[str, str]:
    """Reichweiten einer Rolle (auch für das Audit-Log vor/nach einer Änderung)."""
    return _role_scopes(db, [role.id]).get(role.id, {})


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
    scopes = _role_scopes(db, [role.id for role in roles])
    counts = dict(
        db.execute(
            select(UserRole.role_id, func.count()).where(UserRole.tenant_id == tenant_id).group_by(UserRole.role_id)
        ).all()
    )
    return [_read(role, permissions.get(role.id, frozenset()), int(counts.get(role.id, 0)), scopes.get(role.id, {})) for role in roles]


def _read(role: TenantRole, permissions: frozenset[str], user_count: int, scopes: dict[str, str] | None = None) -> RoleRead:
    return RoleRead(
        id=role.public_id,
        name=role.name,
        description=role.description,
        system_key=role.system_key,
        permissions=sorted(permissions, key=_catalog_order),
        scopes=dict(sorted((scopes or {}).items(), key=lambda item: _catalog_order(item[0]))),
        user_count=user_count,
        locked=role.system_key == ADMIN_ROLE_KEY,
        require_mfa=role.require_mfa,
    )


def _catalog_order(key: str) -> int:
    return list(CATALOG).index(P(key))


# ── Schutzregeln ─────────────────────────────────────────────────────────────────────────────


def lock_tenant(db: Session, tenant_id: int) -> int:
    """Serialisiert alle Rechteänderungen eines Mandanten (Schutzregel 4) und liefert die Zahl
    der handlungsfähigen Administratoren vor der Änderung (für ensure_admin_remains)."""
    db.execute(select(Tenant.id).where(Tenant.id == tenant_id).with_for_update())
    return count_capable_admins(db, tenant_id)


def _ensure_subset(actor: CurrentUser | None, permissions: Iterable[str], scopes: dict[str, str] | None = None) -> None:
    """Schutzregel 1: nur Rechte, die der Akteur selbst hat - und ein Recht mit Reichweite nur dann
    «für alle», wenn der Akteur es selbst für alle hat (``scopes``: Reichweiten der betroffenen
    Rolle bzw. des Kontos; fehlt ein Recht darin, gilt «alle»)."""
    if actor is None:
        return
    permissions = set(permissions)
    missing = permissions - set(actor.permissions)
    widened = {key for key in permissions if key in actor.assigned_only and (scopes or {}).get(key, SCOPE_ALL) == SCOPE_ALL}
    if missing or widened:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "permission_not_held", "message": "Nur Berechtigungen, die man selbst hat, können vergeben oder verwaltet werden"},
        )


def ensure_can_manage_account(db: Session, actor: CurrentUser | None, user_id: int) -> None:
    """Konto eines anderen verwalten (Passwort, Login, E-Mail, Aktiv, MFA, Rollen, Löschen):
    nur, wenn dessen Berechtigungen eine Teilmenge der eigenen sind (Schutzregel 1)."""
    if actor is None:
        return
    target_permissions, _ = load_role_permissions(db, user_id)
    _ensure_subset(actor, target_permissions, {key: SCOPE_ASSIGNED for key in load_role_scopes(db, user_id)})


def count_capable_admins(db: Session, tenant_id: int, *, excluding: set[int] | None = None) -> int:
    """Aktive Konten mit Login, die access.manage haben (über die Standardrolle admin oder eine
    eigene Rolle mit access.manage). Ausgetretene (AppUser.has_left) können sich nicht anmelden
    und zählen deshalb nicht."""
    from app.services.todo_fine_service import today

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
        .where(
            AppUser.tenant_id == tenant_id, AppUser.is_active.is_(True), AppUser.login_enabled.is_(True), grants_access,
            or_(AppUser.left_at.is_(None), AppUser.left_at >= today()),
        )
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
        raise RoleConflict("Der letzte Administrator eines Mandanten kann nicht entfernt oder herabgestuft werden", "last_admin")
    if affects_actor and actor is not None and P.ACCESS_MANAGE.value in actor.permissions:
        own, _ = load_role_permissions(db, actor.user_id)
        account = db.get(AppUser, actor.user_id)
        still_active = account is not None and account.is_active and not account.has_left
        if P.ACCESS_MANAGE.value not in own or not still_active:
            raise RoleConflict("Die eigene Benutzerverwaltung kann man sich nicht selbst entziehen", "own_access_management")


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
        raise RoleConflict("Der letzte Administrator eines Mandanten kann nicht entfernt oder herabgestuft werden", "last_admin")


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
        # Je Rolle: eine Rolle mit «alle» vergeben/entziehen setzt «alle» beim Akteur voraus
        scopes = _role_scopes(db, changed)
        for role_id, role_permissions in permissions.items():
            _ensure_subset(actor, role_permissions, scopes.get(role_id, {}))
    with admin_guard(db, user.tenant_id, actor, affects_actor=actor is not None and user.id == actor.user_id):
        if current - wanted:
            db.execute(delete(UserRole).where(UserRole.user_id == user.id, UserRole.role_id.in_(current - wanted)))
        for role_id in wanted - current:
            db.add(UserRole(tenant_id=user.tenant_id, user_id=user.id, role_id=role_id))
    if actor is not None:
        # Nachvollziehbarkeit (Plan «Berechtigungen», Phase 8): jede Zuweisung mit vorher/nachher,
        # in derselben Transaktion - egal über welchen Weg (Zugriff, Konto anlegen/ändern, Mehrfachauswahl)
        from app.services.audit_service import AuditService

        names = dict(db.execute(select(TenantRole.id, func.coalesce(TenantRole.name, TenantRole.system_key)).where(TenantRole.id.in_(current | wanted))).all())
        # Akteur ohne Konto (Hilfsaufrufe, Tests): ohne Personenbezug statt Fremdschlüsselfehler
        known_actor = db.scalar(select(exists().where(AppUser.id == actor.user_id)))
        AuditService().log(
            db, action="user.roles_changed", actor=actor if known_actor else None, tenant_id=user.tenant_id,
            entity_type="user", entity_id=user.id, commit=False,
            details={"before": sorted(str(names.get(i) or i) for i in current), "after": sorted(str(names.get(i) or i) for i in wanted)},
        )
    return True


def attach_imported_roles(db: Session, user: AppUser, role_ids: Iterable[int]) -> None:
    """Mandantenimport: Rollen eines frisch importierten Kontos im neuen Mandanten. Ohne Akteur
    und ohne Schutzregeln - der Mandant entsteht gerade erst; role_ids stammen aus import_role
    bzw. system_role desselben Mandanten (der zusammengesetzte Fremdschlüssel erzwingt das)."""
    for role_id in dict.fromkeys(role_ids):
        db.add(UserRole(tenant_id=user.tenant_id, user_id=user.id, role_id=role_id))
    db.flush()


# ── Rollen anlegen, ändern, löschen ─────────────────────────────────────────────────────────


def _validated_permissions(keys: Iterable[str]) -> frozenset[str]:
    unknown = [key for key in keys if key not in {permission.value for permission in P}]
    if unknown:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unbekannte Berechtigung")
    # Gespeichert wird die vollständige Menge inkl. Implikationen - dann zeigt die Oberfläche
    # genau das, was wirkt.
    return frozenset(str(key) for key in expand(keys))


def _validated_scopes(keys: Iterable[str], scopes: dict[str, str] | None) -> dict[str, str]:
    """Reichweiten einer neuen Rollen-Konfiguration, aufgelöst für alle Rechte mit Reichweite der
    Rolle (Implikationen erben, siehe permissions.resolve_scopes). Eine Reichweite für ein Recht
    ohne Reichweite oder ein unbekannter Wert ist ein 400; Angaben zu Rechten, die die Rolle nicht
    hat, fallen weg."""
    scoped = {permission.value for permission in SCOPED_PERMISSIONS}
    requested = dict(scopes or {})
    for key, value in requested.items():
        if key not in scoped or value not in CATALOG[P(key)].scopes:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unbekannte Reichweite")
    return {key.value: scope for key, scope in resolve_scopes(list(keys), requested).items()}


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
        raise RoleConflict("Eine Rolle mit diesem Namen gibt es bereits", "role_name_taken")


def _replace_permissions(db: Session, role: TenantRole, keys: frozenset[str], scopes: dict[str, str] | None = None) -> None:
    """Speichert die Menge inkl. Implikationen; als Reichweite nur «assigned» (NULL = alle)."""
    db.execute(delete(TenantRolePermission).where(TenantRolePermission.role_id == role.id))
    for key in sorted(keys):
        scope = SCOPE_ASSIGNED if (scopes or {}).get(key) == SCOPE_ASSIGNED else None
        db.add(TenantRolePermission(role_id=role.id, permission_key=key, scope=scope))


def get_role(db: Session, tenant_id: int, role_id: uuid.UUID) -> TenantRole:
    role = db.scalar(select(TenantRole).where(TenantRole.tenant_id == tenant_id, TenantRole.public_id == role_id))
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rolle nicht gefunden")
    return role


def read_role(db: Session, role: TenantRole) -> RoleRead:
    permissions = _role_permissions(db, [role.id]).get(role.id, frozenset())
    count = int(db.scalar(select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id)) or 0)
    return _read(role, permissions, count, role_scopes(db, role))


def create_role(db: Session, actor: CurrentUser, payload: RoleCreate) -> TenantRole:
    require_permission(actor, P.ACCESS_MANAGE)
    tenant_id = actor.current_tenant_id
    lock_tenant(db, tenant_id)
    if (db.scalar(select(func.count()).select_from(TenantRole).where(TenantRole.tenant_id == tenant_id)) or 0) >= MAX_ROLES_PER_TENANT:
        raise RoleConflict("Zu viele Rollen", "too_many_roles")
    name = _clean_name(payload.name)
    if name is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name fehlt")
    _ensure_unique_name(db, tenant_id, name)
    permissions = _validated_permissions(payload.permissions)
    scopes = _validated_scopes(payload.permissions, payload.scopes)
    _ensure_subset(actor, permissions, scopes)
    role = TenantRole(tenant_id=tenant_id, name=name, description=_clean_description(payload.description), require_mfa=payload.require_mfa)
    db.add(role)
    db.flush()
    _replace_permissions(db, role, permissions, scopes)
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
        raise RoleConflict("Die Rolle Administrator ist fest und kann nicht geändert werden", "admin_role_fixed")
    before = _role_permissions(db, [role.id]).get(role.id, frozenset())
    before_scopes = role_scopes(db, role)
    _ensure_subset(actor, before, before_scopes)
    fields = payload.model_fields_set
    name = role.name
    if "name" in fields:
        name = _clean_name(payload.name)
        if name is None and role.system_key is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name fehlt")
        _ensure_unique_name(db, role.tenant_id, name, excluding_id=role.id)
    after = before
    after_scopes = before_scopes
    new_permissions = "permissions" in fields and payload.permissions is not None
    new_scopes = "scopes" in fields and payload.scopes is not None
    if new_permissions or new_scopes:
        raw = list(payload.permissions or []) if new_permissions else sorted(before)
        # Ohne neue Reichweiten bleiben die bisherigen - eine Änderung nur der Rechte darf «nur
        # zugewiesene» nicht stillschweigend auf «alle» ausweiten.
        requested = payload.scopes if new_scopes else {key: value for key, value in before_scopes.items() if value == SCOPE_ASSIGNED}
        after = _validated_permissions(raw)
        if not new_scopes and requested:
            # Neu dazukommende Rechte mit Reichweite übernehmen «nur zugewiesene» der Rolle - sonst
            # machte z. B. review (ohne Angabe = alle) über die Implikation auch read wieder «alle»
            # (Security-Review Phase 4)
            scoped = {permission.value for permission in SCOPED_PERMISSIONS}
            for key in after - before:
                if key in scoped:
                    requested.setdefault(key, SCOPE_ASSIGNED)
        after_scopes = _validated_scopes(raw, requested)
        _ensure_subset(actor, after, after_scopes)
    with admin_guard(db, role.tenant_id, actor, affects_actor=role.id in actor.role_ids):
        role.name = name
        if "description" in fields:
            role.description = _clean_description(payload.description)
        if "require_mfa" in fields and payload.require_mfa is not None:
            role.require_mfa = payload.require_mfa
        if after != before or after_scopes != before_scopes:
            _replace_permissions(db, role, after, after_scopes)
        db.add(role)
    return before, after


def delete_role(db: Session, actor: CurrentUser, role: TenantRole) -> None:
    require_permission(actor, P.ACCESS_MANAGE)
    lock_tenant(db, role.tenant_id)
    if role.system_key is not None:
        raise RoleConflict("Standardrollen können nicht gelöscht werden", "system_role_not_deletable")
    _ensure_subset(actor, _role_permissions(db, [role.id]).get(role.id, frozenset()), role_scopes(db, role))
    if db.scalar(select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id)):
        raise RoleConflict("Die Rolle ist noch Benutzern zugewiesen", "role_in_use")
    # Eine Rolle ohne Zuweisungen kann niemandem Rechte nehmen - Schutzregeln 2/3 greifen hier nicht.
    db.delete(role)
    db.flush()


# ── Mandantenimport ─────────────────────────────────────────────────────────────────────────


def import_role(
    db: Session, tenant_id: int, *, system_key: str | None, name: str | None, description: str | None, permissions: Iterable[str],
    require_mfa: bool = False, scopes: dict[str, str] | None = None,
) -> TenantRole:
    """Übernimmt eine Rolle aus einem Mandantenexport in einen neu angelegten Mandanten. Die
    Standardrollen hat der Trigger schon angelegt (admin bleibt fest und unverändert), eigene
    Rollen entstehen neu. Unbekannte Berechtigungen (Export einer neueren Installation) fallen
    weg; gespeichert wird die Menge inkl. Implikationen wie bei create_role."""
    role = system_role(db, tenant_id, system_key) if system_key else TenantRole(tenant_id=tenant_id)
    if system_key == ADMIN_ROLE_KEY:
        return role
    role.name = name
    role.description = description
    role.require_mfa = require_mfa  # MFA-Pflicht der Rolle (Migration 0192) geht beim Import nicht verloren
    db.add(role)
    db.flush()
    known = {permission.value for permission in P}
    kept = [key for key in permissions if key in known]
    # Reichweiten (Export ab 0195) gehen beim Import nicht verloren - sonst würde «nur zugewiesene»
    # nach dem Import still zu «alle». Unbekannte Angaben fallen weg wie unbekannte Rechte.
    scoped = {permission.value for permission in SCOPED_PERMISSIONS}
    valid_scopes = {key: value for key, value in (scopes or {}).items() if key in scoped and value in CATALOG[P(key)].scopes}
    _replace_permissions(db, role, frozenset(str(key) for key in expand(kept)), _validated_scopes(kept, valid_scopes))
    db.flush()
    return role
