"""Regression tests for TenantExportService/TenantImportService - previously zero test
coverage despite this being where a critical bug was found and fixed: exporting a tenant
used to bundle the REAL password_hash of users who were merely *referenced* (e.g. as
Template.created_by) by the exported tenant but were not actually members of it, leaking
another tenant's credentials to whoever received the export file. Users belong to exactly
one tenant now, so the export only ever contains the exported tenant's own users.

Covers:
- export bundles the tenant's own users (real password_hash, role as a code) and never a
  foreign tenant's user - a stray reference to one is exported as NULL
- on import a same-email account of another tenant is never linked or touched
- a version-2 archive (roles in a separate user_tenant_role table) still imports
- roundtrip export -> import: core entities (template, protocol, participant) reappear
  under the new tenant with fresh ids, correctly relinked
- import never touches a third, uninvolved tenant's data
- a corrupted archive (no manifest.json, or a zip-slip path) fails cleanly without leaving
  a half-imported tenant behind
- verified custom domains (tenant_domain) travel with the same verification_token/status,
  with global-uniqueness collisions on the target skipped (not crashed) and warned about
- tenant.last_word_import_template_id is remapped to the imported template's new id
  instead of crashing the import on a dangling source-installation id
- gallery_image (the "Fotos" gallery join table) is recreated pointing at the imported
  stored_file's new id
"""
from __future__ import annotations

import json
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.secret_crypto import decrypt_secret, encrypt_secret
from app.core.security import hash_password
from app.core.totp import generate_totp_secret
from app.models.entities import (
    AppUser,
    Event,
    GalleryImage,
    ListDefinition,
    ListEntry,
    Participant,
    PhotoAlbum,
    PhotoAlbumItem,
    Protocol,
    ProtocolElement,
    ProtocolElementBlock,
    DocumentExport,
    DocumentRegistry,
    DocumentAsset,
    DocumentBrand,
    DocumentComponent,
    DocumentTemplate,
    DocumentTemplateAssignment,
    DocumentTemplateRevision,
    ProtocolTodo,
    Role,
    StoredFile,
    SubmissionAssignment,
    SubmissionUploadLog,
    TableSnapshot,
    Template,
    Tenant,
    TenantDomain,
    TodoStatus,
    UserMfaFactor,
    UserProtocolScroll,
    WordImportDocument,
    WordImportProfile,
    WordImportSuggestionOutcome,
)
from app.services.tenant_export_service import TenantExportService
from app.services.tenant_import_service import TenantImportService
from app.services.tenant_transfer_common import (
    WordImportIdMaps,
    remap_word_import_analysis,
    remap_word_import_profile_config,
)
from tests.factories import (
    make_app_user,
    make_cycle_config,
    make_element_definition,
    make_event,
    make_list_definition,
    make_list_entry,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_todo,
    make_template,
    make_tenant,
)


def _read_manifest(zip_path: Path) -> dict:
    with zipfile.ZipFile(zip_path) as zf:
        return json.loads(zf.read("manifest.json").decode("utf-8"))


def _export_import(db, tenant_id: int, scope: str = "full", *, new_name: str = "Import", before_import=None):
    """Export -> (optional hook, e.g. to simulate a fresh target installation) -> import."""
    zip_path, _ = TenantExportService().export(db, tenant_id, scope)
    try:
        if before_import is not None:
            before_import(zip_path)
        return TenantImportService().import_zip(db, zip_path, new_name)
    finally:
        zip_path.unlink(missing_ok=True)


def _rewrite_manifest(zip_path: Path, mutate) -> None:
    manifest = _read_manifest(zip_path)
    mutate(manifest)
    with zipfile.ZipFile(zip_path) as zf:
        members = {name: zf.read(name) for name in zf.namelist() if name != "manifest.json"}
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for name, content in members.items():
            zf.writestr(name, content)


# --- export: own users only / foreign reference handling -----------------------


