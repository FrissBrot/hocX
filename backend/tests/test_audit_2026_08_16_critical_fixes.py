"""Regression tests for the two CRITICAL findings from the 2026-08-16 audit, both in
word_import_service.py:

- S3 (cross-tenant data leak): WordImportService.analyze() used to accept a
  client-supplied template_id without ever checking it belongs to the caller's tenant,
  so a writer in tenant A could point analyze() at tenant B's template_id and have its
  structure (TemplateElements, Matrix/List targets) and attendance roster
  (Participants) reflected back in the analysis response. Fixed by checking
  template.tenant_id == tenant_id once at the very top of analyze(), mirroring the
  guard WordImportQueueService.ingest() already had.

- D10 (broken cleanup after freeze commit): WordImportService.commit() freezes the new
  Protocol (status="abgeschlossen") partway through - and ProtocolService.update_protocol
  commits that transition to the DB immediately (see _run_status_transition_hooks). If a
  later step in commit() (list snapshot patching, outcome-row logging) then raises, the
  except-block's cleanup used to call protocol_service.delete_protocol(db, protocol_id),
  which itself calls get_protocol_or_404_not_frozen() and 409s on an "abgeschlossen"
  protocol - so cleanup failed too, masking the real error and leaving a permanently
  locked, broken protocol behind. Fixed by adding delete_protocol(..., bypass_freeze_check)
  - an internal-only escape hatch never reachable from the public delete-protocol route -
  and using it exactly in this cleanup path.
"""
import json
import zipfile
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Protocol, StoredFile
from app.services.protocol_service import ProtocolService
from app.services.tenant_import_service import TenantImportService
from app.services.tenant_transfer_common import build_row
from app.services.word_import_service import WordImportService

from tests.factories import make_protocol, make_template, make_tenant
from tests.test_word_import_e2e import _build_template, _commit_payload_from_analysis
from tests.word_import_fixtures import default_spec, render_docx


# --- S3: cross-tenant template_id in analyze() -----------------------------------


def test_analyze_rejects_template_id_belonging_to_another_tenant(db):
    tenant_a = make_tenant(db, name="Tenant A")
    tenant_b = make_tenant(db, name="Tenant B")
    template_b = make_template(db, tenant_b.id, name="Tenant B Template")
    db.flush()

    raw_bytes = render_docx(default_spec())
    service = WordImportService()

    with pytest.raises(ValueError, match="Vorlage nicht gefunden"):
        service.analyze(
            db,
            tenant_id=tenant_a.id,
            template_id=template_b.id,
            protocol_date_hint=None,
            raw_bytes=raw_bytes,
        )


def test_analyze_rejects_nonexistent_template_id(db):
    tenant = make_tenant(db)
    db.flush()

    raw_bytes = render_docx(default_spec())
    service = WordImportService()

    with pytest.raises(ValueError, match="Vorlage nicht gefunden"):
        service.analyze(
            db,
            tenant_id=tenant.id,
            template_id=999_999_999,
            protocol_date_hint=None,
            raw_bytes=raw_bytes,
        )


def test_analyze_still_succeeds_for_the_owning_tenants_own_template(db):
    """Sanity check that the new tenant guard doesn't break the legitimate same-tenant
    path - full happy-path coverage already lives in test_word_import_e2e.py."""
    ctx = _build_template(db)
    raw_bytes = render_docx(default_spec())
    service = WordImportService()

    analysis = service.analyze(
        db,
        tenant_id=ctx["tenant"].id,
        template_id=ctx["template"].id,
        protocol_date_hint=None,
        raw_bytes=raw_bytes,
    )

    assert analysis.protocol_date == date(2026, 10, 18)


# --- D10: cleanup after a freeze commit followed by a later failure --------------


def test_delete_protocol_rejects_frozen_protocol_by_default(db):
    """Unchanged public behaviour: the ordinary delete_protocol() (as used by the
    public DELETE /protocols/{id} route) must still 409 on an already-frozen protocol -
    bypass_freeze_check must never be reachable from that route."""
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="abgeschlossen")
    db.flush()

    service = ProtocolService()
    with pytest.raises(HTTPException) as exc_info:
        service.delete_protocol(db, protocol.id)
    assert exc_info.value.status_code == 409

    # Still there - the rejected delete must not have removed anything.
    assert db.get(Protocol, protocol.id) is not None


