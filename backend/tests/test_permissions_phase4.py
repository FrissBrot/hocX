"""Plan «Berechtigungen», Phase 4: Reichweite «zugewiesene» und Prüfer je Abgabe-Auftrag.

1. Reichweite in der Rolle: Implikationen erben sie (review(assigned) => read(assigned)), ein Recht
   ohne Reichweite (submissions.manage) gilt immer für alle; Speicherung über role_service, keine
   Rechteausweitung über die Reichweite, Import behält sie.
2. Durchsetzung: ein Prüfer mit «zugewiesene» sieht nur zugewiesene Aufträge und deren Dateien
   (Liste, Fortschritt, Einzelabruf, Datei-Inhalt, Vorschau, Metadaten, Protokoll, ZIP); fremde
   Aufträge und fremde Mandanten sind 404 (kein Existenz-Orakel). Schliessen/Öffnen nur zugewiesene.
3. Prüfer verwalten: nur submissions.manage, nur Konten mit Login des eigenen Mandanten, auditiert;
   Löschen von Auftrag oder Konto räumt die Zuweisung auf.
4. RLS der neuen Tabelle resource_assignment.
"""
from __future__ import annotations

import uuid
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from app.api.routes import submission_assignments as routes
from app.core.permissions import P, resolve_scopes
from app.core.security import build_current_user
from app.models import AppUser, ResourceAssignment, StoredFile, SubmissionAssignment, SubmissionUpload, SubmissionUploadFile, TenantRolePermission
from app.schemas.role import RoleCreate, RoleUpdate
from app.schemas.submission import SubmissionAssignmentUpdate
from app.services import role_service
from app.services import submission_reviewer_service as reviewers
from tests.factories import GRANDFATHERED_FEATURES, make_app_user, make_tenant
from tests.test_tenant_rls import as_app

FEATURES = GRANDFATHERED_FEATURES + ("abgabebox",)


def _assignment(db, tenant_id: int, title: str) -> SubmissionAssignment:
    assignment = SubmissionAssignment(tenant_id=tenant_id, title=title, public_slug=f"a-{uuid.uuid4().hex[:8]}", source_type="manual")
    db.add(assignment)
    db.flush()
    return assignment


def _upload(db, assignment: SubmissionAssignment, name: str) -> tuple[SubmissionUpload, StoredFile]:
    upload = SubmissionUpload(assignment_id=assignment.id, status="submitted")
    db.add(upload)
    db.flush()
    stored = StoredFile(
        tenant_id=assignment.tenant_id, original_name=name, mime_type="application/pdf",
        storage_path=f"abgabebox/{uuid.uuid4().hex}.pdf", scan_status="clean",
    )
    db.add(stored)
    db.flush()
    db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=stored.id, sort_index=0))
    db.flush()
    return upload, stored


def _role(db, actor, name: str, permissions: list[str], scopes: dict[str, str] | None = None):
    role = role_service.create_role(db, actor, RoleCreate(name=name, permissions=permissions, scopes=scopes))
    db.flush()
    return role


@pytest.fixture
def org(db):
    tenant = make_tenant(db, "Verein A", features=FEATURES)
    other = make_tenant(db, "Verein B", features=FEATURES)
    admin = make_app_user(db, "admin@a.example", tenant_id=tenant.id, role_code="admin")
    admin_user = build_current_user(db, admin)
    reviewer = make_app_user(db, "pruefer@a.example", tenant_id=tenant.id, role_code="reader")
    reviewer_role = _role(db, admin_user, "Prüfer", ["submissions.review"], {"submissions.review": "assigned"})
    role_service.set_user_roles(db, None, reviewer, [reviewer_role])
    mine = _assignment(db, tenant.id, "Berichte")
    foreign = _assignment(db, tenant.id, "Fotos")
    other_tenant = _assignment(db, other.id, "Fremd")
    mine_upload, mine_file = _upload(db, mine, "bericht.pdf")
    foreign_upload, foreign_file = _upload(db, foreign, "geheim.pdf")
    other_upload, other_file = _upload(db, other_tenant, "fremd.pdf")
    routes.patch_assignment(mine.public_id, SubmissionAssignmentUpdate(reviewer_ids=[reviewer.public_id]), db=db, user=admin_user)
    return SimpleNamespace(
        tenant=tenant, other=other, admin=admin, admin_user=admin_user, reviewer=reviewer, reviewer_role=reviewer_role,
        mine=mine, foreign=foreign, other_tenant=other_tenant,
        mine_upload=mine_upload, mine_file=mine_file, foreign_upload=foreign_upload, foreign_file=foreign_file,
        other_upload=other_upload, other_file=other_file,
    )