def test_export_bundles_only_own_users_and_nulls_foreign_references(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_foreign = make_tenant(db, "Tenant Foreign")

    member = make_app_user(db, email="member@a.example", password="member-real-password", tenant_id=tenant_a.id, role_code="writer")
    foreign_creator = make_app_user(
        db, email="foreign@x.example", password="foreign-real-password", tenant_id=tenant_foreign.id, role_code="admin"
    )

    template = make_template(db, tenant_a.id, name="Sitzungsprotokoll")
    template.created_by = foreign_creator.id
    db.add(template)
    db.flush()

    zip_path, _filename = TenantExportService().export(db, tenant_a.id, "full")
    try:
        manifest = _read_manifest(zip_path)
        app_users = {row["email"]: row for row in manifest["tables"]["app_user"]}

        # The tenant's own user travels with real hash and role code (so they can log in on
        # the target installation); the source's tenant id is dropped.
        assert app_users["member@a.example"]["password_hash"] == member.password_hash
        assert app_users["member@a.example"]["role_id"] == "writer"
        assert "tenant_id" not in app_users["member@a.example"]

        # Another tenant's user is not part of this export at all - neither credentials nor
        # email - and a reference to them is exported as NULL, not as their email.
        assert "foreign@x.example" not in app_users
        assert "foreign@x.example" not in json.dumps(manifest)
        assert manifest["tables"]["template"][0]["created_by"] is None
        assert "user_tenant_role" not in manifest["tables"]
        assert manifest["format_version"] == 7
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
    creator = make_app_user(db, email="word-import@example.com", tenant_id=tenant.id, role_code="writer")
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
        # Fresh target installation: the source account (which lives in the source tenant)
        # isn't there, so the import recreates it inside the new tenant.
        db.delete(creator)
        db.flush()
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
    restored_creator = db.scalar(select(AppUser).where(AppUser.email == "word-import@example.com"))
    assert restored_creator.tenant_id == new_tenant.id
    assert imported.created_by == restored_creator.id
    assert imported.imported_by == restored_creator.id
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
    user = make_app_user(db, email="backup@example.com", tenant_id=tenant.id, role_code="admin")
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
        DocumentExport(
            tenant_id=tenant.id, protocol_id=protocol.id, document_type="protocol", version_label="v0.1",
            content_hash="ab" * 32, stored_file_id=generated_file.id,
        ),
        DocumentRegistry(
            tenant_id=tenant.id, sha256="cd" * 32, document_type="protocol", title="Sitzung", status_code="abgeschlossen",
            version_major=1, version_minor=0, version_label="v1.0", source_public_id=protocol.public_id,
        ),
        UserProtocolScroll(user_id=user.id, protocol_id=protocol.id, last_element_id=17),
    ])
    db.flush()
    # Document Studio: Brand-Profil mit hochgeladenem Logo, Mandantenvorlage (Revision verweist
    # auf Logo und Protokoll), Komponente, Zuweisung für die Protokollvorlage
    from app.documents import brand_service, template_service
    from app.documents.brand import BrandTokens
    from app.documents.layout import TemplateContent

    logo_path = tmp_path / "document_assets" / "logo.png"
    logo_path.parent.mkdir(parents=True)
    logo_path.write_bytes(b"png-logo")
    logo = DocumentAsset(tenant_id=tenant.id, kind="image", category="logo", name="Logo", storage_path="document_assets/logo.png", mime_type="image/png")
    db.add(logo)
    db.flush()
    brand = brand_service.create_brand(db, tenant.id, name="Verein", tokens=BrandTokens.model_validate({"assets": {"logo": str(logo.public_id)}}), is_default=True)
    content = TemplateContent.model_validate({"masters": [{"id": "default"}], "body": [
        {"type": "image", "id": "i", "source": {"kind": "asset", "asset_id": str(logo.public_id)}},
        {"type": "data_block", "id": "d", "component": "session_notes", "params": {"protocol_id": str(protocol.public_id)}},
    ]})
    document_template, revision = template_service.create_template(db, tenant.id, name="Monatsbrief", document_type="custom", content=content)
    document_template.brand_id = brand.id
    template_service.publish(db, document_template, user_id=None)
    db.add(DocumentComponent(tenant_id=tenant.id, name="Kopf", schema_version=1, node_json={"type": "image", "id": "k", "source": {"kind": "asset", "asset_id": str(logo.public_id)}}))
    db.add(DocumentTemplateAssignment(tenant_id=tenant.id, document_type="protocol", protocol_template_id=template.id, brand_id=brand.id))
    # STUDIO-010: Export mit Systemvorlage und Brand-Revision behält beide Bezüge
    from app.documents.system_templates import sync_system_templates

    sync_system_templates(db)
    system_template = db.scalar(select(DocumentTemplate).where(DocumentTemplate.system_key == "protocol_standard"))
    db.add(DocumentExport(
        tenant_id=tenant.id, document_type="protocol", version_label="v0.2", content_hash="ef" * 32,
        template_id=system_template.id, brand_revision_id=brand_service.current_revision(db, brand).id,
    ))
    db.flush()

    zip_path, _ = TenantExportService().export(db, tenant.id, "full")
    try:
        manifest = _read_manifest(zip_path)
        assert len(manifest["tables"]["document_asset"]) == 1
        assert len(manifest["tables"]["document_brand"]) == 1 and len(manifest["tables"]["document_brand_revision"]) == 1
        assert len(manifest["tables"]["document_template"]) == 1 and len(manifest["tables"]["document_template_revision"]) == 1
        assert len(manifest["tables"]["document_component"]) == 1 and len(manifest["tables"]["document_template_assignment"]) == 1
        assert len(manifest["tables"]["word_import_profile"]) == 1
        assert len(manifest["tables"]["word_import_suggestion_outcome"]) == 1
        assert len(manifest["tables"]["document_export"]) == 2
        assert len(manifest["tables"]["document_registry"]) == 1
        assert manifest["tables"]["user_protocol_scroll"][0]["user_id"] == str(user.public_id)
        # Fresh target installation: the source account isn't there (see the word import test),
        # and neither is the source tenant's document registry.
        registry_id = db.scalar(select(DocumentRegistry.public_id).where(DocumentRegistry.tenant_id == tenant.id))
        db.query(DocumentRegistry).filter(DocumentRegistry.tenant_id == tenant.id).delete()
        db.delete(user)
        db.flush()
        imported_tenant, warnings = TenantImportService().import_zip(db, zip_path, "Complete Backup (Import)")
    finally:
        zip_path.unlink(missing_ok=True)

    imported_template = db.scalar(select(Template).where(Template.tenant_id == imported_tenant.id))
    imported_protocol = db.scalar(select(Protocol).where(Protocol.tenant_id == imported_tenant.id))
    profile = db.scalar(select(WordImportProfile).where(WordImportProfile.tenant_id == imported_tenant.id))
    outcome = db.scalar(select(WordImportSuggestionOutcome).where(WordImportSuggestionOutcome.tenant_id == imported_tenant.id))
    cache = db.scalar(select(DocumentExport).where(DocumentExport.protocol_id == imported_protocol.id))
    imported_brand = db.scalar(select(DocumentBrand).where(DocumentBrand.tenant_id == imported_tenant.id, DocumentBrand.name == "Verein"))
    imported_logo = db.scalar(select(DocumentAsset).where(DocumentAsset.tenant_id == imported_tenant.id))
    imported_document_template = db.scalar(select(DocumentTemplate).where(DocumentTemplate.tenant_id == imported_tenant.id))
    imported_assignment = db.scalar(select(DocumentTemplateAssignment).where(DocumentTemplateAssignment.tenant_id == imported_tenant.id))
    imported_component = db.scalar(select(DocumentComponent).where(DocumentComponent.tenant_id == imported_tenant.id))
    restored_user = db.scalar(select(AppUser).where(AppUser.email == "backup@example.com"))
    scroll = db.get(UserProtocolScroll, (restored_user.id, imported_protocol.id))

    assert warnings == []
    assert profile.template_id == imported_template.id
    assert profile.mapping_config_json == {"learned": {"source": "target"}}
    assert outcome.template_id == imported_template.id
    assert outcome.suggested_score == pytest.approx(0.87)
    assert cache.stored_file_id is not None and cache.version_label == "v0.1" and cache.content_hash == "ab" * 32
    assert db.get(StoredFile, cache.stored_file_id).tenant_id == imported_tenant.id
    assert (tmp_path / db.get(StoredFile, cache.stored_file_id).storage_path).read_bytes() == b"pdf-cache"
    assert imported_brand.is_default and imported_logo.category == "logo"
    assert brand_service.tokens_of(brand_service.current_revision(db, imported_brand)).assets.logo == imported_logo.public_id
    assert (tmp_path / imported_logo.storage_path).read_bytes() == b"png-logo"
    assert imported_document_template.brand_id == imported_brand.id
    published = db.get(DocumentTemplateRevision, imported_document_template.published_revision_id)
    assert published.status == "published"
    assert published.content_json["body"][0]["source"]["asset_id"] == str(imported_logo.public_id)
    assert published.content_json["body"][1]["params"]["protocol_id"] == str(imported_protocol.public_id)
    assert imported_assignment.protocol_template_id == imported_template.id and imported_assignment.brand_id == imported_brand.id
    assert imported_component.node_json["source"]["asset_id"] == str(imported_logo.public_id)
    system_export = db.scalar(select(DocumentExport).where(DocumentExport.tenant_id == imported_tenant.id, DocumentExport.version_label == "v0.2"))
    assert system_export.template_id == system_template.id
    assert system_export.brand_revision_id == brand_service.current_revision(db, imported_brand).id
    registry = db.scalar(select(DocumentRegistry).where(DocumentRegistry.tenant_id == imported_tenant.id))
    # Dokument-ID bleibt (sie steht im PDF), Quelle zeigt auf das importierte Protokoll
    assert registry.public_id == registry_id and registry.sha256 == "cd" * 32
    assert registry.status_code == "abgeschlossen" and registry.version_label == "v1.0"
    assert registry.source_public_id == imported_protocol.public_id
    assert scroll.last_element_id == 17


def test_import_skips_invalid_document_studio_content(db):
    """STUDIO-011: Ungültige Studio-Inhalte im Archiv werden beim Import geprüft und gemeldet
    statt erst Bibliothek und Export scheitern zu lassen."""
    from app.documents import brand_service, template_service
    from app.documents.layout import TemplateContent

    tenant = make_tenant(db, "Studio Invalid")
    brand = brand_service.create_brand(db, tenant.id, name="Verein", is_default=True)
    document_template, _revision = template_service.create_template(db, tenant.id, name="Gültig", document_type="custom", content=TemplateContent())
    broken_template, broken_revision = template_service.create_template(db, tenant.id, name="Kaputt", document_type="custom", content=TemplateContent())
    db.add(DocumentComponent(tenant_id=tenant.id, name="Kaputt", schema_version=1, node_json={"type": "script", "id": "x"}))
    db.flush()
    # Direkt in der DB verfälscht (Schema verhindert das sonst beim Speichern)
    broken_revision.content_json = {"body": [{"type": "script", "id": "x"}]}
    brand_service.current_revision(db, brand).tokens_json = {"colors": {"primary": "rot"}}
    db.flush()

    zip_path, _ = TenantExportService().export(db, tenant.id, "full")
    try:
        imported_tenant, warnings = TenantImportService().import_zip(db, zip_path, "Studio Invalid (Import)")
    finally:
        zip_path.unlink(missing_ok=True)

    assert any("Komponente 'Kaputt'" in item for item in warnings)
    assert any("Dokumentvorlage 'Kaputt'" in item for item in warnings)
    assert any("Brand-Revision" in item for item in warnings)
    assert db.scalar(select(DocumentComponent).where(DocumentComponent.tenant_id == imported_tenant.id)) is None
    templates = {row.name: row for row in db.scalars(select(DocumentTemplate).where(DocumentTemplate.tenant_id == imported_tenant.id))}
    assert template_service.working_revision(db, templates["Gültig"]) is not None
    assert template_service.working_revision(db, templates["Kaputt"]) is None
    imported_brand = db.scalar(select(DocumentBrand).where(DocumentBrand.tenant_id == imported_tenant.id, DocumentBrand.name == "Verein"))
    assert brand_service.current_revision(db, imported_brand).tokens_json["colors"]["primary"] == "#174B7A"


