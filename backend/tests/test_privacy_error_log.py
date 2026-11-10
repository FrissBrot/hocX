"""Datenschutz-Audit PRIV-002/PRIV-028: Das Fehlerprotokoll enthält keine Personendaten aus
SQL-Parametern oder Postgres-Details, speichert Akteure nur als ID und ordnet Fehler dem Mandanten
des Kontos zu."""
from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request

from app.core.config import settings
from app.core.error_log import best_effort_actor_from_request, record_system_error, redact
from app.core.security import create_session_token
from app.models import SystemErrorLog
from app.services.admin_error_log_service import AdminErrorLogService
from tests.factories import make_app_user, make_tenant


def _request_with_session(token: str) -> Request:
    cookie = f"{settings.auth_session_cookie}={token}".encode()
    return Request({"type": "http", "method": "GET", "path": "/api/x", "headers": [(b"cookie", cookie)], "query_string": b""})


def test_redact_removes_values_from_postgres_details_and_parameters():
    message = (
        '(psycopg.errors.UniqueViolation) duplicate key value violates unique constraint "uq_app_user_login_email"\n'
        "DETAIL:  Key (email)=(max.muster@example.ch) already exists.\n"
        "[SQL: INSERT INTO app_user (email, first_name) VALUES (%(email)s, %(first_name)s)]\n"
        "[parameters: {'email': 'max.muster@example.ch', 'first_name': 'Max'}]"
    )

    cleaned = redact(message)

    assert "max.muster" not in cleaned
    assert "'Max'" not in cleaned
    assert "uq_app_user_login_email" in cleaned  # Diagnose bleibt möglich
    assert redact("Kontakt hans@verein.ch fehlt") == "Kontakt <email> fehlt"


def test_integrity_error_is_logged_without_personal_data(db):
    tenant = make_tenant(db, "Fehlerlog")
    make_app_user(db, email="doppelt@example.com", tenant_id=tenant.id)
    # Zur Laufzeit erzeugt: der Traceback zitiert Quellzeilen, ein Literal stünde sonst dort.
    secret_name = "Geheim" + uuid.uuid4().hex[:8]
    nested = db.begin_nested()
    try:
        db.execute(
            text(
                "INSERT INTO app_user (tenant_id, email, password_hash, login_enabled, first_name, last_name, display_name, is_active) "
                "SELECT :tenant_id, :email, 'x', TRUE, :first, 'Name', :display, TRUE FROM app_user WHERE email = :email"
            ),
            # Wie in der App: Werte nur als gebundene Parameter.
            {"tenant_id": tenant.id, "email": "doppelt@example.com", "first": secret_name, "display": f"{secret_name} Name"},
        )
        raise AssertionError("Unique-Verletzung erwartet")
    except IntegrityError as exc:
        nested.rollback()
        record_system_error(db, exc=exc, tenant_id=tenant.id)

    entry = db.scalars(select(SystemErrorLog).where(SystemErrorLog.tenant_id == tenant.id)).one()
    assert "doppelt@example.com" not in entry.error_message
    assert "doppelt@example.com" not in (entry.traceback or "")
    assert secret_name not in (entry.traceback or "")
    assert entry.actor_email is None


def test_safety_net_assigns_tenant_and_actor_id_from_account(db):
    tenant = make_tenant(db, "Zuordnung")
    user = make_app_user(db, email="zuordnung@example.com", tenant_id=tenant.id)

    tenant_id, actor_user_id, actor_admin_id = best_effort_actor_from_request(db, _request_with_session(create_session_token(user.id)))

    assert (tenant_id, actor_user_id, actor_admin_id) == (tenant.id, user.id, None)


def test_admin_view_resolves_actor_only_while_account_exists(db):
    tenant = make_tenant(db, "Anzeige")
    user = make_app_user(db, email="anzeige@example.com", tenant_id=tenant.id)
    record_system_error(db, exc=RuntimeError("kaputt"), tenant_id=tenant.id, actor_user_id=user.id)
    service = AdminErrorLogService()

    first = service.list_errors(db, tenant_id=tenant.id)
    assert first.items[0].actor_email == "anzeige@example.com"

    db.delete(user)
    db.flush()
    db.expire_all()
    second = service.list_errors(db, tenant_id=tenant.id)
    assert second.items[0].actor_email is None
