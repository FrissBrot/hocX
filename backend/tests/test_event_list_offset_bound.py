"""skip ohne Obergrenze in Termin-Listen (Bug-Bounty 2026-11-20, termine/fehlerbehandlung).

GET /events?skip=10000000000000000000 bzw. GET /protocols/{id}/cycle-events?skip=… reichten den
Wert als OFFSET an PostgreSQL weiter: «bigint out of range» -> 500 plus Fehlerprotokoll.
Jetzt 422 aus der Query-Validierung."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import events as events_routes
from app.api.routes import protocols as protocol_routes
from app.core.db import get_db
from app.core.security import get_current_user
from app.schemas.base import MAX_QUERY_OFFSET
from tests.factories import make_current_user, make_protocol, make_template, make_tenant

HUGE = 10**19


def _client(db, actor) -> TestClient:
    app = FastAPI()
    app.include_router(events_routes.router, prefix="/api")
    app.include_router(protocol_routes.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor
    return TestClient(app, raise_server_exceptions=False)


def test_huge_skip_is_a_validation_error_not_a_database_error(db):
    tenant = make_tenant(db)
    actor = make_current_user(tenant.id, role="writer")
    protocol = make_protocol(db, tenant.id, make_template(db, tenant.id).id)
    client = _client(db, actor)

    assert client.get("/api/events", params={"skip": HUGE}).status_code == 422
    assert client.get(f"/api/protocols/{protocol.public_id}/cycle-events", params={"skip": HUGE}).status_code == 422


def test_skip_at_the_bound_still_works(db):
    tenant = make_tenant(db)
    actor = make_current_user(tenant.id, role="writer")
    client = _client(db, actor)

    response = client.get("/api/events", params={"skip": MAX_QUERY_OFFSET})

    assert response.status_code == 200
    assert response.json() == []
