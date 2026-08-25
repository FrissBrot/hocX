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
- verified custom domains (tenant_domain) travel with the same verification_token/status,
  with global-uniqueness collisions on the target skipped (not crashed) and warned about
- tenant.last_word_import_template_id is remapped to the imported template's new id
  instead of crashing the import on a dangling source-installation id
"""
from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.secret_crypto import decrypt_secret, encrypt_secret
from app.core.totp import generate_totp_secret
from app.models.entities import (
    Participant,
    Protocol,
    ProtocolExportCache,
    StoredFile,
    Template,
    TenantDomain,
    UserMfaFactor,
    UserProtocolScroll,
    WordImportDocument,
    WordImportProfile,
    WordImportSuggestionOutcome,
)
from app.services.tenant_export_service import TenantExportService
from app.services.tenant_import_service import TenantImportService
from tests.factories import (
    make_app_user,
    make_element_definition,
    make_list_definition,
    make_list_entry,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
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


def test_export_import_roundtrip_keeps_word_import_document_and_source_file(db, monkeypatch, tmp_path):
    from app.core.config import settings
    from app.services import tenant_import_service as import_module

    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(import_module.scanner, "scan_file", lambda *args, **kwargs: "clean")

    tenant = make_tenant(db, "Word Import Tenant")
    creator = make_app_user(db, email="word-import@example.com")
    make_user_tenant_role(db, creator.id, tenant.id, role_code="writer")
    template = make_template(db, tenant.id, name="Importvorlage")
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="WI-1")
    source_path = tmp_path / "word-imports" / "source.docx"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"docx-test-content")
    stored_file = StoredFile(
        tenant_id=tenant.id, storage_path="word-imports/source.docx",
        original_name="Sitzung.docx", mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size_bytes=17, scan_status="clean", created_by=creator.id,
    )
    db.add(stored_file)
    db.flush()
    document = WordImportDocument(
        tenant_id=tenant.id, template_id=template.id, stored_file_id=stored_file.id,
        original_filename="Sitzung.docx", display_name="Sitzung", status="importiert",
        analysis_snapshot_json={"title": "Test"}, review_draft_json={"approved": True},
        protocol_id=protocol.id, created_by=creator.id, imported_by=creator.id,
    )
    db.add(document)
    db.flush()

    zip_path, _filename = TenantExportService().export(db, tenant.id, "full")
    try:
        manifest = _read_manifest(zip_path)
        assert manifest["tables"]["word_import_document"][0]["original_filename"] == "Sitzung.docx"
        new_tenant, warnings = TenantImportService().import_zip(db, zip_path, "Word Import Tenant (Import)")
    finally:
        zip_path.unlink(missing_ok=True)

    imported = db.scalar(select(WordImportDocument).where(WordImportDocument.tenant_id == new_tenant.id))
    imported_template = db.scalar(select(Template).where(Template.tenant_id == new_tenant.id))
    imported_protocol = db.scalar(select(Protocol).where(Protocol.tenant_id == new_tenant.id))
    imported_file = db.get(StoredFile, imported.stored_file_id)
    assert warnings == []
    assert imported.template_id == imported_template.id
    assert imported.protocol_id == imported_protocol.id
    assert imported.created_by == creator.id
    assert imported.imported_by == creator.id
    assert imported.analysis_snapshot_json == {"title": "Test"}
    assert imported.review_draft_json == {"approved": True}
    assert imported_file.original_name == "Sitzung.docx"
    assert (tmp_path / imported_file.storage_path).read_bytes() == b"docx-test-content"


def test_full_backup_roundtrip_keeps_remaining_tenant_state(db, monkeypatch, tmp_path):
    """Regression guard for tenant-owned tables that used to be silently omitted."""
    from app.core.config import settings
    from app.services import tenant_import_service as import_module

    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(import_module.scanner, "scan_file", lambda *args, **kwargs: "clean")

    tenant = make_tenant(db, "Complete Backup")
    user = make_app_user(db, email="backup@example.com")
    make_user_tenant_role(db, user.id, tenant.id, role_code="admin")
    template = make_template(db, tenant.id, name="Learned Template")
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="BACKUP-1")
    generated_path = tmp_path / "exports" / "backup.pdf"
    generated_path.parent.mkdir(parents=True)
    generated_path.write_bytes(b"pdf-cache")
    generated_file = StoredFile(
        tenant_id=tenant.id, storage_path="exports/backup.pdf", original_name="backup.pdf",
        mime_type="application/pdf", file_size_bytes=9, scan_status="clean", created_by=user.id,
    )
    db.add(generated_file)
    db.flush()
    db.add_all([
        WordImportProfile(
            tenant_id=tenant.id, template_id=template.id,
            mapping_config_json={"learned": {"source": "target"}},
        ),
        WordImportSuggestionOutcome(
            tenant_id=tenant.id, template_id=template.id, signal_type="event_match",
            suggested_score=0.87, was_accepted=True,
        ),
        ProtocolExportCache(
            protocol_id=protocol.id, export_format="pdf", latex_source="source",
            generated_file_id=generated_file.id, generator_version="test-v1",
        ),
        UserProtocolScroll(user_id=user.id, protocol_id=protocol.id, last_element_id=17),
    ])
    db.flush()

    zip_path, _ = TenantExportService().export(db, tenant.id, "full")
    try:
        manifest = _read_manifest(zip_path)
        assert len(manifest["tables"]["word_import_profile"]) == 1
        assert len(manifest["tables"]["word_import_suggestion_outcome"]) == 1
        assert len(manifest["tables"]["protocol_export_cache"]) == 1
        assert manifest["tables"]["user_protocol_scroll"][0]["user_id"] == user.email
        imported_tenant, warnings = TenantImportService().import_zip(db, zip_path, "Complete Backup (Import)")
    finally:
        zip_path.unlink(missing_ok=True)

    imported_template = db.scalar(select(Template).where(Template.tenant_id == imported_tenant.id))
    imported_protocol = db.scalar(select(Protocol).where(Protocol.tenant_id == imported_tenant.id))
    profile = db.scalar(select(WordImportProfile).where(WordImportProfile.tenant_id == imported_tenant.id))
    outcome = db.scalar(select(WordImportSuggestionOutcome).where(WordImportSuggestionOutcome.tenant_id == imported_tenant.id))
    cache = db.scalar(select(ProtocolExportCache).where(ProtocolExportCache.protocol_id == imported_protocol.id))
    scroll = db.get(UserProtocolScroll, (user.id, imported_protocol.id))

    assert warnings == []
    assert profile.template_id == imported_template.id
    assert profile.mapping_config_json == {"learned": {"source": "target"}}
    assert outcome.template_id == imported_template.id
    assert outcome.suggested_score == pytest.approx(0.87)
    assert cache.generated_file_id is not None
    assert db.get(StoredFile, cache.generated_file_id).tenant_id == imported_tenant.id
    assert (tmp_path / db.get(StoredFile, cache.generated_file_id).storage_path).read_bytes() == b"pdf-cache"
    assert scroll.last_element_id == 17


def test_export_import_roundtrip_restores_all_member_mfa_factors(db):
    tenant = make_tenant(db, "MFA Tenant")
    user = make_app_user(db, email="mfa-transfer@example.com")
    make_user_tenant_role(db, user.id, tenant.id, role_code="admin")
    secret = generate_totp_secret()
    user.preferred_mfa_factor_type = "webauthn"
    db.add_all([
        user,
        UserMfaFactor(
            user_id=user.id,
            factor_type="totp",
            label="Telefon",
            secret_encrypted=encrypt_secret(secret),
            totp_last_counter=123,
        ),
        UserMfaFactor(
            user_id=user.id,
            factor_type="webauthn",
            label="Security Key",
            webauthn_credential_id="portable-credential-id",
            webauthn_public_key_pem="public-key",
            webauthn_sign_count=7,
            webauthn_aaguid="test-aaguid",
            webauthn_rp_id="login.example.com",
            webauthn_transports_json=["usb", "nfc"],
        ),
    ])
    db.flush()

    zip_path, _filename = TenantExportService().export(db, tenant.id, "full")
    try:
        manifest = _read_manifest(zip_path)
        exported = manifest["tables"]["user_mfa_factor"]
        assert len(exported) == 2
        assert next(row for row in exported if row["factor_type"] == "totp")["totp_secret"] == secret
        assert all("secret_encrypted" not in row for row in exported)

        # Simulate the target installation by removing the source-global account. Its
        # tenant membership cascades, while the export archive remains self-contained.
        db.delete(user)
        db.flush()
        _new_tenant, warnings = TenantImportService().import_zip(db, zip_path, "MFA Tenant Import")
    finally:
        zip_path.unlink(missing_ok=True)

    imported_user = db.scalar(select(type(user)).where(type(user).email == "mfa-transfer@example.com"))
    factors = db.scalars(select(UserMfaFactor).where(UserMfaFactor.user_id == imported_user.id)).all()
    assert warnings == []
    assert imported_user.preferred_mfa_factor_type == "webauthn"
    assert {factor.factor_type for factor in factors} == {"totp", "webauthn"}
    imported_totp = next(factor for factor in factors if factor.factor_type == "totp")
    imported_passkey = next(factor for factor in factors if factor.factor_type == "webauthn")
    assert decrypt_secret(imported_totp.secret_encrypted) == secret
    assert imported_totp.totp_last_counter == 123
    assert imported_passkey.webauthn_credential_id == "portable-credential-id"
    assert imported_passkey.webauthn_sign_count == 7
    assert imported_passkey.webauthn_transports_json == ["usb", "nfc"]


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


def test_import_rejects_zip_with_too_many_entries(db, tmp_path):
    """Zip-bomb guard (M19, 2026-08-12 audit): an archive with an excessive entry count must
    be rejected before extractall() ever runs, mirroring file_service.py's MAX_ZIP_ENTRIES
    guard for the word-import ZIP upload."""
    from app.services.tenant_import_service import MAX_IMPORT_ZIP_ENTRIES

    bomb_zip = tmp_path / "entry-bomb.zip"
    with zipfile.ZipFile(bomb_zip, "w") as zf:
        manifest = {"format_version": 1, "scope": "structure", "tables": {"tenant": {"id": 1, "name": "x"}}}
        zf.writestr("manifest.json", json.dumps(manifest))
        for i in range(MAX_IMPORT_ZIP_ENTRIES + 1):
            zf.writestr(f"junk/{i}.txt", "x")

    with pytest.raises(ValueError, match="zu viele Dateien"):
        TenantImportService().import_zip(db, bomb_zip, "Should Not Exist")


def test_import_rejects_zip_with_excessive_uncompressed_size(db, tmp_path):
    """Zip-bomb guard (M19): a small archive that declares a huge uncompressed size (highly
    compressible payload, the classic zip-bomb shape) must be rejected before extractall()
    based on the declared size in the zip's central directory - it should never actually have
    to inflate gigabytes of data to detect this."""
    from app.services.tenant_import_service import MAX_IMPORT_ZIP_TOTAL_BYTES

    bomb_zip = tmp_path / "size-bomb.zip"
    with zipfile.ZipFile(bomb_zip, "w") as zf:
        manifest = {"format_version": 1, "scope": "structure", "tables": {"tenant": {"id": 1, "name": "x"}}}
        zf.writestr("manifest.json", json.dumps(manifest))
        oversized_info = zipfile.ZipInfo("huge.bin")
        zf.writestr(oversized_info, "x")
        # Forge the declared (central-directory) uncompressed size after writing the real
        # (tiny) entry - exactly what a hand-crafted zip bomb does: a small compressed
        # payload that claims to inflate to something enormous.
        zf.NameToInfo["huge.bin"].file_size = MAX_IMPORT_ZIP_TOTAL_BYTES + 1

    with pytest.raises(ValueError, match="entpackt zu gross"):
        TenantImportService().import_zip(db, bomb_zip, "Should Not Exist")


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


# --- table/matrix "linked list" survives export/import (previously reset to nothing) ----
#
# element_definition.configuration_json["blocks"][].configuration_json is where the block
# designer UI actually writes a Matrix/Table block's list link - both the block-level
# "Modus: Automatisch / Quelle: Liste" source (auto_source.list_id) and a per-row "Zeile aus
# Liste" link (rows[].row_config.linked_list_id/linked_list_entry_id). Neither was remapped
# from the source tenant's list_definition/list_entry ids to the freshly imported ones -
# only the unrelated top-level linked_list_id (whole-list "Formular" blocks) was.


def test_export_import_roundtrip_remaps_matrix_auto_source_list_link(db):
    tenant_a = make_tenant(db, "Tenant A")
    source_list = make_list_definition(db, tenant_a.id, name="Leitende")
    definition = make_element_definition(
        db, tenant_a.id, "Matrix",
        blocks=[{
            "id": 1,
            "configuration_json": {
                "mode": "auto",
                "auto_source": {"type": "list", "list_id": source_list.id, "event_tag_filter": None},
            },
        }],
    )

    zip_path, _filename = TenantExportService().export(db, tenant_a.id, "full")
    try:
        new_tenant, _warnings = TenantImportService().import_zip(db, zip_path, "Tenant A (Import)")
    finally:
        zip_path.unlink(missing_ok=True)

    from app.models.entities import ElementDefinition, ListDefinition

    imported_list = db.scalar(select(ListDefinition).where(ListDefinition.tenant_id == new_tenant.id))
    imported_definition = db.scalar(select(ElementDefinition).where(ElementDefinition.tenant_id == new_tenant.id))
    assert imported_definition.id != definition.id
    imported_list_id = imported_definition.configuration_json["blocks"][0]["configuration_json"]["auto_source"]["list_id"]
    assert imported_list_id == imported_list.id
    assert imported_list_id != source_list.id


def test_export_import_roundtrip_remaps_matrix_row_list_entry_link(db):
    tenant_a = make_tenant(db, "Tenant A")
    source_list = make_list_definition(db, tenant_a.id, name="Leitende")
    source_entry = make_list_entry(db, source_list.id, column_one_value={"text_value": "Anna"})
    make_element_definition(
        db, tenant_a.id, "Tabelle",
        blocks=[{
            "id": 1,
            "configuration_json": {
                "rows": [{
                    "id": "1",
                    "row_type": "list_entry",
                    "row_config": {"linked_list_id": source_list.id, "linked_list_entry_id": source_entry.id},
                }],
            },
        }],
    )

    zip_path, _filename = TenantExportService().export(db, tenant_a.id, "full")
    try:
        new_tenant, _warnings = TenantImportService().import_zip(db, zip_path, "Tenant A (Import)")
    finally:
        zip_path.unlink(missing_ok=True)

    from app.models.entities import ElementDefinition, ListDefinition, ListEntry

    imported_list = db.scalar(select(ListDefinition).where(ListDefinition.tenant_id == new_tenant.id))
    imported_entry = db.scalar(select(ListEntry).where(ListEntry.list_definition_id == imported_list.id))
    imported_definition = db.scalar(select(ElementDefinition).where(ElementDefinition.tenant_id == new_tenant.id))
    row_config = imported_definition.configuration_json["blocks"][0]["configuration_json"]["rows"][0]["row_config"]
    assert row_config["linked_list_id"] == imported_list.id
    assert row_config["linked_list_entry_id"] == imported_entry.id
    assert row_config["linked_list_id"] != source_list.id
    assert row_config["linked_list_entry_id"] != source_entry.id


def test_export_import_roundtrip_remaps_protocol_block_row_list_entry_link(db):
    """protocol_element_block.configuration_snapshot_json uses a FLATTENED row shape
    (linked_list_id directly on the row, not nested under row_config like the template
    design-time shape) - materialized that way by protocol_service when a Matrix/Table
    block is copied from its template onto a concrete protocol."""
    tenant_a = make_tenant(db, "Tenant A")
    source_list = make_list_definition(db, tenant_a.id, name="Leitende")
    source_entry = make_list_entry(db, source_list.id, column_one_value={"text_value": "Anna"})
    template = make_template(db, tenant_a.id)
    protocol = make_protocol(db, tenant_a.id, template.id, protocol_number="P-1")
    protocol_element = make_protocol_element(db, protocol.id)
    make_protocol_element_block(
        db, protocol_element.id,
        configuration_snapshot_json={
            "rows": [{
                "id": "1",
                "value_type": "list_entry",
                "linked_list_id": source_list.id,
                "linked_list_entry_id": source_entry.id,
            }],
        },
    )

    zip_path, _filename = TenantExportService().export(db, tenant_a.id, "full")
    try:
        new_tenant, _warnings = TenantImportService().import_zip(db, zip_path, "Tenant A (Import)")
    finally:
        zip_path.unlink(missing_ok=True)

    from app.models.entities import ListDefinition, ListEntry, ProtocolElement, ProtocolElementBlock

    imported_list = db.scalar(select(ListDefinition).where(ListDefinition.tenant_id == new_tenant.id))
    imported_entry = db.scalar(select(ListEntry).where(ListEntry.list_definition_id == imported_list.id))
    imported_protocol_id = db.scalar(select(Protocol.id).where(Protocol.tenant_id == new_tenant.id))
    imported_protocol_element_id = db.scalar(
        select(ProtocolElement.id).where(ProtocolElement.protocol_id == imported_protocol_id)
    )
    imported_block = db.scalar(
        select(ProtocolElementBlock).where(ProtocolElementBlock.protocol_element_id == imported_protocol_element_id)
    )
    row = imported_block.configuration_snapshot_json["rows"][0]
    assert row["linked_list_id"] == imported_list.id
    assert row["linked_list_entry_id"] == imported_entry.id
    assert row["linked_list_id"] != source_list.id
    assert row["linked_list_entry_id"] != source_entry.id


# --- verified custom domains travel with the export, same verification_token -----------
#
# TenantDomain (custom app/abgabebox domain + its verification_token/status/verified_at)
# was previously not exported at all - a tenant transfer silently dropped every domain the
# admin had already set up and verified, forcing them to redo DNS verification from
# scratch on the target installation even though the DNS TXT record still holds the exact
# same token.


def test_export_import_roundtrip_keeps_domain_and_same_verification_token(db, monkeypatch, tmp_path):
    from app.services import tenant_import_service as import_svc_module

    regenerate_calls = []
    monkeypatch.setattr(import_svc_module.traefik_config_service, "regenerate", lambda db: regenerate_calls.append(db))

    tenant_a = make_tenant(db, "Tenant A")
    domain = TenantDomain(
        tenant_id=tenant_a.id, purpose="app", domain="verein-a.example.com",
        verification_token="original-token-abc123", status="active",
    )
    db.add(domain)
    db.flush()
    original_token = domain.verification_token
    original_verified_at = domain.verified_at

    zip_path, _filename = TenantExportService().export(db, tenant_a.id, "structure")
    try:
        manifest = _read_manifest(zip_path)
        assert manifest["tables"]["tenant_domain"][0]["verification_token"] == original_token

        # Simulates importing onto a genuinely different installation, where this domain
        # isn't registered to anyone yet - `domain` is globally unique, so re-importing
        # while the source tenant (and its own domain row) is still around would otherwise
        # legitimately collide with itself; see
        # test_import_skips_domain_already_claimed_by_another_tenant_on_target for that case.
        db.delete(domain)
        db.flush()

        new_tenant, warnings = TenantImportService().import_zip(db, zip_path, "Tenant A (Import)")
    finally:
        zip_path.unlink(missing_ok=True)

    assert warnings == []
    imported_domain = db.scalar(select(TenantDomain).where(TenantDomain.tenant_id == new_tenant.id))
    assert imported_domain is not None
    assert imported_domain.domain == "verein-a.example.com"
    # Same verification code as the source - no re-verification needed, the DNS TXT record
    # the admin already set up still matches.
    assert imported_domain.verification_token == original_token
    assert imported_domain.status == "active"
    assert imported_domain.verified_at == original_verified_at
    # An imported *active* domain must trigger a Traefik config regeneration so the target
    # installation actually starts routing it.
    assert len(regenerate_calls) == 1


def test_import_skips_domain_already_claimed_by_another_tenant_on_target(db, monkeypatch):
    """`domain` is globally unique across the whole installation - if the exact domain is
    already registered to a DIFFERENT tenant already present on the target (e.g.
    re-importing an export while the source tenant still exists there), the row must be
    skipped with a warning rather than crashing the whole import on an IntegrityError."""
    from app.services import tenant_import_service as import_svc_module

    monkeypatch.setattr(import_svc_module.traefik_config_service, "regenerate", lambda db: None)

    tenant_a = make_tenant(db, "Tenant A")
    source_domain = TenantDomain(
        tenant_id=tenant_a.id, purpose="app", domain="taken.example.com",
        verification_token="tok-source", status="active",
    )
    db.add(source_domain)
    db.flush()

    zip_path, _filename = TenantExportService().export(db, tenant_a.id, "structure")
    try:
        # `domain` is globally unique - drop the source's own row and give the exact same
        # domain to a DIFFERENT tenant, simulating that it's already claimed on the target
        # installation by someone else entirely by the time this export is imported there.
        db.delete(source_domain)
        db.flush()
        existing_owner = make_tenant(db, "Existing Owner")
        db.add(TenantDomain(
            tenant_id=existing_owner.id, purpose="app", domain="taken.example.com",
            verification_token="tok-existing", status="active",
        ))
        db.flush()

        new_tenant, warnings = TenantImportService().import_zip(db, zip_path, "Tenant A (Import)")
    finally:
        zip_path.unlink(missing_ok=True)

    assert any("bereits vergeben" in w for w in warnings)
    assert db.scalar(select(TenantDomain).where(TenantDomain.tenant_id == new_tenant.id)) is None
    # The existing owner's domain row must be completely untouched.
    still_there = db.scalar(select(TenantDomain).where(TenantDomain.tenant_id == existing_owner.id))
    assert still_there is not None
    assert still_there.verification_token == "tok-existing"


def test_import_skips_domain_reserved_by_the_installation_itself(db, monkeypatch):
    from app.core.config import settings
    from app.services import tenant_import_service as import_svc_module

    monkeypatch.setattr(settings, "traefik_domain", "hocx.example.com")
    monkeypatch.setattr(import_svc_module.traefik_config_service, "regenerate", lambda db: None)

    tenant_a = make_tenant(db, "Tenant A")
    db.add(TenantDomain(
        tenant_id=tenant_a.id, purpose="app", domain="hocx.example.com",
        verification_token="tok-reserved", status="active",
    ))
    db.flush()

    zip_path, _filename = TenantExportService().export(db, tenant_a.id, "structure")
    try:
        new_tenant, warnings = TenantImportService().import_zip(db, zip_path, "Tenant A (Import)")
    finally:
        zip_path.unlink(missing_ok=True)

    assert any("selbst belegt" in w for w in warnings)
    assert db.scalar(select(TenantDomain).where(TenantDomain.tenant_id == new_tenant.id)) is None


# --- tenant.last_word_import_template_id must not carry a source-installation id --------
#
# Tenant.last_word_import_template_id is an FK to template.id. Importing it unchanged
# previously either crashed the whole import outright (no template with that id exists yet
# on a freshly created target tenant at the point _import_tenant_base commits, long before
# any template has been imported) or, on a coincidental id collision, silently pointed the
# new tenant at an unrelated template belonging to a completely different tenant.


def test_export_import_roundtrip_remaps_last_word_import_template_id(db):
    tenant_a = make_tenant(db, "Tenant A")
    template = make_template(db, tenant_a.id, name="Sitzungsprotokoll")
    tenant_a.last_word_import_template_id = template.id
    db.add(tenant_a)
    db.flush()

    zip_path, _filename = TenantExportService().export(db, tenant_a.id, "structure")
    try:
        # Must not raise an IntegrityError from a dangling/foreign template id.
        new_tenant, _warnings = TenantImportService().import_zip(db, zip_path, "Tenant A (Import)")
    finally:
        zip_path.unlink(missing_ok=True)

    imported_template = db.scalar(select(Template).where(Template.tenant_id == new_tenant.id))
    db.refresh(new_tenant)
    assert imported_template is not None
    assert imported_template.id != template.id
    assert new_tenant.last_word_import_template_id == imported_template.id
