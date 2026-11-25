"""Namen gebüsster Personen in Buchungen (Fachentscheid 2026-11-25).

Eingezogene Bussen erscheinen im Kassenbuch als Buchung «Busse Verspätet: Max Muster» (bzw. als
Pendenzen-Busse), ``locked_detail`` nennt die Person ebenfalls. Wer Bussen anderer Personen nicht
sehen darf (ohne ``reports.personal``, z. B. die Standardrolle «Leser» mit ``finances.read``),
sieht dort statt des Namens «·····» - in der API, in PDFs und Tabellen-Exporten. Gespeichert wird
nichts anders; Kasse und Administration (mit ``reports.personal``) sehen alles.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

MASK = "·····"


def hides_fine_names(user) -> bool:
    """Ohne Person (Auto-PDF, interne Aufrufe) wird nichts maskiert."""
    from app.core.permissions import P

    return user is not None and not user.can(P.REPORTS_PERSONAL)


def fine_names_by_transaction(db: Session, transaction_ids: list[int]) -> dict[int, str]:
    """Buchung → Name der gebüssten Person (Anwesenheits- und Pendenzen-Bussen)."""
    from app.models.entities import AttendanceFine, TodoFine

    ids = [tx_id for tx_id in transaction_ids if tx_id is not None]
    if not ids:
        return {}
    names: dict[int, str] = {}
    for model in (AttendanceFine, TodoFine):
        for tx_id, name in db.execute(
            select(model.collected_transaction_id, model.participant_name_snapshot).where(model.collected_transaction_id.in_(ids))
        ):
            names.setdefault(tx_id, name or "")
    return names


def mask_name(text: str | None, name: str | None) -> str:
    """Den Namen im Buchungstext ersetzen. Steht er nicht (mehr) wörtlich darin, wird alles nach dem
    letzten «: » ersetzt - der Text endet bei Bussen immer mit dem Namen."""
    text = text or ""
    if name and name in text:
        return text.replace(name, MASK)
    head, separator, _tail = text.rpartition(": ")
    return f"{head}{separator}{MASK}" if separator else MASK


FINE_LOCK_REASONS = ("fine_transaction", "todo_fine_transaction")


def mask_transaction_reads(items: list, user) -> list:
    """API (FinanceTransactionRead): Name im Buchungstext und in ``locked_detail`` maskieren.
    ``locked_detail`` ist bei Bussen genau der Name der Person."""
    if not hides_fine_names(user):
        return items
    for item in items:
        if item.locked_reason in FINE_LOCK_REASONS:
            item.description = mask_name(item.description, item.locked_detail)
            item.locked_detail = MASK
    return items
