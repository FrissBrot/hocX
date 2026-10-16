"""Zentraler Bussentarif (fine_tariff): Anwesenheitsblöcke tragen nur fines_enabled, Konto und
Beträge kommen beim Auslesen der Protokollblöcke aus dem Tarif des Mandanten."""
from decimal import Decimal

import pytest

from app.schemas.fines import FineTariffUpdate
from app.services import fine_tariff_service
from app.services.protocol_element_service import ProtocolElementService
from tests.factories import (
    make_finance_account,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)


def test_update_and_read_tariff(db):
    tenant = make_tenant(db)
    account = make_finance_account(db, tenant.id, name="Bussen")

    saved = fine_tariff_service.update_tariff(
        db, tenant.id, FineTariffUpdate(account_id=account.public_id, amount_late=Decimal("5"), amount_absent=Decimal("10.5"))
    )

    assert saved.account_id == account.public_id
    assert saved.amount_late == Decimal("5.00")
    assert fine_tariff_service.read_tariff(db, tenant.id).amount_absent == Decimal("10.50")


def test_tariff_rejects_account_of_other_tenant(db):
    tenant = make_tenant(db, "A")
    other = make_tenant(db, "B")
    foreign_account = make_finance_account(db, other.id)

    with pytest.raises(ValueError):
        fine_tariff_service.update_tariff(db, tenant.id, FineTariffUpdate(account_id=foreign_account.public_id))


def test_attendance_blocks_get_tariff_only_when_fines_enabled(db):
    tenant = make_tenant(db)
    account = make_finance_account(db, tenant.id)
    fine_tariff_service.update_tariff(
        db, tenant.id, FineTariffUpdate(account_id=account.public_id, amount_late=Decimal("2"), amount_absent=Decimal("4"))
    )
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    element = make_protocol_element(db, protocol.id)
    make_protocol_element_block(db, element.id, {"fines_enabled": True, "attendance_entries": []}, sort_index=0, element_type_code="attendance")
    make_protocol_element_block(db, element.id, {"fines_enabled": False, "attendance_entries": []}, sort_index=1, element_type_code="attendance")

    blocks = ProtocolElementService().list_protocol_elements(db, protocol.id)[0].blocks

    enabled, disabled = (block.configuration_snapshot_json for block in blocks)
    assert enabled["fine_account_id"] == str(account.public_id)
    assert (enabled["fine_amount_late"], enabled["fine_amount_absent"]) == (2.0, 4.0)
    assert disabled["fine_account_id"] is None
