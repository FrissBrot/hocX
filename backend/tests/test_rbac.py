"""Rollen und Berechtigungen (RBAC, docs/RBAC_ARCHITECTURE_PROPOSAL.md, Abschnitt H).

1. Äquivalenz: die vier Standardrollen bilden die bisherigen festen Rollen exakt ab - verglichen
   mit einer eingefrorenen Kopie der alten Prüflogik aus core/security.py (vor RBAC).
2. Schutzregeln der Rollenverwaltung (keine Rechteausweitung, letzter Administrator, kein
   Selbstentzug, feste Systemrolle) - auch unter Nebenläufigkeit.
3. Mandantentrennung der neuen Tabellen (RLS, zusammengesetzte Fremdschlüssel).
4. Mehrfachrollen (Vereinigungsmenge) und sofortige Wirkung auf bestehende Sessions.
"""
from __future__ import annotations

import threading
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import engine
from app.core.permissions import CATALOG, SYSTEM_ROLE_PERMISSIONS, P, expand
from app.core.security import CurrentUser, build_current_user, load_role_permissions, require_permission
from app.core.tenant_scope import bind_tenant_scope
from app.documents import permissions as document_permissions
from app.models import AppUser, Permission, Tenant, TenantRole, TenantRolePermission, UserRole
from app.schemas.role import RoleCreate, RoleUpdate
from app.services import role_service
from app.services.access_service import AccessService
from app.services.calendar_feed_service import can_subscribe
from app.services.statistics_common import own_person_key
from tests.factories import assign_roles, make_app_user, make_current_user, make_protocol, make_template, make_tenant, system_role

ROLES = ("admin", "writer", "kassier", "reader")
ALL_FEATURES = frozenset({"finance", "abgabebox", "custom_domain"})


# ── 1. Äquivalenz mit dem alten Rollenmodell ───────────────────────────────────────────────

# Eingefrorene Kopie der alten Regeln (core/security.py, access_service.py, documents/permissions.py,
# statistics_common.PER_PERSON_ROLES vor 0156_rbac). (Funktion, Rollen, nötiges Feature)
LEGACY = {
    "require_reader": ({"reader", "kassier", "writer", "admin"}, None),
    "require_writer": ({"writer", "admin"}, None),
    "require_admin": ({"admin"}, None),
    "require_finance_read": ({"reader", "kassier", "writer", "admin"}, "finance"),
    "require_finance_write": ({"kassier", "admin"}, "finance"),
    "require_abgabebox_read": ({"reader", "kassier", "writer", "admin"}, "abgabebox"),
    "require_abgabebox_write": ({"writer", "admin"}, "abgabebox"),
    "require_all_fines_read": ({"writer", "kassier", "admin"}, None),
    "sees_all_protocols": ({"admin", "writer", "kassier"}, None),
    "per_person_statistics": ({"writer", "kassier", "admin"}, None),
    "document_edit_templates": ({"writer", "admin"}, None),
    "document_publish": ({"admin"}, None),
    "document_personal_data": ({"writer", "admin"}, None),
    "document_unmark_drafts": ({"writer", "admin"}, None),
    "requires_mfa": ({"admin"}, None),
}

# Abbildung auf die neuen Berechtigungen (docs/RBAC_ARCHITECTURE_PROPOSAL.md, E.2).
NEW = {
    "require_reader": lambda user: user.can(P.MEETINGS_READ),
    "require_writer": lambda user: user.can(P.MEETINGS_EDIT),
    "require_admin": lambda user: user.can(P.ACCESS_MANAGE),
    "require_finance_read": lambda user: user.can(P.FINANCES_READ),
    "require_finance_write": lambda user: user.can(P.FINANCES_MANAGE),
    "require_abgabebox_read": lambda user: user.can(P.SUBMISSIONS_READ),
    "require_abgabebox_write": lambda user: user.can(P.SUBMISSIONS_MANAGE),
    "require_all_fines_read": lambda user: user.can(P.REPORTS_PERSONAL),
    "sees_all_protocols": lambda user: AccessService().sees_all_protocols(user),
    "per_person_statistics": lambda user: user.can(P.REPORTS_PERSONAL),
    "document_edit_templates": lambda user: document_permissions.capabilities(user)["edit_templates"],
    "document_publish": lambda user: document_permissions.capabilities(user)["publish_templates"],
    "document_personal_data": lambda user: document_permissions.capabilities(user)["personal_data"],
    "document_unmark_drafts": lambda user: document_permissions.capabilities(user)["unmark_drafts"],
    "requires_mfa": lambda user: any(CATALOG[P(key)].requires_mfa for key in user.permissions),
}


