"""Tarife auch für Anwesenheitsbussen (Migration 0172, fine_tariff_service.amounts_by_participant)."""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.api.routes import todo_fines as route
from app.schemas.fines import FineTariffUpdate
from app.schemas.todo_fines import FineTariffGroupWrite
from app.services import fine_tariff_service, todo_fine_config_service as config
from app.services.element_config import upgrade_block_config
from tests.factories import make_current_user, make_finance_account, make_participant, make_template, make_tenant


@pytest.fixture
def club(db):
    tenant = make_tenant(db, "Tarif Verein")
    account = make_finance_account(db, tenant.id, "Bussenkasse")
    fine_tariff_service.update_tariff(
        db, tenant.id, FineTariffUpdate(account_id=account.public_id, amount_late=Decimal("5"), amount_absent=Decimal("20"))
    )
    standard = config.create_group(db, tenant.id, FineTariffGroupWrite(name="Vollverdiener"))
    learners = config.create_group(db, tenant.id, FineTariffGroupWrite(name="Lernende", amount_late=Decimal("2"), amount_absent=Decimal("8")))
    anna, ben, cleo = (make_participant(db, tenant.id, name) for name in ("Anna", "Ben", "Cleo"))
    anna.fine_tariff_group_id = learners.id
    ben.fine_tariff_group_id = standard.id
    db.flush()
    return {"tenant": tenant, "account": account, "standard": standard, "learners": learners, "anna": anna, "ben": ben, "cleo": cleo}


def test_block_values_carry_no_personal_amounts(db, club):
    values = fine_tariff_service.tariff_block_values(db, club["tenant"].id)
    assert values["fine_amount_late"] == 5.0 and values["fine_amount_absent"] == 20.0
    # Nur ob es Tarif-Beträge gibt - nie Beträge oder Tarife je Person (nur für finances.manage)
    assert values["fine_tariff_amounts"] is True
    assert str(club["anna"].public_id) not in str(values)


def test_amount_follows_the_tariff_of_the_person(db, club):
    tenant_id = club["tenant"].id
    amount = lambda person, kind: fine_tariff_service.amount_for_participant(db, tenant_id, None, person.id if person else None, kind)
    assert amount(club["anna"], "late") == Decimal("2") and amount(club["anna"], "absent") == Decimal("8")
    # Vollverdiener ohne eigene Beträge, Cleo ohne Tarif (Standard = Vollverdiener): Vereinstarif
    assert amount(club["ben"], "late") == Decimal("5") and amount(club["cleo"], "absent") == Decimal("20")
    config.update_group(db, tenant_id, club["standard"], FineTariffGroupWrite(name="Vollverdiener", is_default=True, amount_late=Decimal("6")))
    assert amount(club["cleo"], "late") == Decimal("6") and amount(club["cleo"], "absent") == Decimal("20")


def test_template_override_stays_flat_for_everyone(db, club):
    template = make_template(db, club["tenant"].id)
    template.fine_tariff_override = True
    template.fine_account_id = club["account"].id
    template.fine_amount_late = Decimal("10")
    template.fine_amount_absent = Decimal("30")
    db.flush()
    values = fine_tariff_service.tariff_block_values(db, club["tenant"].id, template.id)
    assert values["fine_amount_late"] == 10.0 and values["fine_tariff_amounts"] is False
    assert fine_tariff_service.amount_for_participant(db, club["tenant"].id, template.id, club["anna"].id, "late") == Decimal("10")


def test_create_fine_with_tariff_uses_the_server_amount(db, club):
    from app.api.routes import fines as fines_route
    from app.schemas.fines import AttendanceFineCreate
    from tests.factories import make_protocol

    tenant_id = club["tenant"].id
    template = make_template(db, tenant_id)
    protocol = make_protocol(db, tenant_id, template.id, protocol_number="T-1")
    kassier = make_current_user(tenant_id, role="kassier")
    payload = lambda person: AttendanceFineCreate(
        protocol_id=protocol.public_id, participant_id=person.public_id, participant_name_snapshot=person.display_name,
        fine_type="late", use_tariff=True, account_id=club["account"].public_id,
    )
    created = fines_route.create_fine(payload(club["anna"]), db=db, user=kassier)
    assert created.amount == Decimal("2.00")
    # Tarif mit 0 für Verspätung: keine Busse
    config.update_group(db, tenant_id, club["learners"], FineTariffGroupWrite(name="Lernende", amount_late=Decimal("0"), amount_absent=Decimal("8")))
    elena = make_participant(db, tenant_id, "Elena")
    elena.fine_tariff_group_id = club["learners"].id
    db.flush()
    assert fines_route.create_fine(payload(elena), db=db, user=kassier).status_code == 204


def test_amounts_are_not_stored_in_block_configuration():
    config_out = upgrade_block_config(None, {"fines_enabled": True, "fine_tariff_amounts": True})
    assert "fine_tariff_amounts" not in config_out


def test_tariffs_need_only_the_finance_feature(db, club):
    tenant_id = club["tenant"].id
    finance_only = make_current_user(tenant_id, role="kassier", features=frozenset({"finance"}))
    assert [group.name for group in route.list_tariffs(db=db, user=finance_only)] == ["Vollverdiener", "Lernende"]
    learners = next(group for group in route.list_tariffs(db=db, user=finance_only) if group.name == "Lernende")
    assert learners.amount_late == Decimal("2.00")
    without_finance = make_current_user(tenant_id, role="kassier", features=frozenset())
    with pytest.raises(HTTPException):
        route.list_tariffs(db=db, user=without_finance)