def test_delete_protocol_bypass_freeze_check_removes_frozen_protocol(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="abgeschlossen")
    db.flush()

    service = ProtocolService()
    deleted = service.delete_protocol(db, protocol.id, bypass_freeze_check=True)

    assert deleted is True
    assert db.get(Protocol, protocol.id) is None


def test_commit_cleans_up_frozen_protocol_when_a_step_after_freeze_fails(db, monkeypatch):
    """End-to-end reproduction of D10: monkeypatches ProtocolService.update_protocol so
    that, right after it performs the real freeze transition (status="abgeschlossen",
    committed internally by _run_status_transition_hooks - exactly what happens on the
    real code path), it raises - simulating a downstream write (list snapshots /
    outcome rows) failing right after the freeze already landed. Before the fix, the
    except-block's cleanup call to delete_protocol() would itself 409 on the now-frozen
    protocol - that competing exception would replace the original RuntimeError below
    instead of the bare `raise` re-raising it cleanly. After the fix, cleanup succeeds
    silently and the original RuntimeError propagates untouched.

    Doesn't assert "no leftover Protocol row" via a post-rollback query on this same
    session: commit()'s own db.rollback() in the except-block rolls back the fixture's
    entire ambient SAVEPOINT (including _build_template's tenant/template setup done
    earlier in this same test), not a scope local to this one call - see the identical
    note on EventService.update_event's rollback path in
    test_audit_2026_08_12_critical_fixes.py and conftest.db's SAVEPOINT-restart design.
    The RuntimeError-propagates-cleanly assertion below already proves delete_protocol
    succeeded without raising its own competing exception, which is what this test needs.
    """
    ctx = _build_template(db)
    raw_bytes = render_docx(default_spec())
    service = WordImportService()
    analysis = service.analyze(
        db, tenant_id=ctx["tenant"].id, template_id=ctx["template"].id,
        protocol_date_hint=None, raw_bytes=raw_bytes,
    )
    payload = _commit_payload_from_analysis(analysis, template_id=ctx["template"].id)

    real_update_protocol = ProtocolService.update_protocol

    def _update_protocol_then_boom(self, db, protocol_id, update_payload):
        result = real_update_protocol(self, db, protocol_id, update_payload)
        if update_payload.status == "abgeschlossen":
            raise RuntimeError("simulated failure after freeze commit landed")
        return result

    monkeypatch.setattr(ProtocolService, "update_protocol", _update_protocol_then_boom)

    with pytest.raises(RuntimeError, match="simulated failure after freeze commit landed"):
        service.commit(db, tenant_id=ctx["tenant"].id, user_id=1, payload=payload)


# --- S4 (tenant_import_service.py): manifest-controlled path traversal + ClamAV bypass ----
#
# TenantImportService._restore_file() joined the attacker-controlled `member_path` field
# from manifest.json (inside an uploaded tenant-import zip, POST /admin/tenants/import,
# require_admin_write) straight onto extract_dir with no containment check, unlike
# _safe_extract()'s zip-entry check a few lines below it - "../../../etc/passwd" or an
# absolute path ("/etc/passwd", which Path.__truediv__ treats as replacing the whole path)
# would read arbitrary files off the server's filesystem into the new tenant's storage.
#
# Separately, tenant_transfer_common.build_row() copied every manifest column 1:1 into the
# new DB row, including StoredFile.scan_status - a manifest shipping
# `"scan_status": "clean"` for a smuggled-in file would mark it as already having passed
# the ClamAV scan, skipping the scan workflow entirely (get_stored_file_content() in
# routes/files.py only blocks "infected"/"pending", it happily serves "clean").