def test_export_import_roundtrip_restores_all_member_mfa_factors(db):
    tenant = make_tenant(db, "MFA Tenant")
    user = make_app_user(db, email="mfa-transfer@example.com", tenant_id=tenant.id, role_code="admin")
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


def test_import_never_links_to_an_account_of_another_tenant_with_the_same_email(db):
    """Importing into an installation where a same-email account already exists (here: the
    source tenant's own user, since the test imports into the same database) must neither
    link the new tenant's data to that account, move it, nor touch its credentials: it lives
    in another tenant. The reference is dropped and reported."""
    tenant_a = make_tenant(db, "Tenant A")
    creator = make_app_user(db, email="creator@shared.example", password="whatever", tenant_id=tenant_a.id, role_code="writer")
    original_hash = creator.password_hash
    template = make_template(db, tenant_a.id)
    template.created_by = creator.id
    db.add(template)
    db.flush()

    zip_path, _filename = TenantExportService().export(db, tenant_a.id, "full")
    try:
        new_tenant, warnings = TenantImportService().import_zip(db, zip_path, "Tenant A (Import)")
    finally:
        zip_path.unlink(missing_ok=True)

    imported_template = db.scalar(select(Template).where(Template.tenant_id == new_tenant.id))
    assert imported_template.created_by is None
    assert any("creator@shared.example" in warning and "anderen Mandanten" in warning for warning in warnings)
    db.refresh(creator)
    assert creator.tenant_id == tenant_a.id
    assert creator.password_hash == original_hash
    assert db.scalar(select(AppUser).where(AppUser.tenant_id == new_tenant.id)) is None


def test_import_creates_the_exported_users_in_the_new_tenant_on_a_fresh_installation(db):
    """The regular move/restore case: the exported email is unknown on the target, so the
    account is created inside the new tenant with its role and original password hash and
    references to it are relinked."""
    tenant_a = make_tenant(db, "Tenant A")
    creator = make_app_user(db, email="restorable@example.com", password="whatever", tenant_id=tenant_a.id, role_code="kassier")
    template = make_template(db, tenant_a.id)
    template.created_by = creator.id
    db.add(template)
    db.flush()

    zip_path, _filename = TenantExportService().export(db, tenant_a.id, "full")
    try:
        # Simulate the fresh target installation: the source account isn't there.
        db.delete(creator)
        db.flush()
        new_tenant, warnings = TenantImportService().import_zip(db, zip_path, "Tenant A (Import)")
    finally:
        zip_path.unlink(missing_ok=True)

    assert warnings == []
    restored = db.scalar(select(AppUser).where(AppUser.email == "restorable@example.com"))
    assert restored.tenant_id == new_tenant.id
    assert restored.password_hash == creator.password_hash
    assert db.get(Role, restored.role_id).code == "kassier"
    imported_template = db.scalar(select(Template).where(Template.tenant_id == new_tenant.id))
    assert imported_template.created_by == restored.id


def test_import_reads_version_2_archives_with_a_separate_user_tenant_role_table(db, tmp_path):
    archive = tmp_path / "v2.zip"
    manifest = {
        "format_version": 2,
        "scope": "structure",
        "tables": {
            "tenant": {"id": 7, "name": "Old Tenant"},
            "app_user": [
                {"id": 1, "email": "v2-member@example.com", "first_name": "V", "last_name": "Two", "display_name": "V Two",
                 "password_hash": hash_password("pw-v2-member"), "default_tenant_id": 7, "is_active": True},
                {"id": 2, "email": "v2-metadata@example.com", "first_name": "M", "last_name": "Only", "display_name": "M Only",
                 "password_hash": "REDACTED:not-a-tenant-member", "default_tenant_id": None, "is_active": True},
            ],
            "user_tenant_role": [{"user_id": "v2-member@example.com", "tenant_id": 7, "role_id": "admin", "is_active": True}],
        },
    }
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))

    new_tenant, _warnings = TenantImportService().import_zip(db, archive, "Imported v2")

    member = db.scalar(select(AppUser).where(AppUser.email == "v2-member@example.com"))
    assert member.tenant_id == new_tenant.id
    assert db.get(Role, member.role_id).code == "admin"
    # A user that was only referenced as metadata was never a member: no tenant to put them in.
    assert db.scalar(select(AppUser).where(AppUser.email == "v2-metadata@example.com")) is None


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
            "element_type_id": 11,
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
            "element_type_id": 6,
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


# --- gallery_image (the "Fotos" gallery join table) survives export/import --------------


def test_export_import_roundtrip_recreates_gallery_image(db, monkeypatch, tmp_path):
    from app.core.config import settings
    from app.services import tenant_import_service as import_svc_module

    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(import_svc_module.scanner, "scan_file", lambda path, host, port: "clean")

    tenant_a = make_tenant(db, "Tenant A")
    (tmp_path / "gallery").mkdir()
    (tmp_path / "gallery" / "photo.png").write_bytes(b"fake-png-bytes")
    stored_file = StoredFile(
        tenant_id=tenant_a.id, original_name="photo.png", mime_type="image/png",
        storage_path="gallery/photo.png", file_size_bytes=14,
    )
    db.add(stored_file)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_a.id, stored_file_id=stored_file.id))
    db.flush()

    zip_path, _filename = TenantExportService().export(db, tenant_a.id, "full")
    try:
        new_tenant, warnings = TenantImportService().import_zip(db, zip_path, "Tenant A (Import)")
    finally:
        zip_path.unlink(missing_ok=True)

    assert warnings == []
    imported_stored_file = db.scalar(select(StoredFile).where(StoredFile.tenant_id == new_tenant.id))
    assert imported_stored_file is not None
    assert imported_stored_file.id != stored_file.id

    imported_gallery_image = db.scalar(select(GalleryImage).where(GalleryImage.tenant_id == new_tenant.id))
    assert imported_gallery_image is not None
    assert imported_gallery_image.stored_file_id == imported_stored_file.id