@pytest.mark.parametrize("features", [ALL_FEATURES, frozenset()], ids=["all-features", "no-features"])
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("check", sorted(LEGACY))
def test_standard_roles_are_equivalent_to_the_old_fixed_roles(check, role, features):
    roles, feature = LEGACY[check]
    expected = role in roles and (feature is None or feature in features)
    user = make_current_user(1, role=role, features=features)
    assert NEW[check](user) is expected


@pytest.mark.parametrize("role", ROLES)
def test_calendar_subscriptions_follow_meetings_read(role):
    """E-11: Termin-Abos jetzt für alle Rollen mit meetings.read (vorher nur writer/admin)."""
    user = make_current_user(1, role=role)
    assert can_subscribe(user, "todos") is True
    assert can_subscribe(user, "events") is True


def test_catalog_matches_the_permission_table(db):
    assert set(db.scalars(select(Permission.key))) == {key.value for key in P}


def test_implications_are_closed_in_the_standard_roles():
    for key, permissions in SYSTEM_ROLE_PERMISSIONS.items():
        assert expand(permissions) == permissions, key
    assert SYSTEM_ROLE_PERMISSIONS["admin"] == frozenset(P)


def test_new_tenants_get_the_standard_roles_with_their_permissions(db):
    tenant = make_tenant(db, "RBAC Neu")
    roles = {role.system_key: role for role in db.scalars(select(TenantRole).where(TenantRole.tenant_id == tenant.id))}
    assert set(roles) == set(ROLES)
    assert all(role.name is None for role in roles.values())
    for key in ("writer", "kassier", "reader"):
        stored = set(db.scalars(select(TenantRolePermission.permission_key).where(TenantRolePermission.role_id == roles[key].id)))
        assert stored == {permission.value for permission in SYSTEM_ROLE_PERMISSIONS[key]}
    # admin hat keine Zeilen und trotzdem alle Berechtigungen (auch künftige)
    assert db.scalar(select(TenantRolePermission.role_id).where(TenantRolePermission.role_id == roles["admin"].id)) is None
    user = make_app_user(db, email="rbac-new-admin@example.com", tenant_id=tenant.id, role_code="admin")
    assert load_role_permissions(db, user.id)[0] == {key.value for key in P}


# ── 2. Mehrfachrollen und Wirkung auf Sessions ─────────────────────────────────────────────


def test_several_roles_grant_the_union_of_their_permissions(db):
    """Der bisher dokumentierte Sonderfall «Schreiber und Kassier muss Admin sein» entfällt."""
    tenant = make_tenant(db, "RBAC Union")
    user = make_app_user(db, email="rbac-union@example.com", tenant_id=tenant.id, role_code="writer")
    assign_roles(db, user, "writer", "kassier")
    current = build_current_user(db, user)
    assert {"meetings.edit", "finances.manage"} <= current.permissions
    assert "access.manage" not in current.permissions
    assign_roles(db, user, "writer")
    assert "finances.manage" not in build_current_user(db, user).permissions


def test_permission_changes_apply_to_existing_sessions_immediately(db):
    """Rechte werden bei jedem Request neu geladen - eine geänderte Rolle wirkt ohne neues Login."""
    tenant = make_tenant(db, "RBAC Session")
    user = make_app_user(db, email="rbac-session@example.com", tenant_id=tenant.id, role_code="kassier")
    kassier = system_role(db, tenant.id, "kassier")
    assert "finances.manage" in build_current_user(db, user).permissions
    db.execute(delete(TenantRolePermission).where(TenantRolePermission.role_id == kassier.id, TenantRolePermission.permission_key == "finances.manage"))
    db.flush()
    assert "finances.manage" not in build_current_user(db, user).permissions


def test_a_permission_without_its_booked_module_has_no_effect():
    user = make_current_user(1, role="kassier", features=frozenset())
    assert P.FINANCES_MANAGE.value in user.permissions
    assert user.can(P.FINANCES_MANAGE) is False
    with pytest.raises(HTTPException) as exc_info:
        require_permission(user, P.FINANCES_MANAGE)
    assert "nicht gebucht" in exc_info.value.detail


