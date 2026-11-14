"""Zugangslinks-Übersicht (app/public_links): jede Art von öffentlichem Link ist registriert.

Neue Token-Spalte oder neue Route ohne Anmeldung → dieser Test schlägt fehl, bis ein Anbieter in
app/public_links/providers.py sie übernimmt oder sie in EXEMPT_COLUMNS / EXEMPT_PUBLIC_ROUTES
begründet ausgenommen ist. So taucht jeder künftige Link-Typ in der Übersicht der Vereins-Admins auf.
"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from app.api.routes import public_links as route
from app.db.base import Base
from app.main import app
from app.models.entities import AccountToken, CalendarFeed, PhotoAlbum, ShareLink, SubmissionLink
from app.public_links import EXEMPT_COLUMNS, EXEMPT_PUBLIC_ROUTES, PROVIDERS, collect_all
from app.public_links import providers  # noqa: F401 - registriert die Anbieter
from tests.factories import make_current_user, make_participant, make_tenant

# Zeitstempel (token_created_at …) sind kein Token
TOKEN_COLUMN = re.compile(r"(^|_)(token|slug|secret)(_|$)")
AUTH_DEPENDENCIES = {"get_current_user", "get_current_admin", "require_admin_write", "require_admin_owner"}


def _covered_columns() -> set[str]:
    return {column for provider in PROVIDERS.values() for column in provider.token_columns}


def test_every_token_column_belongs_to_a_provider_or_is_exempt():
    covered = _covered_columns()
    missing = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            name = f"{table.name}.{column.name}"
            if TOKEN_COLUMN.search(column.name) and not column.name.endswith("_at") and name not in covered and name not in EXEMPT_COLUMNS:
                missing.append(name)
    assert not missing, (
        "Token-/Slug-Spalten ohne Eintrag in der Zugangslinks-Übersicht: "
        f"{missing}. Anbieter in app/public_links/providers.py registrieren oder in EXEMPT_COLUMNS begründen."
    )
    # Ausnahmen und Anbieter zeigen auf Spalten, die es gibt (kein veralteter Eintrag)
    known = {f"{table.name}.{column.name}" for table in Base.metadata.tables.values() for column in table.columns}
    assert not (covered | set(EXEMPT_COLUMNS)) - known


def _dependency_names(dependant) -> set[str]:
    names = set()
    for dependency in dependant.dependencies:
        if dependency.call is not None:
            names.add(getattr(dependency.call, "__name__", ""))
        names |= _dependency_names(dependency)
    return names


def _api_routes(routes, prefix: str = "", extra: frozenset[str] = frozenset()):
    """Alle APIRoutes mit vollem Pfad. Neuere FastAPI-Versionen legen eingebundene Router als
    _IncludedRouter ab (Präfix und Abhängigkeiten im include_context) statt die Routen zu kopieren."""
    for item in routes:
        if isinstance(item, APIRoute):
            yield prefix + item.path, _dependency_names(item.dependant) | extra
            continue
        context = getattr(item, "include_context", None)
        router = getattr(item, "original_router", None)
        if context is not None and router is not None:
            names = {getattr(dep.dependency, "__name__", "") for dep in (context.dependencies or [])}
            yield from _api_routes(router.routes, prefix + (context.prefix or ""), extra | frozenset(names))


def _public_paths() -> list[str]:
    routes = list(_api_routes(app.routes))
    assert len(routes) > 100, "Routen nicht gefunden - FastAPI-Struktur geändert?"
    return [path for path, names in routes if path.startswith("/api") and not (names & AUTH_DEPENDENCIES)]


def test_every_public_route_belongs_to_a_provider_or_is_exempt():
    prefixes = [prefix for provider in PROVIDERS.values() for prefix in provider.public_routes] + list(EXEMPT_PUBLIC_ROUTES)
    missing = sorted({path for path in _public_paths() if not any(path.startswith(prefix) for prefix in prefixes)})
    assert not missing, (
        "Routen ohne Anmeldung, die keinem Anbieter der Zugangslinks-Übersicht zugeordnet sind: "
        f"{missing}. Anbieter in app/public_links/providers.py registrieren oder in EXEMPT_PUBLIC_ROUTES begründen."
    )


def test_registry_entries_match_real_routes():
    paths = _public_paths()
    for prefix in EXEMPT_PUBLIC_ROUTES:
        assert any(path.startswith(prefix) for path in paths), f"veraltete Ausnahme: {prefix}"
    for provider in PROVIDERS.values():
        for prefix in provider.public_routes:
            assert any(path.startswith(prefix) for path in paths), (provider.kind, prefix)


# ── Inhalt der Übersicht ─────────────────────────────────────────────


@pytest.fixture
def club(db):
    tenant = make_tenant(db, "Linkverein")
    other = make_tenant(db, "Fremdverein")
    anna = make_participant(db, tenant.id, "Anna")
    db.flush()
    return {"tenant": tenant, "other": other, "anna": anna}


def test_overview_lists_current_links_of_the_own_tenant_only(db, club):
    now = datetime.now(UTC)
    tenant, other, anna = club["tenant"], club["other"], club["anna"]
    db.add_all([
        ShareLink(tenant_id=tenant.id, name="Fotos Lager", token=uuid.uuid4().hex, expires_at=now + timedelta(days=7)),
        ShareLink(tenant_id=tenant.id, name="Abgelaufen", token=uuid.uuid4().hex, expires_at=now - timedelta(days=1)),
        ShareLink(tenant_id=tenant.id, name="Widerrufen", token=uuid.uuid4().hex, revoked_at=now),
        ShareLink(tenant_id=other.id, name="Fremd", token=uuid.uuid4().hex),
        SubmissionLink(tenant_id=tenant.id, name="Abgabebox Eltern", token=uuid.uuid4().hex),
        AccountToken(tenant_id=tenant.id, user_id=anna.id, purpose="invite", token_hash="h" + uuid.uuid4().hex, expires_at=now + timedelta(days=7)),
        AccountToken(tenant_id=tenant.id, user_id=anna.id, purpose="password_reset", token_hash="h" + uuid.uuid4().hex, used_at=now),
        CalendarFeed(tenant_id=tenant.id, user_id=anna.id, kind="events", calendar_name="Termine", token_hash=uuid.uuid4().hex, token_encrypted="x"),
    ])
    db.flush()
    links = collect_all(db, tenant.id)
    labels = {(link.kind, link.label) for link in links}
    assert ("share_files", "Fotos Lager") in labels
    assert ("submission_link", "Abgabebox Eltern") in labels
    assert ("account_invite", "Anna") in labels
    assert ("calendar_events", "Termine") in labels
    assert not {"Abgelaufen", "Widerrufen", "Fremd"} & {label for _, label in labels}
    assert not any(link.kind == "account_password_reset" for link in links)  # benutzt
    share = next(link for link in links if link.label == "Fotos Lager")
    assert share.expiry == "date" and share.expires_at is not None


def test_partner_album_share_is_listed_for_the_album_owner(db, club):
    from app.models.entities import PhotoAlbumTenantShare

    album = PhotoAlbum(tenant_id=club["tenant"].id, name="Sommerlager")
    db.add(album)
    db.flush()
    db.add(PhotoAlbumTenantShare(album_id=album.id, tenant_id=club["other"].id, status="accepted"))
    db.flush()
    links = collect_all(db, club["tenant"].id)
    partner = next(link for link in links if link.kind == "album_partner")
    assert partner.label == "Sommerlager" and partner.params["partner"] == "Fremdverein"
    assert not any(link.kind == "album_partner" for link in collect_all(db, club["other"].id))


def test_route_requires_settings_manage(db, club):
    admin = make_current_user(club["tenant"].id, role="admin")
    assert isinstance(route.list_public_links(db=db, user=admin), list)
    writer = make_current_user(club["tenant"].id, role="writer")
    with pytest.raises(HTTPException) as exc:
        route.list_public_links(db=db, user=writer)
    assert exc.value.status_code == 403
