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

from sqlalchemy.orm import Session

from app.models import FinanceAccount, FineTariff, Template
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


def tariff_block_values(db: Session, tenant_id: int, template_id: int | None = None) -> dict:
    """Konto (public id) und Beträge für die Block-Konfiguration eines Anwesenheitsblocks:
    der Tarif der Vorlage, falls sie einen eigenen hat, sonst der des Mandanten."""
    template = db.get(Template, template_id) if template_id is not None else None
    if template is not None and template.tenant_id == tenant_id and template.fine_tariff_override:
        account_id = (
            public_id_service.resolve_public_id(db, FinanceAccount, template.fine_account_id) if template.fine_account_id else None
        )
        return {
            "fine_account_id": str(account_id) if account_id else None,
            "fine_amount_late": float(template.fine_amount_late or 0),
            "fine_amount_absent": float(template.fine_amount_absent or 0),
        }
    tariff = read_tariff(db, tenant_id)
    return {
        "fine_account_id": str(tariff.account_id) if tariff.account_id else None,
        "fine_amount_late": float(tariff.amount_late),
        "fine_amount_absent": float(tariff.amount_absent),
    }
