"""Test-Helfer. Mandanten und Benutzer leben in der hocX-Datenbank, nicht hier - der
Wanderplaner kennt nur ihre IDs. Die Helfer liefern deshalb nur eindeutige IDs mit
denselben Aufrufsignaturen wie die frueheren hocX-Fabriken."""

from __future__ import annotations

import itertools
from types import SimpleNamespace

# Hoher Startwert, damit Test-IDs nie mit Daten eines lokal importierten Dev-Bestands kollidieren.
_ids = itertools.count(9_000_000_000)


def make_tenant(db=None, name: str = "Test Tenant") -> SimpleNamespace:
    return SimpleNamespace(id=next(_ids), name=name)


def make_app_user(db=None, email: str = "test@example.com", *, tenant_id: int | None = None, role_code: str = "reader",
                  first_name: str = "Test", last_name: str = "User") -> SimpleNamespace:
    return SimpleNamespace(id=next(_ids), email=email, tenant_id=tenant_id, display_name=f"{first_name} {last_name}")


def make_caller(tenant_id: int, *, user_id: int | None = None, user_name: str | None = None):
    from app.core.internal_auth import Caller

    return Caller(tenant_id=tenant_id, user_id=user_id, user_name=user_name)
