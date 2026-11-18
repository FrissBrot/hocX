"""Benutzerlimit des Abos: offene Einladungen zählen schon beim Einladen mit (Entscheid
18.11.2026) - die eigene Einladung der Person belegt aber keinen zusätzlichen Platz."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.models import AccountToken
from app.services import user_limit_service
from tests.factories import make_app_user, make_participant, make_tenant


def _invite(db, tenant_id: int, person) -> AccountToken:
    token = AccountToken(
        tenant_id=tenant_id, user_id=person.id, purpose="invite", token_hash=f"hash-{person.id}",
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(token)
    db.flush()
    return token


def test_open_invites_count_towards_the_limit(db):
    tenant = make_tenant(db, "Limit Einladungen")
    tenant.user_limit_override = 2
    make_app_user(db, "limit-admin@example.com", tenant_id=tenant.id, role_code="admin")  # 1 Login
    invited = make_participant(db, tenant.id, "Eingeladen")
    other = make_participant(db, tenant.id, "Weitere Person")
    _invite(db, tenant.id, invited)

    assert user_limit_service.pending_invite_count(db, tenant.id) == 1
    # Login + offene Einladung = Limit: niemand weiteres
    with pytest.raises(HTTPException) as full:
        user_limit_service.ensure_login_capacity(db, tenant.id, for_user_id=other.id)
    assert full.value.status_code == 409
    # Die eingeladene Person selbst (erneut senden, annehmen) belegt keinen zusätzlichen Platz
    user_limit_service.ensure_login_capacity(db, tenant.id, for_user_id=invited.id)


def test_expired_or_revoked_invites_do_not_count(db):
    tenant = make_tenant(db, "Limit abgelaufen")
    expired = _invite(db, tenant.id, make_participant(db, tenant.id, "Abgelaufen"))
    expired.expires_at = datetime.now(UTC) - timedelta(days=1)
    revoked = _invite(db, tenant.id, make_participant(db, tenant.id, "Zurückgezogen"))
    revoked.revoked_at = datetime.now(UTC)
    db.flush()
    assert user_limit_service.pending_invite_count(db, tenant.id) == 0
