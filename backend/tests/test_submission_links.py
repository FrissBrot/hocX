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

from app.models.entities import ProtocolTodo, StoredFile, SubmissionAssignment, SubmissionLink, Tenant
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

    # Anlegen gleicht schon ab (FAR-010); ein erneuter Abgleich aktualisiert nur.
    assert service.sync_submission_todos(db, assignment) == {"created": 0, "updated": 1}
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


def _todos(db, assignment_public_id) -> list[ProtocolTodo]:
    assignment = db.scalar(select(SubmissionAssignment).where(SubmissionAssignment.public_id == assignment_public_id))
    return list(db.scalars(select(ProtocolTodo).where(ProtocolTodo.submission_assignment_id == assignment.id)))


def test_event_assignment_creates_todos_for_already_existing_events(db):
    """FAR-010: vorher entstanden Todos nur, wenn ein Termin danach angelegt oder bearbeitet wurde."""
    from tests.factories import make_participant

    tenant = make_tenant(db)
    participant = make_participant(db, tenant.id, display_name="Anna Muster")
    event = _tagged_event(db, tenant.id)
    event.spezial1_ids = [participant.id]
    db.flush()
    link = links.create_link(db, SubmissionLinkCreate(name="Leiter"), tenant_id=tenant.id)

    created = SubmissionService().create_assignment(
        db, _assignment_payload(link_ids=[link.id], responsible_participant_source="spezial1_ids"), tenant_id=tenant.id
    )

    [todo] = _todos(db, created.id)
    assert (todo.assigned_participant_id, todo.tenant_id) == (participant.id, tenant.id)


def test_list_assignment_creates_and_follows_todos_per_list_entry(db):
    """FAR-010: Listen-Abgaben mit Verantwortlichen bekamen nie Todos."""
    from app.api.routes import lists as list_routes
    from app.schemas.list_definition import ListEntryCreate
    from tests.factories import make_current_user, make_list_definition, make_list_entry, make_participant

    tenant = make_tenant(db)
    anna = make_participant(db, tenant.id, display_name="Anna Muster")
    ben = make_participant(db, tenant.id, display_name="Ben Beispiel")
    definition = make_list_definition(db, tenant.id, column_two_title="Verantwortlich", column_two_value_type="participant")
    make_list_entry(db, definition.id, column_one_value={"text": "Zelt"}, column_two_value={"participant_id": anna.id})
    link = links.create_link(db, SubmissionLinkCreate(name="Leiter"), tenant_id=tenant.id)

    created = SubmissionService().create_assignment(
        db,
        SubmissionAssignmentCreate(
            title="Material", public_slug="material", source_type="list", list_definition_id=definition.public_id,
            responsible_participant_source="column_two", link_ids=[link.id],
        ),
        tenant_id=tenant.id,
    )
    assert [todo.assigned_participant_id for todo in _todos(db, created.id)] == [anna.id]

    # Neuer Listeneintrag über die Route: das Todo folgt automatisch.
    list_routes.create_entry(
        definition.public_id,
        ListEntryCreate(sort_index=1, column_one_value={"text": "Kocher"}, column_two_value={"participant_id": str(ben.public_id)}),
        db=db,
        user=make_current_user(tenant.id, role="writer"),
    )
    assert sorted(todo.assigned_participant_id for todo in _todos(db, created.id)) == sorted([anna.id, ben.id])


def test_unexpected_sync_error_is_logged_and_does_not_block_the_change(db, monkeypatch):
    """Vorher verschluckte sync_todos_for_event jeden Fehler (except Exception: pass)."""
    from app.services import submission_service as submission_module
    from tests.factories import make_participant

    tenant = make_tenant(db)
    event = _tagged_event(db, tenant.id)
    event.spezial1_ids = [make_participant(db, tenant.id, display_name="Anna Muster").id]
    db.flush()
    link = links.create_link(db, SubmissionLinkCreate(name="Leiter"), tenant_id=tenant.id)
    logged: list[tuple[str, int | None]] = []

    def broken(self, db, assignment):
        raise RuntimeError("sync kaputt")

    # record_system_error schreibt über eine eigene Verbindung, die den Testmandanten der
    # Rollback-Transaktion nicht sieht - hier nur prüfen, dass der Fehler dort ankäme.
    monkeypatch.setattr(SubmissionService, "sync_submission_todos", broken)
    monkeypatch.setattr(submission_module, "record_system_error", lambda db, *, exc, tenant_id=None, **_kw: logged.append((str(exc), tenant_id)))
    created = SubmissionService().create_assignment(
        db, _assignment_payload(link_ids=[link.id], responsible_participant_source="spezial1_ids"), tenant_id=tenant.id
    )

    assert created.id is not None
    assert logged == [("sync kaputt", tenant.id)]


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


