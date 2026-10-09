"""hocX als Eingang zum Wanderplaner-Service (app/api/routes/hiking_tours.py): Rechte und
Feature-Gating, Pfadpruefung, Weitergabe des Kontexts, Druck-PDF-Ablage, Fehlerkette."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.routes import hiking_tours
from app.core.config import settings
from app.core.db import get_db
from app.core.security import get_current_user
from app.models.entities import StoredFile
from app.services import wanderplaner_client
from app.services.wanderplaner_client import WanderplanerResponse
from tests.factories import make_app_user, make_current_user, make_tenant

TOUR_ID = "0192f0a0-0000-7000-8000-000000000001"


class FakeService:
    def __init__(self, response: WanderplanerResponse | Exception | None = None):
        self.calls: list[dict] = []
        self.response = response or WanderplanerResponse(200, b"[]", {"content-type": "application/json"})

    def __call__(self, method, path, **kwargs):
        self.calls.append({"method": method, "path": path, **kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.fixture
def service(monkeypatch):
    fake = FakeService()
    monkeypatch.setattr(wanderplaner_client, "request", fake)
    synced: list[int] = []
    monkeypatch.setattr(hiking_tours, "sync_photos_for_tours_best_effort", lambda db, tenant_id, **kw: synced.append(tenant_id))
    fake.synced = synced
    return fake


def _client(db, actor):
    app = FastAPI()
    app.include_router(hiking_tours.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor
    return TestClient(app)


def _user(tenant_id, role="writer", features=frozenset({"wanderplaner"})):
    return make_current_user(tenant_id, role=role, user_id=7, features=features)


def test_tenant_without_feature_is_rejected_before_the_service_is_called(db, service):
    tenant = make_tenant(db)
    client = _client(db, _user(tenant.id, role="admin", features=frozenset()))

    assert client.get("/api/hiking-tours").status_code == 403
    assert service.calls == []


@pytest.mark.parametrize(("role", "expected_post"), [("reader", 403), ("kassier", 403), ("writer", 201), ("admin", 201)])
def test_role_matrix_and_forwarded_caller_context(db, service, role, expected_post):
    tenant = make_tenant(db)
    client = _client(db, _user(tenant.id, role=role))

    assert client.get("/api/hiking-tours?limit=5").status_code == 200
    get_call = service.calls[-1]
    assert (get_call["method"], get_call["path"], get_call["query"]) == ("GET", "/api/hiking-tours", "limit=5")
    assert get_call["caller"] == wanderplaner_client.CallerContext(tenant_id=tenant.id, user_id=7, user_name="Test User")

    service.response = WanderplanerResponse(201, b"{}", {"content-type": "application/json"})
    assert client.post("/api/hiking-tours", json={"title": "x"}).status_code == expected_post


@pytest.mark.parametrize("path", ["a/%2e%2e/%2e%2e/internal/tenants/1", "x.y", "a//b"])
def test_paths_outside_the_wanderplaner_api_are_never_forwarded(db, service, path):
    tenant = make_tenant(db)
    client = _client(db, _user(tenant.id, role="admin"))

    assert client.delete(f"/api/hiking-tours/{path}").status_code == 404
    assert service.calls == []


def test_upstream_client_errors_are_passed_through_unchanged(db, service):
    tenant = make_tenant(db)
    service.response = WanderplanerResponse(422, json.dumps({"detail": "Kein Routingprofil gewählt"}).encode(), {"content-type": "application/json"})
    client = _client(db, _user(tenant.id))

    response = client.post(f"/api/hiking-tours/{TOUR_ID}/route", json={})

    assert response.status_code == 422
    assert response.json() == {"detail": "Kein Routingprofil gewählt"}
    assert service.synced == []


def test_tour_changes_trigger_photo_sync_but_waypoint_edits_do_not(db, service):
    tenant = make_tenant(db)
    client = _client(db, _user(tenant.id))
    service.response = WanderplanerResponse(200, b"{}", {"content-type": "application/json"})

    client.patch(f"/api/hiking-tours/{TOUR_ID}/waypoints/{TOUR_ID}", json={})
    assert service.synced == []
    client.patch(f"/api/hiking-tours/{TOUR_ID}", json={"title": "Neu"})
    client.post(f"/api/hiking-tours/{TOUR_ID}/route", json={})
    assert service.synced == [tenant.id, tenant.id]


def test_upstream_server_errors_keep_the_cause_for_system_error_log(service):
    """Der globale HTTPException-Handler protokolliert nur Fehler mit __cause__ (CLAUDE.md)."""
    service.response = wanderplaner_client.WanderplanerUpstreamError("Wanderplaner-Service ... HTTP 500: KeyError")
    with pytest.raises(HTTPException) as exc_info:
        hiking_tours._call_service("GET", "/api/hiking-tours", user=_user(1))
    assert exc_info.value.status_code == 502
    assert isinstance(exc_info.value.__cause__, wanderplaner_client.WanderplanerUpstreamError)

    service.response = wanderplaner_client.WanderplanerUnavailableError("nicht erreichbar")
    with pytest.raises(HTTPException) as exc_info:
        hiking_tours._call_service("GET", "/api/hiking-tours", user=_user(1))
    assert exc_info.value.status_code == 503
    assert exc_info.value.__cause__ is not None


def test_print_stores_the_pdf_as_tenant_file(db, service, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "export_root", str(tmp_path / "exports"))
    tenant = make_tenant(db)
    service.response = WanderplanerResponse(
        200,
        b"%PDF-1.5 test",
        {
            "content-type": "application/pdf",
            "content-disposition": "attachment; filename*=UTF-8''Rigi%20%C3%BCber%20Goldau.pdf",
            hiking_tours.SHEET_COUNT_HEADER: "3",
        },
    )
    # Echter Benutzer: der Audit-Eintrag referenziert app_user per Fremdschluessel.
    writer = make_app_user(db, "drucker@example.com", tenant_id=tenant.id, role_code="writer")
    client = _client(db, make_current_user(tenant.id, role="writer", user_id=writer.id, features=frozenset({"wanderplaner"})))

    response = client.post(f"/api/hiking-tours/{TOUR_ID}/print", json={"paper": "A4", "orientation": "landscape", "scale": 25000})

    assert response.status_code == 200
    body = response.json()
    assert body["sheet_count"] == 3
    stored = db.query(StoredFile).filter(StoredFile.public_id == uuid.UUID(body["generated_file_id"])).one()
    assert stored.tenant_id == tenant.id
    assert stored.original_name == "Rigi über Goldau.pdf"
    assert (Path(settings.storage_root) / stored.storage_path).read_bytes() == b"%PDF-1.5 test"
    assert service.calls[0]["timeout"] == settings.wanderplaner_print_timeout_seconds


def test_print_requires_write_access(db, service):
    tenant = make_tenant(db)
    client = _client(db, _user(tenant.id, role="reader"))

    assert client.post(f"/api/hiking-tours/{TOUR_ID}/print", json={}).status_code == 403
    assert service.calls == []
