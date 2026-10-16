"""Zentraler Bussentarif pro Mandant (siehe FineTariff).

Anwesenheitsblöcke tragen nur noch `fines_enabled`. Beim Auslesen der Protokollblöcke
ergänzt ProtocolElementService Konto und Beträge aus diesem Tarif (tariff_block_values), damit
Desktop- und Mobile-Editor (attendance-fines.ts) unverändert damit arbeiten.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import FinanceAccount, FineTariff
from app.schemas.fines import FineTariffRead, FineTariffUpdate
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


def tariff_block_values(db: Session, tenant_id: int) -> dict:
    """Konto (public id) und Beträge für die Block-Konfiguration eines Anwesenheitsblocks."""
    tariff = read_tariff(db, tenant_id)
    return {
        "fine_account_id": str(tariff.account_id) if tariff.account_id else None,
        "fine_amount_late": float(tariff.amount_late),
        "fine_amount_absent": float(tariff.amount_absent),
    }
