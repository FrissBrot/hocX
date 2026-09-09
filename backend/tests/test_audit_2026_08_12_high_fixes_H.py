"""Regression tests for the 2026-08-12 audit's H18 and H19 findings (both in the
platform-admin area, both HIGH severity, both previously untested).

H18 - AdminTenantService.delete_tenant() hand-rolls a specific FK-safe deletion order
(explicitly deleting protocol/submission_assignment/template before the tenant row itself,
to clear several RESTRICT foreign keys that would otherwise race against Postgres's
per-statement cascade resolution) with zero test coverage anywhere in the repo. Reading it
against the actual model FK constraints (app/models/entities.py) turned up a *real* gap,
not just a hypothetical one: word_import_document has non-nullable RESTRICT FKs into both
template and stored_file, but it doesn't cascade away via protocol/submission_assignment/
template (its protocol_id link is SET NULL, not CASCADE) and wasn't in the hand-rolled
pre-delete list - so deleting any tenant with word_import_document rows (a pending or
already-imported Word upload) would raise a Postgres FK-violation IntegrityError. Fixed in
admin_tenant_service.py by deleting word_import_document explicitly, first. This file adds
the missing regression test: build a tenant with representative rows across every
tenant-scoped table reachable via existing/local factories, delete it, and assert (a) the
delete doesn't raise and (b) every table with an FK into tenant.id - discovered generically
from SQLAlchemy metadata rather than hand-enumerated, so a table added later without
updating this test is still covered - has zero matching rows afterward, plus that a second,
untouched tenant's data survives untouched.

H19 - platform admins had no way to remove a tenant's custom domain: /admin/domains only
exposed GET, and the admin overview table had no actions column. The only removal path was
a tenant's own self-service flow, which doesn't help against an uncooperative or
unreachable tenant that added a domain and never got it DNS-verified (RUNBOOK.md flags the
ACME rate-limit risk from exactly that kind of hanging attempt). Added
AdminDomainService.delete_domain() and DELETE /admin/domains/{id} in admin.py, gated by the
same get_current_admin platform-admin dependency every other route on this router already
requires (the router declares it once, at `APIRouter(dependencies=[Depends(get_current_admin)])`
level). Route-function tests below call it directly as a plain Python callable, matching
this repo's existing route-test convention (see test_protocol_element_list_snapshot_routes.py -
there's no TestClient/auth-cookie harness in this repo), and separately exercise
get_current_admin itself to prove a request without a valid platform-admin session is
rejected with 401 before it would ever reach the route body.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text

from app.api.routes import admin as admin_routes
from app.core.admin_security import CurrentAdmin, get_current_admin
from app.db.base import Base
from app.models.entities import (
    DocumentTemplate,
    DocumentTemplatePart,
    FinanceTransaction,
    GroupEntity,
    Leader,
    Protocol,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolImage,
    ProtocolText,
    StoredFile,
    SubmissionAssignment,
    SubmissionUpload,
    SubmissionUploadFile,
    Template,
    TemplateElement,
    Tenant,
    TenantDomain,
    UserProtocolAccess,
    UserTemplateAccess,
    WordImportDocument,
)
from app.services.admin_domain_service import AdminDomainService
from app.services.admin_tenant_service import AdminTenantService

from tests.factories import (
    make_app_user,
    make_element_definition,
    make_event,
    make_finance_account,
    make_fine,
    make_list_definition,
    make_list_entry,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_text,
    make_protocol_todo,
    make_template,
    make_template_element,
    make_tenant,
    make_user_tenant_role,
    make_word_import_profile,
)


# --- local row builders for the tables tests/factories.py doesn't cover yet ----------
# (kept local to this file rather than added to factories.py, since this task's scope is
# limited to the H18/H19 files - see task instructions).


def make_stored_file(db, tenant_id: int, name: str = "file.pdf") -> StoredFile:
    row = StoredFile(tenant_id=tenant_id, original_name=name, storage_path=f"/tmp/{name}")
    db.add(row)
    db.flush()
    return row


def make_protocol_image(db, protocol_element_block_id: int, stored_file_id: int, sort_index: int = 0) -> ProtocolImage:
    row = ProtocolImage(protocol_element_block_id=protocol_element_block_id, stored_file_id=stored_file_id, sort_index=sort_index)
    db.add(row)
    db.flush()
    return row


def make_word_import_document(db, tenant_id: int, template_id: int, stored_file_id: int, status: str = "eingelesen") -> WordImportDocument:
    row = WordImportDocument(
        tenant_id=tenant_id,
        template_id=template_id,
        stored_file_id=stored_file_id,
        original_filename="import.docx",
        display_name="Import",
        status=status,
    )
    db.add(row)
    db.flush()
    return row


def make_submission_assignment(db, tenant_id: int, list_definition_id: int, public_slug: str) -> SubmissionAssignment:
    row = SubmissionAssignment(
        tenant_id=tenant_id,
        title="Test Abgabe",
        public_slug=public_slug,
        source_type="list",
        list_definition_id=list_definition_id,
        deadline=date(2026, 1, 1),
    )
    db.add(row)
    db.flush()
    return row


def make_submission_upload(db, assignment_id: int, list_entry_id: int, status: str = "submitted") -> SubmissionUpload:
    row = SubmissionUpload(assignment_id=assignment_id, list_entry_id=list_entry_id, status=status)
    db.add(row)
    db.flush()
    return row


def make_submission_upload_file(db, upload_id: int, stored_file_id: int, sort_index: int = 0) -> SubmissionUploadFile:
    row = SubmissionUploadFile(upload_id=upload_id, stored_file_id=stored_file_id, sort_index=sort_index)
    db.add(row)
    db.flush()
    return row


def make_tenant_domain(db, tenant_id: int, domain: str, purpose: str = "app") -> TenantDomain:
    row = TenantDomain(tenant_id=tenant_id, purpose=purpose, domain=domain, verification_token=f"tok-{domain}")
    db.add(row)
    db.flush()
    return row


def make_group_entity(db, tenant_id: int, name: str) -> GroupEntity:
    row = GroupEntity(tenant_id=tenant_id, name=name)
    db.add(row)
    db.flush()
    return row


def make_leader(db, tenant_id: int, name: str) -> Leader:
    row = Leader(tenant_id=tenant_id, name=name)
    db.add(row)
    db.flush()
    return row


def make_document_template(db, tenant_id: int, code: str) -> DocumentTemplate:
    row = DocumentTemplate(tenant_id=tenant_id, code=code, name="Doc", filesystem_path=f"/tmp/{code}.tex")
    db.add(row)
    db.flush()
    return row


def make_document_template_part(db, tenant_id: int, code: str) -> DocumentTemplatePart:
    row = DocumentTemplatePart(tenant_id=tenant_id, code=code, name="Part", part_type="header", storage_path=f"/tmp/{code}.tex")
    db.add(row)
    db.flush()
    return row


def make_user_template_access(db, user_id: int, tenant_id: int, template_id: int) -> UserTemplateAccess:
    row = UserTemplateAccess(user_id=user_id, tenant_id=tenant_id, template_id=template_id)
    db.add(row)
    db.flush()
    return row


def make_user_protocol_access(db, user_id: int, tenant_id: int, protocol_id: int) -> UserProtocolAccess:
    row = UserProtocolAccess(user_id=user_id, tenant_id=tenant_id, protocol_id=protocol_id)
    db.add(row)
    db.flush()
    return row


def _tenant_linked_columns() -> list[tuple]:
    """Every (table, column) pair anywhere in the ORM schema with a foreign key into
    tenant.id - discovered from SQLAlchemy metadata rather than hand-enumerated, so a
    *future* tenant-scoped table is automatically covered by the assertion below without
    anyone remembering to update this test (this is the "generic check" the audit finding
    asked for as the stronger alternative to enumerating tables by name)."""
    pairs = []
    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_keys:
            if fk.column.table.name == "tenant" and fk.column.name == "id":
                pairs.append((table, fk.parent))
    return pairs


def _build_tenant_dataset(db, tenant: Tenant, suffix: str) -> dict:
    """Populates one representative row in every tenant-scoped table reachable via
    existing/local factories, prioritizing the tables delete_tenant's hand-rolled order
    explicitly deletes (protocol/submission_assignment/template) plus their RESTRICT-
    sensitive children, and the word_import_document gap this audit finding uncovered."""
    user = make_app_user(db, email=f"user-{suffix}@example.com")
    make_user_tenant_role(db, user.id, tenant.id)

    template = make_template(db, tenant.id, name=f"Template {suffix}")
    element_def = make_element_definition(db, tenant.id, f"Feld {suffix}", blocks=[{"type": "text"}])
    make_template_element(db, template.id, element_def.id, 0, "Sektion")

    protocol = make_protocol(db, tenant.id, template.id, protocol_number=f"P-{suffix}")
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={})
    make_protocol_text(db, block.id, content="Hallo")
    make_protocol_todo(db, block.id, tenant_id=tenant.id)

    protocol_image_file = make_stored_file(db, tenant.id, name=f"{suffix}-image.pdf")
    make_protocol_image(db, block.id, protocol_image_file.id)

    account = make_finance_account(db, tenant.id)
    make_fine(db, protocol.id, account.id)
    db.add(FinanceTransaction(account_id=account.id, amount=1, description="x", transaction_date=date(2026, 1, 1)))

    list_def = make_list_definition(db, tenant.id, name=f"Liste {suffix}")
    entry = make_list_entry(db, list_def.id)

    assignment = make_submission_assignment(db, tenant.id, list_def.id, public_slug=f"abgabe-{suffix}")
    upload = make_submission_upload(db, assignment.id, entry.id)
    upload_stored_file = make_stored_file(db, tenant.id, name=f"{suffix}-upload.pdf")
    make_submission_upload_file(db, upload.id, upload_stored_file.id)

    word_import_stored_file = make_stored_file(db, tenant.id, name=f"{suffix}-import.docx")
    word_import_document = make_word_import_document(db, tenant.id, template.id, word_import_stored_file.id)
    make_word_import_profile(db, tenant.id, template.id)

    make_participant(db, tenant.id, display_name=f"Person {suffix}")
    make_event(db, tenant.id, title=f"Event {suffix}")
    make_group_entity(db, tenant.id, name=f"Gruppe {suffix}")
    make_leader(db, tenant.id, name=f"Leiter {suffix}")
    domain = make_tenant_domain(db, tenant.id, domain=f"{suffix}.example.com")
    make_document_template(db, tenant.id, code=f"doc-{suffix}")
    make_document_template_part(db, tenant.id, code=f"part-{suffix}")
    make_user_template_access(db, user.id, tenant.id, template.id)
    make_user_protocol_access(db, user.id, tenant.id, protocol.id)

    return {
        "template": template,
        "protocol": protocol,
        "protocol_element_id": element.id,
        "protocol_element_block_id": block.id,
        "assignment": assignment,
        "word_import_document": word_import_document,
        "domain": domain,
    }


# --- H18: delete_tenant --------------------------------------------------------------


def test_delete_tenant_removes_every_tenant_scoped_row_and_spares_other_tenants(db):
    tenant_a = make_tenant(db, "Tenant A (deleted)")
    tenant_b = make_tenant(db, "Tenant B (control)")
    _build_tenant_dataset(db, tenant_a, "a")
    control = _build_tenant_dataset(db, tenant_b, "b")

    linked_columns = _tenant_linked_columns()
    table_names = {table.name for table, _ in linked_columns}
    # Sanity check on the discovery mechanism itself: if this ever finds only the three
    # tables delete_tenant explicitly deletes, something's wrong with the metadata walk
    # and the test below would silently prove nothing. word_import_document specifically
    # is the table this audit finding was actually about.
    assert "word_import_document" in table_names
    assert len(table_names) >= 15

    # This is the core regression: before the fix, this raised sqlalchemy.exc.IntegrityError
    # (FK violation on word_import_document_template_id_fkey) as soon as the explicit
    # `DELETE FROM template` ran, because word_import_document.template_id (RESTRICT,
    # NOT NULL) still pointed at it.
    deleted = AdminTenantService().delete_tenant(db, tenant_a.id)
    assert deleted is True

    assert db.get(Tenant, tenant_a.id) is None

    for table, column in linked_columns:
        count = db.execute(select(func.count()).select_from(table).where(column == tenant_a.id)).scalar_one()
        assert count == 0, f"{table.name}.{column.name} still has rows referencing the deleted tenant"

    # tenant_b (the control, never targeted by this delete) must survive completely
    # untouched - belt-and-suspenders on top of the per-column zero-count check above,
    # which only proves tenant_a's rows are gone, not that tenant_b's were spared.
    assert db.get(Tenant, tenant_b.id) is not None
    assert db.get(Template, control["template"].id) is not None
    assert db.get(Protocol, control["protocol"].id) is not None
    assert db.get(SubmissionAssignment, control["assignment"].id) is not None
    assert db.get(WordImportDocument, control["word_import_document"].id) is not None
    assert db.get(TenantDomain, control["domain"].id) is not None


def test_delete_tenant_cascades_through_non_tenant_scoped_child_tables(db):
    """Separate, focused test for the rows that don't carry their own tenant_id column
    and only cascade transitively through protocol/template/submission_assignment -
    protocol_element(_block), protocol_text, template_element, submission_upload(_file)."""
    tenant = make_tenant(db, "Tenant Cascade")
    data = _build_tenant_dataset(db, tenant, "cascade")

    assert AdminTenantService().delete_tenant(db, tenant.id) is True

    assert db.get(Protocol, data["protocol"].id) is None
    assert db.get(ProtocolElement, data["protocol_element_id"]) is None
    assert db.get(ProtocolElementBlock, data["protocol_element_block_id"]) is None
    assert (
        db.scalar(select(func.count()).select_from(ProtocolText).where(ProtocolText.protocol_element_block_id == data["protocol_element_block_id"]))
        == 0
    )
    assert (
        db.scalar(select(func.count()).select_from(TemplateElement).where(TemplateElement.template_id == data["template"].id))
        == 0
    )
    assert db.get(SubmissionAssignment, data["assignment"].id) is None
    assert (
        db.scalar(select(func.count()).select_from(SubmissionUpload).where(SubmissionUpload.assignment_id == data["assignment"].id))
        == 0
    )
    assert db.get(WordImportDocument, data["word_import_document"].id) is None


def test_delete_tenant_returns_false_for_unknown_tenant(db):
    assert AdminTenantService().delete_tenant(db, 999_999_999) is False


def test_delete_tenant_route_audits_without_fk_violation(db):
    """Regression for the 2026-08-18 production 500: the route's audit.log call ran
    *after* AdminTenantService.delete_tenant() already committed the tenant's deletion,
    passing that now-nonexistent id as tenant_id - audit_log.tenant_id has a FK into
    tenant.id, so the INSERT raised psycopg.errors.ForeignKeyViolation and the DELETE
    request 500'd (the tenant was in fact already gone by then; only the audit write
    failed). Fixed by not passing tenant_id at all for this event - which tenant was
    deleted is already recorded via entity_type="tenant"/entity_id."""
    tenant = make_tenant(db, "Route Delete Tenant")
    admin = CurrentAdmin(admin_id=1, admin_public_id=uuid.uuid4(), email="ops@example.com", display_name="Ops")

    admin_routes.delete_tenant(tenant.public_id, db=db, current_admin=admin)

    assert db.get(Tenant, tenant.id) is None
    audit_rows = db.execute(
        text("SELECT action, tenant_id, entity_type, entity_id FROM audit_log WHERE action = 'admin.tenant_deleted' AND entity_id = :id"),
        {"id": tenant.id},
    ).all()
    assert len(audit_rows) == 1
    assert audit_rows[0].tenant_id is None
    assert audit_rows[0].entity_type == "tenant"


def test_delete_tenant_route_404_for_unknown_tenant(db):
    admin = CurrentAdmin(admin_id=1, admin_public_id=uuid.uuid4(), email="ops@example.com", display_name="Ops")
    with pytest.raises(HTTPException) as exc_info:
        admin_routes.delete_tenant(uuid.uuid4(), db=db, current_admin=admin)
    assert exc_info.value.status_code == 404


# --- H19: domain deletion -------------------------------------------------------------


def test_delete_domain_service_removes_row_and_leaves_tenant_intact(db):
    tenant = make_tenant(db, "Domain Tenant")
    domain = make_tenant_domain(db, tenant.id, domain="unverified.example.com")

    deleted = AdminDomainService().delete_domain(db, domain.id)

    assert deleted is not None
    assert deleted.domain == "unverified.example.com"
    assert db.get(TenantDomain, domain.id) is None
    assert db.get(Tenant, tenant.id) is not None


def test_delete_domain_service_returns_none_for_unknown_id(db):
    assert AdminDomainService().delete_domain(db, 999_999_999) is None


def test_delete_domain_route_deletes_and_audits_as_platform_admin(db):
    tenant = make_tenant(db, "Route Tenant")
    domain = make_tenant_domain(db, tenant.id, domain="route-delete.example.com")
    admin = CurrentAdmin(admin_id=1, admin_public_id=uuid.uuid4(), email="ops@example.com", display_name="Ops")

    admin_routes.delete_domain(domain.public_id, db=db, current_admin=admin)

    assert db.get(TenantDomain, domain.id) is None
    audit_rows = db.execute(
        text("SELECT action, tenant_id FROM audit_log WHERE entity_type = 'tenant_domain' AND entity_id = :id"),
        {"id": domain.id},
    ).all()
    assert len(audit_rows) == 1
    assert audit_rows[0].action == "admin.domain_deleted"
    assert audit_rows[0].tenant_id == tenant.id


def test_delete_domain_route_404_for_unknown_domain(db):
    admin = CurrentAdmin(admin_id=1, admin_public_id=uuid.uuid4(), email="ops@example.com", display_name="Ops")
    with pytest.raises(HTTPException) as exc_info:
        admin_routes.delete_domain(uuid.uuid4(), db=db, current_admin=admin)
    assert exc_info.value.status_code == 404


def test_delete_domain_route_unreachable_without_platform_admin_session():
    """The DELETE route lives on the same router as every other /admin/* route (including
    the pre-existing DELETE /admin/tenants/{id}), which declares
    `dependencies=[Depends(get_current_admin)]` once at the router level - so it was
    already unreachable without a valid, signed platform-admin session cookie before this
    change, same as every neighboring route. get_current_admin resolves PlatformAdmin
    sessions only (a completely separate auth system from the customer-facing AppUser/
    tenant-role auth - own cookie, own signing secret, see admin_security.py's module
    docstring), so a regular tenant writer/reader session cookie is not even the right
    shape of token to be accepted here; the concrete rejection this dependency produces
    for "no valid platform-admin session" is a 401, which is what this exercises directly
    (calling the route function itself bypasses FastAPI's Depends resolution entirely -
    see test_protocol_element_list_snapshot_routes.py's docstring for why that's this
    repo's existing convention - so the dependency has to be exercised on its own)."""
    with pytest.raises(HTTPException) as exc_info:
        get_current_admin(admin=None)
    assert exc_info.value.status_code == 401
