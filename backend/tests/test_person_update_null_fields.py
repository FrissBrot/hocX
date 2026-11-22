"""Ausdrückliches null/leerer Name beim Bearbeiten einer Person (Bug-Bounty 2026-11-22,
mitglieder-rollen/eingaben).

`ParticipantUpdate`/`UserUpdate` erlaubten `null` für NOT-NULL-Spalten (Anzeigename, aktiv,
Zusatzdaten) und einen leeren Anzeigenamen. `null` scheiterte erst am NOT-NULL-Constraint:
400 «could not be updated», aber mit Eintrag im Fehlerprotokoll (IntegrityError als Ursache).
Ein leerer oder nur aus Leerzeichen bestehender Name wurde gespeichert, die Person erschien
namenlos in Listen und Auswahlfeldern - beim Anlegen ist das verboten (min_length=1)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import get_db
from app.core.security import get_current_user
from app.main import app
from app.models import Participant, SystemErrorLog
from tests.factories import make_current_user, make_participant, make_tenant


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


def _errors(db, tenant_id: int) -> int:
    return len(db.scalars(select(SystemErrorLog.id).where(SystemErrorLog.tenant_id == tenant_id)).all())


@pytest.mark.parametrize(
    "body",
    [{"display_name": None}, {"display_name": ""}, {"display_name": "   "}, {"is_active": None}],
    ids=["name-null", "name-leer", "name-leerzeichen", "aktiv-null"],
)
@pytest.mark.parametrize("route", ["participants", "users"])
def test_patch_person_rejects_null_and_blank_name(admin_client, db, route, body):
    client, tenant = admin_client
    person = make_participant(db, tenant_id=tenant.id, display_name="Anna Muster")

    response = client.patch(f"/api/{route}/{person.public_id}", json=body)

    assert response.status_code == 422
    db.refresh(person)
    assert person.display_name == "Anna Muster"
    assert person.is_active is True
    assert _errors(db, tenant.id) == 0


def test_blank_name_does_not_break_member_list(admin_client, db):
    """Vorher: PATCH mit leerem Namen wurde gespeichert, danach scheiterte die Antwort-Validierung
    (ParticipantRead verlangt min_length=1) - und damit GET /participants für den ganzen Mandanten."""
    client, tenant = admin_client
    person = make_participant(db, tenant_id=tenant.id, display_name="Anna Muster")
    client.patch(f"/api/participants/{person.public_id}", json={"display_name": ""})

    response = client.get("/api/participants")

    assert response.status_code == 200
    assert [row["display_name"] for row in response.json()] == ["Anna Muster"]


def test_patch_person_trims_and_keeps_partial_updates(admin_client, db):
    client, tenant = admin_client
    person = make_participant(db, tenant_id=tenant.id, display_name="Anna Muster")
    response = client.patch(f"/api/participants/{person.public_id}", json={"first_name": "Anna"})
    assert response.status_code == 200
    db.refresh(person)
    assert person.display_name == "Anna Muster" and person.first_name == "Anna"
