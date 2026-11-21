"""E-Mail-Versand über SMTP mit der Konfiguration aus /admin/notifications (Migration 0170).

Das Passwort liegt verschlüsselt in platform_notification_settings (secret_crypto) und wird nur
für den Versand entschlüsselt. Tests ersetzen den Transport über ``override_transport``.
"""
from __future__ import annotations

import smtplib
import socket
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


# Fehlerklassen für den zentralen Versandstatus (delivery_status.py, /admin/system, ntfy). Bewusst
# grob: sie sagen, wo es klemmt, ohne Serverantworten, Adressen oder Zugangsdaten zu tragen.
REASONS = ("connection", "timeout", "tls", "auth", "sender_rejected", "recipient_rejected", "message_rejected", "rejected", "other")
# Fehler, die zu einer einzelnen Nachricht/Adresse gehören (abgelehnter Empfänger, Nicht-ASCII-Adresse
# ohne SMTPUTF8, zu gross, Inhaltsfilter): sagen nichts über den Dienst und dürfen - von einem Mandanten
# auslösbar - keine Anmeldungen anderer sperren (Security-Review M1).
MESSAGE_REASONS = frozenset({"recipient_rejected", "message_rejected"})


class EmailError(RuntimeError):
    """Versand fehlgeschlagen; die Meldung enthält keine Zugangsdaten und keine Empfängeradressen.
    ``reason`` ist eine der REASONS (Tests, die den Transport ersetzen, dürfen sie weglassen)."""

    def __init__(self, message: str, *, reason: str = "other") -> None:
        super().__init__(message)
        self.reason = reason if reason in REASONS else "other"


def classify(exc: BaseException, *, sending: bool = False) -> str:
    """Fehlerklasse einer SMTP-/Netzwerk-Ausnahme (Reihenfolge: speziell vor allgemein).
    ``sending``: der Fehler kam erst beim Übertragen der Nachricht (nach Verbindung, TLS und
    Anmeldung). Dann gilt eine Ablehnung als nachrichtenbezogen - ausser 421 (Dienst nicht verfügbar)
    und Verbindungsabbrüchen, die weiter den Dienst betreffen."""
    if sending and isinstance(exc, (smtplib.SMTPNotSupportedError, smtplib.SMTPSenderRefused, smtplib.SMTPDataError)):
        if not (isinstance(exc, smtplib.SMTPResponseException) and exc.smtp_code == 421):
            return "message_rejected"
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "auth"
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "recipient_rejected"
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return "sender_rejected"
    if isinstance(exc, (ssl.SSLError, smtplib.SMTPNotSupportedError)):
        return "tls"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(exc, (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, ConnectionError, socket.gaierror)):
        return "connection"
    if isinstance(exc, smtplib.SMTPResponseException):
        return "rejected"
    if isinstance(exc, OSError):
        return "connection"
    return "other"


def _safe_detail(exc: BaseException) -> str:
    """Fehlertext ohne Empfängeradressen: SMTPRecipientsRefused trägt im Text die abgelehnten
    Adressen (dict Adresse -> Antwort) - dort nur die Statuscodes behalten."""
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        codes = sorted({str(code) for code, _message in exc.recipients.values()})
        return f"{type(exc).__name__}: {', '.join(codes) or '-'}"
    # Serverantworten können Adressen enthalten («550 <x@y> rejected») - wie im Fehlerprotokoll maskieren
    from app.core.error_log import redact

    return redact(f"{type(exc).__name__}: {str(exc)[:300]}")


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
    # Eingebettete Bilder (Vereinslogo) als multipart/related zum HTML-Teil, referenziert über cid:
    images: tuple = ()


Transport = Callable[[EmailConfig, OutgoingEmail], None]
Probe = Callable[[EmailConfig], None]
_override: Transport | None = None
_override_probe: Probe | None = None


def override_transport(transport: Transport | None) -> None:
    """Nur für Tests: Versand abfangen (None stellt SMTP wieder her)."""
    global _override
    _override = transport


def override_probe(probe: Probe | None) -> None:
    """Nur für Tests: Verbindungsprobe ersetzen (None stellt SMTP wieder her)."""
    global _override_probe
    _override_probe = probe


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
    if email.images:
        html_part = message.get_payload()[1]
        for image in email.images:
            html_part.add_related(image.data, maintype="image", subtype=image.subtype, cid=f"<{image.cid}>", disposition="inline")
    return message


def _smtp_session(config: EmailConfig, action: Callable[[smtplib.SMTP], None], timeout: float = SMTP_TIMEOUT_SECONDS) -> None:
    context = ssl.create_default_context()
    sending = False
    try:
        if config.security == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(config.host, config.port, timeout=timeout, context=context)
        else:
            client = smtplib.SMTP(config.host, config.port, timeout=timeout)
        with client:
            if config.security == "starttls":
                client.starttls(context=context)
            if config.username:
                client.login(config.username, config.password or "")
            sending = True
            action(client)
    except (smtplib.SMTPException, OSError) as exc:
        # Nur Art und Text des Fehlers, nie Zugangsdaten oder Empfängeradressen
        raise EmailError(_safe_detail(exc), reason=classify(exc, sending=sending)) from exc


def _smtp_send(config: EmailConfig, email: OutgoingEmail) -> None:
    _smtp_session(config, lambda client: client.send_message(_message(config, email)))


def _smtp_probe(config: EmailConfig) -> None:
    def noop(client: smtplib.SMTP) -> None:
        code, _message = client.noop()
        if code != 250:
            raise smtplib.SMTPResponseException(code, b"NOOP")

    _smtp_session(config, noop, timeout=10)


def send(config: EmailConfig, email: OutgoingEmail) -> None:
    """Eine Mail versenden. Wirft EmailError. Den zentralen Versandstatus meldet der Aufrufer
    (delivery_status.record_success/record_failure), weil nur er Session und Anlass kennt."""
    (_override or _smtp_send)(config, email)


def probe(config: EmailConfig) -> None:
    """Verbindung, TLS und Anmeldung am SMTP-Server prüfen, ohne eine Mail zu senden (NOOP).
    Wirft EmailError. Für die Erholung nach Verbindungs-/Anmeldefehlern (delivery_status)."""
    (_override_probe or _smtp_probe)(config)
