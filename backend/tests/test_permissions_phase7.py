"""Plan «Berechtigungen», Phase 7: «Ansehen als …» (GET /api/users/{id}/access-preview).

Nur lesende Vorschau ohne Sitzung des Kontos (services/access_preview_service.py):
- liefert Rechte inkl. Reichweite, Module, Rollen, MFA-Pflicht und die sichtbaren Abgaben;
- nur mit access.manage (403), nur eigener Mandant (fremd und unbekannt: gleiche 404);
- nur Konten ohne mehr Rechte als man selbst (403 permission_not_held, im Verlauf als failure);
- jeder Aufruf steht im Verlauf (user.access_previewed).
Die Rollen-Vorlagen sind Frontend-Konstanten (frontend/lib/role-templates.ts, vitest).
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.api.routes import roles as routes
from app.core.security import build_current_user
from app.models import SubmissionAssignment
from app.schemas.role import RoleCreate
from app.services import role_service
from app.services import submission_reviewer_service as reviewers
from tests.factories import GRANDFATHERED_FEATURES, make_app_user, make_tenant

FEATURES = GRANDFATHERED_FEATURES + ("abgabebox",)


def _assignment(db, tenant_id: int, title: str) -> SubmissionAssignment:
    assignment = SubmissionAssignment(tenant_id=tenant_id, title=title, public_slug=f"a-{uuid.uuid4().hex[:8]}", source_type="manual")
    db.add(assignment)
    db.flush()
    return assignment


def _audit(db, tenant_id: int) -> list[tuple[str, int, dict]]:
    return [
        (row.outcome, row.entity_id, row.details_json)
        for row in db.execute(
            text("SELECT outcome, entity_id, details_json FROM audit_log WHERE tenant_id = :t AND action = 'user.access_previewed' ORDER BY id"),
            {"t": tenant_id},
        )
    ]


@pytest.fixture
def org(db):
    tenant = make_tenant(db, "Verein Vorschau", features=FEATURES)
    other = make_tenant(db, "Verein Fremd", features=FEATURES)
    admin = make_app_user(db, "admin@vorschau.example", tenant_id=tenant.id, role_code="admin")
    actor = build_current_user(db, admin)
    reviewer = make_app_user(db, "pruefer@vorschau.example", tenant_id=tenant.id, role_code="reader")
    role = role_service.create_role(db, actor, RoleCreate(name="Prüfer", permissions=["submissions.review"], scopes={"submissions.review": "assigned"}, require_mfa=True))
    db.flush()
    role_service.set_user_roles(db, None, reviewer, [role])
    mine = _assignment(db, tenant.id, "Berichte")
    _assignment(db, tenant.id, "Fotos")
    reviewers.set_reviewers(db, actor, mine, {reviewer.id})
    db.commit()
    return {"tenant": tenant, "other": other, "admin": admin, "actor": actor, "reviewer": reviewer, "mine": mine}


def test_preview_shows_permissions_scopes_and_assigned_submissions(db, org):
    result = routes.get_access_preview(org["reviewer"].public_id, db, org["actor"])

    by_key = {item.key: item for item in result.permissions}
    assert set(by_key) == {"submissions.read", "submissions.review"}
    assert by_key["submissions.review"].scope == "assigned"
    assert by_key["submissions.read"].scope == "assigned"
    assert all(item.effective and item.feature_access == "full" for item in by_key.values())
    assert [role.name for role in result.roles] == ["Prüfer"]
    assert result.mfa_required is True and result.mfa_active is False
    assert "abgabebox" in result.enabled_features
    assert result.submissions is not None and result.submissions.scope == "assigned"
    assert [item.title for item in result.submissions.assigned] == ["Berichte"]
    assert result.submissions.visible_count == 1

    [(outcome, entity_id, details)] = _audit(db, org["tenant"].id)
    assert outcome == "success" and entity_id == org["reviewer"].id
    assert details["target"] == str(org["reviewer"].public_id)


def test_preview_admin_target_sees_all_submissions(db, org):
    other_admin = make_app_user(db, "admin2@vorschau.example", tenant_id=org["tenant"].id, role_code="admin")
    db.commit()
    result = routes.get_access_preview(other_admin.public_id, db, org["actor"])
    assert result.submissions is not None and result.submissions.scope == "all" and result.submissions.visible_count == 2
    assert result.submissions.assigned == []
    assert {item.key for item in result.permissions} >= {"access.manage", "settings.manage"}
    assert result.mfa_required is True


def test_preview_feature_not_booked_is_not_effective(db):
    tenant = make_tenant(db, "Ohne Finanzen")  # finance nicht gebucht
    admin = make_app_user(db, "admin@ohne.example", tenant_id=tenant.id, role_code="admin")
    reader = make_app_user(db, "leser@ohne.example", tenant_id=tenant.id, role_code="reader")
    db.commit()
    result = routes.get_access_preview(reader.public_id, db, build_current_user(db, admin))
    finances = next(item for item in result.permissions if item.key == "finances.read")
    assert finances.feature_access == "none" and finances.effective is False
    assert next(item for item in result.permissions if item.key == "meetings.read").effective is True
    # abgabebox nicht gebucht: keine Abgaben sichtbar
    assert result.submissions is None


def test_preview_foreign_and_unknown_accounts_are_404(db, org):
    foreign = make_app_user(db, "fremd@fremd.example", tenant_id=org["other"].id, role_code="reader")
    db.commit()
    for target in (foreign.public_id, uuid.uuid4()):
        with pytest.raises(HTTPException) as exc:
            routes.get_access_preview(target, db, org["actor"])
        assert exc.value.status_code == 404
    assert _audit(db, org["tenant"].id) == []
    assert _audit(db, org["other"].id) == []


def test_preview_requires_access_manage(db, org):
    writer = make_app_user(db, "schreiber@vorschau.example", tenant_id=org["tenant"].id, role_code="writer")
    db.commit()
    with pytest.raises(HTTPException) as exc:
        routes.get_access_preview(org["reviewer"].public_id, db, build_current_user(db, writer))
    assert exc.value.status_code == 403
    assert _audit(db, org["tenant"].id) == []


def test_preview_of_higher_privileged_account_is_rejected_and_audited(db, org):
    # Benutzerverwalter ohne Finanzrechte darf den Admin nicht «ansehen als»
    manager = make_app_user(db, "verwalter@vorschau.example", tenant_id=org["tenant"].id, role_code="reader")
    role = role_service.create_role(db, org["actor"], RoleCreate(name="Benutzerverwaltung", permissions=["access.manage", "meetings.read"]))
    db.flush()
    role_service.set_user_roles(db, None, manager, [role])
    db.commit()
    manager_user = build_current_user(db, manager)

    with pytest.raises(HTTPException) as exc:
        routes.get_access_preview(org["admin"].public_id, db, manager_user)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "permission_not_held"
    # Auch «nur zugewiesene» → «alle» ist eine Ausweitung: der Prüfer hat review(assigned),
    # der Verwalter gar nicht - abgelehnt
    with pytest.raises(HTTPException):
        routes.get_access_preview(org["reviewer"].public_id, db, manager_user)

    entries = _audit(db, org["tenant"].id)
    assert [outcome for outcome, _, _ in entries] == ["failure", "failure"]
    assert entries[0][1] == org["admin"].id


def test_preview_does_not_change_the_target_account(db, org):
    reviewer = org["reviewer"]
    before = db.execute(
        text("SELECT session_revoke_at, first_login_at, password_hash, login_enabled, is_active FROM app_user WHERE id = :id"), {"id": reviewer.id}
    ).one()
    routes.get_access_preview(reviewer.public_id, db, org["actor"])
    after = db.execute(
        text("SELECT session_revoke_at, first_login_at, password_hash, login_enabled, is_active FROM app_user WHERE id = :id"), {"id": reviewer.id}
    ).one()
    assert tuple(before) == tuple(after)


def test_preview_lists_only_titles_the_actor_may_read(db, org):
    # Verwalter mit Abgaben nur «zugewiesene»: sieht beim Prüfer nur Titel gemeinsamer Aufträge
    manager = make_app_user(db, "verwalter2@vorschau.example", tenant_id=org["tenant"].id, role_code="reader")
    role = role_service.create_role(
        db, org["actor"],
        RoleCreate(name="Verwaltung zugewiesen", permissions=["access.manage", "submissions.review"], scopes={"submissions.review": "assigned"}),
    )
    db.flush()
    role_service.set_user_roles(db, None, manager, [role])
    db.commit()
    manager_user = build_current_user(db, manager)

    result = routes.get_access_preview(org["reviewer"].public_id, db, manager_user)
    assert result.submissions is not None and result.submissions.visible_count == 1
    assert result.submissions.assigned == []

    reviewers.set_reviewers(db, org["actor"], org["mine"], {org["reviewer"].id, manager.id})
    db.commit()
    result = routes.get_access_preview(org["reviewer"].public_id, db, build_current_user(db, manager))
    assert [item.title for item in result.submissions.assigned] == ["Berichte"]
