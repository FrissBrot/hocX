"""Sicherheitsmails an die Person bei riskanten/verdächtigen Anmeldungen.

Über die bestehende Benachrichtigungs-Infrastruktur (``app.notifications.publish``, Versand-Loop
``notification_dispatch``, Texte in allen Sprachen). Dedupe über ``publish(dedupe=...)``, nie eine
Mail je Fehlversuch:

| Art | Auslöser | Dedupe | abschaltbar |
|---|---|---|---|
| ``security.login_new_device`` | erfolgreiche Anmeldung, Gerät dem Konto unbekannt, Konto hat schon andere bekannte Geräte | je Gerät | ja (Kategorie ``security_logins``) |
| ``security.login_suspicious`` | erfolgreiche Anmeldung mit Risiko «hoch» oder «kritisch» | je Netz und Tag | nein |
| ``security.failed_attempts`` | Fehlversuche auf das Konto erreichen ``auth_account_failures_challenge`` | je 6-h-Fenster | nein |
| ``security.login_after_lockout`` | erfolgreiche Anmeldung, nachdem das Konto/der Faktor gesperrt war | je Tag | nein |

Entscheid Abschaltbarkeit (DSGVO Art. 32, Datenminimierung): Warnungen, die auf einen laufenden
Angriff oder eine mögliche Übernahme hinweisen, sind Teil der Sicherheit des Kontos und gehen wie
die bestehenden Hinweise zu Passwort- und MFA-Änderungen immer raus. «Neues Gerät» ist bei
normaler Nutzung häufig und wird deshalb abschaltbar angeboten (Standard: an). Die Mails enthalten
nur Zeitpunkt, grobe Gerätebeschreibung und Gründe - keine IP, keinen Ort, keine Links mit Token.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import AppUser
from app.notifications import publish


def _payload(**values) -> dict:
    return {"at": datetime.now(UTC).isoformat(), **{key: value for key, value in values.items() if value is not None}}


def _eligible(user: AppUser | None) -> bool:
    return user is not None and user.login_enabled and user.is_active and bool((user.email or "").strip())


def new_device(db: Session, user: AppUser, *, device_hash: str, device: str | None) -> None:
    if _eligible(user):
        publish(db, kind="security.login_new_device", tenant_id=user.tenant_id, recipient_ids=[user.id],
                payload=_payload(device=device), dedupe=f"device:{device_hash}")


def suspicious_login(db: Session, user: AppUser, *, net_hash: str | None, device: str | None, reasons: list[str]) -> None:
    if _eligible(user):
        day = datetime.now(UTC).strftime("%Y%m%d")
        publish(db, kind="security.login_suspicious", tenant_id=user.tenant_id, recipient_ids=[user.id],
                payload=_payload(device=device, reasons=reasons[:8]), dedupe=f"{net_hash or '-'}:{day}")


def failed_attempts(db: Session, user: AppUser, *, count: int) -> None:
    if _eligible(user):
        now = datetime.now(UTC)
        window = f"{now:%Y%m%d}-{now.hour // 6}"
        publish(db, kind="security.failed_attempts", tenant_id=user.tenant_id, recipient_ids=[user.id],
                payload=_payload(count=count), dedupe=window)


def login_after_lockout(db: Session, user: AppUser, *, device: str | None) -> None:
    if _eligible(user):
        publish(db, kind="security.login_after_lockout", tenant_id=user.tenant_id, recipient_ids=[user.id],
                payload=_payload(device=device), dedupe=datetime.now(UTC).strftime("%Y%m%d"))
