"""Zentraler Weg für Benachrichtigungen an Personen (Migration 0170, docs/NOTIFICATIONS.md).

Fachcode ruft nur ``publish`` auf - in seiner eigenen Transaktion, damit bei einem Rollback nichts
verschickt wird. Wer die Nachricht bekommt, ob sie noch aktuell ist und wie sie aussieht, prüft
der Versand-Loop (dispatch.py) erst beim Versand: dann gelten die aktuellen Einstellungen,
Rechte und Daten. Heute gibt es nur den Kanal E-Mail (SMTP, email_transport.py).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Notification
from app.notifications.catalog import KINDS


def publish(
    db: Session,
    *,
    kind: str,
    tenant_id: int,
    recipient_ids: Iterable[int],
    subject_id: int | None = None,
    payload: dict[str, Any] | None = None,
    dedupe: str | None = None,
) -> int:
    """Legt je Empfänger eine Benachrichtigung an (ohne Commit). `dedupe` macht sie einmalig:
    der Schlüssel wird je Empfänger zu ``<kind>:<dedupe>:<empfänger>`` und eine zweite
    Veröffentlichung wird still ignoriert. Liefert die Zahl neuer Zeilen."""
    spec = KINDS[kind]
    deliver_after = datetime.now(timezone.utc) + spec.delay
    created = 0
    for recipient_id in dict.fromkeys(recipient_ids):
        if recipient_id is None:
            continue
        statement = insert(Notification).values(
            tenant_id=tenant_id, recipient_id=recipient_id, kind=kind, group_key=spec.group, subject_id=subject_id,
            payload=payload or {}, dedupe_key=f"{kind}:{dedupe}:{recipient_id}" if dedupe is not None else None,
            status="pending", deliver_after=deliver_after,
        ).on_conflict_do_nothing(constraint="uq_notification_dedupe_key").returning(Notification.id)
        created += len(db.execute(statement).all())
    return created
