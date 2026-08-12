"""Regression tests for TenantExportService/TenantImportService - previously zero test
coverage despite this being where a critical bug was found and fixed: exporting a tenant
used to bundle the REAL password_hash of users who were merely *referenced* (e.g. as
Template.created_by) by the exported tenant but were not actually members of it, leaking
another tenant's credentials to whoever received the export file (see
REDACTED_PASSWORD_HASH_MARKER in tenant_transfer_common.py).

Covers:
- export bundles real password_hash only for actual tenant members, and redacts it (with
  REDACTED_PASSWORD_HASH_MARKER) for everyone else referenced only as metadata
- foreign (cross-tenant) app_user references are exported by email, not by numeric id
- roundtrip export -> import: core entities (template, protocol, participant) reappear
  under the new tenant with fresh ids, correctly relinked
- import never touches a third, uninvolved tenant's data
- a corrupted archive (no manifest.json, or a zip-slip path) fails cleanly without leaving
  a half-imported tenant behind
"""
from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.entities import Participant, Protocol, Template
from app.services.tenant_export_service import TenantExportService
from app.services.tenant_import_service import TenantImportService
from tests.factories import (
    make_app_user,
    make_participant,
    make_protocol,
    make_template,
    make_tenant,
    make_user_tenant_role,
)


def _read_manifest(zip_path: Path) -> dict:
    with zipfile.ZipFile(zip_path) as zf:
        return json.loads(zf.read("manifest.json").decode("utf-8"))


# --- export: password hash redaction / foreign reference handling -----------------------


