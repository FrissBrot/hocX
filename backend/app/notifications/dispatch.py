"""Loop notification_dispatch (job-worker): fällige Benachrichtigungen bündeln und versenden.

Je Empfänger und Gruppe (catalog.Kind.group) eine Mail mit allen fälligen Einträgen. Vor dem
Versand wird alles neu geprüft: Konto aktiv und im selben Mandanten, E-Mail vorhanden, Login oder
vom Admin erlaubter Versand ohne Login, Kategorie nicht abgeschaltet, Eintrag noch aktuell.
Fehlschläge werden mit wachsendem Abstand wiederholt, nach MAX_ATTEMPTS als `failed` markiert.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.error_log import record_system_error
from app.models import AccountToken, Notification, NotificationPreference, Participant, PlatformNotificationSettings, Tenant
from app.notifications import account, email_transport, exports, fines, submissions, todos
from app.notifications.catalog import CATEGORIES, GROUPS_WITHOUT_LOGIN, KINDS
from app.notifications.render import Brand, render

_logger = logging.getLogger(__name__)

BATCH_GROUPS = 200
MAX_ATTEMPTS = 5
RETRY_MINUTES = (5, 15, 60, 240)
# Ohne konfigurierten Versand bleiben Einträge so lange liegen, danach verfallen sie.
PENDING_EXPIRY = timedelta(days=7)
RETENTION = timedelta(days=90)
# Grössere Logos nicht in jede Mail packen (Profilbilder sind normalisierte PNGs, meist klein)
LOGO_MAX_BYTES = 200_000
# Aktuelle Daten je Gruppe; fehlt eine Benachrichtigung im Ergebnis, ist sie überholt.
ITEM_LOADERS = {
    "todo.new": todos.items_for,
    "todo.reminder": todos.items_for,
    "todo.done": todos.items_for,
    "account.password_reset": account.link_items_for,
    "account.invite": account.link_items_for,
    "account.security": account.security_items_for,
    "account.email_changed": account.email_changed_items_for,
    "export": exports.items_for,
    "fine.upcoming": fines.upcoming_items_for,
    "fine.issued": fines.issued_items_for,
    "submission.withdrawn": submissions.items_for,
}


def tenant_brand(db: Session, tenant_id: int) -> Brand:
    """Kopf der Mail: Vereinsname und Logo (aus dem Objektspeicher, eingebettet statt verlinkt).
    Ohne Logo oder wenn es nicht lesbar ist: Initialen (bewusst ohne Fehler, rein kosmetisch)."""
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        return Brand("hocX")
    logo = None
    if tenant.profile_image_path and tenant.profile_image_path.lower().endswith(".png"):
        try:
            from app.core.storage import MAIN, get_object_store

            data = get_object_store().get_bytes(MAIN, tenant.profile_image_path)
            logo = data if len(data) <= LOGO_MAX_BYTES else None
        except Exception:  # noqa: BLE001 - Logo ist Zierde, die Mail geht ohne raus
            _logger.warning("Vereinslogo für Mail nicht lesbar (Mandant %s)", tenant_id)
    return Brand(tenant.name or "hocX", logo)


def preference_enabled(db: Session, user_id: int, category: str) -> bool:
    if not CATEGORIES[category].configurable:
        return True  # Pflichtmitteilung (Konto und Sicherheit)
    value = db.scalar(select(NotificationPreference.enabled).where(NotificationPreference.user_id == user_id, NotificationPreference.category == category))
    return CATEGORIES[category].default if value is None else bool(value)


def recipient_block_reason(person: Participant | None, tenant_id: int, group: str | None = None) -> str | None:
    if person is None or person.tenant_id != tenant_id:
        return "recipient_missing"
    if not person.is_active:
        return "recipient_inactive"
    if person.has_left:
        return "recipient_left"
    if not (person.email or "").strip():
        return "no_email"
    if not person.login_enabled and not person.notify_without_login and group not in GROUPS_WITHOUT_LOGIN:
        return "no_login"
    return None


def _skip(rows: list[Notification], reason: str) -> None:
    for row in rows:
        row.status = "skipped"
        row.skip_reason = reason


def _fail(db: Session, rows: list[Notification], error: str, *, smtp_status: bool = True) -> None:
    now = datetime.now(timezone.utc)
    for row in rows:
        row.attempts += 1
        row.last_error = error[:500]
        if row.attempts >= MAX_ATTEMPTS:
            row.status = "failed"
        else:
            row.deliver_after = now + timedelta(minutes=RETRY_MINUTES[min(row.attempts, len(RETRY_MINUTES)) - 1])
    # Der «letzte Fehler» in den Mail-Einstellungen beschreibt den Versand - ein Fehler vor dem
    # Versand (Laden/Rendern) gehört nur ins Fehlerprotokoll.
    settings_row = db.get(PlatformNotificationSettings, 1) if smtp_status else None
    if settings_row is not None:
        settings_row.email_last_error = error[:500]
        settings_row.email_last_error_at = now


def _due_rows(db: Session, tenant_id: int, recipient_id: int, group: str) -> list[Notification]:
    return list(db.scalars(
        select(Notification)
        .where(
            Notification.recipient_id == recipient_id, Notification.group_key == group, Notification.status == "pending",
            Notification.tenant_id == tenant_id, Notification.deliver_after <= func.now() + timedelta(minutes=15),
        )
        .order_by(Notification.id)
        .with_for_update(skip_locked=True)
    ).all())


def _count_failed_attempt(db: Session, tenant_id: int, recipient_id: int, group: str, exc: Exception) -> None:
    """Auch ein Fehler vor dem Versand (Laden, Rendern) zählt als Versuch. Sonst blieb die Gruppe
    ohne Zähler «pending», lief jede Minute erneut, schrieb jedes Mal ins Fehlerprotokoll und
    endete nie als «failed». Ist die Datenbank selbst weg, scheitert auch das - dann zählt der
    Versuch eben nicht."""
    try:
        _fail(db, _due_rows(db, tenant_id, recipient_id, group), type(exc).__name__, smtp_status=False)
        db.commit()
    except Exception:  # noqa: BLE001 - der ursprüngliche Fehler ist bereits protokolliert
        db.rollback()
        _logger.warning("Fehlversuch für Empfänger %s nicht gezählt", recipient_id, exc_info=True)


def _deliver_group(db: Session, config: email_transport.EmailConfig, tenant_id: int, recipient_id: int, group: str) -> str:
    rows = _due_rows(db, tenant_id, recipient_id, group)
    if not rows:
        return "none"
    person = db.get(Participant, recipient_id)
    reason = recipient_block_reason(person, tenant_id, group)
    if reason is None:
        allowed = [row for row in rows if preference_enabled(db, recipient_id, KINDS[row.kind].category)]
        _skip([row for row in rows if row not in allowed], "preference_off")
        rows = allowed
    else:
        _skip(rows, reason)
        return "skipped"
    items = ITEM_LOADERS[group](db, rows, recipient_id, base_url=config.link_base_url)
    _skip([row for row in rows if row.id not in items], "obsolete")
    rows = [row for row in rows if row.id in items]
    if not rows:
        return "skipped"
    # Einträge mit eigener Zieladresse (Login-E-Mail geändert -> alte Adresse): je Adresse eine Mail,
    # hier nur die neueste; ältere gleicher Adresse gelten mit als versendet.
    target = items[rows[-1].id].get("to")
    if target:
        rows = [row for row in rows if items[row.id].get("to") == target]
    brand = tenant_brand(db, tenant_id)
    rendered = render(
        lang=person.preferred_language, group=group, items=[items[row.id] for row in rows], recipient_name=person.first_name or person.display_name,
        tenant_name=brand.name, base_url=config.link_base_url, can_login=person.login_enabled, brand=brand,
    )
    try:
        email_transport.send(config, email_transport.OutgoingEmail(
            to=target or person.email.strip(), subject=rendered.subject, text=rendered.text, html=rendered.html, images=rendered.images,
        ))
    except email_transport.EmailError as exc:
        _fail(db, rows, str(exc))
        return "failed"
    except Exception as exc:  # unerwartet (z. B. ungültige Adresse): ins Fehlerprotokoll, als Versuch zählen
        _logger.exception("Mail an Empfänger %s nicht versendbar", recipient_id)
        record_system_error(db, exc=exc, tenant_id=tenant_id)
        _fail(db, rows, type(exc).__name__)
        return "error"
    now = datetime.now(timezone.utc)
    for row in rows:
        row.status = "sent"
        row.sent_at = now
        row.last_error = None
    settings_row = db.get(PlatformNotificationSettings, 1)
    if settings_row is not None:
        # Wie bei der Test-Mail: ein erfolgreicher Versand löst den letzten Fehler ab.
        settings_row.email_last_sent_at = now
        settings_row.email_last_error = None
        settings_row.email_last_error_at = None
    return "sent"


def run(db: Session) -> dict[str, int]:
    """Ein Durchlauf des Loops: versenden, Verfallenes markieren, Altes löschen."""
    now = datetime.now(timezone.utc)
    counts: dict[str, int] = defaultdict(int)
    db.execute(delete(Notification).where(Notification.status != "pending", Notification.created_at < now - RETENTION))
    # Einmal-Links (account.py): nach derselben Frist weg, offene nur, wenn abgelaufen
    db.execute(delete(AccountToken).where(
        AccountToken.created_at < now - RETENTION,
        or_(AccountToken.used_at.is_not(None), AccountToken.revoked_at.is_not(None), AccountToken.expires_at < now, AccountToken.expires_at.is_(None)),
    ))
    config = email_transport.load_config(db)
    if config is None:
        expired = db.scalars(select(Notification).where(Notification.status == "pending", Notification.created_at < now - PENDING_EXPIRY)).all()
        _skip(list(expired), "email_disabled")
        counts["expired"] = len(expired)
        db.commit()
        return dict(counts)
    # Von der Abgabebox erledigte Abgabe-Aufgaben (Datenbank-Trigger) nachtragen
    # (ein Fehler hier darf den Versand der übrigen Mails nicht anhalten)
    try:
        counts["submission_done"] = todos.scan_submission_done(db, now=now)
        db.commit()
    except Exception as exc:
        db.rollback()
        _logger.exception("Abgabe-Mails konnten nicht nachgetragen werden")
        record_system_error(db, exc=exc)
        counts["error"] += 1
    groups = db.execute(
        select(Notification.tenant_id, Notification.recipient_id, Notification.group_key)
        .where(Notification.status == "pending")
        .group_by(Notification.tenant_id, Notification.recipient_id, Notification.group_key)
        .having(func.min(Notification.deliver_after) <= func.now())
        .limit(BATCH_GROUPS)
    ).all()
    db.commit()
    for tenant_id, recipient_id, group in groups:
        try:
            counts[_deliver_group(db, config, tenant_id, recipient_id, group)] += 1
            db.commit()
        except Exception as exc:  # Daten- oder Programmfehler: Gruppe auslassen, der Rest läuft weiter
            db.rollback()
            _logger.exception("Benachrichtigung an Empfänger %s fehlgeschlagen", recipient_id)
            record_system_error(db, exc=exc, tenant_id=tenant_id)
            counts["error"] += 1
            _count_failed_attempt(db, tenant_id, recipient_id, group, exc)
    return dict(counts)
