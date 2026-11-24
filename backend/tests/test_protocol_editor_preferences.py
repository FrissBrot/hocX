"""Editor-Vorlieben Akkordeon/Rad-Effekt sind mit dem Protokoll-Editor 1a (1.6) entfallen: nicht
mehr in CurrentUser und Session, beim Speichern des eigenen Profils noch eine Version toleriert
(ignoriert, kein 422 für ältere Clients)."""

from __future__ import annotations

import dataclasses

from app.core.security import CurrentUser, build_current_user
from app.schemas.user import SessionUserRead, UserSelfUpdate
from app.services.user_service import UserService

from tests.factories import make_app_user


def test_editor_preferences_are_gone_from_session_and_current_user(db):
    assert "protocol_accordion_enabled" not in SessionUserRead.model_fields
    assert "protocol_wheel_enabled" not in SessionUserRead.model_fields
    current_fields = {field.name for field in dataclasses.fields(CurrentUser)}
    assert "protocol_accordion_enabled" not in current_fields
    assert "protocol_wheel_enabled" not in current_fields


def test_old_clients_may_still_send_preferences_which_are_ignored(db):
    user = make_app_user(db, email="wheel@example.com")
    actor = build_current_user(db, user)
    before = dict(user.external_identity_json or {})

    UserService().update_self(db, actor, UserSelfUpdate(protocol_wheel_enabled=True, protocol_accordion_enabled=False))
    db.refresh(user)
    assert dict(user.external_identity_json or {}) == before

    UserService().update_self(db, actor, UserSelfUpdate(preferred_language="de", protocol_wheel_enabled=True))
    db.refresh(user)
    assert user.preferred_language == "de"
    assert "protocol_wheel_enabled" not in (user.external_identity_json or {})
