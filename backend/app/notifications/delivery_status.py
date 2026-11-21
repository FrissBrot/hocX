"""Zentraler Status des E-Mail-Versands (Version 1.5.1, «Maildienst-Ausfall erkennen»).

Jeder Versandversuch über ``email_transport.send`` meldet sein Ergebnis hierher: der Loop
notification_dispatch (alle Benachrichtigungen inkl. Einladung, Passwort-Reset, Konto-Mails), der
Login-Bestätigungscode (auth_security/email_challenge.py) und die Test-Mail aus dem Adminportal.
Dazu kommt die Verbindungsprobe des Loops (``probe_if_idle``).

Der Status liegt dauerhaft in ``platform_notification_settings`` (Migration 0210): letzter Erfolg
(``email_last_sent_at``), letzter Fehler (``email_last_error[_at]``, Text ohne Zugangsdaten und
Empfängeradressen), Fehlerklasse, Fehler in Folge und «gestört seit». Kein Redis-Zustand: die
Datenbank ist für alle Prozesse (backend, job-worker) dieselbe Quelle und übersteht Neustarts.

Bewertung (``read``):
- ``disabled``: Versand nicht eingerichtet - ruhig, kein Alarm, Login wie bisher (smtp-Zweig).
- ``failing``: mindestens ein Fehler seit dem letzten Erfolg. Schon ein Fehler genügt, weil jeder
  Fehler hier einen echten Verbindungs-, TLS-, Anmelde- oder Annahmefehler des Servers bedeutet
  (keine Zustellprobleme beim Empfänger, die meldet SMTP erst später per Bounce) - und weil ein
  einzelner Login-Code, der nicht ankommt, die Anmeldung schon verhindert.
  Ausnahme nachrichtenbezogene Fehler (``email_transport.MESSAGE_REASONS``: abgelehnter Empfänger,
  Ablehnung erst beim Übertragen, z. B. Nicht-ASCII-Adresse, zu gross, Inhaltsfilter). Die sagen
  nichts über den Dienst und lassen sich von einem Mandanten über Personendaten auslösen - sie
  dürfen Anmeldungen anderer nicht sperren. Erst ab RECIPIENT_REJECTED_THRESHOLD in Folge ohne
  Erfolg dazwischen (z. B. «Relay access denied» für alle) gilt der Versand als ``rejecting``
  (Warnung im Monitoring, sperrt keine Anmeldungen; der einzelne Login, dessen Code nicht rausgeht,
  bekommt trotzdem die klare Meldung).
- ``never``: eingerichtet, aber noch nie etwas versendet; sonst ``ok``.
Der erste Erfolg (Mail oder Probe) hebt jeden Fehlerzustand auf.

Fehler landen zusätzlich in system_error_log (CLAUDE.md «Zentrale Fehlererfassung»), gedrosselt:
beim ersten Fehler nach einem Erfolg, bei neuer Fehlerklasse und sonst höchstens stündlich je
Klasse - ein ausgefallener Server soll das Protokoll nicht mit hunderten Einträgen füllen.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.error_log import record_system_error
from app.core.redis_client import get_redis_sync
from app.models import PlatformNotificationSettings
from app.notifications import email_transport

_logger = logging.getLogger(__name__)

KINDS = ("dispatch", "login_code", "test", "probe")
RECIPIENT_REJECTED_THRESHOLD = 3
# Während einer Störung darf höchstens ein Login je Zeitraum den Versand wirklich versuchen (dient
# zugleich als Probe); alle anderen bekommen sofort «Anmeldung aktuell nicht möglich».
LOGIN_RETRY_SECONDS = 60
# Ein Erfolg schreibt nur, wenn sich etwas ändert oder der letzte Erfolg so alt ist - der Loop
# verschickt bis zu 200 Mails je Lauf und soll nicht 200-mal dieselbe Zeile ändern.
SUCCESS_WRITE_INTERVAL_SECONDS = 60
ERROR_LOG_INTERVAL_SECONDS = 3600
# Erholung per Probe nur, wo eine Verbindung ohne Mail etwas aussagt.
PROBE_REASONS = frozenset({"connection", "timeout", "tls", "auth"})

_LOGIN_RETRY_KEY = "hocx:mail_status:login_retry"
_ERROR_LOGGED_KEY = "hocx:mail_status:error_logged:"


class MailDeliveryFailure(RuntimeError):
    """Eintrag im Fehlerprotokoll für einen gescheiterten Versand (ohne verketteten Stacktrace, damit
    keine Serverantwort mit Adressen mitwandert; der Text ist bereits bereinigt)."""


@dataclass(frozen=True)
class DeliveryStatus:
    state: str  # disabled | never | ok | failing | rejecting
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    failing_since: datetime | None = None
    failures: int = 0
    reason: str | None = None

    @property
    def blocks_login(self) -> bool:
        return self.state == "failing"


def read(db: Session) -> DeliveryStatus:
    """Aktueller Status direkt aus der Datenbank (nicht aus der Identity-Map der Session)."""
    row = db.execute(
        select(
            PlatformNotificationSettings.email_enabled, PlatformNotificationSettings.smtp_host,
            PlatformNotificationSettings.email_from_address, PlatformNotificationSettings.email_last_sent_at,
            PlatformNotificationSettings.email_last_error_at, PlatformNotificationSettings.email_failing_since,
            PlatformNotificationSettings.email_failure_count, PlatformNotificationSettings.email_failure_reason,
        ).where(PlatformNotificationSettings.id == 1)
    ).one_or_none()
    if row is None or not (row.email_enabled and row.smtp_host and row.email_from_address):
        return DeliveryStatus(state="disabled")
    failures = int(row.email_failure_count or 0)
    reason = row.email_failure_reason
    if failures and reason not in email_transport.MESSAGE_REASONS:
        state = "failing"
    elif failures >= RECIPIENT_REJECTED_THRESHOLD:
        state = "rejecting"
    elif row.email_last_sent_at is None and not failures:
        state = "never"
    else:
        state = "ok"
    return DeliveryStatus(
        state=state, last_success_at=row.email_last_sent_at, last_failure_at=row.email_last_error_at if failures else None,
        failing_since=row.email_failing_since if failures else None, failures=failures, reason=reason if failures else None,
    )


def record_success(db: Session) -> None:
    """Versand (oder Probe) erfolgreich: Störung aufheben, letzten Erfolg setzen. Committet die
    übergebene Session (wie record_system_error) - der Status darf nicht mit einem späteren
    Rollback des Aufrufers verloren gehen. Wirft nur, wenn schon die Arbeit des Aufrufers nicht
    gespeichert werden kann."""
    table = PlatformNotificationSettings
    # Erst die Arbeit des Aufrufers (z. B. «sent» im Loop) festschreiben: ein Fehler beim Status
    # darf eine bereits versendete Mail nicht zurückrollen (Security-Review N1).
    db.commit()
    try:
        _write_success(db, table)
    except Exception as exc:  # noqa: BLE001 - Status ist Zusatz, der Versand hat geklappt
        db.rollback()
        _logger.exception("Versandstatus (Erfolg) konnte nicht gespeichert werden")
        record_system_error(db, exc=exc)


def _write_success(db: Session, table) -> None:
    previous = db.scalar(select(table.email_failure_count).where(table.id == 1))
    db.execute(
        update(table)
        .where(
            table.id == 1,
            (table.email_failure_count != 0) | table.email_last_error.is_not(None) | table.email_last_sent_at.is_(None)
            | (table.email_last_sent_at < func.now() - func.make_interval(0, 0, 0, 0, 0, 0, SUCCESS_WRITE_INTERVAL_SECONDS)),
        )
        .values(
            email_last_sent_at=func.now(), email_last_error=None, email_last_error_at=None,
            email_failure_count=0, email_failure_reason=None, email_failing_since=None,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    if previous:
        _logger.info("E-Mail-Versand funktioniert wieder (nach %s Fehlern)", previous)


def record_failure(db: Session, exc: email_transport.EmailError, *, kind: str, tenant_id: int | None = None) -> None:
    """Versand gescheitert: Fehler zählen, Klasse und bereinigten Text festhalten, gedrosselt ins
    Fehlerprotokoll. Committet die übergebene Session (siehe record_success). Wirft nie - ein Fehler
    beim Festhalten darf den eigentlichen Ablauf (Login-Antwort, Loop) nicht ersetzen."""
    reason = getattr(exc, "reason", "other")
    message = str(exc)[:500]
    table = PlatformNotificationSettings
    try:
        # Fehlversuchs-Zähler des Aufrufers zuerst festschreiben (Security-Review N1)
        db.commit()
    except Exception:  # noqa: BLE001 - dann scheitert unten auch der Status; protokolliert wird trotzdem
        db.rollback()
        _logger.exception("Arbeit vor dem Versandstatus konnte nicht gespeichert werden")
    try:
        previous = db.execute(select(table.email_failure_count, table.email_failure_reason).where(table.id == 1)).one_or_none()
        db.execute(
            update(table)
            .where(table.id == 1)
            .values(
                email_last_error=message, email_last_error_at=func.now(), email_failure_count=table.email_failure_count + 1,
                email_failure_reason=reason, email_failing_since=func.coalesce(table.email_failing_since, func.now()),
            )
            .execution_options(synchronize_session=False)
        )
        db.commit()
    except Exception as status_exc:  # noqa: BLE001 - Status ist Zusatz; der Versandfehler geht unten ins Protokoll
        db.rollback()
        _logger.exception("Versandstatus konnte nicht gespeichert werden")
        record_system_error(db, exc=status_exc)
        previous = None
    if kind == "login_code":
        # Dieser Login war der Versuch: die nächsten LOGIN_RETRY_SECONDS antworten sofort.
        _claim(_LOGIN_RETRY_KEY, LOGIN_RETRY_SECONDS)
    transition = previous is None or not previous.email_failure_count or previous.email_failure_reason != reason
    # Immer beanspruchen (setzt die Stundensperre auch beim Übergang)
    due = _claim(f"{_ERROR_LOGGED_KEY}{reason}", ERROR_LOG_INTERVAL_SECONDS)
    if transition or due:
        record_system_error(db, exc=MailDeliveryFailure(f"E-Mail-Versand fehlgeschlagen ({kind}, {reason}): {message}"), tenant_id=tenant_id)


def login_blocked(db: Session) -> bool:
    """True, wenn eine Anmeldung, die einen Mailcode bräuchte, gar nicht erst versenden soll:
    Versand gestört und der Versuch je LOGIN_RETRY_SECONDS ist schon vergeben. Ist Redis weg,
    wird nicht versucht (Antwort sofort statt bis zu 20 s SMTP-Wartezeit je Anmeldung)."""
    if not read(db).blocks_login:
        return False
    return not _claim(_LOGIN_RETRY_KEY, LOGIN_RETRY_SECONDS)


def probe_if_idle(db: Session, config: email_transport.EmailConfig) -> str | None:
    """Vom Loop aufgerufen, wenn in seinem Lauf nichts versendet wurde: ist der Versand wegen
    Verbindung/TLS/Anmeldung gestört, Verbindung prüfen (ohne Mail). So erholt sich der Status,
    auch wenn gerade niemand eine Mail auslöst (z. B. nach dem Korrigieren des Passworts).
    Liefert "ok"/"failed" oder None (keine Probe nötig)."""
    status = read(db)
    if status.state != "failing" or status.reason not in PROBE_REASONS:
        return None
    db.commit()  # keine offene Transaktion während der Netzwerkprobe (bis zu 10 s)
    try:
        email_transport.probe(config)
    except email_transport.EmailError as exc:
        record_failure(db, exc, kind="probe")
        return "failed"
    record_success(db)
    return "ok"


def _claim(key: str, ttl_seconds: int) -> bool:
    try:
        return bool(get_redis_sync().set(key, "1", nx=True, ex=ttl_seconds))
    except Exception:  # noqa: BLE001 - Redis weg: nichts beanspruchen (Aufrufer entscheiden vorsichtig)
        _logger.warning("Redis für den Versandstatus nicht erreichbar", exc_info=True)
        return False
