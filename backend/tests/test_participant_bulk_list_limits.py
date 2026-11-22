"""Listenlänge der Mitglieder-Massenaktionen (Bug-Bounty 2026-11-22, mitglieder-rollen/eingaben).

Massen-Einladen und -Rollen begrenzen die Liste auf 500 IDs, Massenlöschen und die
Vorlagen-Zuordnungen hatten keine Grenze. Eine Liste mit mehr als 65 535 IDs (rund 2,8 MB,
unter dem allgemeinen Body-Limit von 10 MB) sprengte die Parametergrenze von PostgreSQL in
`resolve_internal_ids`: 500 samt Eintrag im Fehlerprotokoll statt 422."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.core.security import get_current_user
from app.main import app
from tests.factories import make_current_user, make_participant, make_tenant, make_template

_TOO_MANY = 70_000


@pytest.fixture()
def admin_client(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="admin")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield TestClient(app, raise_server_exceptions=False), tenant
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


def _ids(count: int) -> list[str]:
    return [str(uuid.uuid4()) for _ in range(count)]


def test_bulk_delete_with_huge_list_is_422_not_500(admin_client):
    client, _ = admin_client
    response = client.request("DELETE", "/api/participants", json={"participant_ids": _ids(_TOO_MANY)})
    assert response.status_code == 422


def test_template_participants_with_huge_list_is_422_not_500(admin_client, db):
    client, tenant = admin_client
    template = make_template(db, tenant_id=tenant.id)
    response = client.put(f"/api/templates/{template.public_id}/participants", json={"participant_ids": _ids(_TOO_MANY)})
    assert response.status_code == 422


def test_participant_templates_with_huge_list_is_422_not_500(admin_client, db):
    client, tenant = admin_client
    participant = make_participant(db, tenant_id=tenant.id)
    response = client.put(f"/api/participants/{participant.public_id}/templates", json={"template_ids": _ids(_TOO_MANY)})
    assert response.status_code == 422


def test_bulk_delete_normal_list_still_works(admin_client, db):
    client, tenant = admin_client
    participant = make_participant(db, tenant_id=tenant.id)
    response = client.request("DELETE", "/api/participants", json={"participant_ids": [str(participant.public_id)]})
    assert response.status_code == 200
    assert response.json() == {"deleted_count": 1}
