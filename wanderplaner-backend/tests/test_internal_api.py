"""Vertrauensgrenze und Service-zu-Service-Endpunkte (app/core/internal_auth.py,
app/api/routes/internal.py) ueber echte HTTP-Aufrufe."""

from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import get_db
from app.main import app
from app.services.hiking_tour_service import HikingTourService
from tests.factories import make_tenant
from tests.test_hiking_tour_service import GOLDAU, _basic_payload

TOKEN = "test-internal-token"
DAY = date(2026, 7, 10)


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(settings, "internal_token", TOKEN)
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _headers(tenant_id, token=TOKEN, **extra):
    return {"Authorization": f"Bearer {token}", "X-Hocx-Tenant-Id": str(tenant_id), **extra}


def test_requests_without_valid_token_are_rejected(client):
    tenant = make_tenant()
    assert client.get("/api/hiking-tours", headers={"X-Hocx-Tenant-Id": str(tenant.id)}).status_code == 401
    assert client.get("/api/hiking-tours", headers=_headers(tenant.id, token="falsch")).status_code == 401
    assert client.delete(f"/internal/tenants/{tenant.id}").status_code == 401
    assert client.get("/api/hiking-tours").status_code == 401
    assert client.get("/api/hiking-tours", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 400


def test_empty_configured_token_fails_closed(client, monkeypatch):
    monkeypatch.setattr(settings, "internal_token", "")
    assert client.get("/api/hiking-tours", headers=_headers(1, token="")).status_code == 401


def test_tours_are_scoped_to_the_tenant_header(client, db):
    owner = make_tenant()
    other = make_tenant()
    tour = HikingTourService().create_tour(db, _basic_payload(), tenant_id=owner.id)

    own = client.get("/api/hiking-tours", headers=_headers(owner.id))
    foreign_list = client.get("/api/hiking-tours", headers=_headers(other.id))
    foreign_detail = client.get(f"/api/hiking-tours/{tour.public_id}", headers=_headers(other.id))

    assert [item["id"] for item in own.json()] == [str(tour.public_id)]
    assert foreign_list.json() == []
    assert foreign_detail.status_code == 404


def test_reconnaissance_stores_the_url_encoded_user_name(client, db):
    tenant = make_tenant()
    tour = HikingTourService().create_tour(db, _basic_payload(), tenant_id=tenant.id)

    response = client.patch(
        f"/api/hiking-tours/{tour.public_id}/reconnaissance",
        json={"checklist": {}},
        headers=_headers(tenant.id, **{"X-Hocx-User-Id": "42", "X-Hocx-User-Name": "J%C3%BCrg%20M%C3%BCller"}),
    )

    assert response.status_code == 200
    assert response.json()["reconnoitered_by_name"] == "Jürg Müller"


def test_photo_matches_endpoint(client, db):
    tenant = make_tenant()
    tour = HikingTourService().create_tour(db, _basic_payload(tour_date=DAY), tenant_id=tenant.id)
    file_id = uuid4()

    response = client.post(
        f"/internal/tenants/{tenant.id}/photo-matches",
        json={"photos": [{"file_id": str(file_id), "lat": GOLDAU["lat"], "lon": GOLDAU["lon"], "taken_on": DAY.isoformat()}]},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "tours": [{"id": str(tour.public_id), "title": tour.title}],
        "matches": [{"file_id": str(file_id), "tour_id": str(tour.public_id)}],
    }


def test_delete_tenant_data_removes_only_that_tenant(client, db):
    gone = make_tenant()
    kept = make_tenant()
    service = HikingTourService()
    service.create_tour(db, _basic_payload(), tenant_id=gone.id)
    kept_tour = service.create_tour(db, _basic_payload(), tenant_id=kept.id)

    response = client.delete(f"/internal/tenants/{gone.id}", headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.json() == {"deleted_tours": 1}
    assert service.list_tours(db, tenant_id=gone.id) == []
    assert service.list_tours(db, tenant_id=kept.id) == [kept_tour]
