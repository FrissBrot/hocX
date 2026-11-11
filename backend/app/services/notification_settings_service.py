"""ntfy-Konfiguration und Status-Token für Uptime Kuma (/admin/notifications). Genau eine Zeile in
platform_notification_settings (id = 1). Tokens nur verschlüsselt (secret_crypto)."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import urllib.parse
from dataclasses import replace
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.secret_crypto import decrypt_secret, encrypt_secret
from app.models import PlatformNotificationSettings
from app.schemas.admin import EmailSettingsRead, EmailSettingsWrite, NotificationSettingsRead, NotificationSettingsWrite
from app.services import ntfy_client

# Einfache Plausibilität für Absender- und Testadressen (kein vollständiger RFC-5322-Parser).
_EMAIL_PATTERN = re.compile(r"^[^@\s<>\"]+@[^@\s<>\"]+\.[^@\s<>\"]+$")
_HOST_PATTERN = re.compile(r"^[A-Za-z0-9.-]{1,255}$")

# ntfy erlaubt in Topic-Namen nur diese Zeichen (max. 64).
_TOPIC_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _validate_http_url(value: str | None, *, field: str) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"{field}: nur http(s)-URLs sind erlaubt")
    return value.rstrip("/")


def _status_url(token: str | None) -> str | None:
    if not token:
        return None
    path = "/api/system-status/summary?" + urllib.parse.urlencode({"token": token})
    return f"https://{settings.traefik_domain}{path}" if settings.traefik_domain else path


class NotificationSettingsService:
    def get_row(self, db: Session) -> PlatformNotificationSettings:
        row = db.get(PlatformNotificationSettings, 1)
        if row is None:
            row = PlatformNotificationSettings(id=1)
            db.add(row)
            db.commit()
            db.refresh(row)
        return row

    def read(self, db: Session) -> NotificationSettingsRead:
        row = self.get_row(db)
        status_token = decrypt_secret(row.status_token_encrypted) if row.status_token_encrypted else None
        return NotificationSettingsRead(
            ntfy_enabled=row.ntfy_enabled,
            ntfy_server_url=row.ntfy_server_url,
            ntfy_topic=row.ntfy_topic,
            ntfy_token_set=row.ntfy_token_encrypted is not None,
            admin_url=row.admin_url,
            reminder_hours=row.reminder_hours,
            status_token=status_token,
            status_url=_status_url(status_token),
            last_sent_at=row.last_sent_at,
            last_send_error=row.last_send_error,
            last_send_error_at=row.last_send_error_at,
        )

    def update(self, db: Session, payload: NotificationSettingsWrite) -> NotificationSettingsRead:
        server_url = _validate_http_url(payload.ntfy_server_url, field="ntfy-Server")
        admin_url = _validate_http_url(payload.admin_url, field="Admin-URL")
        topic = (payload.ntfy_topic or "").strip() or None
        if topic is not None and not _TOPIC_PATTERN.match(topic):
            raise ValueError("ntfy-Topic: nur Buchstaben, Ziffern, '-' und '_' (max. 64 Zeichen)")
        if payload.ntfy_enabled and (server_url is None or topic is None):
            raise ValueError("Für aktive Benachrichtigungen werden ntfy-Server und Topic benötigt")

        row = self.get_row(db)
        row.ntfy_enabled = payload.ntfy_enabled
        row.ntfy_server_url = server_url
        row.ntfy_topic = topic
        row.admin_url = admin_url
        row.reminder_hours = payload.reminder_hours
        if payload.ntfy_token is not None:
            token = payload.ntfy_token.strip()
            row.ntfy_token_encrypted = encrypt_secret(token) if token else None
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        return self.read(db)

    def rotate_status_token(self, db: Session) -> NotificationSettingsRead:
        token = secrets.token_urlsafe(32)
        row = self.get_row(db)
        row.status_token_hash = _hash_token(token)
        row.status_token_encrypted = encrypt_secret(token)
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        return self.read(db)

    def verify_status_token(self, db: Session, token: str | None) -> bool:
        row = db.get(PlatformNotificationSettings, 1)
        if not token or row is None or row.status_token_hash is None:
            return False
        return hmac.compare_digest(_hash_token(token), row.status_token_hash)

    def send(self, db: Session, message: ntfy_client.NtfyMessage) -> None:
        """Versendet über die gespeicherte Konfiguration und hält Erfolg/Fehler am Datensatz fest
        (für die Anzeige auf der Einstellungsseite). Wirft NtfyError weiter."""
        row = self.get_row(db)
        if not row.ntfy_server_url or not row.ntfy_topic:
            raise ntfy_client.NtfyError("ntfy-Server und Topic sind nicht konfiguriert")
        # click ist ein Pfad der Admin-Oberfläche ("/admin/system") - ohne konfigurierte Admin-URL
        # gibt es keinen sinnvollen Link, dann ohne.
        message = replace(message, click=row.admin_url + message.click if row.admin_url and message.click else None)
        token = decrypt_secret(row.ntfy_token_encrypted) if row.ntfy_token_encrypted else None
        now = datetime.now(timezone.utc)
        try:
            ntfy_client.send(server_url=row.ntfy_server_url, topic=row.ntfy_topic, token=token, message=message)
        except ntfy_client.NtfyError as exc:
            row.last_send_error = str(exc)[:500]
            row.last_send_error_at = now
            db.commit()
            raise
        row.last_sent_at = now
        row.last_send_error = None
        row.last_send_error_at = None
        db.commit()

    # ── E-Mail (SMTP, Migration 0170) ───────────────────────────────

    def read_email(self, db: Session) -> EmailSettingsRead:
        from sqlalchemy import func, select

        from app.models import Notification
        from app.notifications.email_transport import link_base_url

        row = self.get_row(db)
        counts = dict(db.execute(
            select(Notification.status, func.count()).where(Notification.status.in_(("pending", "failed"))).group_by(Notification.status)
        ).all())
        return EmailSettingsRead(
            email_enabled=row.email_enabled,
            smtp_host=row.smtp_host,
            smtp_port=row.smtp_port,
            smtp_security=row.smtp_security,  # type: ignore[arg-type]
            smtp_username=row.smtp_username,
            smtp_password_set=row.smtp_password_encrypted is not None,
            email_from_address=row.email_from_address,
            email_from_name=row.email_from_name,
            email_link_base_url=row.email_link_base_url,
            effective_link_base_url=link_base_url(row),
            email_last_sent_at=row.email_last_sent_at,
            email_last_error=row.email_last_error,
            email_last_error_at=row.email_last_error_at,
            pending_count=counts.get("pending", 0),
            failed_count=counts.get("failed", 0),
        )

    def update_email(self, db: Session, payload: EmailSettingsWrite) -> EmailSettingsRead:
        host = (payload.smtp_host or "").strip() or None
        if host is not None and not _HOST_PATTERN.match(host):
            raise ValueError("SMTP-Server: nur Hostname oder IP-Adresse")
        from_address = (payload.email_from_address or "").strip() or None
        if from_address is not None and not _EMAIL_PATTERN.match(from_address):
            raise ValueError("Absenderadresse ist keine gültige E-Mail-Adresse")
        link_base = _validate_http_url(payload.email_link_base_url, field="Link-Basis")
        if link_base is not None and not link_base.startswith("https://"):
            raise ValueError("Link-Basis: nur https-URLs")
        if payload.email_enabled and (host is None or from_address is None):
            raise ValueError("Für den Versand werden SMTP-Server und Absenderadresse benötigt")
        row = self.get_row(db)
        row.email_enabled = payload.email_enabled
        row.smtp_host = host
        row.smtp_port = payload.smtp_port
        row.smtp_security = payload.smtp_security
        row.smtp_username = (payload.smtp_username or "").strip() or None
        if payload.smtp_password is not None:
            row.smtp_password_encrypted = encrypt_secret(payload.smtp_password) if payload.smtp_password else None
        row.email_from_address = from_address
        row.email_from_name = payload.email_from_name.strip() or "hocX"
        row.email_link_base_url = link_base
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        return self.read_email(db)

    def send_test_email(self, db: Session, to: str) -> None:
        """Test-Mail mit der gespeicherten Konfiguration (auch wenn der Versand noch aus ist).
        Wirft ValueError bei ungültiger Adresse/fehlender Konfiguration, EmailError beim Versand."""
        from app.notifications import email_transport
        from app.notifications.render import render_test

        to = to.strip()
        if not _EMAIL_PATTERN.match(to):
            raise ValueError("Empfänger ist keine gültige E-Mail-Adresse")
        config = email_transport.load_config(db, require_enabled=False)
        if config is None:
            raise ValueError("SMTP-Server und Absenderadresse sind nicht konfiguriert")
        rendered = render_test(lang="de", base_url=config.link_base_url)
        row = self.get_row(db)
        now = datetime.now(timezone.utc)
        try:
            email_transport.send(config, email_transport.OutgoingEmail(to=to, subject=rendered.subject, text=rendered.text, html=rendered.html))
        except email_transport.EmailError as exc:
            row.email_last_error = str(exc)[:500]
            row.email_last_error_at = now
            db.commit()
            raise
        row.email_last_sent_at = now
        row.email_last_error = None
        row.email_last_error_at = None
        db.commit()