def test_reimport_keeps_links_and_assignments_but_never_shares_a_live_token(db):
    """Since 2026-10-11 a full_abgabebox export is a complete backup and carries the links
    WITH their tokens (a restore onto another installation keeps every handed-out URL
    working, see test_tenant_export_import.py). As long as the source tenant still exists
    on the same installation, though, its tokens stay its credentials: the import keeps
    names, default flag and Abgabe assignments, but issues fresh tokens."""
    import json
    import zipfile

    from app.services.tenant_export_service import TenantExportService
    from app.services.tenant_import_service import TenantImportService

    source = make_tenant(db, "Quelle")
    link = links.create_link(db, SubmissionLinkCreate(name="Eltern"), tenant_id=source.id)
    SubmissionService().create_assignment(db, _assignment_payload(link_ids=[link.id]), tenant_id=source.id)
    source_tokens = {item.token for item in db.scalars(select(SubmissionLink).where(SubmissionLink.tenant_id == source.id))}

    zip_path, _ = TenantExportService().export(db, source.id, "full_abgabebox")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert link.token in {row["token"] for row in manifest["tables"]["submission_link"]}
        imported, warnings = TenantImportService().import_zip(db, zip_path, "Quelle (Import)")
    finally:
        zip_path.unlink(missing_ok=True)

    imported_links = {
        item.name: item for item in db.scalars(select(SubmissionLink).where(SubmissionLink.tenant_id == imported.id))
    }
    assert "Eltern" in imported_links
    assert not ({item.token for item in imported_links.values()} & source_tokens)
    assert any("Token" in warning for warning in warnings)
    imported_assignment = db.scalar(select(SubmissionAssignment).where(SubmissionAssignment.tenant_id == imported.id))
    assert [item.id for item in imported_assignment.links] == [imported_links["Eltern"].id]


def test_import_without_links_in_the_archive_creates_a_fresh_default_link(db):
    """Scope "full" (no Abgabebox) and archives from before 2026-10-11 carry no links."""
    from app.services.tenant_export_service import TenantExportService
    from app.services.tenant_import_service import TenantImportService

    source = make_tenant(db, "Quelle")
    links.create_link(db, SubmissionLinkCreate(name="Eltern"), tenant_id=source.id)

    zip_path, _ = TenantExportService().export(db, source.id, "full")
    try:
        imported, _warnings = TenantImportService().import_zip(db, zip_path, "Quelle (Import)")
    finally:
        zip_path.unlink(missing_ok=True)

    imported_links = db.scalars(select(SubmissionLink).where(SubmissionLink.tenant_id == imported.id)).all()
    assert [(item.name, item.is_default) for item in imported_links] == [("Standard", True)]


# ── Isolation: what the restricted public role may and may not do ─────────


def _probe_as_abgabebox(db, sql: str, params: dict | None = None, *, link_token: str | None = None):
    """Runs one statement as the restricted role inside a manually managed SAVEPOINT (the `db`
    fixture already drives its own savepoints, so Session.begin_nested() as a context manager
    would clash with it). Returns (rows, None) on success or (None, error_text) if Postgres
    refused. ROLLBACK TO SAVEPOINT also undoes SET LOCAL ROLE and clears the aborted state, so
    the surrounding test transaction stays usable either way."""
    connection = db.connection()
    connection.execute(text("SAVEPOINT abgabebox_probe"))
    try:
        connection.execute(text("SET LOCAL ROLE hocx_abgabebox"))
        # Wie abgabebox-backend/app/link_scope.py: ohne Link-Token sieht die Rolle per RLS nichts.
        connection.execute(text("SELECT set_config('app.abgabebox_link', :token, true)"), {"token": link_token or ""})
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
        db, "SELECT id, tenant_id, token FROM submission_link WHERE token = :token", {"token": link.token}, link_token=link.token
    )
    assert error is None
    assert rows[0].tenant_id == tenant.id
    rows, error = _probe_as_abgabebox(db, "SELECT assignment_id, link_id FROM submission_assignment_link", link_token=link.token)
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