def _not_found(call) -> HTTPException:
    with pytest.raises(HTTPException) as caught:
        call()
    assert caught.value.status_code == 404
    return caught.value


# ── 1. Reichweite in der Rolle ──────────────────────────────────────────────────────────────


def test_resolve_scopes():
    assert resolve_scopes(["submissions.review"], {"submissions.review": "assigned"}) == {
        P.SUBMISSIONS_REVIEW: "assigned", P.SUBMISSIONS_READ: "assigned",
    }
    # manage hat keine Reichweite: read gilt für alle, review bleibt eingeschränkt
    assert resolve_scopes(["submissions.review", "submissions.manage"], {"submissions.review": "assigned"}) == {
        P.SUBMISSIONS_REVIEW: "assigned", P.SUBMISSIONS_READ: "all",
    }
    assert resolve_scopes(["submissions.review"], {}) == {P.SUBMISSIONS_REVIEW: "all", P.SUBMISSIONS_READ: "all"}
    assert resolve_scopes(["submissions.review"], {"submissions.review": "assigned", "submissions.read": "all"})[P.SUBMISSIONS_READ] == "all"
    assert resolve_scopes(["meetings.read"], {}) == {}


def test_role_stores_scope_with_implication(db, org):
    read = role_service.read_role(db, org.reviewer_role)
    assert read.scopes == {"submissions.read": "assigned", "submissions.review": "assigned"}
    stored = dict(db.execute(
        select(TenantRolePermission.permission_key, TenantRolePermission.scope).where(TenantRolePermission.role_id == org.reviewer_role.id)
    ).all())
    assert stored == {"submissions.read": "assigned", "submissions.review": "assigned"}

    combined = _role(db, org.admin_user, "Verwaltung", ["submissions.review", "submissions.manage"], {"submissions.review": "assigned"})
    assert role_service.read_role(db, combined).scopes == {"submissions.read": "all", "submissions.review": "assigned"}

    plain = _role(db, org.admin_user, "Leser", ["submissions.read"])
    assert role_service.read_role(db, plain).scopes == {"submissions.read": "all"}
    # Standardrollen und Bestand: NULL = alle
    assert role_service.role_scopes(db, role_service.system_role(db, org.tenant.id, "reader")) == {"submissions.read": "all"}


def test_scope_for_unscoped_permission_is_rejected(db, org):
    with pytest.raises(HTTPException) as caught:
        _role(db, org.admin_user, "Falsch", ["meetings.read"], {"meetings.read": "assigned"})
    assert caught.value.status_code == 400


def test_update_without_scopes_keeps_assigned(db, org):
    role_service.update_role(db, org.admin_user, org.reviewer_role, RoleUpdate(permissions=["submissions.review", "meetings.read"]))
    assert role_service.read_role(db, org.reviewer_role).scopes == {"submissions.read": "assigned", "submissions.review": "assigned"}
    role_service.update_role(db, org.admin_user, org.reviewer_role, RoleUpdate(scopes={"submissions.review": "all"}))
    assert role_service.read_role(db, org.reviewer_role).scopes == {"submissions.read": "all", "submissions.review": "all"}


def test_current_user_assigned_only(db, org):
    user = build_current_user(db, org.reviewer)
    assert user.assigned_only == frozenset({"submissions.read", "submissions.review"})
    assert not user.sees_all(P.SUBMISSIONS_READ)
    # Eine zweite Rolle mit «alle» hebt die Einschränkung für dieses Recht auf
    role_service.set_user_roles(db, None, org.reviewer, [org.reviewer_role, role_service.system_role(db, org.tenant.id, "reader")])
    user = build_current_user(db, org.reviewer)
    assert user.assigned_only == frozenset({"submissions.review"})
    assert build_current_user(db, org.admin).assigned_only == frozenset()