def test_account_without_roles_has_no_permissions(db):
    tenant = make_tenant(db, "RBAC Leer")
    user = make_app_user(db, email="rbac-empty@example.com", tenant_id=tenant.id)
    db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    db.flush()
    current = build_current_user(db, user)
    assert current.permissions == frozenset()
    assert not any(current.can(key) for key in P)


# ── 3. Rollenverwaltung und Schutzregeln ───────────────────────────────────────────────────


def _actor(db, user: AppUser) -> CurrentUser:
    return build_current_user(db, user, mfa_verified=True)


def _tenant_with_admin(db, name: str):
    tenant = make_tenant(db, name)
    admin = make_app_user(db, email=f"admin-{uuid.uuid4().hex[:8]}@rbac.example", tenant_id=tenant.id, role_code="admin")
    return tenant, admin


def test_admin_creates_a_role_and_assigns_it(db):
    tenant, admin = _tenant_with_admin(db, "RBAC Rolle")
    member = make_app_user(db, email="rbac-member@example.com", tenant_id=tenant.id)
    role = role_service.create_role(db, _actor(db, admin), RoleCreate(name="  Protokoll   führung ", permissions=["meetings.edit"]))
    assert role.name == "Protokoll führung"
    read = role_service.read_role(db, role)
    # Gespeichert wird die vollständige Menge inkl. Implikationen.
    assert set(read.permissions) == {"meetings.edit", "meetings.read_drafts", "meetings.read"}
    role_service.set_user_roles(db, _actor(db, admin), member, [role])
    assert build_current_user(db, member).can(P.MEETINGS_EDIT)


def test_role_names_are_unique_per_tenant_case_insensitive(db):
    tenant, admin = _tenant_with_admin(db, "RBAC Namen")
    role_service.create_role(db, _actor(db, admin), RoleCreate(name="Revisor", permissions=[]))
    with pytest.raises(HTTPException) as exc_info:
        role_service.create_role(db, _actor(db, admin), RoleCreate(name="revisor", permissions=[]))
    assert exc_info.value.status_code == 409
    other, other_admin = _tenant_with_admin(db, "RBAC Namen 2")
    assert role_service.create_role(db, _actor(db, other_admin), RoleCreate(name="Revisor", permissions=[])).tenant_id == other.id


def test_unknown_permissions_are_rejected(db):
    _tenant, admin = _tenant_with_admin(db, "RBAC Unbekannt")
    with pytest.raises(HTTPException) as exc_info:
        role_service.create_role(db, _actor(db, admin), RoleCreate(name="Neu", permissions=["root.everything"]))
    assert exc_info.value.status_code == 400


def _user_manager(db, tenant: Tenant, *extra: str) -> AppUser:
    """Konto mit einer eigenen Rolle "Benutzerverwaltung" (access.manage + extra), ohne admin."""
    role = TenantRole(tenant_id=tenant.id, name=f"Benutzerverwaltung {uuid.uuid4().hex[:6]}")
    db.add(role)
    db.flush()
    for key in ("access.manage", *extra):
        db.add(TenantRolePermission(role_id=role.id, permission_key=key))
    user = make_app_user(db, email=f"manager-{uuid.uuid4().hex[:8]}@rbac.example", tenant_id=tenant.id)
    db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    db.add(UserRole(tenant_id=tenant.id, user_id=user.id, role_id=role.id))
    db.flush()
    return user


def test_no_privilege_escalation_via_role_assignment_or_role_editing(db):
    tenant, _admin = _tenant_with_admin(db, "RBAC Eskalation")
    # Hat die Rechte der Standardrolle reader (die das neue Mitglied schon hat), aber nicht mehr.
    manager = _actor(db, _user_manager(db, tenant, "meetings.read", "finances.read", "submissions.read"))
    member = make_app_user(db, email="rbac-esc-member@example.com", tenant_id=tenant.id)

    for attempt in (
        lambda: role_service.set_user_roles(db, manager, member, [system_role(db, tenant.id, "admin")]),
        lambda: role_service.set_user_roles(db, manager, member, [system_role(db, tenant.id, "kassier")]),
        lambda: role_service.create_role(db, manager, RoleCreate(name="Kasse", permissions=["finances.manage"])),
        lambda: role_service.update_role(db, manager, system_role(db, tenant.id, "reader"), RoleUpdate(permissions=["meetings.read", "data.export"])),
    ):
        with pytest.raises(HTTPException) as exc_info:
            attempt()
        assert exc_info.value.status_code == 403
    # Was er selbst hat, darf er vergeben.
    reader_only = role_service.create_role(db, manager, RoleCreate(name="Nur lesen", permissions=["meetings.read"]))
    assert role_service.set_user_roles(db, manager, member, [reader_only]) is True