def test_restore_file_rejects_relative_path_traversal_member_path(tmp_path):
    """Direct unit test of the fixed _restore_file(): a manifest member_path that walks out
    of extract_dir via '../' must raise instead of resolving to a path outside it."""
    service = TenantImportService()
    service.extract_dir = tmp_path / "extract"
    service.extract_dir.mkdir()
    (tmp_path / "outside.txt").write_text("should never be read")

    with pytest.raises(ValueError, match="Unsicherer Pfad"):
        service._restore_file(
            "../outside.txt", root=str(tmp_path / "storage"), new_tenant_id=1, subdir="files"
        )


def test_restore_file_rejects_absolute_member_path(tmp_path):
    """An absolute member_path (e.g. "/etc/passwd") must also be rejected - Path(a) / "/x"
    silently discards "a" per Python's own Path.__truediv__ semantics, so without the
    containment check this would let the manifest point straight at any file on disk."""
    service = TenantImportService()
    service.extract_dir = tmp_path / "extract"
    service.extract_dir.mkdir()

    with pytest.raises(ValueError, match="Unsicherer Pfad"):
        service._restore_file(
            "/etc/passwd", root=str(tmp_path / "storage"), new_tenant_id=1, subdir="files"
        )


def test_import_zip_aborts_when_stored_file_manifest_entry_uses_path_traversal(db, tmp_path):
    """Full-pipeline reproduction: a hand-crafted import zip whose stored_file row points its
    storage_path at a traversal target must abort the whole import with a clear error
    instead of copying a file from outside extract_dir into the new tenant's storage."""
    evil_zip = tmp_path / "traversal-manifest.zip"
    with zipfile.ZipFile(evil_zip, "w") as zf:
        manifest = {
            "format_version": 1,
            "scope": "full",
            "tables": {
                "tenant": {"id": 1, "name": "Attacker Tenant"},
                "stored_file": [
                    {
                        "id": 1,
                        "tenant_id": 1,
                        "original_name": "evil.bin",
                        "storage_path": "../../../etc/passwd",
                        "scan_status": "clean",
                    }
                ],
            },
        }
        zf.writestr("manifest.json", json.dumps(manifest))

    with pytest.raises(ValueError, match="Unsicherer Pfad"):
        TenantImportService().import_zip(db, evil_zip, "Should Not Exist")


def test_build_row_forces_scan_status_to_pending_ignoring_manifest_clean_claim():
    """Direct unit test of the fixed build_row(): a manifest dict claiming
    scan_status="clean" must not survive into the built ORM row - it must be forced to the
    safe "pending" default (the same state a fresh upload starts in), never trusted as-is.
    Also guards against StoredFile.scan_status's DB-level server_default of 'clean' - simply
    dropping the column from `values` would silently fall back to that unsafe default too."""
    data = {
        "tenant_id": 1,
        "original_name": "smuggled.bin",
        "mime_type": "application/octet-stream",
        "storage_path": "files/whatever.bin",
        "scan_status": "clean",
    }

    row = build_row(StoredFile, data, {"tenant_id": 1})

    assert row.scan_status == "pending"
    assert row.scan_status != "clean"


def test_build_row_scan_status_override_still_wins_over_forced_default():
    """Sanity check that the forced default doesn't break the legitimate use of `overrides`:
    TenantImportService._import_stored_files actually re-scans the restored bytes through
    ClamAV and passes the real result via overrides - that must still land in the row."""
    data = {
        "tenant_id": 1,
        "original_name": "checked.bin",
        "storage_path": "files/whatever.bin",
        "scan_status": "clean",  # manifest value - must be ignored either way
    }

    row = build_row(StoredFile, data, {"tenant_id": 1, "scan_status": "infected"})

    assert row.scan_status == "infected"


