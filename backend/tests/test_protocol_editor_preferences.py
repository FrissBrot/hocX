"""Editor-Vorlieben im Profil (Akkordeon, Rad-Effekt): gespeichert in
external_identity_json, gespiegelt in CurrentUser und der Session."""

from __future__ import annotations

from app.core.security import build_current_user
from app.schemas.user import UserSelfUpdate
from app.services.user_service import UserService

from tests.factories import make_app_user


def test_wheel_effect_defaults_on_and_is_stored_without_touching_accordion(db):
    user = make_app_user(db, email="wheel@example.com")
    actor = build_current_user(db, user)
    assert actor.protocol_wheel_enabled is True
    assert actor.protocol_accordion_enabled is True

    UserService().update_self(db, actor, UserSelfUpdate(protocol_wheel_enabled=False))
    db.refresh(user)
    actor = build_current_user(db, user)
    assert actor.protocol_wheel_enabled is False
    assert actor.protocol_accordion_enabled is True

    UserService().update_self(db, actor, UserSelfUpdate(protocol_accordion_enabled=False))
    db.refresh(user)
    actor = build_current_user(db, user)
    assert actor.protocol_wheel_enabled is False
    assert actor.protocol_accordion_enabled is False