def test_no_account_takeover_of_higher_privileged_users(db):
    """Passwort/Login/MFA eines Kontos verwaltet nur, wer mindestens dessen Rechte hat."""
    from app.schemas.user import UserUpdate
    from app.services.mfa_service import MfaService
    from app.services.user_service import UserService

    tenant, admin = _tenant_with_admin(db, "RBAC Übernahme")
    manager = _actor(db, _user_manager(db, tenant))
    with pytest.raises(HTTPException) as exc_info:
        UserService().update_user(db, admin.id, UserUpdate(password="ein neues langes passwort"), manager)
    assert exc_info.value.status_code == 403
    with pytest.raises(HTTPException) as exc_info:
        MfaService()._managed_user(db, manager, admin.id)
    assert exc_info.value.status_code == 403


def test_the_admin_role_is_fixed_and_standard_roles_are_not_deletable(db):
    tenant, admin = _tenant_with_admin(db, "RBAC Fest")
    actor = _actor(db, admin)
    with pytest.raises(HTTPException) as exc_info:
        role_service.update_role(db, actor, system_role(db, tenant.id, "admin"), RoleUpdate(name="Chef"))
    assert exc_info.value.status_code == 409
    for key in ROLES:
        with pytest.raises(HTTPException) as exc_info:
            role_service.delete_role(db, actor, system_role(db, tenant.id, key))
        assert exc_info.value.status_code == 409
    # Standardrollen lassen sich umbenennen und wieder auf die Standardbezeichnung zurücksetzen.
    reader = system_role(db, tenant.id, "reader")
    role_service.update_role(db, actor, reader, RoleUpdate(name="Mitglied"))
    assert reader.name == "Mitglied"
    role_service.update_role(db, actor, reader, RoleUpdate(name=""))
    assert reader.name is None


def test_a_role_in_use_cannot_be_deleted(db):
    tenant, admin = _tenant_with_admin(db, "RBAC In Gebrauch")
    actor = _actor(db, admin)
    role = role_service.create_role(db, actor, RoleCreate(name="Helfer", permissions=["meetings.read"]))
    member = make_app_user(db, email="rbac-helper@example.com", tenant_id=tenant.id)
    role_service.set_user_roles(db, actor, member, [role])
    with pytest.raises(HTTPException) as exc_info:
        role_service.delete_role(db, actor, role)
    assert exc_info.value.status_code == 409
    role_service.set_user_roles(db, actor, member, [system_role(db, tenant.id, "reader")])
    role_service.delete_role(db, actor, role)
    assert db.get(TenantRole, role.id) is None


def test_last_capable_admin_survives_role_changes(db):
    tenant, admin = _tenant_with_admin(db, "RBAC Letzter")
    custom = _user_manager(db, tenant)
    platform = None  # Plattform-Admin-Pfad: ohne Eskalationsschutz, Letzter-Admin-Schutz gilt
    # Zwei handlungsfähige: admin (Standardrolle) und custom (eigene Rolle mit access.manage).
    role_service.set_user_roles(db, platform, admin, [system_role(db, tenant.id, "reader")])
    custom_role = db.get(TenantRole, db.scalar(select(UserRole.role_id).where(UserRole.user_id == custom.id)))
    with pytest.raises(HTTPException) as exc_info:
        role_service.set_user_roles(db, platform, custom, [system_role(db, tenant.id, "reader")])
    assert exc_info.value.status_code == 409
    # Auch das Entfernen von access.manage aus der letzten Rolle zählt (durch einen anderen Admin).
    other_admin = make_app_user(db, email="rbac-other-admin@example.com", tenant_id=tenant.id, role_code="admin")
    role_service.set_user_roles(db, platform, other_admin, [system_role(db, tenant.id, "reader")])
    assert role_service.count_capable_admins(db, tenant.id) == 1
    actor = CurrentUser(**{**make_current_user(tenant.id, role="admin").__dict__, "user_id": admin.id})
    with pytest.raises(HTTPException) as exc_info:
        role_service.update_role(db, actor, custom_role, RoleUpdate(permissions=["meetings.read"]))
    assert exc_info.value.status_code == 409
    # Der Savepoint hat die abgelehnte Änderung zurückgenommen.
    assert role_service.count_capable_admins(db, tenant.id) == 1