def test_no_escalation_through_scope(db, org):
    """Wer ein Recht nur für zugewiesene hat, vergibt es nicht für alle (Schutzregel 1)."""
    partial = make_app_user(db, "teiladmin@a.example", tenant_id=org.tenant.id, role_code="reader")
    partial_role = _role(
        db, org.admin_user, "Teil-Admin", ["access.manage", "meetings.read", "submissions.review"], {"submissions.review": "assigned"},
    )
    role_service.set_user_roles(db, None, partial, [partial_role])
    actor = build_current_user(db, partial)
    assert actor.assigned_only == frozenset({"submissions.read", "submissions.review"})

    with pytest.raises(HTTPException) as caught:
        _role(db, actor, "Alle Abgaben", ["submissions.read"])
    assert caught.value.status_code == 403
    with pytest.raises(HTTPException) as caught:
        _role(db, actor, "Alle prüfen", ["submissions.review"], {"submissions.review": "all"})
    assert caught.value.status_code == 403
    allowed = _role(db, actor, "Prüfer 2", ["submissions.review"], {"submissions.review": "assigned"})
    assert role_service.read_role(db, allowed).scopes["submissions.read"] == "assigned"

    # Rolle mit «alle» zuweisen bzw. Konto mit «alle» verwalten: verweigert
    read_all = _role(db, org.admin_user, "Abgaben lesen", ["submissions.read"])
    target = make_app_user(db, "ziel@a.example", tenant_id=org.tenant.id, role_code="reader")
    role_service.set_user_roles(db, None, target, [])
    with pytest.raises(HTTPException) as caught:
        role_service.set_user_roles(db, actor, target, [read_all])
    assert caught.value.status_code == 403
    role_service.set_user_roles(db, None, target, [read_all])
    with pytest.raises(HTTPException) as caught:
        role_service.ensure_can_manage_account(db, actor, target.id)
    assert caught.value.status_code == 403
    # «nur zugewiesene» vergeben geht
    role_service.set_user_roles(db, None, target, [])
    assert role_service.set_user_roles(db, actor, target, [allowed]) is True


def test_import_keeps_scopes(db, org):
    tenant = make_tenant(db, "Import", features=FEATURES)
    role = role_service.import_role(
        db, tenant.id, system_key=None, name="Prüfer", description=None,
        permissions=["submissions.review", "submissions.read"], scopes={"submissions.review": "assigned", "submissions.read": "assigned"},
    )
    assert role_service.read_role(db, role).scopes == {"submissions.read": "assigned", "submissions.review": "assigned"}
    legacy = role_service.import_role(db, tenant.id, system_key=None, name="Alt", description=None, permissions=["submissions.review"])
    assert role_service.read_role(db, legacy).scopes == {"submissions.read": "all", "submissions.review": "all"}


# ── 2. Durchsetzung ─────────────────────────────────────────────────────────────────────────


def test_reviewer_lists_only_assigned(db, org):
    user = build_current_user(db, org.reviewer)
    listed = routes.list_assignments(db=db, user=user)
    assert [item.id for item in listed] == [org.mine.public_id]
    assert listed[0].reviewer_ids == [org.reviewer.public_id]
    assert set(routes.get_assignment_summaries(db=db, user=user)) == {str(org.mine.public_id)}
    # Verwaltung sieht weiterhin alle des eigenen Mandanten (keine fremden)
    assert {item.id for item in routes.list_assignments(db=db, user=org.admin_user)} == {org.mine.public_id, org.foreign.public_id}


def test_reviewer_single_access_is_404_for_unassigned_and_foreign(db, org):
    user = build_current_user(db, org.reviewer)
    assert routes.get_assignment_summary(org.mine.public_id, db=db, user=user) is not None
    assert [element.element_ref for element in routes.list_elements(org.mine.public_id, db=db, user=user)] == ["manual"]
    routes.get_upload_log(org.mine.public_id, element_ref="manual", db=db, user=user)
    for assignment in (org.foreign, org.other_tenant):
        _not_found(lambda: routes.get_assignment_summary(assignment.public_id, db=db, user=user))
        _not_found(lambda: routes.list_elements(assignment.public_id, db=db, user=user))
        _not_found(lambda: routes.get_upload_log(assignment.public_id, element_ref="manual", db=db, user=user))
        _not_found(lambda: routes.download_all_files_zip(assignment.public_id, db=db, user=user))


def test_reviewer_file_access_only_for_assigned(db, org, monkeypatch):
    user = build_current_user(db, org.reviewer)
    monkeypatch.setattr(routes, "object_response", lambda *args, **kwargs: "inhalt")
    monkeypatch.setattr(routes.file_service, "ensure_thumbnail", lambda *args, **kwargs: None)
    monkeypatch.setattr(routes.file_service, "get_stored_file_metadata", lambda *args, **kwargs: None)

    assert routes.get_submission_file_content(org.mine_upload.public_id, org.mine_file.public_id, db=db, user=user) == "inhalt"
    assert _not_found(lambda: routes.get_submission_file_thumbnail(org.mine_upload.public_id, org.mine_file.public_id, db=db, user=user)).detail == "Keine Vorschau verfügbar"
    assert _not_found(lambda: routes.get_submission_file_metadata(org.mine_upload.public_id, org.mine_file.public_id, db=db, user=user)).detail == "Keine Metadaten verfügbar"

    for upload, stored in ((org.foreign_upload, org.foreign_file), (org.other_upload, org.other_file)):
        for route in (routes.get_submission_file_content, routes.get_submission_file_thumbnail, routes.get_submission_file_metadata):
            assert _not_found(lambda: route(upload.public_id, stored.public_id, db=db, user=user)).detail == "Datei nicht gefunden"


