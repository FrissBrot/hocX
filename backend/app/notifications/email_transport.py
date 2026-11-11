"""E-Mail-Versand über SMTP mit der Konfiguration aus /admin/notifications (Migration 0170).

Das Passwort liegt verschlüsselt in platform_notification_settings (secret_crypto) und wird nur
für den Versand entschlüsselt. Tests ersetzen den Transport über ``override_transport``.
"""
from __future__ import annotations

import smtplib
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.secret_crypto import decrypt_secret
from app.models import PlatformNotificationSettings

SMTP_TIMEOUT_SECONDS = 20


class EmailError(RuntimeError):
    """Versand fehlgeschlagen; die Meldung enthält keine Zugangsdaten."""


@dataclass(frozen=True)
class EmailConfig:
    host: str
    port: int
    security: str
    username: str | None
    password: str | None
    from_address: str
    from_name: str
    link_base_url: str | None


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    subject: str
    text: str
    html: str


Transport = Callable[[EmailConfig, OutgoingEmail], None]
_override: Transport | None = None


def override_transport(transport: Transport | None) -> None:
    """Nur für Tests: Versand abfangen (None stellt SMTP wieder her)."""
    global _override
    _override = transport


def link_base_url(row: PlatformNotificationSettings) -> str | None:
    if row.email_link_base_url:
        return row.email_link_base_url.rstrip("/")
    return f"https://{settings.traefik_domain}" if settings.traefik_domain else None


def load_config(db: Session, *, require_enabled: bool = True) -> EmailConfig | None:
    """Konfiguration oder None, wenn der Versand aus ist oder Angaben fehlen."""
    row = db.get(PlatformNotificationSettings, 1)
    if row is None or (require_enabled and not row.email_enabled) or not row.smtp_host or not row.email_from_address:
        return None
    return EmailConfig(
        host=row.smtp_host, port=row.smtp_port, security=row.smtp_security, username=row.smtp_username or None,
        password=decrypt_secret(row.smtp_password_encrypted) if row.smtp_password_encrypted else None,
        from_address=row.email_from_address, from_name=row.email_from_name or "hocX", link_base_url=link_base_url(row),
    )


def _message(config: EmailConfig, email: OutgoingEmail) -> EmailMessage:
    message = EmailMessage()
    message["From"] = formataddr((config.from_name, config.from_address))
    message["To"] = email.to.strip()
    message["Subject"] = email.subject
    message["Message-ID"] = make_msgid(domain=config.from_address.rpartition("@")[2] or None)
    # Automatisch erzeugt: keine Abwesenheitsnotizen zurück (RFC 3834)
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(email.text)
    message.add_alternative(email.html, subtype="html")
    return message


def _smtp_send(config: EmailConfig, email: OutgoingEmail) -> None:
    context = ssl.create_default_context()
    try:
        if config.security == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(config.host, config.port, timeout=SMTP_TIMEOUT_SECONDS, context=context)
        else:
            client = smtplib.SMTP(config.host, config.port, timeout=SMTP_TIMEOUT_SECONDS)
        with client:
            if config.security == "starttls":
                client.starttls(context=context)
            if config.username:
                client.login(config.username, config.password or "")
            client.send_message(_message(config, email))
    except (smtplib.SMTPException, OSError) as exc:
        # Nur Art und Text des Fehlers, nie Zugangsdaten
        raise EmailError(f"{type(exc).__name__}: {str(exc)[:300]}") from exc


def send(config: EmailConfig, email: OutgoingEmail) -> None:
    (_override or _smtp_send)(config, email)