def test_admins_cannot_remove_their_own_user_management(db):
    """E-2: Selbstentzug von access.manage nur durch einen anderen Administrator."""
    tenant, admin = _tenant_with_admin(db, "RBAC Selbst")
    make_app_user(db, email="rbac-second@example.com", tenant_id=tenant.id, role_code="admin")
    with pytest.raises(HTTPException) as exc_info:
        role_service.set_user_roles(db, _actor(db, admin), admin, [system_role(db, tenant.id, "writer")])
    assert exc_info.value.status_code == 409
    assert load_role_permissions(db, admin.id)[0] == {key.value for key in P}


def test_roles_of_another_tenant_cannot_be_assigned(db):
    tenant, admin = _tenant_with_admin(db, "RBAC Eigen")
    other = make_tenant(db, "RBAC Fremd")
    member = make_app_user(db, email="rbac-foreign@example.com", tenant_id=tenant.id)
    foreign = system_role(db, other.id, "admin")
    with pytest.raises(HTTPException) as exc_info:
        role_service.resolve_roles(db, tenant.id, [foreign.public_id])
    assert exc_info.value.status_code == 400
    with pytest.raises(HTTPException) as exc_info:
        role_service.get_role(db, tenant.id, foreign.public_id)
    assert exc_info.value.status_code == 404
    # Auch an der Anwendung vorbei verhindert die Datenbank die Zuweisung (zusammengesetzter FK).
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.execute(text("INSERT INTO user_role (tenant_id, user_id, role_id) VALUES (:t, :u, :r)"), {"t": tenant.id, "u": member.id, "r": foreign.id})


def test_role_tables_are_tenant_isolated(db):
    tenant_a, tenant_b = make_tenant(db, "RBAC RLS A"), make_tenant(db, "RBAC RLS B")
    user_b = make_app_user(db, email="rbac-rls@example.com", tenant_id=tenant_b.id)
    role_b_id = system_role(db, tenant_b.id, "writer").id
    user_b_id = user_b.id
    db.flush()
    db.expire_all()
    db.execute(text("SET LOCAL ROLE hocx_app"))
    bind_tenant_scope(db, tenant_a.id)
    try:
        assert db.scalar(select(TenantRole.id).where(TenantRole.id == role_b_id)) is None
        assert db.scalar(select(TenantRolePermission.role_id).where(TenantRolePermission.role_id == role_b_id)) is None
        assert db.scalar(select(UserRole.user_id).where(UserRole.user_id == user_b_id)) is None
        # Die Permission-Liste ist global und nur lesbar.
        assert db.scalar(select(Permission.key).where(Permission.key == "meetings.read")) == "meetings.read"
        with pytest.raises(Exception):
            with db.begin_nested():
                db.execute(text("INSERT INTO permission (key) VALUES ('evil.permission')"))
    finally:
        bind_tenant_scope(db, None)
        db.execute(text("RESET ROLE"))
        db.expire_all()


# ── 4. Nebenläufigkeit: zwei Admins stufen sich gleichzeitig gegenseitig herab ───────────────