def test_reviewer_zip_only_for_assigned(db, org, monkeypatch, tmp_path):
    monkeypatch.setattr(routes.settings, "upload_root", str(tmp_path))
    monkeypatch.setattr(routes, "get_object_store", lambda: SimpleNamespace(exists=lambda namespace, key: True))
    monkeypatch.setattr(routes, "write_object_to_zip", lambda archive, namespace, key, name: archive.writestr(name, b"x"))
    user = build_current_user(db, org.reviewer)
    response = routes.download_all_files_zip(org.mine.public_id, db=db, user=user)
    with zipfile.ZipFile(response.path) as archive:
        assert archive.namelist() == ["bericht.pdf"]
    _not_found(lambda: routes.download_all_files_zip(org.foreign.public_id, db=db, user=user))


def test_close_and_reopen_only_assigned(db, org):
    user = build_current_user(db, org.reviewer)
    assert routes.close_element(org.mine.public_id, "manual", db=db, user=user).status == "closed"
    assert routes.reopen_element(org.mine.public_id, "manual", db=db, user=user).status != "closed"
    _not_found(lambda: routes.close_element(org.foreign.public_id, "manual", db=db, user=user))
    _not_found(lambda: routes.reopen_element(org.other_tenant.public_id, "manual", db=db, user=user))

    # Lesen für alle, prüfen nur zugewiesene: fremder Auftrag sichtbar, aber Schliessen 403
    role_service.set_user_roles(db, None, org.reviewer, [org.reviewer_role, role_service.system_role(db, org.tenant.id, "reader")])
    user = build_current_user(db, org.reviewer)
    assert len(routes.list_assignments(db=db, user=user)) == 2
    with pytest.raises(HTTPException) as caught:
        routes.close_element(org.foreign.public_id, "manual", db=db, user=user)
    assert caught.value.status_code == 403


def test_manage_still_sees_and_reviews_all(db, org):
    writer = make_app_user(db, "schreiber@a.example", tenant_id=org.tenant.id, role_code="writer")
    user = build_current_user(db, writer)
    assert user.assigned_only == frozenset()
    assert routes.close_element(org.foreign.public_id, "manual", db=db, user=user).status == "closed"
    _not_found(lambda: routes.list_elements(org.other_tenant.public_id, db=db, user=user))


def test_reviewer_without_any_assignment_sees_nothing(db, org):
    routes.patch_assignment(org.mine.public_id, SubmissionAssignmentUpdate(reviewer_ids=[]), db=db, user=org.admin_user)
    user = build_current_user(db, org.reviewer)
    assert routes.list_assignments(db=db, user=user) == []
    assert routes.get_assignment_summaries(db=db, user=user) == {}
    _not_found(lambda: routes.list_elements(org.mine.public_id, db=db, user=user))


# ── 3. Prüfer verwalten ─────────────────────────────────────────────────────────────────────


def test_reviewers_need_manage(db, org):
    user = build_current_user(db, org.reviewer)
    with pytest.raises(HTTPException) as caught:
        routes.patch_assignment(org.mine.public_id, SubmissionAssignmentUpdate(reviewer_ids=[]), db=db, user=user)
    assert caught.value.status_code == 403
    with pytest.raises(HTTPException) as caught:
        routes.list_reviewer_candidates(db=db, user=user)
    assert caught.value.status_code == 403


