"""«Die aktuelle Session bleibt» gilt auch auf einer Mandanten-Domain.

Auf einer eigenen App-Domain des Vereins ist die Session ein Kind der Session auf der Hauptdomain
(Domain-Bridge, ``auth_session.parent_id``) und lebt nie länger als diese. Passwort ändern,
Faktor hinzufügen/entfernen und «Andere Geräte abmelden» behalten die aktuelle Session - dort
widerrief ``revoke_all(except_id=Kind)`` aber die Eltern-Session, womit die eigene Kind-Session
beim nächsten Request ungültig war (Abmeldung statt «bleibt angemeldet»).
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import Response
from starlette.requests import Request

from app.api.routes import users as users_route
from app.auth_security import sessions
from app.core.security import build_current_user, create_session_token, validate_session_token
from app.models import AuthSession
from app.schemas.user import UserPasswordChange
from tests.factories import make_app_user, make_tenant

PASSWORD = "correct horse battery staple"


def _req() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/api/users/me/password", "query_string": b"", "headers": []})


def _session_token(response: Response) -> str:
    for header in response.headers.getlist("set-cookie"):
        name, _, rest = header.partition("=")
        if name.endswith("hocx_session"):
            return rest.split(";", 1)[0]
    raise AssertionError("kein Session-Cookie gesetzt")


def _on_custom_domain(db, email: str):
    user = make_app_user(db, email=email, tenant_id=make_tenant(db).id, role_code="writer")
    parent = sessions.create(db, user_id=user.id, tenant_id=user.tenant_id, mfa=False, amr=["pwd"], host="hocx.example")
    child = sessions.create(
        db, user_id=user.id, tenant_id=user.tenant_id, mfa=False, amr=["bridge"], parent_id=parent.id,
        host="verein.example", expires_at=parent.expires_at,
    )
    other = sessions.create(db, user_id=user.id, tenant_id=user.tenant_id, mfa=False, amr=["pwd"], host="hocx.example")
    current = build_current_user(db, user)
    current.session_id = child.id
    current.auth_time = datetime.now(UTC)
    return user, parent, child, other, current


def test_revoke_others_keeps_the_current_bridge_session(db):
    user, parent, child, other, current = _on_custom_domain(db, "bridge-others@example.com")
    parent_cookie = create_session_token(user.id, sid=str(parent.id), expires_at=parent.expires_at)
    assert validate_session_token(db, parent_cookie) is not None
    response = Response()
    users_route.revoke_my_other_sessions(response, db=db, user=current)
    db.expire_all()
    # Das Cookie der Hauptdomain endet trotzdem (session_revoke_at), nur der Registereintrag bleibt
    assert validate_session_token(db, parent_cookie) is None
    assert db.get(AuthSession, other.id).revoked_at is not None
    assert validate_session_token(db, _session_token(response)) is not None
    assert db.get(AuthSession, child.id).revoked_at is None


def test_password_change_keeps_the_current_bridge_session(db):
    _user, _parent, child, other, current = _on_custom_domain(db, "bridge-password@example.com")
    response = Response()
    users_route.change_my_password(
        UserPasswordChange(current_password=PASSWORD, new_password="Kx7#qLm2!vRt9wZp"), _req(), response, db=db, user=current,
    )
    db.expire_all()
    assert db.get(AuthSession, other.id).revoked_at is not None
    assert validate_session_token(db, _session_token(response)) is not None
    assert db.get(AuthSession, child.id).revoked_at is None
