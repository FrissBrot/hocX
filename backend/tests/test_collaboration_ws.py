"""collaboration_ws.py's pure/DB-lookup helpers - the WebSocket route itself needs a live
Redis pub/sub connection and isn't exercised here (see conftest.py's `db` fixture docstring
for why this repo's tests run against the real dev DB in a rolled-back transaction instead
of a separate test container/mock)."""
from __future__ import annotations

from app.api.routes.collaboration_ws import _active_app_domain_origins, _field_update_requires_lock
from tests.factories import make_tenant, make_tenant_domain


def test_active_app_domain_origins_includes_active_app_domain(db):
    tenant = make_tenant(db)
    make_tenant_domain(db, tenant.id, domain="verein.example.org")
    assert "https://verein.example.org" in _active_app_domain_origins(db)


def test_active_app_domain_origins_excludes_pending_domain(db):
    # A domain the tenant registered but hasn't finished verifying yet must not grant WS
    # access on it - only an "active" app domain is a real, working origin for this tenant.
    tenant = make_tenant(db)
    make_tenant_domain(db, tenant.id, domain="pending.example.org", status="pending")
    assert "https://pending.example.org" not in _active_app_domain_origins(db)


def test_active_app_domain_origins_excludes_abgabebox_purpose_domain(db):
    # abgabebox-frontend is a separate app with its own origin story - an "abgabebox"-purpose
    # domain has nothing to do with this main-app collaboration WebSocket.
    tenant = make_tenant(db)
    make_tenant_domain(db, tenant.id, domain="abgabe.example.org", purpose="abgabebox")
    assert "https://abgabe.example.org" not in _active_app_domain_origins(db)


def test_field_update_requires_lock_for_plain_block_key():
    assert _field_update_requires_lock("block-123") is True


def test_field_update_requires_lock_for_matrix_cell_key():
    assert _field_update_requires_lock("block-123-cell-0-1") is True


def test_field_update_does_not_require_lock_for_todos_and_images():
    # Regression test: these two suffixed keys broadcast the block's whole, already
    # REST-confirmed todos/images array rather than a diff of one contested field, and the
    # only lock ever taken by the frontend is on the bare "block-<id>" key - never on these
    # suffixed keys. Requiring lock ownership here (as for a plain "block-<id>" edit) meant
    # every todo/image field_update was silently rejected since they were introduced.
    assert _field_update_requires_lock("block-123-todos") is False
    assert _field_update_requires_lock("block-123-images") is False


def test_field_update_does_not_require_lock_for_unrelated_pings():
    assert _field_update_requires_lock("element-titles") is False
    assert _field_update_requires_lock("track-changes-toggle") is False
