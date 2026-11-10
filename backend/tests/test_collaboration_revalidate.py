"""SEC-007-Revalidierung offener WebSockets: eine DB-Session je Prüfung, kurzer Cache je
(Token, Protokoll) für mehrere Tabs, gesperrter Login beendet die Verbindung."""

import uuid

import pytest

from app.api.routes import collaboration_ws as ws
from app.core.security import create_session_token
from tests.factories import make_app_user, make_protocol, make_template, make_tenant


class _Shared:
    """Fixture-Session für den Code unter Test; close() darf sie nicht schliessen."""

    def __init__(self, db):
        self._db = db
        self.opened = 0

    def __call__(self):
        self.opened += 1
        return self

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._db, name)


@pytest.fixture
def world(db, monkeypatch):
    ws._revalidate_cache.clear()
    shared = _Shared(db)
    monkeypatch.setattr(ws, "SessionLocal", shared)
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="geplant")
    account = make_app_user(db, email=f"ws-{uuid.uuid4().hex[:8]}@example.com", tenant_id=tenant.id, role_code="writer")
    return shared, protocol, account, create_session_token(account.id)


def test_revalidate_returns_user_and_protocol_with_one_session(world):
    shared, protocol, account, token = world
    current, protocol_id = ws._revalidate(token, protocol.public_id)
    assert current.user_id == account.id and protocol_id == protocol.id
    assert shared.opened == 1


def test_second_tab_within_the_cache_window_needs_no_database(world):
    shared, protocol, _account, token = world
    ws._revalidate(token, protocol.public_id)
    ws._revalidate(token, protocol.public_id)
    assert shared.opened == 1
    # Anderes Protokoll: eigener Eintrag
    ws._revalidate(token, uuid.uuid4())
    assert shared.opened == 2


def test_cache_expires_and_blocked_login_closes_the_connection(world, db, monkeypatch):
    shared, protocol, account, token = world
    ws._revalidate(token, protocol.public_id)
    account.login_enabled = False
    db.flush()
    monkeypatch.setattr(ws, "REVALIDATE_CACHE_SECONDS", 0)
    current, protocol_id = ws._revalidate(token, protocol.public_id)
    assert current is None and protocol_id is None
