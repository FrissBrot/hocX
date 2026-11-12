"""Bussentarif: zentral pro Mandant (FineTariff), optional je Protokollvorlage übersteuert
(Template.fine_tariff_override, 0137).

Anwesenheitsblöcke tragen nur noch `fines_enabled`. Beim Auslesen der Protokollblöcke
ergänzt ProtocolElementService Konto und Beträge aus dem Tarif der Vorlage bzw. des Mandanten
(tariff_block_values), damit Desktop- und Mobile-Editor (attendance-fines.ts) unverändert damit
arbeiten. Der Tarif wird live gelesen: eine Änderung gilt sofort für offene Protokolle, bereits
erfasste Bussen behalten ihren Betrag.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FinanceAccount, FineTariff, FineTariffGroup, Participant, Template
from app.schemas.fines import FineTariffRead, FineTariffUpdate, TemplateFineTariffRead, TemplateFineTariffUpdate
from app.services import public_id_service


def get_tariff(db: Session, tenant_id: int) -> FineTariff | None:
    return db.get(FineTariff, tenant_id)


def read_tariff(db: Session, tenant_id: int) -> FineTariffRead:
    tariff = get_tariff(db, tenant_id)
    if tariff is None:
        return FineTariffRead()
    return FineTariffRead(
        account_id=public_id_service.resolve_public_id(db, FinanceAccount, tariff.account_id) if tariff.account_id else None,
        amount_late=Decimal(str(tariff.amount_late or 0)),
        amount_absent=Decimal(str(tariff.amount_absent or 0)),
    )


def update_tariff(db: Session, tenant_id: int, payload: FineTariffUpdate) -> FineTariffRead:
    account_id: int | None = None
    if payload.account_id is not None:
        account_id = public_id_service.resolve_internal_id(db, FinanceAccount, payload.account_id, tenant_id=tenant_id)
        if account_id is None:
            raise ValueError("Finance account not found")
    tariff = get_tariff(db, tenant_id)
    if tariff is None:
        tariff = FineTariff(tenant_id=tenant_id)
        db.add(tariff)
    tariff.account_id = account_id
    tariff.amount_late = payload.amount_late
    tariff.amount_absent = payload.amount_absent
    db.commit()
    return read_tariff(db, tenant_id)


def read_template_tariff(db: Session, template: Template) -> TemplateFineTariffRead:
    return TemplateFineTariffRead(
        override=template.fine_tariff_override,
        account_id=public_id_service.resolve_public_id(db, FinanceAccount, template.fine_account_id) if template.fine_account_id else None,
        amount_late=Decimal(str(template.fine_amount_late or 0)),
        amount_absent=Decimal(str(template.fine_amount_absent or 0)),
        tenant_tariff=read_tariff(db, template.tenant_id),
    )


def update_template_tariff(db: Session, template: Template, payload: TemplateFineTariffUpdate) -> TemplateFineTariffRead:
    """override=False setzt die Vorlage auf den Mandantentarif zurück; Konto und Beträge werden
    dann geleert, damit kein verdeckter Alt-Tarif wieder auftaucht."""
    account_id: int | None = None
    if payload.override and payload.account_id is not None:
        account_id = public_id_service.resolve_internal_id(db, FinanceAccount, payload.account_id, tenant_id=template.tenant_id)
        if account_id is None:
            raise ValueError("Finance account not found")
    template.fine_tariff_override = payload.override
    template.fine_account_id = account_id
    template.fine_amount_late = payload.amount_late if payload.override else Decimal("0")
    template.fine_amount_absent = payload.amount_absent if payload.override else Decimal("0")
    db.commit()
    return read_template_tariff(db, template)


def _groups(db: Session, tenant_id: int) -> list[FineTariffGroup]:
    return list(db.scalars(select(FineTariffGroup).where(FineTariffGroup.tenant_id == tenant_id)))


def has_attendance_tariffs(db: Session, tenant_id: int) -> bool:
    """Ob ein Tarif eigene Beträge für Verspätung/Absenz hat (dann rechnet der Server je Person)."""
    return any(group.amount_late is not None or group.amount_absent is not None for group in _groups(db, tenant_id))


def amount_for_participant(db: Session, tenant_id: int, template_id: int | None, participant_id: int | None, fine_type: str) -> Decimal:
    """Betrag einer Anwesenheitsbusse nach dem Tarif der Person (Migration 0172): eine Vorlage mit
    eigenem Tarif gilt für alle gleich; sonst der Betrag des Tarifs der Person (ohne Tarif: der
    Standardtarif), ohne eigenen Betrag der Vereinstarif."""
    values = tariff_block_values(db, tenant_id, template_id)
    base = Decimal(str(values["fine_amount_late" if fine_type == "late" else "fine_amount_absent"]))
    if not values.get("fine_tariff_amounts"):
        return base
    groups = _groups(db, tenant_id)
    person = db.get(Participant, participant_id) if participant_id is not None else None
    group_id = person.fine_tariff_group_id if person is not None and person.tenant_id == tenant_id else None
    group = next((g for g in groups if g.id == group_id), None) if group_id is not None else next((g for g in groups if g.is_default), None)
    amount = (group.amount_late if fine_type == "late" else group.amount_absent) if group is not None else None
    return Decimal(str(amount)) if amount is not None else base


def tariff_block_values(db: Session, tenant_id: int, template_id: int | None = None) -> dict:
    """Konto (public id) und Beträge für die Block-Konfiguration eines Anwesenheitsblocks:
    der Tarif der Vorlage, falls sie einen eigenen hat (gleich für alle Personen), sonst der des
    Mandanten; fine_tariff_amounts sagt, ob Tarife eigene Beträge haben (amount_for_participant)."""
    template = db.get(Template, template_id) if template_id is not None else None
    if template is not None and template.tenant_id == tenant_id and template.fine_tariff_override:
        account_id = (
            public_id_service.resolve_public_id(db, FinanceAccount, template.fine_account_id) if template.fine_account_id else None
        )
        return {
            "fine_account_id": str(account_id) if account_id else None,
            "fine_amount_late": float(template.fine_amount_late or 0),
            "fine_amount_absent": float(template.fine_amount_absent or 0),
            "fine_tariff_amounts": False,
        }
    tariff = read_tariff(db, tenant_id)
    late, absent = float(tariff.amount_late), float(tariff.amount_absent)
    return {
        "fine_account_id": str(tariff.account_id) if tariff.account_id else None,
        "fine_amount_late": late,
        "fine_amount_absent": absent,
        # Nur ob es Tarif-Beträge gibt (kein Betrag je Person: der Tarif einer Person ist nur für
        # finances.manage sichtbar). Den Betrag bestimmt der Server beim Anlegen (use_tariff).
        "fine_tariff_amounts": has_attendance_tariffs(db, tenant_id),
    }


def attendance_fine_values(
    db: Session, config: dict, tenant_id: int | None, template_id: int | None, tariff: dict | None = None
) -> dict:
    """Bussen-Schlüssel, die die API in die Konfiguration eines Anwesenheitsblocks einsetzt
    (attendance-fines.ts liest sie): gespeichert ist nur fines_enabled, Konto und Beträge kommen
    aus dem Tarif. Jede Antwort mit einem Anwesenheitsblock muss sie tragen - fehlten sie in der
    Antwort auf einen Klick, legte der Editor danach keine Bussen mehr an und entfernte keine
    mehr (Bug 2026-11-08). ``tariff`` erspart beim Auflisten mehrerer Blöcke die Abfrage."""
    if config.get("fines_enabled") and tenant_id is not None:
        return tariff if tariff is not None else tariff_block_values(db, tenant_id, template_id)
    return {"fine_account_id": None, "fine_amount_late": 0, "fine_amount_absent": 0, "fine_tariff_amounts": False}