def test_concurrent_mutual_demotion_leaves_one_admin():
    """RBAC-Analyse S-6: ohne Mandantensperre zählten beide Transaktionen noch zwei Admins und
    beide Herabstufungen gingen durch - der Mandant stand ohne Admin da."""
    setup = Session(bind=engine, autoflush=False, future=True)
    tenant = make_tenant(setup, f"RBAC Parallel {uuid.uuid4().hex[:6]}")
    first = make_app_user(setup, email=f"p1-{uuid.uuid4().hex[:8]}@rbac.example", tenant_id=tenant.id, role_code="admin")
    second = make_app_user(setup, email=f"p2-{uuid.uuid4().hex[:8]}@rbac.example", tenant_id=tenant.id, role_code="admin")
    tenant_id, ids = tenant.id, (first.id, second.id)
    setup.commit()
    setup.close()

    barrier = threading.Barrier(2)
    results: list[str] = []

    def demote(target_id: int) -> None:
        session = Session(bind=engine, autoflush=False, future=True)
        try:
            target = session.get(AppUser, target_id)
            reader = role_service.system_role(session, tenant_id, "reader")
            barrier.wait()
            role_service.set_user_roles(session, None, target, [reader])
            session.commit()
            results.append("ok")
        except HTTPException as exc:
            session.rollback()
            results.append(str(exc.status_code))
        finally:
            session.close()

    threads = [threading.Thread(target=demote, args=(user_id,)) for user_id in ids]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert sorted(results) == ["409", "ok"]
        check = Session(bind=engine, future=True)
        try:
            assert role_service.count_capable_admins(check, tenant_id) == 1
        finally:
            check.close()
    finally:
        cleanup = Session(bind=engine, future=True)
        try:
            cleanup.execute(delete(Tenant).where(Tenant.id == tenant_id))
            cleanup.commit()
        finally:
            cleanup.close()


# ── 5. Ressourcenregeln (Phase 0) ─────────────────────────────────────────────────────────


def test_unrestricted_readers_see_finalized_protocols_only(db):
    tenant = make_tenant(db, "RBAC Entwürfe")
    template = make_template(db, tenant.id)
    final = make_protocol(db, tenant.id, template.id, protocol_number="F-1", status="abgeschlossen")
    draft = make_protocol(db, tenant.id, template.id, protocol_number="D-1", status="vorbereitet")
    access = AccessService()
    reader = make_current_user(tenant.id, role="reader")
    visible = access.protocol_visibility(db, reader)
    assert visible(final) is True and visible(draft) is False
    assert access.can_read_protocol(db, reader, draft.id) is False
    writer = make_current_user(tenant.id, role="writer")
    assert access.can_read_protocol(db, writer, draft.id) is True
    assert access.protocol_visibility(db, writer)(draft) is True


def test_per_person_statistics_follow_reports_personal(db):
    tenant = make_tenant(db, "RBAC Statistik")
    assert own_person_key(db, make_current_user(tenant.id, role="kassier")) is None
    assert own_person_key(db, make_current_user(tenant.id, role="reader", user_id=7)) == "id:7"
    custom = make_current_user(tenant.id, user_id=8, permissions=frozenset({"meetings.read", "reports.personal"}))
    assert own_person_key(db, custom) is None


# ── 6. Lese-Lecks aus der RBAC-Analyse (S-3, S-4) und die Rollen-API ──────────────────────


def _restricted_reader(db, tenant, template):
    """Leser, der als Teilnehmer nur `template` zugeordnet ist (Ressourcenregel R3)."""
    from app.services.participant_service import ParticipantService

    user = make_app_user(db, email=f"restricted-{uuid.uuid4().hex[:8]}@rbac.example", tenant_id=tenant.id)
    ParticipantService().replace_templates_for_participant(db, user.id, [template.id])
    db.flush()
    return make_current_user(tenant.id, role="reader", user_id=user.id)


def test_restricted_readers_only_see_their_protocols_in_subroutes_and_todo_blocks(db):
    from app.api.routes import protocols as protocol_routes
    from app.api.routes import todos as todo_routes
    from tests.factories import make_protocol_element, make_protocol_element_block

    tenant = make_tenant(db, "RBAC S-3")
    own_template, other_template = make_template(db, tenant.id, name="Eigene"), make_template(db, tenant.id, name="Fremde")
    reader = _restricted_reader(db, tenant, own_template)
    foreign = make_protocol(db, tenant.id, other_template.id, protocol_number="X-1", status="abgeschlossen")
    element = make_protocol_element(db, foreign.id)
    make_protocol_element_block(db, element.id, {}, element_type_code="todo")

    with pytest.raises(HTTPException) as exc_info:
        protocol_routes.get_protocol_period(foreign.public_id, db=db, user=reader)
    assert exc_info.value.status_code == 403
    with pytest.raises(HTTPException):
        protocol_routes.get_pending_todos(foreign.public_id, db=db, user=reader)
    blocks = todo_routes.list_todo_blocks(db=db, user=reader)
    assert all(block["protocol_id"] != foreign.public_id for block in blocks)
    writer = make_current_user(tenant.id, role="writer")
    assert any(block["protocol_id"] == foreign.public_id for block in todo_routes.list_todo_blocks(db=db, user=writer))


