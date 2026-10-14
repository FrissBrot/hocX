"""Speicherprofile und Storage-Admin-API: Validierung, Geheimhaltung der Zugangsdaten,
Verbindungstest, Schutz aktiver/benötigter Profile, Berechtigungen und Audit."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.routes import admin_storage
from app.core.admin_security import CurrentAdmin, get_current_admin
from app.core.db import get_db
from app.models import StorageProfile, StorageState
from app.services import storage_profile_service as sps
from tests.storage_support import committed_storage, create_test_profile, requires_s3, s3_profile_values  # noqa: F401


def _client(db, role: str = "owner") -> TestClient:
    app = FastAPI()
    app.include_router(admin_storage.router, prefix="/api/admin")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_admin] = lambda: CurrentAdmin(admin_id=1, admin_public_id=uuid.uuid4(), email=f"{role}@example.com", display_name=role, role=role)
    return TestClient(app)


def _values(**overrides) -> dict:
    values = {
        "name": f"Profil {uuid.uuid4().hex[:6]}", "provider": "hetzner", "region": "fsn1", "bucket": "hocx-prod",
        "prefix": f"p-{uuid.uuid4().hex[:6]}", "access_key": "AKIAEXAMPLE1234", "secret_key": "super-geheim-1234567890",
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize("override,message", [
    ({"provider": "s3_compatible", "endpoint_url": "http://s3.example.com"}, "HTTPS"),
    ({"provider": "s3_compatible", "endpoint_url": "https://user:pw@s3.example.com"}, "Zugangsdaten"),
    ({"bucket": "Ungültig_Bucket"}, "Bucket"),
    ({"prefix": "../escape"}, "Präfix"),
    ({"provider": "unknown"}, "Anbieter"),
    ({"restricted_access_key": "only-key"}, "vollständig"),
])
def test_dangerous_or_invalid_profiles_are_rejected(db, override, message):
    with pytest.raises(sps.StorageProfileError, match=message):
        sps.create_profile(db, _values(**override), actor_email="x")


def test_hetzner_endpoint_is_derived_from_the_region(db):
    profile = sps.create_profile(db, _values(), actor_email="x")
    assert profile.endpoint_url == "https://fsn1.your-objectstorage.com"
    assert profile.addressing_style == "virtual"


def test_overlapping_namespaces_are_rejected(db):
    first = sps.create_profile(db, _values(prefix="hocx/prod"), actor_email="x")
    with pytest.raises(sps.StorageProfileError, match="überschneidet"):
        sps.create_profile(db, _values(prefix="hocx/prod/sub"), actor_email="x")
    with pytest.raises(sps.StorageProfileError, match="überschneidet"):
        sps.create_profile(db, _values(prefix=""), actor_email="x")
    assert sps.create_profile(db, _values(prefix="hocx/other"), actor_email="x").id != first.id


def test_secrets_are_encrypted_at_rest_and_never_returned(db):
    client = _client(db)
    response = client.post("/api/admin/storage/profiles", json=_values(access_key="AKIAPLAINTEXT9876", secret_key="dont-leak-this-secret"))
    assert response.status_code == 201
    body = response.text
    assert "dont-leak-this-secret" not in body and "AKIAPLAINTEXT9876" not in body
    assert response.json()["access_key_masked"] == "••••9876" and response.json()["has_secret_key"] is True
    row = db.execute(text("SELECT access_key_enc, secret_key_enc FROM storage_profile WHERE public_id = :id"), {"id": response.json()["id"]}).one()
    assert "dont-leak-this-secret" not in row.secret_key_enc and "AKIAPLAINTEXT9876" not in row.access_key_enc
    listing = client.get("/api/admin/storage/profiles").text
    assert "dont-leak-this-secret" not in listing
    audit = db.execute(text("SELECT details_json::text FROM audit_log WHERE action = 'admin.storage_profile_created' ORDER BY id DESC LIMIT 1")).scalar()
    assert "dont-leak-this-secret" not in audit


def test_read_only_admins_cannot_change_storage(db):
    client = _client(db, role="support")
    assert client.get("/api/admin/storage/overview").status_code == 200
    assert client.post("/api/admin/storage/profiles", json=_values()).status_code == 403


def test_active_and_builtin_profiles_are_protected(committed_storage):
    # Echte Commits: die Routen rollen bei 409 selbst zurück, das verträgt die Savepoint-Session
    # des db-Fixtures nicht. committed_storage stellt den Ausgangszustand danach wieder her.
    db = committed_storage
    state = db.get(StorageState, 1)
    filesystem = db.get(StorageProfile, state.active_profile_id)
    client = _client(db)
    assert client.delete(f"/api/admin/storage/profiles/{filesystem.public_id}").status_code == 409
    assert client.patch(f"/api/admin/storage/profiles/{filesystem.public_id}", json={"name": "x"}).status_code == 409
    profile = sps.create_profile(db, _values(), actor_email="x")
    db.execute(text("UPDATE storage_state SET active_profile_id = :id WHERE id = 1"), {"id": profile.id})
    db.commit()
    assert client.patch(f"/api/admin/storage/profiles/{profile.public_id}", json={"bucket": "anderer-bucket"}).status_code == 409
    assert client.patch(f"/api/admin/storage/profiles/{profile.public_id}", json={"is_enabled": False}).status_code == 409
    assert client.delete(f"/api/admin/storage/profiles/{profile.public_id}").status_code == 409


def test_credential_rotation_bumps_the_config_version_and_requires_a_new_test(db):
    profile = sps.create_profile(db, _values(), actor_email="x")
    profile.last_test_ok = True
    version = profile.config_version
    sps.update_profile(db, profile, {"secret_key": "neu-rotiert-1234567"}, actor_email="x")  # gitleaks:allow - Test-Platzhalter, kein echtes Secret
    assert profile.config_version == version + 1 and profile.last_test_ok is None


def test_a_migration_needs_a_successfully_tested_target(committed_storage):
    db = committed_storage
    client = _client(db)
    profile = sps.create_profile(db, _values(), actor_email="x")
    db.commit()
    response = client.post("/api/admin/storage/migrations", json={"target_profile_id": str(profile.public_id)})
    assert response.status_code == 409 and "Verbindungstest" in response.json()["detail"]


@requires_s3
def test_connection_test_writes_reads_verifies_and_deletes_an_isolated_object(db):
    profile = create_test_profile(db, f"Test {uuid.uuid4().hex[:6]}", f"conn-{uuid.uuid4().hex[:6]}", provider="garage_local")
    result = _client(db).post(f"/api/admin/storage/profiles/{profile.public_id}/test").json()
    assert result["ok"] is True, result
    for area in ("main", "abgabebox"):
        assert all(result[area][step] for step in ("write", "head", "read", "list", "delete"))
    assert result["restricted_credentials"] is True


@requires_s3
def test_connection_test_reports_wrong_credentials_without_leaking_them(db):
    values = s3_profile_values(f"Kaputt {uuid.uuid4().hex[:6]}", f"bad-{uuid.uuid4().hex[:6]}")
    values.update({"provider": "garage_local", "secret_key": "f" * 64})
    profile = sps.create_profile(db, values, actor_email="x")
    result = sps.run_connection_test(db, profile)
    assert result["ok"] is False and profile.last_test_ok is False
    assert "f" * 64 not in (result["error"] or "") and os.environ["TEST_S3_ACCESS_KEY"] not in (result["error"] or "")
