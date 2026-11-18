"""Neue Rechte und Rollen-Migration (Plan «Berechtigungen», Phase 3, Migrationen 0190/0191).

- Probelauf je Rolle: niemand verliert ein Recht; neu hinzu kommen nur die umbenannten/abgetrennten
  Fähigkeiten und «eigene Pendenzen erledigen» für alle (Entscheid 18.11.2026).
- Standardrollen neuer Mandanten haben die neuen Rechte (hocx_seed_tenant_roles).
- Eigene Pendenzen: nur Status, nur eigene; ohne Recht read-only.
- Vier-Augen-Prinzip: Verfasser schliesst nicht selbst ab, abschliessen braucht meetings.approve.
- Personen ansehen ohne Kontaktdaten.
"""
from __future__ import annotations

import dataclasses

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.routes import participants as participant_routes
from app.api.routes import protocols as protocol_routes
from app.api.routes import todos as todo_routes
from app.models import ProtocolTodo, TenantRole, TenantRolePermission, TodoStatus
from app.schemas.protocol import ProtocolTodoUpdate, ProtocolUpdate
from app.services import permission_mapping
from tests.factories import (
    make_current_user,
    make_participant,
    make_protocol,
    make_template,
    make_tenant,
)


def _role_keys(db, tenant_id: int, system_key: str) -> set[str]:
    role = db.scalar(select(TenantRole).where(TenantRole.tenant_id == tenant_id, TenantRole.system_key == system_key))
    return set(db.scalars(select(TenantRolePermission.permission_key).where(TenantRolePermission.role_id == role.id)))


def test_new_tenant_gets_the_new_rights_and_nobody_loses_anything(db):
    tenant = make_tenant(db, "Rechte")
    reader = _role_keys(db, tenant.id, "reader")
    writer = _role_keys(db, tenant.id, "writer")
    kassier = _role_keys(db, tenant.id, "kassier")
    assert "todos.complete_own" in reader and "todos.complete_own" in kassier
    assert {"meetings.approve", "photos.manage", "files.read", "sharing.public", "submissions.review"} <= writer
    assert "fines.manage" in kassier and "fines.manage" not in writer
    # Datenauskunft für andere war data.export (nur Admin): Schreiber bekommen sie nicht
    assert "participants.export" not in writer

    for change in permission_mapping.report(db, tenant_id=tenant.id):
        assert set(change.before) <= set(change.after)
        # Nach der Migration ist der Probelauf idempotent: nichts mehr hinzuzufügen
        assert change.added == []


def test_mapping_only_adds_renamed_capabilities():
    assert permission_mapping.mapped({"meetings.read"}) == {"meetings.read", "todos.complete_own"}
    assert permission_mapping.mapped({"files.manage"}) >= {"files.read", "photos.read", "photos.manage", "sharing.public"}
    assert "participants.export" not in permission_mapping.mapped({"participants.manage"})
    assert "participants.export" in permission_mapping.mapped({"data.export"})


@pytest.fixture
def todo_setup(db):
    tenant = make_tenant(db, "Pendenzen")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    me = make_participant(db, tenant.id, "Ich")
    other = make_participant(db, tenant.id, "Andere")
    return {"tenant": tenant, "protocol": protocol, "me": me, "other": other}


def _todo(db, tenant_id: int, assignee_id: int) -> ProtocolTodo:
    open_id = db.scalar(select(TodoStatus.id).where(TodoStatus.code == "open"))
    todo = ProtocolTodo(tenant_id=tenant_id, protocol_element_block_id=None, sort_index=0, task="Aufgabe",
                        assigned_participant_id=assignee_id, todo_status_id=open_id, tags=[])
    db.add(todo)
    db.flush()
    return todo


def test_reader_completes_only_own_tasks_and_only_the_status(db, todo_setup):
    tenant, me, other = todo_setup["tenant"], todo_setup["me"], todo_setup["other"]
    done_id = db.scalar(select(TodoStatus.id).where(TodoStatus.code == "done"))
    mine, theirs = _todo(db, tenant.id, me.id), _todo(db, tenant.id, other.id)
    reader = dataclasses.replace(make_current_user(tenant.id, role="reader"), user_id=me.id)

    todo_routes.patch_todo(mine.public_id, ProtocolTodoUpdate(todo_status_id=done_id), db=db, user=reader)
    db.refresh(mine)
    assert mine.todo_status_id == done_id

    with pytest.raises(HTTPException) as other_todo:
        todo_routes.patch_todo(theirs.public_id, ProtocolTodoUpdate(todo_status_id=done_id), db=db, user=reader)
    assert other_todo.value.status_code == 404
    with pytest.raises(HTTPException) as more_fields:
        todo_routes.patch_todo(mine.public_id, ProtocolTodoUpdate(task="Umbenannt"), db=db, user=reader)
    assert more_fields.value.status_code == 403

    read_only = dataclasses.replace(reader, permissions=reader.permissions - {"todos.complete_own"})
    with pytest.raises(HTTPException) as no_right:
        todo_routes.patch_todo(mine.public_id, ProtocolTodoUpdate(todo_status_id=done_id), db=db, user=read_only)
    assert no_right.value.status_code == 403


