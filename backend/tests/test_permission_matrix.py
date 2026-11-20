"""Berechtigungsmatrix (Plan «Berechtigungen, Datei-Kontexte und Kontext-Freigaben», Phase 0).

Hält den Ist-Zustand fest: Standardrolle × Route → erlaubt/verweigert. Die erwartete Matrix
erzeugt ``scripts/sync-route-permissions.py`` aus dem Quelltext und dem Katalog
(``permissions/permission-matrix.json``, Kopie in ``tests/fixtures``). Dieser Test ruft jede
GET-Route der Matrix wirklich auf - mit jeder Standardrolle, einem Mandanten mit allen Features
und Platzhalter-IDs - und prüft, dass die Route genau die Rollen ausserhalb der Matrix mit 403
abweist. Eine Prüfung, die erst NACH dem Laden eines Objekts kommt, fällt dadurch ebenso auf
(404 statt 403) wie eine Route, die stiller schützt als die Übersicht behauptet.

Schreibende Routen prüft dieser Test nicht (die Body-Validierung käme vor der Rechteprüfung);
sie deckt die statische Matrix ab, deren Diff jede Änderung zeigt.
"""
from __future__ import annotations

import dataclasses
import json
import re
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.core.features_generated import FEATURES
from app.core.security import get_current_user
from tests.factories import make_current_user, make_tenant

MATRIX = json.loads((Path(__file__).parent / "fixtures" / "permission-matrix.json").read_text(encoding="utf-8"))
ROLES = MATRIX["roles"]
GET_ROUTES = {key: entry for key, entry in MATRIX["routes"].items() if key.startswith("GET ") and " (" not in key}

# Bekannte, begründete Abweichungen vom Muster «verweigert = 403» (Route → Begründung). Eine neue
# Abweichung ist ein Befund (siehe docs/permissions-inventory.md), kein Eintrag hier ohne Grund.
KNOWN_DEVIATIONS: dict[str, str] = {}

_PLACEHOLDERS = {
    "year": "2026",
    "cycle_year": "2026",
    "role": "original",
    "file_name": "inter.woff2",
    "example_key": "beispiel",
    "kind": "protocol",
    "table_name": "list_entry",
    "token": "nicht-vorhanden",
    # Unbekannte Quelle ergäbe 404 vor der Rechteprüfung (keine Daten, aber nicht prüfbar)
    "source": "participants",
}


def _path(template: str) -> str:
    def value(match: re.Match[str]) -> str:
        name = match.group(1).split(":")[0]
        if name in _PLACEHOLDERS:
            return _PLACEHOLDERS[name]
        if name.endswith("year"):
            return "2026"
        return str(uuid.uuid4())

    return re.sub(r"\{([^}]+)\}", value, template)


@pytest.fixture
def app_for(db):
    """Die echten Routen der App, ohne Middleware/Lifespan (keine Hintergrund-Jobs)."""
    from app.main import app as main_app

    bare = FastAPI()
    bare.router.routes = list(main_app.router.routes)
    bare.exception_handlers.update(main_app.exception_handlers)
    # Overrides liest FastAPI von der App, an der die Routen hängen (main_app), nicht von der Kopie
    saved = dict(main_app.dependency_overrides)
    main_app.dependency_overrides[get_db] = lambda: db
    tenant = make_tenant(db, "Matrix", features=tuple(FEATURES))

    def client(role: str) -> TestClient:
        # Mit bestätigtem zweitem Faktor (Administrationsrechte verlangen MFA; z. B. der
        # Gesamtexport prüft mfa_verified zusätzlich zur Berechtigung)
        actor = dataclasses.replace(make_current_user(tenant.id, role=role, features=frozenset(FEATURES)), mfa_verified=True)
        main_app.dependency_overrides[get_current_user] = lambda: actor
        return TestClient(bare, raise_server_exceptions=False)

    yield client
    main_app.dependency_overrides.clear()
    main_app.dependency_overrides.update(saved)


def test_matrix_has_routes_and_roles():
    assert set(ROLES) >= {"admin", "writer", "kassier", "reader"}
    assert len(GET_ROUTES) > 50
    # Dateiauslieferung ist in der Matrix markiert (Phase 0: alle Stellen, die Dateien ausliefern)
    assert any(entry.get("serves_files") for entry in MATRIX["routes"].values())


def test_get_routes_reject_exactly_the_roles_outside_the_matrix(app_for, db, monkeypatch):
    # GET /activity protokolliert das Öffnen mit eigenem Commit; der wirft hier die Savepoint-Kette
    # um (db.rollback() nach jeder Route nähme dann den Mandanten mit). Geprüft werden nur Rechte.
    from app.api.routes import activity as activity_routes

    monkeypatch.setattr(activity_routes, "_audit_view", lambda *_args, **_kwargs: None)
    findings: list[str] = []
    for role in ROLES:
        client = app_for(role)
        for key, entry in GET_ROUTES.items():
            if key in KNOWN_DEVIATIONS:
                continue
            path = _path(key.split(" ", 1)[1])
            status = client.get(path).status_code
            db.rollback()  # ein Fehler einer Route soll die nächste nicht beeinflussen
            if status == 422:
                continue  # Pflicht-Query-Parameter fehlen: nicht ohne Daten prüfbar
            allowed = role in entry["allowed"]
            if not allowed and status != 403:
                findings.append(f"{role}: {key} sollte 403 sein, war {status}")
            if allowed and status in (401, 403):
                findings.append(f"{role}: {key} sollte erlaubt sein, war {status}")
    assert findings == [], "\n".join(findings)
