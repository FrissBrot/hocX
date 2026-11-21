"""Maildienst-Ausfall erkennen (1.5.1): zentraler Versandstatus (notifications/delivery_status.py),
Login mit gestörtem Versand, Monitoring-Problem email:smtp:<reason>, Erholung."""
from __future__ import annotations

import smtplib
import ssl
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import select, text
from starlette.requests import Request

from app.auth_security import devices, events
from app.core.redis_client import get_redis_sync
from app.models import AuthEvent, PlatformNotificationSettings, SystemErrorLog
from app.notifications import delivery_status, dispatch, email_transport
from app.schemas.admin import JobStatusOverview
from app.schemas.user import LoginRequest
from app.services import system_alert_service, system_health_service
from app.services.auth_service import AuthService
from app.services.notification_settings_service import NotificationSettingsService
from tests.factories import make_app_user, make_mfa_enrolled_user, make_tenant

PASSWORD = "correct horse battery staple"
NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


def _flush_redis() -> None:
    client = get_redis_sync()
    for pattern in ("ratelimit:*", "authsec:*", "authblock:*", "mfa:flow:*", "hocx:mail_status:*"):
        for key in client.scan_iter(pattern):
            client.delete(key)
    from app.core import rate_limit

    rate_limit.local_window.clear()


@pytest.fixture(autouse=True)
def _clean():
    _flush_redis()
    yield
    _flush_redis()
    email_transport.override_transport(None)
    email_transport.override_probe(None)


class Transport:
    """Ersetzt SMTP: zählt Versuche, scheitert mit ``error`` (None = Erfolg)."""

    def __init__(self) -> None:
        self.error: email_transport.EmailError | None = None
        self.sent: list = []
        self.attempts = 0

    def __call__(self, config, email) -> None:
        self.attempts += 1
        if self.error is not None:
            raise self.error
        self.sent.append(email)


@pytest.fixture
def smtp(db):
    row = NotificationSettingsService().get_row(db)
    row.email_enabled = True
    row.smtp_host = "smtp.example.com"
    row.email_from_address = "noreply@example.com"
    row.email_link_base_url = "https://app.example.com"
    db.commit()
    transport = Transport()
    email_transport.override_transport(transport)
    return transport


def _auth_error() -> email_transport.EmailError:
    return email_transport.EmailError("SMTPAuthenticationError: (535, b'auth failed')", reason="auth")


def _req(cookies: dict[str, str] | None = None) -> Request:
    header = "; ".join(f"{name}={value}" for name, value in (cookies or {}).items())
    return Request({"type": "http", "method": "POST", "path": "/api/auth/login", "query_string": b"", "headers": [(b"cookie", header.encode())] if header else []})


def _login(db, email: str, password: str = PASSWORD, *, ip: str = "203.0.113.150", cookies: dict | None = None):
    return AuthService().login(db, Response(), LoginRequest(email=email, password=password), client_address=ip, request=_req(cookies))


def _risky_user(db, email: str):
    """Admin ohne Faktor mit bekanntem Netz: Anmeldung aus neuem Netz braucht einen Mailcode
    (wie test_auth_hardening::test_risky_login_without_factor_requires_an_email_code)."""
    tenant = make_tenant(db)
    user = make_app_user(db, email=email, tenant_id=tenant.id, role_code="admin")
    events.record(event_type="login.success", outcome="success", user_id=user.id, tenant_id=tenant.id)
    db.execute(text("UPDATE auth_event SET src_net_hash = 'bekanntes-netz' WHERE actor_user_id = :id"), {"id": user.id})
    db.commit()
    return user


def _mail_errors(db) -> list[SystemErrorLog]:
    db.expire_all()
    return list(db.scalars(select(SystemErrorLog).where(SystemErrorLog.error_type == "MailDeliveryFailure").order_by(SystemErrorLog.id)))


# ── Transport: Fehlerklassen ohne Adressen ───────────────────────────────────────────────