def test_import_zip_forces_pending_scan_status_despite_manifest_claiming_clean(db, tmp_path, monkeypatch):
    """End-to-end reproduction of the ClamAV-bypass half of S4: a manifest with a real file
    and a spoofed `"scan_status": "clean"` entry must not result in scan_status="clean" in
    the database after import. The real scanner call is monkeypatched to a deterministic
    "pending" (simulating the normal fail-open path when ClamAV can't be reached) so the
    test isn't at the mercy of whether a real ClamAV daemon is reachable in this environment -
    the point being tested is that the manifest's claim is never trusted, not what a live
    scan happens to return."""
    from app.services import tenant_import_service as svc_module

    monkeypatch.setattr(svc_module.scanner, "scan_file", lambda path, host, port: "pending")

    evil_zip = tmp_path / "spoofed-scan-status.zip"
    with zipfile.ZipFile(evil_zip, "w") as zf:
        manifest = {
            "format_version": 1,
            "scope": "full",
            "tables": {
                "tenant": {"id": 1, "name": "Attacker Tenant"},
                "stored_file": [
                    {
                        "id": 1,
                        "tenant_id": 1,
                        "original_name": "smuggled.bin",
                        "mime_type": "application/octet-stream",
                        "storage_path": "files/payload.bin",
                        "file_size_bytes": 7,
                        "checksum_sha256": "deadbeef",
                        "scan_status": "clean",  # attacker-spoofed
                    }
                ],
            },
        }
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("files/payload.bin", b"payload")

    new_tenant, _warnings = TenantImportService().import_zip(db, evil_zip, "Spoofed Scan Status Import")

    imported = db.scalar(select(StoredFile).where(StoredFile.tenant_id == new_tenant.id))
    assert imported is not None
    assert imported.scan_status == "pending"
    assert imported.scan_status != "clean"


# --- S1: export_latex (app/api/routes/exports.py) missing tenant check on protocol_id -------
#
# export_latex only checked require_admin(user) but never verified the protocol belonged to
# the caller's tenant - unlike its sibling routes (export_pdf, latest_export, ...) which all
# call access_service.ensure_can_read_protocol(...). A Tenant-A admin could export any
# Tenant-B protocol's LaTeX source by guessing/enumerating its id. Fixed by adding the same
# access_service.ensure_can_read_protocol(db, user, protocol_id) call used by the neighboring
# routes, right after require_admin(user).


def test_s1_export_latex_rejects_protocol_from_foreign_tenant(db):
    from app.api.routes import exports as exports_route
    from tests.factories import make_current_user

    tenant_a = make_tenant(db, "Tenant A (S1)")
    tenant_b = make_tenant(db, "Tenant B (S1)")
    template_b = make_template(db, tenant_b.id)
    protocol_b = make_protocol(db, tenant_b.id, template_b.id, protocol_number="S1-B-1")
    user_a = make_current_user(tenant_a.id, role="admin")

    with pytest.raises(HTTPException) as exc_info:
        exports_route.export_latex(protocol_b.id, request=None, db=db, user=user_a)
    assert exc_info.value.status_code == 403


def test_s1_export_latex_tenant_check_passes_through_for_own_tenant_protocol(db):
    """Sanity check that the new access check doesn't break same-tenant access: a Tenant-A
    admin exporting their own protocol must get past the tenant check. The protocol has no
    materialized document-template snapshot, so it still fails - but with a 404 ValueError
    from deeper in the service (not the 403 the cross-tenant case gets), proving the tenant
    check itself passed."""
    from app.api.routes import exports as exports_route
    from tests.factories import make_current_user

    tenant_a = make_tenant(db, "Tenant A (S1b)")
    template_a = make_template(db, tenant_a.id)
    protocol_a = make_protocol(db, tenant_a.id, template_a.id, protocol_number="S1-A-1")
    # Deterministically missing (not "" - which resolves to the cwd and would actually exist).
    protocol_a.document_template_path_snapshot = "/nonexistent/does-not-matter-s1"
    db.add(protocol_a)
    db.flush()
    user_a = make_current_user(tenant_a.id, role="admin")

    with pytest.raises(HTTPException) as exc_info:
        exports_route.export_latex(protocol_a.id, request=None, db=db, user=user_a)
    assert exc_info.value.status_code == 404


# --- S2: export_global_pdf's "list" branch (app/services/export_service.py) missing
# tenant check on list_definition_id -----------------------------------------------------
#
# list_definition_id comes straight from the POST /exports/lists request body
# (GlobalListExportRequest). export_global_pdf loaded the referenced ListDefinition via
# db.get(...) without ever checking it belonged to the caller's tenant, so a Tenant-A user
# could export the contents of any Tenant-B list by passing its id. Fixed by checking
# list_def.tenant_id == tenant_id right after the db.get(...) lookup and raising the same
# ValueError("List not found") used for the not-found case (-> 404 at the route layer),
# so a foreign-tenant id is indistinguishable from a nonexistent one.


