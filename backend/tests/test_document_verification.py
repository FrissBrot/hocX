"""Öffentliche Prüfung (Migration 0117): Die Freigabelogik steckt in der View
document_verification_public, die restricted Rolle hocx_abgabebox darf nur die Funktion
verify_document() aufrufen - weder Register noch View lesen."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.models import DocumentRegistry
from tests.factories import make_tenant

ROLE = "hocx_abgabebox"


def _entry(db, tenant, sha_char: str, *, document_type="protocol", source=None, version=(0, 1), status="durchgeführt"):
    entry = DocumentRegistry(
        tenant_id=tenant.id, sha256=sha_char * 64, document_type=document_type, title=f"Dokument {sha_char}",
        status_code=status if document_type == "protocol" else None,
        version_major=version[0] if version else None, version_minor=version[1] if version else None,
        version_label=f"v{version[0]}.{version[1]}" if version else None, source_public_id=source,
    )
    db.add(entry)
    db.flush()
    return entry


def _verify(db, sha256: str):
    """Ruft die Funktion als restricted Rolle auf (in einem Savepoint, der zurückgesetzt wird)."""
    savepoint = db.begin_nested()
    try:
        db.execute(text(f"SET LOCAL ROLE {ROLE}"))
        return db.execute(text("SELECT * FROM verify_document(:sha)"), {"sha": sha256}).mappings().first()
    finally:
        savepoint.rollback()
        db.execute(text("RESET ROLE"))


@pytest.fixture
def setup(db):
    tenant = make_tenant(db, "Prüfverein")
    other = make_tenant(db, "Anderer Verein")
    protocol = uuid.uuid4()
    entries = {
        "v01": _entry(db, tenant, "1", source=protocol, version=(0, 1)),
        "v02": _entry(db, tenant, "2", source=protocol, version=(0, 2)),
        "v02_again": _entry(db, tenant, "3", source=protocol, version=(0, 2)),
        "todos": _entry(db, tenant, "4", document_type="todos", version=None),
        "foreign_same_protocol_id": _entry(db, other, "5", source=protocol, version=(1, 0)),
    }
    return tenant, other, entries


def test_identity_only_with_tenant_consent_and_badge_only_with_admin_confirmation(db, setup):
    tenant, _, entries = setup
    tenant.identity_verified_at = datetime.now(UTC)
    db.flush()

    row = _verify(db, entries["todos"].sha256)
    assert row["document_id"] == entries["todos"].public_id and row["title"] == "Dokument 4"
    assert row["tenant_name"] is None and row["tenant_public_id"] is None and row["tenant_has_logo"] is None
    assert row["organization_verified"] is False  # bestätigt, aber Anzeige nicht freigegeben

    tenant.verify_show_identity = True
    tenant.identity_verified_at = None
    db.flush()
    row = _verify(db, entries["todos"].sha256)
    assert row["tenant_name"] == "Prüfverein" and row["tenant_public_id"] == tenant.public_id
    assert row["tenant_has_logo"] is False and row["organization_verified"] is False

    tenant.identity_verified_at = datetime.now(UTC)
    db.flush()
    assert _verify(db, entries["todos"].sha256)["organization_verified"] is True


def test_newer_version_only_for_protocols_and_only_when_allowed(db, setup):
    tenant, _, entries = setup
    first = _verify(db, entries["v01"].sha256)
    assert first["is_superseded"] is True and first["latest_version_label"] == "v0.2"
    # gleiche Version neu gerendert ist nicht «neuer»
    assert _verify(db, entries["v02"].sha256)["is_superseded"] is False
    assert _verify(db, entries["v02_again"].sha256)["is_superseded"] is False
    # andere Dokumenttypen haben keine Version
    assert _verify(db, entries["todos"].sha256)["is_superseded"] is None
    # Mandanten-Isolation: v1.0 desselben Quell-IDs beim anderen Mandanten zählt nicht
    assert first["latest_version_label"] == "v0.2"

    tenant.verify_show_newer_version = False
    db.flush()
    hidden = _verify(db, entries["v01"].sha256)
    assert hidden["is_superseded"] is None and hidden["latest_version_label"] is None


def test_unknown_or_malformed_hash_returns_nothing(db, setup):
    assert _verify(db, "f" * 64) is None
    assert _verify(db, "1" * 63) is None
    assert _verify(db, ("1" * 63) + "G") is None
    assert _verify(db, "' OR 1=1 --") is None


@pytest.mark.parametrize("statement", [
    "SELECT * FROM document_registry LIMIT 1",
    "SELECT * FROM document_verification_public LIMIT 1",
    "SELECT verify_show_identity FROM tenant LIMIT 1",
    "SELECT name FROM tenant LIMIT 1",
    "SELECT billing_note FROM tenant LIMIT 1",
])
def test_restricted_role_cannot_read_registry_view_or_settings(db, setup, statement):
    savepoint = db.begin_nested()
    try:
        db.execute(text(f"SET LOCAL ROLE {ROLE}"))
        with pytest.raises(ProgrammingError, match="permission denied"):
            db.execute(text(statement))
    finally:
        savepoint.rollback()
        db.execute(text("RESET ROLE"))


def test_other_restricted_roles_cannot_call_the_function(db, setup):
    _, _, entries = setup
    savepoint = db.begin_nested()
    try:
        db.execute(text("SET LOCAL ROLE hocx_photo_worker"))
        with pytest.raises(ProgrammingError, match="permission denied"):
            db.execute(text("SELECT * FROM verify_document(:sha)"), {"sha": entries["todos"].sha256})
    finally:
        savepoint.rollback()
        db.execute(text("RESET ROLE"))


def test_restricted_role_still_reads_the_columns_the_abgabebox_needs(db, setup):
    tenant, _, _ = setup
    savepoint = db.begin_nested()
    try:
        db.execute(text(f"SET LOCAL ROLE {ROLE}"))
        row = db.execute(text("SELECT id, storage_quota_bytes FROM tenant WHERE id = :id"), {"id": tenant.id}).one()
        assert row.id == tenant.id
    finally:
        savepoint.rollback()
        db.execute(text("RESET ROLE"))