def test_export_import_roundtrip_remaps_the_live_photo_clip(db, monkeypatch, tmp_path):
    """gallery_image.live_video_stored_file_id points at a second stored_file of the same tenant -
    it must follow that file's new id, not keep the exported one (stored_file.id is global)."""
    from app.core.config import settings
    from app.services import tenant_import_service as import_svc_module

    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(import_svc_module.scanner, "scan_file", lambda path, host, port: "clean")

    tenant_a = make_tenant(db, "Tenant A")
    (tmp_path / "gallery").mkdir()
    (tmp_path / "gallery" / "photo.jpg").write_bytes(b"fake-jpeg-bytes")
    (tmp_path / "gallery" / "photo.mp4").write_bytes(b"fake-mp4-bytes")
    photo = StoredFile(
        tenant_id=tenant_a.id, original_name="photo.jpg", mime_type="image/jpeg",
        storage_path="gallery/photo.jpg", file_size_bytes=15,
    )
    clip = StoredFile(
        tenant_id=tenant_a.id, original_name="photo.mp4", mime_type="video/mp4",
        storage_path="gallery/photo.mp4", file_size_bytes=14,
    )
    db.add_all([photo, clip])
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_a.id, stored_file_id=photo.id, live_video_stored_file_id=clip.id))
    db.flush()

    zip_path, _filename = TenantExportService().export(db, tenant_a.id, "full")
    try:
        new_tenant, warnings = TenantImportService().import_zip(db, zip_path, "Tenant A (Import)")
    finally:
        zip_path.unlink(missing_ok=True)

    assert warnings == []
    imported_clip = db.scalar(select(StoredFile).where(StoredFile.tenant_id == new_tenant.id, StoredFile.mime_type == "video/mp4"))
    imported_gallery_image = db.scalar(select(GalleryImage).where(GalleryImage.tenant_id == new_tenant.id))
    assert imported_clip is not None and imported_clip.id != clip.id
    assert imported_gallery_image.live_video_stored_file_id == imported_clip.id


def test_export_import_roundtrip_remaps_gallery_image_event_id(db, monkeypatch, tmp_path):
    """Regression test (2026-09-17 audit fix): _import_gallery_images used to pass
    event_id through unremapped, unlike every other imported table's event FK - since
    event.id is a global sequence, that either crashes the import on a stray FK violation
    or, worse, silently cross-links the imported photo to a same-numbered event belonging
    to a completely different tenant. A second, unrelated tenant with its own event whose
    internal id happens to be lower is created first here specifically so the source
    tenant's event does NOT land on id 1, the way a bug that forgot to remap could
    accidentally still "work" by coincidence in a near-empty test database."""
    from app.core.config import settings
    from app.services import tenant_import_service as import_svc_module

    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(import_svc_module.scanner, "scan_file", lambda path, host, port: "clean")

    other_tenant = make_tenant(db, "Other Tenant")
    make_event(db, other_tenant.id, title="Other Tenant's Event")

    tenant_a = make_tenant(db, "Tenant A")
    event = make_event(db, tenant_a.id, title="Tenant A's Event")
    (tmp_path / "gallery").mkdir()
    (tmp_path / "gallery" / "photo.png").write_bytes(b"fake-png-bytes")
    stored_file = StoredFile(
        tenant_id=tenant_a.id, original_name="photo.png", mime_type="image/png",
        storage_path="gallery/photo.png", file_size_bytes=14,
    )
    db.add(stored_file)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_a.id, stored_file_id=stored_file.id, event_id=event.id))
    db.flush()

    zip_path, _filename = TenantExportService().export(db, tenant_a.id, "full")
    try:
        new_tenant, warnings = TenantImportService().import_zip(db, zip_path, "Tenant A (Import)")
    finally:
        zip_path.unlink(missing_ok=True)

    assert warnings == []
    imported_event = db.scalar(select(Event).where(Event.tenant_id == new_tenant.id))
    assert imported_event is not None
    assert imported_event.id != event.id

    imported_gallery_image = db.scalar(select(GalleryImage).where(GalleryImage.tenant_id == new_tenant.id))
    assert imported_gallery_image is not None
    assert imported_gallery_image.event_id == imported_event.id


# --- links stored outside of plain FK columns (full-backup audit 2026-10-11) -----


def _storage(monkeypatch, tmp_path):
    from app.core.config import settings
    from app.services import tenant_import_service as import_module

    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "abgabebox_storage_root", str(tmp_path))
    monkeypatch.setattr(import_module.scanner, "scan_file", lambda *args, **kwargs: "clean")


def _stored_image(db, tmp_path, tenant_id: int, name: str = "photo.png") -> StoredFile:
    (tmp_path / name).write_bytes(b"fake-png-bytes")
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name=name, mime_type="image/png", storage_path=name, file_size_bytes=14,
    )
    db.add(stored_file)
    db.flush()
    return stored_file


def test_export_import_roundtrip_remaps_submission_assignment_cycle_filter(db):
    """submission_assignment.cycle_config_id used to be copied unchanged: the imported
    Abgabe pointed at the SOURCE tenant's Zyklus (and on a fresh installation the FK
    aborted the whole import)."""
    make_tenant(db, "Unrelated")  # pushes ids apart so a missing remap can't pass by luck
    tenant = make_tenant(db, "Abgaben")
    cycle = make_cycle_config(db, tenant.id, name="Vereinsjahr")
    db.add(SubmissionAssignment(
        tenant_id=tenant.id, title="Berichte", public_slug="berichte", source_type="events", tag_filter="lager",
        cycle_config_id=cycle.id, cycle_offsets=[0],
    ))
    db.flush()

    new_tenant, warnings = _export_import(db, tenant.id, "full_abgabebox")

    imported = db.scalar(select(SubmissionAssignment).where(SubmissionAssignment.tenant_id == new_tenant.id))
    from app.models.entities import CycleConfig

    imported_cycle = db.scalar(select(CycleConfig).where(CycleConfig.tenant_id == new_tenant.id))
    assert warnings == []
    assert imported.cycle_config_id == imported_cycle.id != cycle.id
    assert imported.cycle_offsets == [0]


def test_export_import_roundtrip_remaps_responsible_assignments_snapshot(db):
    """protocol_element.responsible_assignments_snapshot (the protocol's frozen
    Verantwortliche) embeds participant/list ids - it used to be copied verbatim."""
    make_tenant(db, "Unrelated")
    tenant = make_tenant(db, "Verantwortliche")
    participant = make_participant(db, tenant.id, "Anna")
    gone = make_participant(db, tenant.id, "Wird geloescht")
    definition = make_list_definition(db, tenant.id, column_one_value_type="participant")
    entry = make_list_entry(db, definition.id, column_one_value={"participant_id": participant.id})
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    element = make_protocol_element(db, protocol.id)
    element.responsible_assignments_snapshot = [
        {"participant_id": participant.id, "list_definition_id": definition.id, "list_entry_id": entry.id, "locked": True},
        {"participant_id": gone.id},
    ]
    db.flush()

    def drop_second_participant(zip_path):
        _rewrite_manifest(zip_path, lambda m: m["tables"].update(
            app_user=[row for row in m["tables"]["app_user"] if row["id"] != gone.id]
        ))

    new_tenant, _ = _export_import(db, tenant.id, before_import=drop_second_participant)

    new_participant = db.scalar(select(Participant).where(Participant.tenant_id == new_tenant.id))
    new_definition = db.scalar(select(ListDefinition).where(ListDefinition.tenant_id == new_tenant.id))
    new_entry = db.scalar(select(ListEntry).where(ListEntry.list_definition_id == new_definition.id))
    new_element = db.scalar(
        select(ProtocolElement).join(Protocol).where(Protocol.tenant_id == new_tenant.id)
    )
    # The unresolvable assignment is dropped instead of keeping a source-tenant id.
    assert new_element.responsible_assignments_snapshot == [
        {"participant_id": new_participant.id, "list_definition_id": new_definition.id, "list_entry_id": new_entry.id, "locked": True},
    ]


