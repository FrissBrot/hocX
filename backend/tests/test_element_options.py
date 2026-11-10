"""Neue Block-Optionen aus der Element-Analyse: Zeitraumregeln der Finanzblöcke, Kontostand
zum Stichtag, Optionen der Bussenliste."""
from datetime import date

from app.models import FinanceTransaction
from app.repositories.finance_repository import FinanceRepository
from app.documents.context import BuildContext
from app.documents.providers import finance as finance_provider
from app.documents.providers.protocol import _finance_balance_block
from app.services.protocol_period_service import protocol_period, transaction_matches
from tests.factories import make_cycle_config, make_finance_account, make_fine, make_protocol, make_template, make_tenant


def _protocols(db):
    tenant = make_tenant(db)
    cycle = make_cycle_config(db, tenant.id, reset_month=7, reset_day=31)
    template = make_template(db, tenant.id)
    template.cycle_config_id = cycle.id
    earlier = make_protocol(db, tenant.id, template.id, protocol_number="P-1")
    earlier.protocol_date = date(2026, 3, 1)
    current = make_protocol(db, tenant.id, template.id, protocol_number="P-2")
    current.protocol_date = date(2026, 4, 1)
    db.flush()
    return tenant, earlier, current


def test_protocol_period_previous_date_and_cycle_bounds(db):
    _tenant, _earlier, current = _protocols(db)
    assert protocol_period(db, current) == {
        "previous_protocol_date": "2026-03-01",
        "cycle_start": "2025-08-01",
        "cycle_end": "2026-07-31",
    }


def test_transaction_rules_match_frontend():
    period = {"previous_protocol_date": "2026-03-01", "cycle_start": "2025-08-01", "cycle_end": "2026-07-31"}
    since_last = {"finance_filter_type": "since_last_session"}
    assert not transaction_matches(date(2026, 3, 1), since_last, protocol_date=date(2026, 4, 1), period=period)
    assert transaction_matches(date(2026, 3, 2), since_last, protocol_date=date(2026, 4, 1), period=period)
    cycle = {"finance_filter_type": "this_cycle"}
    assert transaction_matches(date(2025, 9, 1), cycle, protocol_date=date(2026, 4, 1), period=period)
    assert not transaction_matches(date(2025, 6, 1), cycle, protocol_date=date(2026, 4, 1), period=period)
    year = {"finance_filter_type": "this_year"}
    assert transaction_matches(date(2025, 1, 5), year, protocol_date=date(2025, 12, 1), period=period)


def test_balance_as_of_protocol_date(db):
    tenant, _earlier, current = _protocols(db)
    account = make_finance_account(db, tenant.id)
    for day, amount in ((date(2026, 1, 1), 100), (date(2026, 5, 1), 50)):
        db.add(FinanceTransaction(account_id=account.id, amount=amount, description="x", transaction_date=day))
    db.flush()

    assert FinanceRepository().balance_as_of(db, account.id, date(2026, 4, 1)) == 100.0
    assert FinanceRepository().balance_as_of(db, account.id) == 150.0
    ctx = BuildContext(db=db, tenant_id=tenant.id, language="de", protocol=current)
    block = _finance_balance_block(ctx, current, {"finance_account_id": account.id, "finance_balance_date": "protocol_date"}, {})
    assert block.balances[0].amount == "100.00"


def test_fine_list_options_in_export(db):
    tenant, _earlier, current = _protocols(db)
    account = make_finance_account(db, tenant.id, name="Bussen")
    other = make_finance_account(db, tenant.id, name="Anderes")
    make_fine(db, current.id, account.id, participant_name_snapshot="Zora")
    collected = make_fine(db, current.id, account.id, participant_name_snapshot="Anna")
    collected.status = "collected"
    make_fine(db, current.id, other.id, participant_name_snapshot="Ben")
    db.flush()

    ctx = BuildContext(db=db, tenant_id=tenant.id, language="de", protocol=current)

    def names(table) -> list[str]:
        return [row.cells[0].v for group in table.groups for row in group.rows]

    content = names(finance_provider.protocol_fines(ctx, current, {"fine_list_account_id": account.id, "fine_list_status": "open"}))
    assert content == ["Zora"]

    grouped = names(finance_provider.protocol_fines(ctx, current, {"fine_list_group_by": "participant"}))
    assert grouped.index("Anna") < grouped.index("Ben") < grouped.index("Zora")


def test_attendance_block_excludes_configured_participants(db):
    from tests.factories import make_element_definition, make_participant, make_template_element, make_template_participant
    from tests.test_protocol_template_sync import _block, _blocks, _create, _elements

    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    anna = make_participant(db, tenant.id, display_name="Anna")
    ben = make_participant(db, tenant.id, display_name="Ben")
    for participant in (anna, ben):
        make_template_participant(db, template.id, participant.id)
    definition = make_element_definition(db, tenant.id, "Anwesenheit", blocks=[
        _block(db, code="attendance", title="Anwesenheit", configuration_json={"attendance_excluded_participant_ids": [ben.id]}),
    ])
    make_template_element(db, template.id, definition.id, sort_index=10, section_name="Anwesenheit")

    protocol = _create(db, template)
    block = _blocks(db, _elements(db, protocol.id)[0].id)[0]

    assert [entry["participant_name"] for entry in block.configuration_snapshot_json["attendance_entries"]] == ["Anna"]