def test_classify_smtp_errors():
    assert email_transport.classify(smtplib.SMTPAuthenticationError(535, b"no")) == "auth"
    assert email_transport.classify(smtplib.SMTPRecipientsRefused({"a@example.com": (550, b"no")})) == "recipient_rejected"
    assert email_transport.classify(smtplib.SMTPSenderRefused(553, b"no", "noreply@example.com")) == "sender_rejected"
    assert email_transport.classify(ssl.SSLError("bad cert")) == "tls"
    assert email_transport.classify(smtplib.SMTPNotSupportedError("STARTTLS")) == "tls"
    assert email_transport.classify(TimeoutError()) == "timeout"
    assert email_transport.classify(ConnectionRefusedError()) == "connection"
    assert email_transport.classify(smtplib.SMTPServerDisconnected("weg")) == "connection"
    assert email_transport.classify(smtplib.SMTPDataError(554, b"spam")) == "rejected"
    assert email_transport.classify(ValueError("x")) == "other"
    # Erst beim Übertragen: nachrichtenbezogen (z. B. Nicht-ASCII-Adresse ohne SMTPUTF8, 552 zu gross,
    # Inhaltsfilter) - ein Mandant soll damit nicht alle Anmeldungen sperren können (Review M1)
    assert email_transport.classify(smtplib.SMTPNotSupportedError("SMTPUTF8"), sending=True) == "message_rejected"
    assert email_transport.classify(smtplib.SMTPSenderRefused(552, b"too big", "noreply@example.com"), sending=True) == "message_rejected"
    assert email_transport.classify(smtplib.SMTPDataError(554, b"spam"), sending=True) == "message_rejected"
    assert email_transport.classify(smtplib.SMTPDataError(421, b"try later"), sending=True) == "rejected"
    assert email_transport.classify(smtplib.SMTPServerDisconnected("weg"), sending=True) == "connection"


def test_non_ascii_address_does_not_mark_the_service_failing(db, smtp, monkeypatch):
    class Utf8Unsupported:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def starttls(self, **_kwargs):
            return (220, b"ok")

        def send_message(self, _message):
            raise smtplib.SMTPNotSupportedError("SMTPUTF8 not supported by server")

    email_transport.override_transport(None)
    monkeypatch.setattr(email_transport.smtplib, "SMTP", Utf8Unsupported)
    config = email_transport.load_config(db)
    with pytest.raises(email_transport.EmailError) as exc:
        email_transport.send(config, email_transport.OutgoingEmail(to="jörg@example.com", subject="s", text="t", html="h"))
    delivery_status.record_failure(db, exc.value, kind="dispatch")
    status = delivery_status.read(db)
    assert status.reason == "message_rejected" and not status.blocks_login


def test_status_write_failure_never_rolls_back_a_sent_mail(db, smtp, monkeypatch):
    """Review N1: scheitert das Status-UPDATE nach erfolgreichem Versand, bleibt die Arbeit des
    Aufrufers gespeichert und es wird nichts geworfen."""
    def boom(*_args, **_kwargs):
        raise RuntimeError("lock timeout")

    monkeypatch.setattr(delivery_status, "_write_success", boom)
    delivery_status.record_success(db)  # wirft nicht
    assert any(entry.error_message == "lock timeout" for entry in db.scalars(select(SystemErrorLog).where(SystemErrorLog.error_type == "RuntimeError")))


def test_smtp_error_text_has_no_recipient_address(monkeypatch):
    class Refusing:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def send_message(self, _message):
            raise smtplib.SMTPRecipientsRefused({"geheim.person@example.com": (550, b"5.1.1 user unknown geheim.person@example.com")})

    config = email_transport.EmailConfig("smtp.example.com", 587, "none", None, None, "noreply@example.com", "hocX", None)
    monkeypatch.setattr(email_transport.smtplib, "SMTP", Refusing)
    with pytest.raises(email_transport.EmailError) as exc:
        email_transport._smtp_send(config, email_transport.OutgoingEmail(to="geheim.person@example.com", subject="s", text="t", html="h"))
    assert exc.value.reason == "recipient_rejected"
    assert "geheim" not in str(exc.value) and "550" in str(exc.value)


def test_server_answers_are_redacted():
    detail = email_transport._safe_detail(smtplib.SMTPDataError(550, b"<anna.muster@example.com> rejected after DATA"))
    assert "anna.muster" not in detail and "<email>" in detail


# ── Zentraler Status ─────────────────────────────────────────────────────────────────────


def test_not_configured_is_a_quiet_own_state(db):
    row = NotificationSettingsService().get_row(db)
    row.email_enabled = False
    db.commit()
    assert delivery_status.read(db).state == "disabled"
    check = system_health_service._check_email(db)
    assert check.status == "unknown" and check.params["state"] == "disabled"
    problems = system_alert_service.derive_problems(_snapshot([check]), JobStatusOverview(items=[], generated_at=NOW), now=NOW)
    assert not [problem for problem in problems if problem.source == "email"]