def test_export_import_roundtrip_remaps_block_repeat_sources(db):
    """configuration_snapshot_json.repeat_source_id binds a block to an Event or a
    ProtocolTodo (and writes back into it) - both used to keep the source id."""
    make_tenant(db, "Unrelated")
    tenant = make_tenant(db, "Wiederholen")
    event = make_event(db, tenant.id, title="Lager")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    element = make_protocol_element(db, protocol.id)
    todo_block = make_protocol_element_block(db, element.id, {}, sort_index=0, element_type_code="todo")
    todo = make_protocol_todo(db, todo_block.id, task="Material", tenant_id=tenant.id)
    make_protocol_element_block(
        db, element.id, {"repeat_source_type": "event", "repeat_source_id": event.id}, sort_index=1
    )
    make_protocol_element_block(
        db, element.id, {"repeat_source_type": "todo", "repeat_source_id": todo.id}, sort_index=2
    )

    new_tenant, warnings = _export_import(db, tenant.id)

    new_event = db.scalar(select(Event).where(Event.tenant_id == new_tenant.id))
    new_todo = db.scalar(select(ProtocolTodo).where(ProtocolTodo.tenant_id == new_tenant.id))
    blocks = db.scalars(
        select(ProtocolElementBlock).join(ProtocolElement).join(Protocol)
        .where(Protocol.tenant_id == new_tenant.id).order_by(ProtocolElementBlock.sort_index)
    ).all()
    assert warnings == []
    assert blocks[1].configuration_snapshot_json["repeat_source_id"] == new_event.id != event.id
    assert blocks[2].configuration_snapshot_json["repeat_source_id"] == new_todo.id != todo.id


def test_import_drops_unresolvable_event_participant_ids(db):
    tenant = make_tenant(db, "Termine")
    participant = make_participant(db, tenant.id, "Anna")
    event = make_event(db, tenant.id)
    event.participant_ids = [participant.id, 999_999_999]
    db.flush()

    new_tenant, _ = _export_import(db, tenant.id)

    new_participant = db.scalar(select(Participant).where(Participant.tenant_id == new_tenant.id))
    new_event = db.scalar(select(Event).where(Event.tenant_id == new_tenant.id))
    assert new_event.participant_ids == [new_participant.id]


def test_import_keeps_public_ids_on_a_fresh_installation(db, monkeypatch, tmp_path):
    """A restore onto an installation that doesn't know the tenant keeps every public_id,
    so links, bookmarks and public_id-based references (element_ref ...) stay valid."""
    _storage(monkeypatch, tmp_path)
    tenant = make_tenant(db, "Backup")
    event = make_event(db, tenant.id, title="Lager")
    participant = make_participant(db, tenant.id, "Anna")
    tenant_public_id, event_public_id, participant_public_id = tenant.public_id, event.public_id, participant.public_id

    def delete_source(_zip_path):
        db.delete(db.get(Tenant, tenant.id))
        db.flush()

    new_tenant, warnings = _export_import(db, tenant.id, before_import=delete_source)

    assert warnings == []
    assert new_tenant.public_id == tenant_public_id
    assert db.scalar(select(Event).where(Event.tenant_id == new_tenant.id)).public_id == event_public_id
    assert db.scalar(select(Participant).where(Participant.tenant_id == new_tenant.id)).public_id == participant_public_id


def test_import_rewrites_public_id_references_when_public_ids_are_taken(db, monkeypatch, tmp_path):
    """Re-importing while the source still exists: every public_id is taken, so each row
    gets a fresh one - and every reference stored by public_id (Abgabe element_ref on
    gallery images, upload logs and todos) has to follow, or it points at the source."""
    _storage(monkeypatch, tmp_path)
    tenant = make_tenant(db, "Abgabebox")
    event = make_event(db, tenant.id, title="Lager")
    assignment = SubmissionAssignment(
        tenant_id=tenant.id, title="Fotos", public_slug="fotos", source_type="events", tag_filter="lager",
    )
    db.add(assignment)
    stored_file = _stored_image(db, tmp_path, tenant.id)
    element_ref = f"event-{event.public_id}"
    db.add_all([
        GalleryImage(
            tenant_id=tenant.id, stored_file_id=stored_file.id,
            submission_assignment_id=assignment.id, submission_element_ref=element_ref,
        ),
        SubmissionUploadLog(assignment_id=assignment.id, element_ref=element_ref, status="success"),
    ])
    open_status_id = db.scalar(select(TodoStatus.id).where(TodoStatus.code == "open"))
    db.add(ProtocolTodo(
        tenant_id=tenant.id, task="Fotos hochladen", todo_status_id=open_status_id,
        submission_assignment_id=assignment.id, element_ref=element_ref,
    ))
    db.flush()

    new_tenant, warnings = _export_import(db, tenant.id, "full_abgabebox")

    new_event = db.scalar(select(Event).where(Event.tenant_id == new_tenant.id))
    new_ref = f"event-{new_event.public_id}"
    assert warnings == []
    assert new_event.public_id != event.public_id
    assert db.scalar(select(GalleryImage).where(GalleryImage.tenant_id == new_tenant.id)).submission_element_ref == new_ref
    assert db.scalar(
        select(SubmissionUploadLog).join(SubmissionAssignment).where(SubmissionAssignment.tenant_id == new_tenant.id)
    ).element_ref == new_ref
    assert db.scalar(select(ProtocolTodo).where(ProtocolTodo.tenant_id == new_tenant.id)).element_ref == new_ref


def test_export_import_roundtrip_restores_photo_albums(db, monkeypatch, tmp_path):
    """photo_album/photo_album_item used to be missing from the export entirely."""
    _storage(monkeypatch, tmp_path)
    tenant = make_tenant(db, "Fotos")
    cycle = make_cycle_config(db, tenant.id)
    photo = _stored_image(db, tmp_path, tenant.id)
    foreign_photo = _stored_image(db, tmp_path, make_tenant(db, "Partner").id, "partner.png")
    manual = PhotoAlbum(tenant_id=tenant.id, name="Highlights")
    by_cycle = PhotoAlbum(tenant_id=tenant.id, name="2026", kind="cycle", cycle_config_id=cycle.id, cycle_year=2026)
    db.add_all([manual, by_cycle])
    db.flush()
    db.add_all([
        PhotoAlbumItem(album_id=manual.id, file_id=photo.public_id, is_best=True, best_override="include"),
        PhotoAlbumItem(album_id=by_cycle.id, file_id=photo.public_id),
        # A partner tenant's photo in our (shared) album doesn't travel with our export.
        PhotoAlbumItem(album_id=manual.id, file_id=foreign_photo.public_id),
    ])
    db.flush()

    new_tenant, warnings = _export_import(db, tenant.id)

    new_photo = db.scalar(select(StoredFile).where(StoredFile.tenant_id == new_tenant.id))
    albums = {a.name: a for a in db.scalars(select(PhotoAlbum).where(PhotoAlbum.tenant_id == new_tenant.id))}
    from app.models.entities import CycleConfig

    new_cycle = db.scalar(select(CycleConfig).where(CycleConfig.tenant_id == new_tenant.id))
    assert warnings == []
    assert set(albums) == {"Highlights", "2026"}
    assert albums["2026"].cycle_config_id == new_cycle.id
    items = db.scalars(select(PhotoAlbumItem).where(PhotoAlbumItem.album_id == albums["Highlights"].id)).all()
    assert [(i.file_id, i.is_best, i.best_override) for i in items] == [(new_photo.public_id, True, "include")]
    assert db.scalar(select(PhotoAlbumItem.file_id).where(PhotoAlbumItem.album_id == albums["2026"].id)) == new_photo.public_id