def test_restricted_role_sees_only_the_tenant_of_its_link(db):
    """SEC-008 (Migration 0133_abgabebox_rls): die Rolle sieht nur Daten des Mandanten, dem das
    gesetzte Link-Token gehört - ohne Token nichts, auch nicht die Tokens anderer Links."""
    tenant, other = make_tenant(db), make_tenant(db)
    link = links.create_link(db, SubmissionLinkCreate(name="Eltern"), tenant_id=tenant.id)
    second_link = links.create_link(db, SubmissionLinkCreate(name="Leitende"), tenant_id=tenant.id)
    other_link = links.create_link(db, SubmissionLinkCreate(name="Fremd"), tenant_id=other.id)
    own_file = StoredFile(tenant_id=tenant.id, original_name="a.jpg", mime_type="image/jpeg", storage_path="uploads/a.jpg")
    other_file = StoredFile(tenant_id=other.id, original_name="b.jpg", mime_type="image/jpeg", storage_path="uploads/b.jpg")
    db.add_all([own_file, other_file])
    db.flush()
    file_ids = {"ids": [own_file.id, other_file.id]}
    file_query = "SELECT id FROM stored_file WHERE id = ANY(:ids)"

    rows, error = _probe_as_abgabebox(db, file_query, file_ids)
    assert error is None and rows == []
    rows, error = _probe_as_abgabebox(db, "SELECT token FROM submission_link")
    assert error is None and rows == []

    rows, error = _probe_as_abgabebox(db, file_query, file_ids, link_token=link.token)
    assert error is None and [row.id for row in rows] == [own_file.id]
    rows, error = _probe_as_abgabebox(db, "SELECT token FROM submission_link", link_token=link.token)
    assert error is None and [row.token for row in rows] == [link.token]
    assert second_link.token not in [row.token for row in rows]

    rows, error = _probe_as_abgabebox(db, file_query, file_ids, link_token=other_link.token)
    assert error is None and [row.id for row in rows] == [other_file.id]
    # Ein erfundenes Token öffnet keinen Mandanten.
    rows, error = _probe_as_abgabebox(db, file_query, file_ids, link_token="x" * 32)
    assert error is None and rows == []


def test_restricted_role_cannot_write_files_into_another_tenant(db):
    tenant, other = make_tenant(db), make_tenant(db)
    link = links.create_link(db, SubmissionLinkCreate(name="Eltern"), tenant_id=tenant.id)

    _rows, error = _probe_as_abgabebox(
        db,
        "INSERT INTO stored_file (tenant_id, original_name, mime_type, storage_path) VALUES (:tenant, 'x', 'image/png', 'u/x')",
        {"tenant": other.id},
        link_token=link.token,
    )
    assert error is not None and "row-level security" in error


def test_restricted_role_reads_no_file_metadata_beyond_duplicate_checks(db):
    for column in ("gps_latitude", "original_name", "storage_path", "camera_model"):
        assert _denied(db, f"SELECT {column} FROM stored_file")
    _rows, error = _probe_as_abgabebox(db, "SELECT id, tenant_id, checksum_sha256, perceptual_hash FROM stored_file")
    assert error is None


def test_every_migrated_tenant_has_a_default_link(db):
    """Migration 0075 backfills one default link per pre-existing tenant (e.g. the demo tenants
    the baseline seeds into the test DB), so no existing Abgabe went dark. Nothing a test creates
    is visible here - every test's transaction is rolled back - so anything without a link would
    be a tenant the migration missed."""
    missing = db.execute(
        text("SELECT id FROM tenant t WHERE NOT EXISTS (SELECT 1 FROM submission_link l WHERE l.tenant_id = t.id)")
    ).all()
    assert missing == []