def test_four_eyes_blocks_the_author_and_closing_needs_approve(db):
    tenant = make_tenant(db, "Vier Augen")
    template = make_template(db, tenant.id)
    author_person = make_participant(db, tenant.id, "Verfasserin")
    reviewer_person = make_participant(db, tenant.id, "Prüfer")
    protocol = make_protocol(db, tenant.id, template.id, status="durchgeführt")
    protocol.created_by = author_person.id
    db.flush()
    author = dataclasses.replace(make_current_user(tenant.id, role="writer"), user_id=author_person.id)
    reviewer = dataclasses.replace(make_current_user(tenant.id, role="writer"), user_id=reviewer_person.id)

    without_approve = dataclasses.replace(reviewer, permissions=reviewer.permissions - {"meetings.approve"})
    with pytest.raises(HTTPException) as missing:
        protocol_routes._ensure_can_approve(db, without_approve, protocol)
    assert missing.value.status_code == 403

    protocol_routes._ensure_can_approve(db, author, protocol)  # Standard: Vier-Augen aus
    tenant.four_eyes_protocols = True
    db.flush()
    with pytest.raises(HTTPException) as own:
        protocol_routes._ensure_can_approve(db, author, protocol)
    assert own.value.status_code == 403 and own.value.detail["code"] == "four_eyes_required"
    protocol_routes._ensure_can_approve(db, reviewer, protocol)


def test_reading_people_without_contacts_hides_the_email(db):
    tenant = make_tenant(db, "Kontakte")
    person = make_participant(db, tenant.id, "Anna")
    person.email = "anna@example.com"
    db.flush()
    viewer = make_current_user(tenant.id, permissions=frozenset({"participants.read"}))
    [read] = participant_routes._overview_reads(db, viewer, [person])
    assert read.email is None and read.roles == [] and read.login_status == "none"
    manager = make_current_user(tenant.id, role="writer")
    [read] = participant_routes._overview_reads(db, manager, [person])
    assert read.email == "anna@example.com"


def test_people_search_does_not_match_emails_without_contacts(db):
    from app.api.routes import search as search_routes

    tenant = make_tenant(db, "Suche Kontakte")
    person = make_participant(db, tenant.id, "Anna Beispiel")
    person.email = "geheim.adresse@example.com"
    db.flush()
    assert search_routes.search_people(db, tenant.id, "geheim.adresse", by_email=False) == []
    assert [hit.name for hit in search_routes.search_people(db, tenant.id, "geheim.adresse")] == ["Anna Beispiel"]


def test_admin_mfa_reset_does_not_start_a_new_grace_period(db):
    from datetime import UTC, datetime, timedelta

    from app.core.mfa_policy import mfa_grace_until
    from app.models import AppUser, UserMfaFactor
    from app.services.mfa_service import MfaService
    from tests.factories import make_app_user

    tenant = make_tenant(db, "MFA Reset")
    tenant.require_mfa = True
    admin = make_app_user(db, "reset-admin@example.com", tenant_id=tenant.id, role_code="admin")
    person = make_app_user(db, "reset-person@example.com", tenant_id=tenant.id, role_code="reader")
    person.first_login_at = datetime.now(UTC) - timedelta(days=30)
    factor = UserMfaFactor(user_id=person.id, factor_type="totp", label="App", secret_encrypted="x")
    db.add(factor)
    db.flush()
    actor = dataclasses.replace(make_current_user(tenant.id, role="admin", user_id=admin.id), mfa_verified=True)
    MfaService().delete_managed_user_factor(db, actor, person.id, factor.id)
    assert db.get(AppUser, person.id).mfa_grace_until is not None
    assert mfa_grace_until(db, person.id, tenant_id=tenant.id) is None