def test_first_failure_marks_failing_and_first_success_recovers(db, smtp):
    assert delivery_status.read(db).state == "never"
    delivery_status.record_failure(db, _auth_error(), kind="dispatch")
    delivery_status.record_failure(db, _auth_error(), kind="dispatch")
    status = delivery_status.read(db)
    assert (status.state, status.failures, status.reason) == ("failing", 2, "auth")
    assert status.blocks_login and status.failing_since is not None and status.last_failure_at is not None
    # Ins Fehlerprotokoll: einmal (Übergang), nicht je Fehler; Quelle bleibt der Default
    errors = _mail_errors(db)
    assert len(errors) == 1 and errors[0].source == "backend" and "(dispatch, auth)" in errors[0].error_message
    delivery_status.record_success(db)
    status = delivery_status.read(db)
    assert (status.state, status.failures, status.reason, status.failing_since) == ("ok", 0, None, None)
    assert status.last_success_at is not None
    row = db.get(PlatformNotificationSettings, 1)
    assert row.email_last_error is None and row.email_last_error_at is None


def test_new_failure_class_is_logged_again(db, smtp):
    delivery_status.record_failure(db, _auth_error(), kind="dispatch")
    delivery_status.record_failure(db, email_transport.EmailError("ConnectionRefusedError: x", reason="connection"), kind="dispatch")
    assert len(_mail_errors(db)) == 2


def test_rejected_recipients_only_warn_and_never_block_logins(db, smtp):
    rejected = email_transport.EmailError("SMTPRecipientsRefused: 550", reason="recipient_rejected")
    for _ in range(delivery_status.RECIPIENT_REJECTED_THRESHOLD - 1):
        delivery_status.record_failure(db, rejected, kind="dispatch")
    below = delivery_status.read(db)
    assert below.state == "ok" and not below.blocks_login and below.failures == delivery_status.RECIPIENT_REJECTED_THRESHOLD - 1
    delivery_status.record_failure(db, rejected, kind="dispatch")
    status = delivery_status.read(db)
    assert status.state == "rejecting" and not status.blocks_login
    check = system_health_service._check_email(db)
    problems = system_alert_service.derive_problems(_snapshot([check]), JobStatusOverview(items=[], generated_at=NOW), now=NOW)
    email = [problem for problem in problems if problem.source == "email"]
    assert [(p.key, p.severity) for p in email] == [("email:smtp:recipient_rejected", "warning")]


# ── Login ────────────────────────────────────────────────────────────────────────────────


def test_login_needing_a_code_fails_clearly_when_sending_fails(db, smtp):
    user = _risky_user(db, "mailout-risky@example.com")
    smtp.error = _auth_error()
    with pytest.raises(HTTPException) as exc:
        _login(db, user.email)
    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "auth_email_unavailable"
    assert "Administrator" in exc.value.detail["message"]
    assert smtp.attempts == 1
    assert delivery_status.read(db).state == "failing"
    db.expire_all()
    assert db.scalar(select(AuthEvent).where(AuthEvent.actor_user_id == user.id, AuthEvent.outcome == "blocked")) is not None

    # Gestört: der nächste Login versucht gar nicht erst zu senden (sofortige Antwort)
    with pytest.raises(HTTPException) as exc:
        _login(db, user.email)
    assert exc.value.detail["code"] == "auth_email_unavailable" and smtp.attempts == 1

    # Falsches Passwort bleibt «ungültig» - kein Orakel über den Versandstatus vor dem Passwort
    with pytest.raises(HTTPException) as exc:
        _login(db, user.email, "falsch-falsch-falsch")
    assert exc.value.detail["code"] == "invalid_credentials"

    # Erholung: nach Ablauf der Sperre (hier gelöscht) versucht ein Login wieder echt und klappt
    get_redis_sync().delete(delivery_status._LOGIN_RETRY_KEY)
    smtp.error = None
    result = _login(db, user.email)
    assert result.mfa is not None and result.mfa.status == "email_verification_required"
    assert delivery_status.read(db).state == "ok"


def test_known_devices_and_accounts_with_a_factor_are_unaffected(db, smtp):
    delivery_status.record_failure(db, _auth_error(), kind="dispatch")
    user = _risky_user(db, "mailout-known@example.com")
    device_id = devices.new_device_id()
    devices.remember(db, user_id=user.id, tenant_id=user.tenant_id, device_id=device_id, user_agent_family="Firefox · Linux")
    db.flush()
    result = _login(db, user.email, cookies={devices.cookie_name(): devices.encode_cookie(device_id)})
    assert result.mfa is None or result.mfa.status != "email_verification_required"

    enrolled, _secret = make_mfa_enrolled_user(db, email="mailout-factor@example.com")
    result = _login(db, enrolled.email)
    assert not result.authenticated and result.mfa.status == "verification_required"
    assert smtp.attempts == 0