def _s2_make_document_template_with_dir(db, tenant_id: int, code: str = "s2-default"):
    """A DocumentTemplate row backed by a real (empty) directory, so export_global_pdf gets
    past its template_path.exists()/shutil.copytree steps and actually reaches the
    list_definition_id lookup under test."""
    import tempfile

    from app.models import DocumentTemplate

    template_dir = tempfile.mkdtemp(prefix="hocx-test-s2-doctemplate-")
    doc_template = DocumentTemplate(
        tenant_id=tenant_id, code=code, name="Test Layout", filesystem_path=template_dir,
    )
    db.add(doc_template)
    db.flush()
    return doc_template


def test_s2_export_global_list_rejects_list_definition_from_foreign_tenant(db):
    from app.api.routes import exports as exports_route
    from tests.factories import make_current_user, make_list_definition

    tenant_a = make_tenant(db, "Tenant A (S2)")
    tenant_b = make_tenant(db, "Tenant B (S2)")
    doc_template_a = _s2_make_document_template_with_dir(db, tenant_a.id)
    list_def_b = make_list_definition(db, tenant_b.id, name="Foreign List (S2)")
    user_a = make_current_user(tenant_a.id, role="admin")

    body = exports_route.GlobalListExportRequest(
        template_id=doc_template_a.id,
        list_definition_id=list_def_b.id,
    )

    with pytest.raises(HTTPException) as exc_info:
        _run(exports_route.export_global_list(body, request=None, db=db, user=user_a))
    assert exc_info.value.status_code == 404


def test_s2_export_global_pdf_service_rejects_list_definition_from_foreign_tenant(db):
    """Same as above but exercising ExportService.export_global_pdf directly, to pin the fix
    at the service layer (where the actual db.get(ListDefinition, ...) call lives) regardless
    of how future routes call into it."""
    from app.services.export_service import ExportService
    from tests.factories import make_list_definition

    tenant_a = make_tenant(db, "Tenant A (S2b)")
    tenant_b = make_tenant(db, "Tenant B (S2b)")
    doc_template_a = _s2_make_document_template_with_dir(db, tenant_a.id)
    list_def_b = make_list_definition(db, tenant_b.id, name="Foreign List (S2b)")

    service = ExportService()
    with pytest.raises(ValueError, match="List not found"):
        _run(
            service.export_global_pdf(
                db, tenant_a.id, doc_template_a.id, "list",
                list_definition_id=list_def_b.id,
            )
        )


def _run(coro):
    import asyncio

    return asyncio.run(coro)


# --- D1 (protocol_service.py): _cycle_bounds crashes on a schema-valid but real-invalid
# reset_month/reset_day combination (e.g. Feb 30) -----------------------------------------


def test_cycle_bounds_clamps_invalid_reset_day_instead_of_raising():
    """CycleConfig validates reset_month (1-12) and reset_day (1-31) independently, so
    reset_month=2, reset_day=30 is schema-valid but not a real calendar date. Before the
    fix, ProtocolService._cycle_bounds() built date(year, 2, 30) directly and raised
    ValueError, blocking every protocol-numbering call for the whole template. Fixed by
    routing through cycle_utils.reset_boundary(), which clamps to the last valid day of
    the month - mirrors the clamp cycle_utils.get_cycle_year() already had."""
    from app.services.protocol_service import ProtocolService

    service = ProtocolService()
    cycle_start, cycle_end = service._cycle_bounds(date(2026, 3, 1), reset_month=2, reset_day=30)

    # Clamped reset boundary is Feb 28, 2026 (2026 is not a leap year) -> cycle starts the
    # day after.
    assert cycle_start == date(2026, 3, 1)
    assert cycle_end == date(2027, 2, 28)