def test_export_import_roundtrip_restores_table_snapshots(db):
    """Cycle snapshots of the Listen (table_snapshot) were missing from the export; their row
    copies carry list/participant ids and are remapped like live rows."""
    make_tenant(db, "Unrelated")
    tenant = make_tenant(db, "Snapshots")
    cycle = make_cycle_config(db, tenant.id)
    participant = make_participant(db, tenant.id, "Anna")
    definition = make_list_definition(db, tenant.id, column_one_value_type="participant")
    entry = make_list_entry(db, definition.id, column_one_value={"participant_id": participant.id})
    deleted_entry_row = {"id": 987_654, "public_id": "0190a000-0000-7000-8000-000000000001",
                         "list_definition_id": definition.id, "column_one_value_json": {}}
    db.add_all([
        TableSnapshot(tenant_id=tenant.id, cycle_config_id=cycle.id, cycle_year=2025, table_name="list_definition",
                      snapshot_json=[{"id": definition.id, "public_id": str(definition.public_id), "tenant_id": tenant.id}]),
        TableSnapshot(tenant_id=tenant.id, cycle_config_id=cycle.id, cycle_year=2025, table_name="list_entry",
                      snapshot_json=[
                          {"id": entry.id, "public_id": str(entry.public_id), "list_definition_id": definition.id,
                           "column_one_value_json": {"participant_id": participant.id}},
                          deleted_entry_row,
                      ]),
    ])
    db.flush()

    new_tenant, warnings = _export_import(db, tenant.id)

    new_definition = db.scalar(select(ListDefinition).where(ListDefinition.tenant_id == new_tenant.id))
    new_entry = db.scalar(select(ListEntry).where(ListEntry.list_definition_id == new_definition.id))
    new_participant = db.scalar(select(Participant).where(Participant.tenant_id == new_tenant.id))
    snapshots = {s.table_name: s for s in db.scalars(select(TableSnapshot).where(TableSnapshot.tenant_id == new_tenant.id))}
    assert warnings == []
    assert snapshots["list_definition"].snapshot_json == [
        {"id": new_definition.id, "public_id": str(new_definition.public_id), "tenant_id": new_tenant.id}
    ]
    live_row, deleted_row = snapshots["list_entry"].snapshot_json
    assert live_row == {
        "id": new_entry.id, "public_id": str(new_entry.public_id), "list_definition_id": new_definition.id,
        "column_one_value_json": {"participant_id": new_participant.id},
    }
    # A row deleted live since the snapshot keeps its identity, under a placeholder id that
    # can never collide with a real row.
    assert deleted_row["id"] == -987_654
    assert deleted_row["list_definition_id"] == new_definition.id


def test_import_drops_plan_unknown_on_target_instead_of_failing(db):
    tenant = make_tenant(db, "Plan")

    def unknown_plan(zip_path):
        _rewrite_manifest(zip_path, lambda m: m["tables"]["tenant"].update(plan_code="does-not-exist"))

    new_tenant, warnings = _export_import(db, tenant.id, before_import=unknown_plan)

    assert new_tenant.plan_code is None
    assert any("does-not-exist" in warning for warning in warnings)


_MAPS = WordImportIdMaps(
    participant_map={1: 101}, event_map={2: 102}, list_definition_map={3: 103},
    list_entry_map={4: 104}, template_element_map={5: 105}, protocol_map={6: 106},
)


def test_word_import_profile_config_is_remapped():
    config = {
        "heading_to_target": {"kurse": {"template_element_id": 5, "block_sort_index": 0}, "alt": {"template_element_id": 9}},
        "table_roles_by_signature": {"sig": {"role": "list", "list_definition_id": 3, "matrix_key": None},
                                     "m": {"role": "matrix", "list_definition_id": None, "matrix_key": "5:2"}},
        "participant_name_overrides": {"anna": 1, "fremd": 77, "total": None},
        "matrix_column_overrides": {"5:2:jungs": "gen-p-1", "5:2:fix": "col-a", "9:0:x": "col-b"},
        "rejected_candidates": {
            "event:2026-01-01|lager": {"rejected": [2, 88], "chosen": 2},
            "name:anna": {"rejected": [1], "chosen": None},
            "list_entry:3:zelt": {"rejected": [4], "chosen": 4},
            "matrix_column:5:2:jungs": {"rejected": ["gen-e-2"], "chosen": "col-a"},
            "table_role:sig": {"rejected": ["ignore"], "chosen": "list"},
        },
        "event_conflict_resolutions": {"2|lager": {"title_source": "doc"}, "88|weg": {"title_source": "doc"}},
        "new_event_link_resolutions": {"sitzung": {"linked_event_id": 2}},
        "event_ignored_keys": ["kategorie", "5:2:row1:gen-e-2:lager"],
        "no_link_names": ["total"],
    }

    result = remap_word_import_profile_config(config, _MAPS)

    assert result["heading_to_target"] == {"kurse": {"template_element_id": 105, "block_sort_index": 0}}
    assert result["table_roles_by_signature"] == {
        "sig": {"role": "list", "list_definition_id": 103, "matrix_key": None},
        "m": {"role": "matrix", "list_definition_id": None, "matrix_key": "105:2"},
    }
    assert result["participant_name_overrides"] == {"anna": 101, "total": None}
    assert result["matrix_column_overrides"] == {"105:2:jungs": "gen-p-101", "105:2:fix": "col-a"}
    assert result["rejected_candidates"] == {
        "event:2026-01-01|lager": {"rejected": [102], "chosen": 102},
        "name:anna": {"rejected": [101], "chosen": None},
        "list_entry:103:zelt": {"rejected": [104], "chosen": 104},
        "matrix_column:105:2:jungs": {"rejected": ["gen-e-102"], "chosen": "col-a"},
        "table_role:sig": {"rejected": ["ignore"], "chosen": "list"},
    }
    assert result["event_conflict_resolutions"] == {"102|lager": {"title_source": "doc"}}
    assert result["new_event_link_resolutions"] == {"sitzung": {"linked_event_id": 102}}
    assert result["event_ignored_keys"] == ["kategorie", "105:2:row1:gen-e-102:lager"]
    assert result["no_link_names"] == ["total"]


