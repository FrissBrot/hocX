"""MAIN-BE-019: Die Bussen-Statistik addiert keine Beträge verschiedener Währungen, und mit
Begründung gelöschte Bussen zählen nicht mit."""
from decimal import Decimal

from app.documents.providers.statistics import _main_currency_rows
from app.services.statistics_common import fetch_fines_by_participant, fetch_fines_by_type
from tests.factories import make_finance_account, make_fine, make_protocol, make_template, make_tenant


def _setup(db):
    tenant = make_tenant(db, "Währungen")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    chf = make_finance_account(db, tenant.id, name="Kasse CHF")
    eur = make_finance_account(db, tenant.id, name="Kasse EUR")
    eur.currency_label = "EUR"
    db.flush()
    make_fine(db, protocol_id=protocol.id, account_id=chf.id, amount=Decimal("5.00"), participant_name_snapshot="Anna")
    make_fine(db, protocol_id=protocol.id, account_id=chf.id, amount=Decimal("5.00"), participant_name_snapshot="Ben", fine_type="absent")
    make_fine(db, protocol_id=protocol.id, account_id=eur.id, amount=Decimal("7.00"), participant_name_snapshot="Anna", fine_type="absent")
    deleted = make_fine(db, protocol_id=protocol.id, account_id=chf.id, amount=Decimal("99.00"), participant_name_snapshot="Cara")
    deleted.status = "deleted"
    deleted.delete_comment = "Erlassen"
    db.flush()
    return tenant, chf


def test_amounts_are_grouped_by_currency(db):
    tenant, chf = _setup(db)

    by_participant = {(row.name, row.currency): (int(row.count), Decimal(row.amount)) for row in fetch_fines_by_participant(db, tenant.id)}
    assert by_participant == {
        ("Anna", chf.currency_label): (1, Decimal("5.00")),
        ("Ben", chf.currency_label): (1, Decimal("5.00")),
        ("Anna", "EUR"): (1, Decimal("7.00")),
    }
    by_type = {(row.fine_type, row.currency): Decimal(row.amount) for row in fetch_fines_by_type(db, tenant.id)}
    assert by_type == {("late", chf.currency_label): Decimal("5.00"), ("absent", chf.currency_label): Decimal("5.00"), ("absent", "EUR"): Decimal("7.00")}


def test_charts_use_the_main_currency_for_amounts(db):
    tenant, chf = _setup(db)

    rows = _main_currency_rows(fetch_fines_by_participant(db, tenant.id))

    assert sorted((row.name, row.currency) for row in rows) == [("Anna", chf.currency_label), ("Ben", chf.currency_label)]
