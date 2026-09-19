"""Abgabe-Links: the public Abgabebox is reached via a random link token instead of the tenant's
public_slug. Covers the admin-side behavior (link CRUD, which Abgabe is reachable over which
link, default link, todo reference links, tenant clone) and - most importantly - that the
restricted hocx_abgabebox DB role got exactly the narrow grants it needs to resolve a token and
nothing more, so the strict separation of the public service is unchanged.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models.entities import ProtocolTodo, SubmissionAssignment, SubmissionLink, Tenant
from app.schemas.submission import (
    SubmissionAssignmentCreate,
    SubmissionAssignmentUpdate,
    SubmissionLinkCreate,
    SubmissionLinkUpdate,
)
from app.services import submission_link_service
from app.services.admin_tenant_service import AdminTenantService
from app.schemas.admin import AdminTenantCreate
from app.services.submission_link_service import SubmissionLinkService
from app.services.submission_service import SubmissionService
from app.services.tenant_clone_service import TenantCloneService
from tests.factories import make_event, make_tenant

links = SubmissionLinkService()


def _assignment_payload(slug: str = "fotos", **overrides) -> SubmissionAssignmentCreate:
    values = dict(
        title="Fotos einreichen",
        public_slug=slug,
        source_type="events",
        tag_filter="lager",
        offset_days_before=7,
        offset_days_after=7,
    )
    values.update(overrides)
    return SubmissionAssignmentCreate(**values)


# ── Tokens / link CRUD ────────────────────────────────────────────────────


def test_generated_tokens_are_long_random_and_url_safe():
    tokens = {submission_link_service.generate_token() for _ in range(200)}
    assert len(tokens) == 200
    assert all(len(t) >= 32 and all(c.isalnum() or c in "-_" for c in t) for t in tokens)


def test_create_link_returns_url_built_from_token(db):
    tenant = make_tenant(db)

    created = links.create_link(db, SubmissionLinkCreate(name="Eltern"), tenant_id=tenant.id)

    assert created.name == "Eltern"
    assert created.is_default is False
    assert created.url.endswith(f"/{created.token}")
    assert created.assignment_count == 0


def test_link_names_are_unique_per_tenant_case_insensitively(db):
    tenant_a = make_tenant(db, "A")
    tenant_b = make_tenant(db, "B")
    links.create_link(db, SubmissionLinkCreate(name="Eltern"), tenant_id=tenant_a.id)

    with pytest.raises(ValueError):
        links.create_link(db, SubmissionLinkCreate(name="eltern"), tenant_id=tenant_a.id)
    # Another tenant may reuse the same name.
    links.create_link(db, SubmissionLinkCreate(name="Eltern"), tenant_id=tenant_b.id)


def test_only_one_default_link_per_tenant(db):
    tenant = make_tenant(db)
    first = links.create_link(db, SubmissionLinkCreate(name="Erster", is_default=True), tenant_id=tenant.id)
    second = links.create_link(db, SubmissionLinkCreate(name="Zweiter", is_default=True), tenant_id=tenant.id)

    listed = {link.name: link for link in links.list_links(db, tenant_id=tenant.id)}
    assert listed["Erster"].is_default is False
    assert listed["Zweiter"].is_default is True

    link_row = links.get_link(db, first.id, tenant_id=tenant.id)
    links.update_link(db, link_row, SubmissionLinkUpdate(is_default=True))
    listed = {link.name: link for link in links.list_links(db, tenant_id=tenant.id)}
    assert listed["Erster"].is_default is True
    assert listed["Zweiter"].is_default is False
    assert second.id != first.id


def test_regenerate_token_changes_the_url(db):
    tenant = make_tenant(db)
    created = links.create_link(db, SubmissionLinkCreate(name="Eltern"), tenant_id=tenant.id)

    regenerated = links.regenerate_token(db, links.get_link(db, created.id, tenant_id=tenant.id))

    assert regenerated.token != created.token
    assert regenerated.id == created.id


def test_links_cannot_be_looked_up_across_tenants(db):
    tenant_a = make_tenant(db, "A")
    tenant_b = make_tenant(db, "B")
    created = links.create_link(db, SubmissionLinkCreate(name="Eltern"), tenant_id=tenant_a.id)

    assert links.get_link(db, created.id, tenant_id=tenant_b.id) is None
    with pytest.raises(ValueError):
        submission_link_service.resolve_links(db, [created.id], tenant_id=tenant_b.id)


def test_new_tenant_created_via_admin_gets_a_default_link(db):
    created = AdminTenantService().create_tenant(db, AdminTenantCreate(name="Neuer Verein"))

    tenant = db.scalar(select(Tenant).where(Tenant.public_id == created.id))
    tenant_links = db.scalars(select(SubmissionLink).where(SubmissionLink.tenant_id == tenant.id)).all()
    assert len(tenant_links) == 1
    assert tenant_links[0].is_default is True
    assert tenant_links[0].name == "Standard"


# ── Which Abgabe is reachable over which link ─────────────────────────────


def test_new_assignment_defaults_to_the_tenants_default_link(db):
    tenant = make_tenant(db)
    default = submission_link_service.create_default_link(db, tenant.id)
    links.create_link(db, SubmissionLinkCreate(name="Eltern"), tenant_id=tenant.id)

    created = SubmissionService().create_assignment(db, _assignment_payload(), tenant_id=tenant.id)

    assert created.link_ids == [default.public_id]


def test_assignment_can_be_attached_to_several_links_or_none(db):
    tenant = make_tenant(db)
    a = links.create_link(db, SubmissionLinkCreate(name="A"), tenant_id=tenant.id)
    b = links.create_link(db, SubmissionLinkCreate(name="B"), tenant_id=tenant.id)
    service = SubmissionService()

    both = service.create_assignment(db, _assignment_payload("both", link_ids=[a.id, b.id]), tenant_id=tenant.id)
    none = service.create_assignment(db, _assignment_payload("none", link_ids=[]), tenant_id=tenant.id)

    assert set(both.link_ids) == {a.id, b.id}
    assert none.link_ids == []


def test_assignment_cannot_use_another_tenants_link(db):
    tenant_a = make_tenant(db, "A")
    tenant_b = make_tenant(db, "B")
    foreign = links.create_link(db, SubmissionLinkCreate(name="Fremd"), tenant_id=tenant_b.id)

    with pytest.raises(ValueError):
        SubmissionService().create_assignment(db, _assignment_payload(link_ids=[foreign.id]), tenant_id=tenant_a.id)

    own = SubmissionService().create_assignment(db, _assignment_payload("own", link_ids=[]), tenant_id=tenant_a.id)
    assignment = db.scalar(select(SubmissionAssignment).where(SubmissionAssignment.public_id == own.id))
    with pytest.raises(ValueError):
        SubmissionService().update_assignment(db, assignment.id, SubmissionAssignmentUpdate(link_ids=[foreign.id]))


def test_update_assignment_replaces_links_and_none_leaves_them_untouched(db):
    tenant = make_tenant(db)
    a = links.create_link(db, SubmissionLinkCreate(name="A"), tenant_id=tenant.id)
    b = links.create_link(db, SubmissionLinkCreate(name="B"), tenant_id=tenant.id)
    service = SubmissionService()
    created = service.create_assignment(db, _assignment_payload(link_ids=[a.id]), tenant_id=tenant.id)
    assignment = db.scalar(select(SubmissionAssignment).where(SubmissionAssignment.public_id == created.id))

    updated = service.update_assignment(db, assignment.id, SubmissionAssignmentUpdate(link_ids=[b.id]))
    assert updated.link_ids == [b.id]

    untouched = service.update_assignment(db, assignment.id, SubmissionAssignmentUpdate(title="Neuer Titel"))
    assert untouched.link_ids == [b.id]

    cleared = service.update_assignment(db, assignment.id, SubmissionAssignmentUpdate(link_ids=[]))
    assert cleared.link_ids == []


def test_deleting_a_link_removes_it_from_its_assignments_but_keeps_the_assignments(db):
    tenant = make_tenant(db)
    a = links.create_link(db, SubmissionLinkCreate(name="A"), tenant_id=tenant.id)
    b = links.create_link(db, SubmissionLinkCreate(name="B"), tenant_id=tenant.id)
    created = SubmissionService().create_assignment(db, _assignment_payload(link_ids=[a.id, b.id]), tenant_id=tenant.id)
    assignment = db.scalar(select(SubmissionAssignment).where(SubmissionAssignment.public_id == created.id))

    links.delete_link(db, links.get_link(db, a.id, tenant_id=tenant.id))

    db.refresh(assignment)
    assert [link.public_id for link in assignment.links] == [b.id]


def test_deleting_an_assignment_removes_only_its_link_rows(db):
    tenant = make_tenant(db)
    link = links.create_link(db, SubmissionLinkCreate(name="A"), tenant_id=tenant.id)
    service = SubmissionService()
    created = service.create_assignment(db, _assignment_payload(link_ids=[link.id]), tenant_id=tenant.id)
    assignment = db.scalar(select(SubmissionAssignment).where(SubmissionAssignment.public_id == created.id))

    assert service.delete_assignment(db, assignment.id) is True

    assert links.get_link(db, link.id, tenant_id=tenant.id) is not None


# ── Todo reference links ──────────────────────────────────────────────────


def _tagged_event(db, tenant_id: int):
    event = make_event(db, tenant_id, title="Sommerlager")
    event.tag = "lager"
    db.flush()
    return event


def test_todo_sync_uses_a_link_url_and_needs_a_link(db):
    from tests.factories import make_participant

    tenant = make_tenant(db)
    participant = make_participant(db, tenant.id, display_name="Anna Muster")
    event = _tagged_event(db, tenant.id)
    event.spezial1_ids = [participant.id]
    db.flush()
    link = links.create_link(db, SubmissionLinkCreate(name="Leiter"), tenant_id=tenant.id)
    service = SubmissionService()
    created = service.create_assignment(
        db, _assignment_payload(link_ids=[link.id], responsible_participant_source="spezial1_ids"), tenant_id=tenant.id
    )
    assignment = db.scalar(select(SubmissionAssignment).where(SubmissionAssignment.public_id == created.id))

    result = service.sync_submission_todos(db, assignment)

    assert result["created"] == 1
    todo = db.scalar(select(ProtocolTodo).where(ProtocolTodo.submission_assignment_id == assignment.id))
    assert f"/{link.token}/fotos/event-{event.public_id}" in todo.reference_link

    # A rotated token must not leave the todo pointing at the dead URL.
    regenerated = links.regenerate_token(db, links.get_link(db, link.id, tenant_id=tenant.id))
    service.refresh_todo_links(db, assignment)
    db.refresh(todo)
    assert f"/{regenerated.token}/fotos/" in todo.reference_link

    # With no link left there is no reachable URL: sync refuses, existing todos lose the link.
    service.update_assignment(db, assignment.id, SubmissionAssignmentUpdate(link_ids=[]))
    db.refresh(todo)
    assert todo.reference_link is None
    with pytest.raises(ValueError):
        service.sync_submission_todos(db, assignment)


# ── Cloning must never carry tokens over ──────────────────────────────────


def test_clone_gets_fresh_tokens_but_the_same_link_structure(db):
    source = make_tenant(db, "Quelle")
    default = submission_link_service.create_default_link(db, source.id)
    other = links.create_link(db, SubmissionLinkCreate(name="Eltern"), tenant_id=source.id)
    service = SubmissionService()
    created = service.create_assignment(db, _assignment_payload(link_ids=[other.id]), tenant_id=source.id)

    cloned = TenantCloneService().clone_full(db, source.id, "Quelle (Kopie)")

    cloned_links = {
        link.name: link for link in db.scalars(select(SubmissionLink).where(SubmissionLink.tenant_id == cloned.id))
    }
    assert set(cloned_links) == {"Standard", "Eltern"}
    assert cloned_links["Standard"].is_default is True
    source_tokens = {default.token, other.token}
    assert not source_tokens & {link.token for link in cloned_links.values()}

    cloned_assignment = db.scalar(select(SubmissionAssignment).where(SubmissionAssignment.tenant_id == cloned.id))
    assert cloned_assignment is not None
    assert {link.name for link in cloned_assignment.links} == {"Eltern"}
    assert created.link_ids == [other.id]


def test_clone_of_a_tenant_without_links_still_gets_a_default_link(db):
    source = make_tenant(db, "Quelle ohne Links")

    cloned = TenantCloneService().clone_full(db, source.id, "Kopie")

    cloned_links = db.scalars(select(SubmissionLink).where(SubmissionLink.tenant_id == cloned.id)).all()
    assert len(cloned_links) == 1
    assert cloned_links[0].is_default is True


def test_export_never_contains_link_tokens_and_import_creates_a_fresh_default_link(db):
    import json
    import zipfile

    from app.services.tenant_export_service import TenantExportService
    from app.services.tenant_import_service import TenantImportService

    source = make_tenant(db, "Quelle")
    link = links.create_link(db, SubmissionLinkCreate(name="Eltern"), tenant_id=source.id)
    SubmissionService().create_assignment(db, _assignment_payload(link_ids=[link.id]), tenant_id=source.id)

    zip_path, _ = TenantExportService().export(db, source.id, "full_abgabebox")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            manifest_text = zf.read("manifest.json").decode("utf-8")
        assert link.token not in manifest_text
        assert "submission_link" not in json.loads(manifest_text)["tables"]
        imported, _warnings = TenantImportService().import_zip(db, zip_path, "Quelle (Import)")
    finally:
        zip_path.unlink(missing_ok=True)

    imported_links = db.scalars(select(SubmissionLink).where(SubmissionLink.tenant_id == imported.id)).all()
    assert [(item.name, item.is_default) for item in imported_links] == [("Standard", True)]
    assert imported_links[0].token != link.token
    imported_assignment = db.scalar(select(SubmissionAssignment).where(SubmissionAssignment.tenant_id == imported.id))
    assert [item.id for item in imported_assignment.links] == [imported_links[0].id]


# ── Isolation: what the restricted public role may and may not do ─────────


def _probe_as_abgabebox(db, sql: str, params: dict | None = None):
    """Runs one statement as the restricted role inside a manually managed SAVEPOINT (the `db`
    fixture already drives its own savepoints, so Session.begin_nested() as a context manager
    would clash with it). Returns (rows, None) on success or (None, error_text) if Postgres
    refused. ROLLBACK TO SAVEPOINT also undoes SET LOCAL ROLE and clears the aborted state, so
    the surrounding test transaction stays usable either way."""
    connection = db.connection()
    connection.execute(text("SAVEPOINT abgabebox_probe"))
    try:
        connection.execute(text("SET LOCAL ROLE hocx_abgabebox"))
        result = connection.execute(text(sql), params or {})
        rows = result.all() if result.returns_rows else []
        return rows, None
    except DBAPIError as exc:
        return None, str(exc.orig)
    finally:
        connection.execute(text("ROLLBACK TO SAVEPOINT abgabebox_probe"))


def _denied(db, sql: str) -> bool:
    _rows, error = _probe_as_abgabebox(db, sql)
    return error is not None and "permission denied" in error


def test_restricted_role_can_resolve_a_token_but_only_read_the_columns_it_needs(db):
    tenant = make_tenant(db)
    link = links.create_link(db, SubmissionLinkCreate(name="Eltern"), tenant_id=tenant.id)
    created = SubmissionService().create_assignment(db, _assignment_payload(link_ids=[link.id]), tenant_id=tenant.id)
    assert created.link_ids == [link.id]

    rows, error = _probe_as_abgabebox(
        db, "SELECT id, tenant_id, token FROM submission_link WHERE token = :token", {"token": link.token}
    )
    assert error is None
    assert rows[0].tenant_id == tenant.id
    rows, error = _probe_as_abgabebox(db, "SELECT assignment_id, link_id FROM submission_assignment_link")
    assert error is None
    assert len(rows) >= 1

    # Never the human-readable name / default flag / timestamps of a link ...
    assert _denied(db, "SELECT name FROM submission_link")
    assert _denied(db, "SELECT is_default FROM submission_link")
    assert _denied(db, "SELECT * FROM submission_link")
    # ... and never any write - a compromised public process cannot mint or alter access.
    assert _denied(db, "INSERT INTO submission_link (tenant_id, name, token) VALUES (1, 'x', 'y')")
    assert _denied(db, "UPDATE submission_link SET token = 'x'")
    assert _denied(db, "DELETE FROM submission_link")
    assert _denied(db, "INSERT INTO submission_assignment_link (assignment_id, link_id) VALUES (1, 1)")
    assert _denied(db, "DELETE FROM submission_assignment_link")


def test_every_migrated_tenant_has_a_default_link(db):
    """Migration 0075 backfills one default link per pre-existing tenant (e.g. the demo tenants
    the baseline seeds into the test DB), so no existing Abgabe went dark. Nothing a test creates
    is visible here - every test's transaction is rolled back - so anything without a link would
    be a tenant the migration missed."""
    missing = db.execute(
        text("SELECT id FROM tenant t WHERE NOT EXISTS (SELECT 1 FROM submission_link l WHERE l.tenant_id = t.id)")
    ).all()
    assert missing == []