def test_word_import_analysis_is_remapped():
    name = {"raw_name": "Anna", "participant_id": 1, "originally_suggested_participant_id": 77,
            "candidates": [{"participant_id": 1}, {"participant_id": 77}]}
    analysis = {
        "tables": [{"index": 0, "list_definition_id": 3, "matrix_key": "5:0"}],
        "text_mappings": [{"template_element_id": 5, "matched_event_id": 2, "event_candidates": [{"event_id": 2}, {"event_id": 88}],
                           "form_fields": [{"names": [dict(name)]}], "form_fields_by_target": {"5:1": [{"names": []}], "9:0": []}}],
        "text_targets": [{"template_element_id": 5}, {"template_element_id": 9}],
        "attendance_mappings": [{"suggested_participant_id": 1, "candidates": [{"participant_id": 1}]}],
        "event_mappings": [{"matched_event_id": 2, "candidates": [{"event_id": 2}], "matrix_key": "5:0", "column_key": "gen-e-2"}],
        "list_definitions": [{"id": 3, "name": "Material"}, {"id": 99, "name": "Fremd"}],
        "list_mappings": [{"matched_entry_id": 4, "column_one_names": [dict(name)], "column_two_names": [], "candidates": [{"entry_id": 4}]}],
        "matrix_options": [{"matrix_key": "5:0"}, {"matrix_key": "9:0"}],
        "matrix_mappings": [{"matrix_key": "5:0", "column_key": "gen-l-4", "column_candidates": [{"column_key": "gen-p-77"}, {"column_key": "fix"}], "names": []},
                            {"matrix_key": "9:9", "names": []}],
        "duplicate_protocols": [{"id": 6}, {"id": 66}],
    }

    result = remap_word_import_analysis(analysis, _MAPS)

    remapped_name = {"raw_name": "Anna", "participant_id": 101, "originally_suggested_participant_id": None, "candidates": [{"participant_id": 101}]}
    assert result["tables"] == [{"index": 0, "list_definition_id": 103, "matrix_key": "105:0"}]
    text = result["text_mappings"][0]
    assert (text["template_element_id"], text["matched_event_id"], text["event_candidates"]) == (105, 102, [{"event_id": 102}])
    assert text["form_fields"] == [{"names": [remapped_name]}]
    assert text["form_fields_by_target"] == {"105:1": [{"names": []}]}
    assert result["text_targets"] == [{"template_element_id": 105}]
    assert result["attendance_mappings"] == [{"suggested_participant_id": 101, "candidates": [{"participant_id": 101}]}]
    assert result["event_mappings"] == [{"matched_event_id": 102, "candidates": [{"event_id": 102}], "matrix_key": "105:0", "column_key": "gen-e-102"}]
    assert result["list_definitions"] == [{"id": 103, "name": "Material"}]
    assert result["list_mappings"][0]["matched_entry_id"] == 104
    assert result["list_mappings"][0]["column_one_names"] == [remapped_name]
    assert result["list_mappings"][0]["candidates"] == [{"entry_id": 104}]
    assert result["matrix_options"] == [{"matrix_key": "105:0"}]
    assert result["matrix_mappings"] == [{"matrix_key": "105:0", "column_key": "gen-l-104", "column_candidates": [{"column_key": "fix"}], "names": []}]
    assert result["duplicate_protocols"] == [{"id": 106}]


# --- links, subscriptions, partner relations, tenant settings (full backup) ---------


def _delete_tenant(db, tenant_id: int):
    """Simulates restoring onto an installation where the tenant doesn't exist (anymore)."""
    from sqlalchemy import delete

    def hook(_zip_path):
        db.execute(delete(Tenant).where(Tenant.id == tenant_id))
        db.flush()

    return hook


def _make_submission_link(db, tenant_id: int, assignment_id: int, *, name: str, token: str):
    from app.models.entities import SubmissionLink
    from app.services import submission_link_service

    link = SubmissionLink(tenant_id=tenant_id, name=name, token=token, is_default=name == "Standard")
    db.add(link)
    db.flush()
    submission_link_service.attach_assignments(db, link, [assignment_id])
    db.flush()
    return link


def test_full_backup_restores_abgabebox_links_with_their_tokens(db):
    from app.models.entities import SubmissionLink, submission_assignment_link_table

    tenant = make_tenant(db, "Links")
    assignment = SubmissionAssignment(tenant_id=tenant.id, title="Berichte", public_slug="berichte", source_type="manual")
    db.add(assignment)
    db.flush()
    _make_submission_link(db, tenant.id, assignment.id, name="Standard", token="token-standard-123")
    _make_submission_link(db, tenant.id, assignment.id, name="Leiter", token="token-leiter-456")

    new_tenant, warnings = _export_import(db, tenant.id, "full_abgabebox", before_import=_delete_tenant(db, tenant.id))

    links = {link.name: link for link in db.scalars(select(SubmissionLink).where(SubmissionLink.tenant_id == new_tenant.id))}
    new_assignment = db.scalar(select(SubmissionAssignment).where(SubmissionAssignment.tenant_id == new_tenant.id))
    attached = set(db.scalars(
        select(submission_assignment_link_table.c.link_id).where(submission_assignment_link_table.c.assignment_id == new_assignment.id)
    ))
    assert warnings == []
    assert {name: link.token for name, link in links.items()} == {"Standard": "token-standard-123", "Leiter": "token-leiter-456"}
    assert links["Standard"].is_default is True
    assert attached == {links["Standard"].id, links["Leiter"].id}


def test_reimport_on_same_installation_never_reuses_a_link_token(db):
    """While the source tenant still exists, its tokens are its credentials - the copy gets
    fresh ones (and a warning), never a second tenant behind the same URL."""
    from app.models.entities import SubmissionLink

    tenant = make_tenant(db, "Links")
    assignment = SubmissionAssignment(tenant_id=tenant.id, title="Berichte", public_slug="berichte", source_type="manual")
    db.add(assignment)
    db.flush()
    _make_submission_link(db, tenant.id, assignment.id, name="Standard", token="token-standard-123")

    new_tenant, warnings = _export_import(db, tenant.id, "full_abgabebox")

    new_link = db.scalar(select(SubmissionLink).where(SubmissionLink.tenant_id == new_tenant.id))
    assert new_link.token != "token-standard-123"
    assert any("Token" in warning for warning in warnings)


def test_full_backup_restores_share_links_and_calendar_feeds(db, monkeypatch, tmp_path):
    from app.models.entities import CalendarFeed, ShareLink, ShareLinkFile
    from app.services import calendar_feed_service

    _storage(monkeypatch, tmp_path)
    tenant = make_tenant(db, "Freigaben")
    user = make_app_user(db, email="feed@example.com", tenant_id=tenant.id, role_code="admin")
    photo = _stored_image(db, tmp_path, tenant.id)
    album = PhotoAlbum(tenant_id=tenant.id, name="Lager")
    db.add(album)
    db.flush()
    album_link = ShareLink(tenant_id=tenant.id, name="Album", token="share-album-token", album_id=album.id, created_by=user.id)
    file_link = ShareLink(tenant_id=tenant.id, name="Auswahl", token="share-file-token")
    db.add_all([album_link, file_link])
    db.flush()
    db.add(ShareLinkFile(share_link_id=file_link.id, file_id=photo.public_id))
    db.add(CalendarFeed(
        tenant_id=tenant.id, user_id=user.id, kind="events", calendar_name="Termine",
        token_hash=calendar_feed_service.hash_token("feed-token"),
        token_encrypted=__import__("app.core.secret_crypto", fromlist=["encrypt_secret"]).encrypt_secret("feed-token"),
    ))
    db.flush()
    album_id, album_link_id = album.id, album_link.id

    new_tenant, warnings = _export_import(db, tenant.id, before_import=_delete_tenant(db, tenant.id))

    links = {link.name: link for link in db.scalars(select(ShareLink).where(ShareLink.tenant_id == new_tenant.id))}
    new_user = db.scalar(select(AppUser).where(AppUser.email == "feed@example.com"))
    new_photo = db.scalar(select(StoredFile).where(StoredFile.tenant_id == new_tenant.id))
    feed = db.scalar(select(CalendarFeed).where(CalendarFeed.tenant_id == new_tenant.id))
    assert warnings == []
    # Same ids and tokens: every handed-out URL keeps working after the restore.
    assert links["Album"].token == "share-album-token"
    assert links["Album"].id == album_link_id and links["Album"].album_id == album_id
    assert links["Album"].created_by == new_user.id
    assert db.scalar(select(ShareLinkFile.file_id).where(ShareLinkFile.share_link_id == links["Auswahl"].id)) == new_photo.public_id
    assert feed.user_id == new_user.id
    assert feed.token_hash == calendar_feed_service.hash_token("feed-token")
    assert calendar_feed_service.token_of(feed) == "feed-token"