def test_reviewers_only_login_accounts_of_own_tenant(db, org):
    foreign_user = make_app_user(db, "fremd@b.example", tenant_id=org.other.id, role_code="reader")
    no_login = make_app_user(db, "ohne@a.example", tenant_id=org.tenant.id, role_code="reader")
    no_login.login_enabled = False
    db.flush()
    for candidate in (foreign_user, no_login):
        with pytest.raises(ValueError):
            reviewers.resolve_reviewers(db, org.mine, org.tenant.id, [candidate.public_id])
    with pytest.raises(ValueError):
        reviewers.resolve_reviewers(db, org.mine, org.tenant.id, [uuid.uuid4()])
    candidates = {item.id for item in routes.list_reviewer_candidates(db=db, user=org.admin_user)}
    assert org.reviewer.public_id in candidates
    assert foreign_user.public_id not in candidates and no_login.public_id not in candidates
    # Bereits zugewiesen darf bleiben, auch nach Entzug des Logins - neu zuweisen nicht
    org.reviewer.login_enabled = False
    db.flush()
    assert reviewers.resolve_reviewers(db, org.mine, org.tenant.id, [org.reviewer.public_id]) == {org.reviewer.id}
    with pytest.raises(ValueError):
        reviewers.resolve_reviewers(db, org.foreign, org.tenant.id, [org.reviewer.public_id])
    org.reviewer.login_enabled = True
    db.flush()
    # Zuweisung unverändert, Änderung auditiert
    assert routes.list_assignments(db=db, user=org.admin_user)[0].reviewer_ids == [org.reviewer.public_id]
    actions = db.scalars(text("SELECT action FROM audit_log WHERE action = 'submission_assignment.reviewers_changed'")).all()
    assert actions
    # Über die Route: 400 (zuletzt, weil die Route dabei die Testtransaktion zurückrollt)
    with pytest.raises(HTTPException) as caught:
        routes.patch_assignment(org.mine.public_id, SubmissionAssignmentUpdate(reviewer_ids=[foreign_user.public_id]), db=db, user=org.admin_user)
    assert caught.value.status_code == 400


def test_deleting_assignment_or_account_removes_assignment(db, org):
    def count() -> int:
        return db.scalar(select(func.count()).select_from(ResourceAssignment).where(ResourceAssignment.tenant_id == org.tenant.id))

    assert count() == 1
    db.execute(delete(AppUser).where(AppUser.id == org.reviewer.id))
    assert count() == 0
    reviewer2 = make_app_user(db, "pruefer2@a.example", tenant_id=org.tenant.id, role_code="reader")
    routes.patch_assignment(org.foreign.public_id, SubmissionAssignmentUpdate(reviewer_ids=[reviewer2.public_id]), db=db, user=org.admin_user)
    assert count() == 1
    db.execute(delete(SubmissionAssignment).where(SubmissionAssignment.id == org.foreign.id))
    assert count() == 0


def test_database_rejects_cross_tenant_assignment(db, org):
    foreign_user = make_app_user(db, "fremd2@b.example", tenant_id=org.other.id, role_code="reader")
    savepoint = db.begin_nested()
    db.add(ResourceAssignment(tenant_id=org.tenant.id, resource_type="submission_assignment", resource_id=org.mine.id, user_id=foreign_user.id))
    with pytest.raises(IntegrityError):
        db.flush()
    savepoint.rollback()


# ── 4. RLS ──────────────────────────────────────────────────────────────────────────────────


def test_resource_assignment_rls(db, org):
    reviewer_b = make_app_user(db, "pruefer@b.example", tenant_id=org.other.id, role_code="reader")
    db.add(ResourceAssignment(tenant_id=org.other.id, resource_type="submission_assignment", resource_id=org.other_tenant.id, user_id=reviewer_b.id))
    db.flush()
    with as_app(db, org.tenant.id):
        assert set(db.scalars(select(ResourceAssignment.tenant_id))) == {org.tenant.id}
    with as_app(db, org.other.id):
        assert set(db.scalars(select(ResourceAssignment.tenant_id))) == {org.other.id}


def test_adding_a_scoped_right_without_scopes_keeps_assigned(db, org):
    """Security-Review Phase 4: Nur Rechte ändern (ohne scopes) darf «nur zugewiesene» nicht über
    ein neu dazukommendes Recht (review impliziert read) auf «alle» ausweiten."""
    read_only = _role(db, org.admin_user, "Nur zugewiesen lesen", ["submissions.read"], {"submissions.read": "assigned"})
    role_service.update_role(db, org.admin_user, read_only, RoleUpdate(permissions=["submissions.read", "submissions.review"]))
    assert role_service.read_role(db, read_only).scopes == {"submissions.read": "assigned", "submissions.review": "assigned"}


def test_reviewer_candidates_need_submission_read(db, org):
    """Als Prüfer nur Konten anbieten, die Abgaben sehen dürfen (Security-Review Phase 4)."""
    minutes_only = _role(db, org.admin_user, "Nur Sitzungen", ["meetings.read"])
    clerk = make_app_user(db, "sitzungen@a.example", tenant_id=org.tenant.id, role_code="reader")
    role_service.set_user_roles(db, None, clerk, [minutes_only])
    db.flush()
    candidates = {item.id for item in routes.list_reviewer_candidates(db=db, user=org.admin_user)}
    assert clerk.public_id not in candidates
    assert org.reviewer.public_id in candidates and org.admin.public_id in candidates