def test_resend_with_failing_mail_uses_the_same_code(db, smtp):
    from app.auth_security import email_challenge

    user = _risky_user(db, "mailout-resend@example.com")
    ticket = _login(db, user.email).mfa.ticket
    smtp.error = _auth_error()
    with pytest.raises(HTTPException) as exc:
        email_challenge.resend(db, ticket)
    assert exc.value.detail["code"] == "auth_email_unavailable"


def test_password_reset_availability_reports_disturbance(db, smtp):
    from app.api.routes.auth import password_reset_available

    request = Request({"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": [], "client": ("203.0.113.9", 1)})
    assert password_reset_available(request, db).model_dump() == {"enabled": True, "disturbed": False}
    delivery_status.record_failure(db, _auth_error(), kind="dispatch")
    assert password_reset_available(request, db).model_dump() == {"enabled": True, "disturbed": True}


# ── Monitoring und Erholung ──────────────────────────────────────────────────────────────


def _snapshot(checks):
    from app.schemas.admin import SystemHealthSnapshot

    return SystemHealthSnapshot(collected_at=NOW, docker_configured=False, docker_available=False, checks=checks)


def test_monitoring_reports_failing_mail_as_critical_problem(db, smtp):
    delivery_status.record_failure(db, _auth_error(), kind="login_code")
    check = system_health_service._check_email(db)
    assert check.status == "critical"
    assert check.params["failures"] == 1 and check.params["reason"] == "auth" and check.params["failingSince"]
    assert any(c.key == "email" for c in system_health_service.collect_checks(db, NOW))
    problems = system_alert_service.derive_problems(_snapshot([check]), JobStatusOverview(items=[], generated_at=NOW), now=NOW)
    email = [problem for problem in problems if problem.source == "email"]
    assert len(email) == 1
    problem = email[0]
    assert (problem.key, problem.subject, problem.reason, problem.severity) == ("email:smtp:auth", "smtp", "auth", "critical")
    assert "Anmeldung am SMTP-Server abgelehnt" in problem.title and "Test-Mail" in problem.message
    assert not [p for p in problems if p.key == "check:email"]

    delivery_status.record_success(db)
    check = system_health_service._check_email(db)
    assert check.status == "ok" and check.params["lastSuccessAt"]
    problems = system_alert_service.derive_problems(_snapshot([check]), JobStatusOverview(items=[], generated_at=NOW), now=NOW)
    assert not [problem for problem in problems if problem.source == "email"]


def test_dispatch_probe_recovers_without_mail_traffic(db, smtp):
    delivery_status.record_failure(db, email_transport.EmailError("ConnectionRefusedError: x", reason="connection"), kind="dispatch")
    probes: list = []

    def failing_probe(config):
        probes.append(config)
        raise email_transport.EmailError("ConnectionRefusedError: x", reason="connection")

    email_transport.override_probe(failing_probe)
    assert dispatch.run(db).get("probe_failed") == 1
    assert delivery_status.read(db).failures == 2
    email_transport.override_probe(lambda config: probes.append(config))
    assert dispatch.run(db).get("probe_ok") == 1
    assert delivery_status.read(db).state == "ok" and len(probes) == 2
    # Nicht gestört: keine Probe
    assert "probe_ok" not in dispatch.run(db) and len(probes) == 2


def test_no_probe_for_rejections_the_probe_cannot_see(db, smtp):
    delivery_status.record_failure(db, email_transport.EmailError("SMTPSenderRefused: 553", reason="sender_rejected"), kind="dispatch")
    email_transport.override_probe(lambda config: pytest.fail("keine Probe erwartet"))
    assert not any(key.startswith("probe") for key in dispatch.run(db))
    assert delivery_status.read(db).state == "failing"


def test_test_mail_records_failure_and_success(db, smtp):
    service = NotificationSettingsService()
    smtp.error = _auth_error()
    with pytest.raises(email_transport.EmailError):
        service.send_test_email(db, "admin@example.com")
    assert delivery_status.read(db).state == "failing"
    smtp.error = None
    service.send_test_email(db, "admin@example.com")
    assert delivery_status.read(db).state == "ok"