def test_cycle_bounds_still_matches_get_cycle_year_for_a_normal_reset_date():
    """Sanity check that the shared reset_boundary() helper didn't change behaviour for
    the common, already-valid case (reset_month=12, reset_day=31, the CycleConfig
    default)."""
    from app.core.cycle_utils import get_cycle_year
    from app.services.protocol_service import ProtocolService

    service = ProtocolService()
    d = date(2026, 6, 15)
    cycle_start, cycle_end = service._cycle_bounds(d, reset_month=12, reset_day=31)

    assert cycle_start.year == get_cycle_year(d, 12, 31)
    assert cycle_start == date(2026, 1, 1)
    assert cycle_end == date(2026, 12, 31)


# --- D8 (element_definition_service.py): matrix blocks with a foreign-tenant
# linked_list_id spread that tenant's list content into every protocol using them --------


def test_create_element_definition_rejects_linked_list_from_foreign_tenant(db):
    from app.schemas.template import ElementDefinitionBlockCreate, ElementDefinitionCreate
    from app.services.element_definition_service import ElementDefinitionService
    from tests.factories import make_list_definition

    tenant_a = make_tenant(db, "Tenant A (D8)")
    tenant_b = make_tenant(db, "Tenant B (D8)")
    foreign_list = make_list_definition(db, tenant_b.id, name="Foreign List (D8)")

    payload = ElementDefinitionCreate(
        title="Matrix mit fremder Liste",
        blocks=[
            ElementDefinitionBlockCreate(
                id=1,
                title="Matrix",
                element_type_id=11,
                render_type_id=5,
                sort_index=1,
                configuration_json={"linked_list_id": foreign_list.id},
            )
        ],
    )

    service = ElementDefinitionService()
    with pytest.raises(ValueError, match="Linked list"):
        service.create_element_definition(db, payload, tenant_id=tenant_a.id)


def test_create_element_definition_accepts_linked_list_from_own_tenant(db):
    from app.schemas.template import ElementDefinitionBlockCreate, ElementDefinitionCreate
    from app.services.element_definition_service import ElementDefinitionService
    from tests.factories import make_list_definition

    tenant_a = make_tenant(db, "Tenant A (D8b)")
    own_list = make_list_definition(db, tenant_a.id, name="Own List (D8b)")

    payload = ElementDefinitionCreate(
        title="Matrix mit eigener Liste",
        blocks=[
            ElementDefinitionBlockCreate(
                id=1,
                title="Matrix",
                element_type_id=11,
                render_type_id=5,
                sort_index=1,
                configuration_json={"linked_list_id": own_list.id},
            )
        ],
    )

    service = ElementDefinitionService()
    result = service.create_element_definition(db, payload, tenant_id=tenant_a.id)
    assert result.blocks[0].configuration_json["linked_list_id"] == own_list.id


def test_update_element_definition_rejects_linked_list_from_foreign_tenant(db):
    from app.schemas.template import (
        ElementDefinitionBlockCreate,
        ElementDefinitionCreate,
        ElementDefinitionUpdate,
    )
    from app.services.element_definition_service import ElementDefinitionService
    from tests.factories import make_list_definition

    tenant_a = make_tenant(db, "Tenant A (D8c)")
    tenant_b = make_tenant(db, "Tenant B (D8c)")
    foreign_list = make_list_definition(db, tenant_b.id, name="Foreign List (D8c)")

    service = ElementDefinitionService()
    created = service.create_element_definition(
        db,
        ElementDefinitionCreate(
            title="Matrix",
            blocks=[
                ElementDefinitionBlockCreate(
                    id=1, title="Matrix", element_type_id=11, render_type_id=5, sort_index=1,
                )
            ],
        ),
        tenant_id=tenant_a.id,
    )

    update_payload = ElementDefinitionUpdate(
        blocks=[
            ElementDefinitionBlockCreate(
                id=1, title="Matrix", element_type_id=11, render_type_id=5, sort_index=1,
                configuration_json={"linked_list_id": foreign_list.id},
            )
        ]
    )
    with pytest.raises(ValueError, match="Linked list"):
        service.update_element_definition(db, created.id, update_payload)