def test_participant_names_in_document_sources_need_participant_or_meeting_rights(db):
    """S-4/E-12: die Quelle 'participants' lieferte jedem Leser alle Namen, obwohl
    GET /participants participants.manage verlangt."""
    from app.api.routes import documents as document_routes

    tenant = make_tenant(db, "RBAC S-4")
    make_app_user(db, email="rbac-s4@example.com", tenant_id=tenant.id)
    with pytest.raises(HTTPException) as exc_info:
        document_routes.list_source_options("participants", protocol_id=None, db=db, user=make_current_user(tenant.id, role="reader"))
    assert exc_info.value.status_code == 403
    assert document_routes.list_source_options("participants", protocol_id=None, db=db, user=make_current_user(tenant.id, role="writer"))


def test_role_routes_need_access_manage_and_audit_changes(db):
    from app.api.routes import roles as role_routes
    from app.schemas.role import UserRolesUpdate

    tenant, admin = _tenant_with_admin(db, "RBAC API")
    reader = make_current_user(tenant.id, role="reader")
    for call in (
        lambda: role_routes.list_roles(db=db, user=reader),
        lambda: role_routes.get_permission_catalog(user=reader),
        lambda: role_routes.create_role(RoleCreate(name="X", permissions=[]), db=db, user=reader),
    ):
        with pytest.raises(HTTPException) as exc_info:
            call()
        assert exc_info.value.status_code == 403

    actor = _actor(db, admin)
    assert {entry.key for entry in role_routes.get_permission_catalog(user=actor)} == {key.value for key in P}
    created = role_routes.create_role(RoleCreate(name="Revisor", permissions=["meetings.read_drafts"]), db=db, user=actor)
    assert set(created.permissions) == {"meetings.read_drafts", "meetings.read"}
    member = make_app_user(db, email="rbac-api-member@example.com", tenant_id=tenant.id)
    refs = role_routes.set_user_roles(member.public_id, UserRolesUpdate(role_ids=[created.id]), db=db, user=actor)
    assert [ref.id for ref in refs] == [created.id]
    other_tenant_user = make_app_user(db, email="rbac-api-foreign@example.com", tenant_id=make_tenant(db, "RBAC API 2").id)
    with pytest.raises(HTTPException) as exc_info:
        role_routes.set_user_roles(other_tenant_user.public_id, UserRolesUpdate(role_ids=[created.id]), db=db, user=actor)
    assert exc_info.value.status_code == 404
    actions = set(db.scalars(text("SELECT action FROM audit_log WHERE tenant_id = :t"), {"t": tenant.id}))
    assert {"role.created", "user.roles_changed"} <= actions


def test_participant_routes_cannot_remove_or_lock_out_higher_privileged_accounts(db):
    """Security-Review: über /participants liessen sich Admins von einem Konto mit nur
    access.manage + participants.manage löschen oder deaktivieren (an /users vorbei)."""
    from app.api.routes import participants as participant_routes
    from app.schemas.participant import ParticipantBulkDelete, ParticipantUpdate

    tenant, admin = _tenant_with_admin(db, "RBAC Teilnehmer-Routen")
    manager = _actor(db, _user_manager(db, tenant, "participants.manage"))
    for call in (
        lambda: participant_routes.patch_participant(admin.public_id, ParticipantUpdate(is_active=False), db=db, user=manager),
        lambda: participant_routes.patch_participant(admin.public_id, ParticipantUpdate(email="neu@rbac.example"), db=db, user=manager),
        lambda: participant_routes.delete_participant(admin.public_id, db=db, user=manager),
        lambda: participant_routes.bulk_delete_participants(ParticipantBulkDelete(participant_ids=[admin.public_id]), db=db, user=manager),
    ):
        with pytest.raises(HTTPException) as exc_info:
            call()
        assert exc_info.value.status_code == 403
    assert db.get(AppUser, admin.id).is_active is True
