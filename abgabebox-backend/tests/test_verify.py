"""Öffentliche Echtheitsprüfung (POST /api/public/verify).

Die Semantik der Freigaben (Name/Logo/Abzeichen/neuere Version) prüft backend/tests/
test_document_verification.py direkt gegen die View/Funktion. Hier: Eingabeprüfung, Antwortform
(kein ID-Leak bei found=false), Vergleich der Dokument-ID und - gegen die echte Test-DB mit der
restricted Rolle - dass nur die Funktion erreichbar ist.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import repository
from app.db import SessionLocal
from app.main import app

client = TestClient(app)
ORIGINAL = b"%PDF-1.7 hocX original"
SHA = hashlib.sha256(ORIGINAL).hexdigest()
DOC_ID = uuid.uuid4()
TENANT_ID = uuid.uuid4()


def _row(**overrides):
    row = {
        "document_id": DOC_ID, "document_type": "protocol", "title": "Vorstandssitzung", "status_code": "abgeschlossen",
        "version_label": "v1.2", "created_at": datetime(2026, 5, 1, tzinfo=UTC), "is_superseded": True,
        "latest_version_label": "v1.3", "tenant_name": "Musterverein", "tenant_public_id": TENANT_ID,
        "tenant_has_logo": True, "organization_verified": True,
    }
    row.update(overrides)
    return row


@pytest.fixture
def registry(monkeypatch):
    rows = {SHA: _row()}
    monkeypatch.setattr(repository, "verify_document", lambda db, *, sha256: rows.get(sha256))
    return rows


def test_original_is_found_with_released_fields(registry):
    response = client.post("/api/public/verify", json={"sha256": SHA})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    body = response.json()
    assert body["found"] is True and body["document_id"] == str(DOC_ID)
    assert body["is_superseded"] is True and body["latest_version_label"] == "v1.3"
    assert body["tenant_name"] == "Musterverein" and body["organization_verified"] is True
    assert "document_id_matches" not in body


def test_one_changed_byte_is_not_found(registry):
    changed = bytearray(ORIGINAL)
    changed[-1] ^= 0x01
    response = client.post("/api/public/verify", json={"sha256": hashlib.sha256(bytes(changed)).hexdigest(), "document_id": str(DOC_ID)})
    # Kein Hinweis, ob die mitgeschickte (existierende) Dokument-ID bekannt ist
    assert response.json() == {"found": False}


def test_document_id_from_another_qr_code(registry):
    assert client.post("/api/public/verify", json={"sha256": SHA, "document_id": str(DOC_ID)}).json()["document_id_matches"] is True
    other = client.post("/api/public/verify", json={"sha256": SHA, "document_id": str(uuid.uuid4())}).json()
    assert other["found"] is True and other["document_id_matches"] is False


def test_fields_not_released_by_the_tenant_are_absent(registry):
    registry[SHA] = _row(tenant_name=None, tenant_public_id=None, tenant_has_logo=None, organization_verified=False, is_superseded=None, latest_version_label=None)
    body = client.post("/api/public/verify", json={"sha256": SHA}).json()
    assert "tenant_name" not in body and "tenant_public_id" not in body and "is_superseded" not in body
    assert body["organization_verified"] is False


@pytest.mark.parametrize("payload", [
    {"sha256": SHA.upper()},
    {"sha256": SHA[:-1]},
    {"sha256": SHA + "0"},
    {"sha256": "g" * 64},
    {"sha256": SHA, "document_id": "kein-uuid"},
    {"sha256": SHA, "extra": 1},
    {},
])
def test_invalid_input_is_rejected_before_any_lookup(monkeypatch, payload):
    monkeypatch.setattr(repository, "verify_document", lambda *a, **k: pytest.fail("darf nicht abgefragt werden"))
    assert client.post("/api/public/verify", json=payload).status_code == 422


def test_restricted_role_reaches_only_the_function():
    """Gegen die echte Test-DB als hocx_abgabebox: unbekannter Hash ergibt keine Zeile, das
    Register und die View sind nicht lesbar."""
    db = SessionLocal()
    try:
        assert repository.verify_document(db, sha256="0" * 64) is None
        for statement in ("SELECT 1 FROM document_registry LIMIT 1", "SELECT 1 FROM document_verification_public LIMIT 1"):
            with pytest.raises(Exception, match="permission denied"):
                db.execute(text(statement))
            db.rollback()
    finally:
        db.close()


def test_verify_domain_of_the_issuer_is_passed_on(registry):
    registry[SHA] = _row(verify_domain="verify.musterverein.ch")
    assert client.post("/api/public/verify", json={"sha256": SHA}).json()["verify_domain"] == "verify.musterverein.ch"
    registry[SHA] = _row(verify_domain=None)
    assert "verify_domain" not in client.post("/api/public/verify", json={"sha256": SHA}).json()


def test_verify_site_for_a_tenant_verify_domain(monkeypatch):
    seen = {}

    def fake_site(db, *, domain):
        seen["domain"] = domain
        return {"domain": domain, "tenant_name": "Musterverein", "tenant_public_id": TENANT_ID, "tenant_has_logo": False, "organization_verified": True}

    monkeypatch.setattr(repository, "verify_site", fake_site)
    response = client.get("/api/public/verify/site", params={"domain": "Verify.Musterverein.ch:443"})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    body = response.json()
    # Port und Grossschreibung des Host-Headers spielen keine Rolle
    assert seen["domain"] == "verify.musterverein.ch"
    assert body["tenant_name"] == "Musterverein" and body["organization_verified"] is True
    assert body["central_verify_url"].endswith("/verify")


def test_verify_site_on_the_central_page_has_only_the_central_url(monkeypatch):
    monkeypatch.setattr(repository, "verify_site", lambda db, *, domain: None)
    body = client.get("/api/public/verify/site", params={"domain": "abgabe.example.com"}).json()
    assert set(body) == {"central_verify_url"}


@pytest.mark.parametrize("domain", ["", "a b", "x" * 254, "evil.ch/path", "evil.ch?x=1"])
def test_verify_site_rejects_malformed_hosts(monkeypatch, domain):
    monkeypatch.setattr(repository, "verify_site", lambda *a, **k: pytest.fail("darf nicht abgefragt werden"))
    assert client.get("/api/public/verify/site", params={"domain": domain}).status_code == 422


def test_restricted_role_can_call_verify_site():
    db = SessionLocal()
    try:
        assert repository.verify_site(db, domain="unknown.example.ch") is None
    finally:
        db.close()