def test_export_redacts_password_hash_for_non_member_but_keeps_it_for_member(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_foreign = make_tenant(db, "Tenant Foreign")

    member = make_app_user(db, email="member@a.example", password="member-real-password")
    make_user_tenant_role(db, member.id, tenant_a.id, role_code="writer")

    foreign_creator = make_app_user(db, email="foreign@x.example", password="foreign-real-password")
    make_user_tenant_role(db, foreign_creator.id, tenant_foreign.id, role_code="admin")

    template = make_template(db, tenant_a.id, name="Sitzungsprotokoll")
    template.created_by = foreign_creator.id
    db.add(template)
    db.flush()

    zip_path, _filename = TenantExportService().export(db, tenant_a.id, "full")
    try:
        manifest = _read_manifest(zip_path)
        app_users = {row["email"]: row for row in manifest["tables"]["app_user"]}

        # The actual tenant member's real hash must travel with the export (so they can log
        # in on the target installation).
        assert app_users["member@a.example"]["password_hash"] == member.password_hash
        assert app_users["member@a.example"]["password_hash"] != "REDACTED:not-a-tenant-member"

        # The foreign user is only a metadata reference (created_by) - never a member of
        # tenant_a - so their real credentials must NOT leave the installation.
        assert app_users["foreign@x.example"]["password_hash"] == "REDACTED:not-a-tenant-member"
        assert app_users["foreign@x.example"]["password_hash"] != foreign_creator.password_hash

        # Foreign references are exported by email, never by the source installation's
        # numeric id (which would be meaningless - or worse, collide - on the target).
        template_row = manifest["tables"]["template"][0]
        assert template_row["created_by"] == "foreign@x.example"
    finally:
        zip_path.unlink(missing_ok=True)


# --- roundtrip: export -> import re-links core entities under fresh ids -----------------


def test_export_import_roundtrip_recreates_core_entities_with_new_ids(db):
    tenant_a = make_tenant(db, "Tenant A")
    template = make_template(db, tenant_a.id, name="Vorstandssitzung")
    protocol = make_protocol(db, tenant_a.id, template.id, protocol_number="P-42")
    participant = make_participant(db, tenant_a.id, display_name="Anna Muster")

    zip_path, _filename = TenantExportService().export(db, tenant_a.id, "full")
    try:
        new_tenant, warnings = TenantImportService().import_zip(db, zip_path, "Tenant A (Import)")
    finally:
        zip_path.unlink(missing_ok=True)

    assert new_tenant.id != tenant_a.id
    assert new_tenant.name == "Tenant A (Import)"

    imported_template = db.scalar(select(Template).where(Template.tenant_id == new_tenant.id))
    assert imported_template is not None
    assert imported_template.id != template.id
    assert imported_template.name == "Vorstandssitzung"

    imported_protocol = db.scalar(select(Protocol).where(Protocol.tenant_id == new_tenant.id))
    assert imported_protocol is not None
    assert imported_protocol.id != protocol.id
    assert imported_protocol.protocol_number == "P-42"
    # The imported protocol must point at the NEW template's id, not the source tenant's.
    assert imported_protocol.template_id == imported_template.id

    imported_participant = db.scalar(select(Participant).where(Participant.tenant_id == new_tenant.id))
    assert imported_participant is not None
    assert imported_participant.id != participant.id
    assert imported_participant.display_name == "Anna Muster"


def test_import_resolves_existing_target_user_by_email_instead_of_creating_duplicate(db):
    """A created_by reference to a user who already has an account on the target
    installation (matched by email) must resolve to that EXISTING account, not spawn a
    second, unusable one with a random password."""
    tenant_a = make_tenant(db, "Tenant A")
    creator = make_app_user(db, email="creator@shared.example", password="whatever")
    make_user_tenant_role(db, creator.id, tenant_a.id, role_code="writer")
    template = make_template(db, tenant_a.id)
    template.created_by = creator.id
    db.add(template)
    db.flush()

    zip_path, _filename = TenantExportService().export(db, tenant_a.id, "full")
    try:
        new_tenant, _warnings = TenantImportService().import_zip(db, zip_path, "Tenant A (Import)")
    finally:
        zip_path.unlink(missing_ok=True)

    imported_template = db.scalar(select(Template).where(Template.tenant_id == new_tenant.id))
    assert imported_template.created_by == creator.id


# --- cross-tenant safety: an uninvolved third tenant is never touched -------------------


def test_export_and_import_never_modifies_an_uninvolved_tenant(db):
    tenant_a = make_tenant(db, "Tenant A")
    make_template(db, tenant_a.id, name="A-Template")

    bystander = make_tenant(db, "Unbeteiligter Verein")
    bystander_template = make_template(db, bystander.id, name="Bystander Template")
    bystander_protocol = make_protocol(db, bystander.id, bystander_template.id, protocol_number="BYSTANDER-1")
    bystander_participant = make_participant(db, bystander.id, display_name="Bystander Person")

    zip_path, _filename = TenantExportService().export(db, tenant_a.id, "full")
    try:
        TenantImportService().import_zip(db, zip_path, "Tenant A (Import)")
    finally:
        zip_path.unlink(missing_ok=True)

    db.expire_all()
    still_there_template = db.get(Template, bystander_template.id)
    still_there_protocol = db.get(Protocol, bystander_protocol.id)
    still_there_participant = db.get(Participant, bystander_participant.id)

    assert still_there_template is not None
    assert still_there_template.tenant_id == bystander.id
    assert still_there_template.name == "Bystander Template"
    assert still_there_protocol is not None
    assert still_there_protocol.protocol_number == "BYSTANDER-1"
    assert still_there_participant is not None
    assert still_there_participant.display_name == "Bystander Person"

    # No template/protocol/participant belonging to the bystander tenant was duplicated or
    # otherwise created as a side effect of exporting/importing a *different* tenant.
    assert db.scalar(
        select(Template).where(Template.tenant_id == bystander.id, Template.id != bystander_template.id)
    ) is None


# --- error handling: a corrupted archive fails cleanly -----------------------------------


def test_import_rejects_zip_without_manifest(db, tmp_path):
    bad_zip = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("not-a-manifest.txt", "nope")

    with pytest.raises(ValueError, match="manifest.json"):
        TenantImportService().import_zip(db, bad_zip, "Should Not Exist")


def test_import_rejects_zip_slip_path(db, tmp_path):
    """A malicious/corrupted archive whose member path escapes the extraction directory
    must be rejected outright rather than being extracted onto the filesystem."""
    evil_zip = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil_zip, "w") as zf:
        manifest = {"format_version": 1, "scope": "structure", "tables": {"tenant": {"id": 1, "name": "x"}}}
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("../../etc/evil.txt", "malicious")

    with pytest.raises(ValueError, match="Unsicherer Pfad"):
        TenantImportService().import_zip(db, evil_zip, "Should Not Exist")


def test_failed_import_does_not_leave_a_half_imported_tenant(db):
    """format_version mismatch fails after extraction but before any tenant row is
    created - must raise cleanly with no partial tenant left in the tenant list."""
    from app.models.entities import Tenant

    fd = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    fd.close()
    bad_zip = Path(fd.name)
    with zipfile.ZipFile(bad_zip, "w") as zf:
        manifest = {"format_version": 999, "scope": "structure", "tables": {}}
        zf.writestr("manifest.json", json.dumps(manifest))

    tenants_before = set(db.scalars(select(Tenant.id)).all())
    try:
        with pytest.raises(ValueError, match="Nicht unterstützte Export-Version"):
            TenantImportService().import_zip(db, bad_zip, "Should Not Exist")
    finally:
        bad_zip.unlink(missing_ok=True)

    tenants_after = set(db.scalars(select(Tenant.id)).all())
    assert tenants_after == tenants_before