def test_full_backup_restores_features_storage_packages_and_partner_relations(db, monkeypatch, tmp_path):
    from app.core.security import hash_password
    from app.models.entities import (
        Feature,
        PhotoAlbumTenantShare,
        PlatformAdmin,
        StoragePackage,
        TenantFeature,
        TenantStoragePackage,
        TenantTrust,
    )
    from app.services import tenant_trust_service

    _storage(monkeypatch, tmp_path)
    admin = PlatformAdmin(email="ops@example.com", password_hash=hash_password("x"), display_name="Ops")
    package = StoragePackage(code="test-10gb", name="10 GB", bytes=10 * 1024**3)
    db.add_all([admin, package])
    db.flush()
    feature_code = db.scalar(select(Feature.code).limit(1))
    tenant = make_tenant(db, "Verein")
    partner = make_tenant(db, "Partnerverein")
    db.add_all([
        TenantFeature(tenant_id=tenant.id, feature_code=feature_code, enabled_by_admin_id=admin.id),
        TenantStoragePackage(tenant_id=tenant.id, package_code="test-10gb", quantity=2, added_by_admin_id=admin.id),
    ])
    tenant_trust_service.establish(db, tenant.id, partner.id)
    own_album = PhotoAlbum(tenant_id=tenant.id, name="Unser Album")
    partner_album = PhotoAlbum(tenant_id=partner.id, name="Partner-Album")
    db.add_all([own_album, partner_album])
    db.flush()
    our_photo = _stored_image(db, tmp_path, tenant.id)
    db.add_all([
        PhotoAlbumTenantShare(album_id=own_album.id, tenant_id=partner.id, status="accepted"),
        PhotoAlbumTenantShare(album_id=partner_album.id, tenant_id=tenant.id, status="accepted"),
        PhotoAlbumItem(album_id=partner_album.id, file_id=our_photo.public_id),
    ])
    db.flush()
    own_album_id, partner_album_id = own_album.id, partner_album.id

    new_tenant, warnings = _export_import(db, tenant.id, before_import=_delete_tenant(db, tenant.id))

    feature = db.scalar(select(TenantFeature).where(TenantFeature.tenant_id == new_tenant.id))
    storage = db.scalar(select(TenantStoragePackage).where(TenantStoragePackage.tenant_id == new_tenant.id))
    new_photo = db.scalar(select(StoredFile).where(StoredFile.tenant_id == new_tenant.id))
    assert (feature.feature_code, feature.enabled_by_admin_id) == (feature_code, admin.id)
    assert (storage.package_code, storage.quantity, storage.added_by_admin_id) == ("test-10gb", 2, admin.id)
    low, high = sorted((new_tenant.id, partner.id))
    assert db.get(TenantTrust, (low, high)) is not None
    assert db.get(PhotoAlbumTenantShare, (own_album_id, partner.id)).status == "accepted"
    assert db.get(PhotoAlbumTenantShare, (partner_album_id, new_tenant.id)).status == "accepted"
    assert db.get(PhotoAlbumItem, (partner_album_id, new_photo.public_id)) is not None
    # Restored relations to other tenants are surfaced to the importing admin.
    assert any("Partnerverein" in warning for warning in warnings)


def test_import_skips_partner_relations_when_partner_is_missing(db):
    from app.models.entities import TenantTrust
    from app.services import tenant_trust_service

    tenant = make_tenant(db, "Verein")
    partner = make_tenant(db, "Partnerverein")
    tenant_trust_service.establish(db, tenant.id, partner.id)
    db.flush()

    new_tenant, warnings = _export_import(db, tenant.id, before_import=_delete_tenant(db, partner.id))

    assert db.scalar(
        select(TenantTrust).where((TenantTrust.tenant_low_id == new_tenant.id) | (TenantTrust.tenant_high_id == new_tenant.id))
    ) is None
    assert any("Vertrauensbeziehung" in warning for warning in warnings)


def test_import_keeps_registry_with_original_and_never_imports_identity_verification(db):
    """Ein Archiv, das in dieselbe Installation zurückgespielt wird: der Hash gehört weiter dem
    Original (Eintrag übersprungen, Warnung). Die Bestätigung der Organisation durch hocX reist nie
    mit - auch nicht, wenn ein (manipuliertes) Archiv sie behauptet."""
    tenant = make_tenant(db, "Registerverein")
    tenant.identity_verified_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tenant.identity_verification_note = "Handelsregister geprüft"
    tenant.verify_show_identity = True
    db.add(DocumentRegistry(tenant_id=tenant.id, sha256="ef" * 32, document_type="todos", title="Pendenzen"))
    db.flush()

    zip_path, _ = TenantExportService().export(db, tenant.id, "full")
    try:
        imported_tenant, warnings = TenantImportService().import_zip(db, zip_path, "Registerverein (Kopie)")
    finally:
        zip_path.unlink(missing_ok=True)

    assert db.scalar(select(DocumentRegistry.tenant_id).where(DocumentRegistry.sha256 == "ef" * 32)) == tenant.id
    assert db.scalar(select(DocumentRegistry).where(DocumentRegistry.tenant_id == imported_tenant.id)) is None
    assert any("Dokumentenregister: 1 Einträge übersprungen" in warning for warning in warnings)
    assert imported_tenant.identity_verified_at is None and imported_tenant.identity_verification_note is None
    assert imported_tenant.verify_show_identity is True


def test_import_converts_house_styles_and_recipes_of_format_6_archives(db, tmp_path):
    """Archive der Dokument-Engine vor dem Document Studio: Hausstil → Brand-Profil (Standard
    bleibt Standard), Rezept → veröffentlichte Mandantenvorlage, Hausstil der Protokollvorlage →
    Brand-Zuweisung."""
    import zipfile

    from app.documents import brand_service

    manifest = {
        "format_version": 6,
        "scope": "structure",
        "tables": {
            "tenant": {"id": 1, "name": "Altarchiv"},
            "document_style": [
                {"id": 10, "tenant_id": 1, "name": "Standard", "style_key": "classic", "tokens_json": {"primary_color": "#a83f2f", "title_page": "modern"}, "is_default": True, "version": 1},
                {"id": 11, "tenant_id": 1, "name": "Jugend", "style_key": "compact", "tokens_json": {}, "is_default": False, "version": 1},
            ],
            "document_recipe": [{"id": 5, "tenant_id": 1, "name": "Monatsbrief", "document_type": "custom", "blocks_json": [{"type": "heading", "params": {"text": "Hallo"}}], "options_json": {}, "style_id": 11}],
            "template": [{"id": 3, "tenant_id": 1, "name": "Jugendvorstand", "status": "active", "version": 1, "document_style_id": 11}],
        },
    }
    zip_path = tmp_path / "alt.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
    imported_tenant, warnings = TenantImportService().import_zip(db, zip_path, "Altarchiv (Import)")

    brands = {brand.name: brand for brand in db.scalars(select(DocumentBrand).where(DocumentBrand.tenant_id == imported_tenant.id))}
    assert set(brands) == {"Standard", "Jugend"} and brands["Standard"].is_default
    tokens = brand_service.tokens_of(brand_service.current_revision(db, brands["Standard"]))
    assert tokens.colors.primary == "#A83F2F" and tokens.layout.title_page
    recipe_template = db.scalar(select(DocumentTemplate).where(DocumentTemplate.tenant_id == imported_tenant.id))
    assert recipe_template.name == "Monatsbrief" and recipe_template.published_revision_id and recipe_template.brand_id == brands["Jugend"].id
    assignment = db.scalar(select(DocumentTemplateAssignment).where(DocumentTemplateAssignment.tenant_id == imported_tenant.id))
    assert assignment.brand_id == brands["Jugend"].id and assignment.document_type == "protocol"
