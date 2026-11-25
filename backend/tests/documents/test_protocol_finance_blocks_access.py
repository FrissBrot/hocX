"""Protokoll-Export: Finanz- und Bussenblöcke im Protokoll halten dieselben Rechte ein wie die
eigenständigen Document-Studio-Bausteine und die API.

- «Bussenliste» (fine_list): ohne reports.personal nur die eigenen Bussen (wie GET /api/fines,
  /protocols/{id}/fines und der Baustein «Bussen», BuildContext.own_fines_participant_id).
- «Kontostand»/«Buchungen» (finance_balance/finance_transactions): nur mit finances.read inkl.
  gebuchtem Modul (wie /api/finance/* und die Bausteine mit access="finance")."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.documents.catalog import BlockSpec
from app.documents.compiler import build_blocks
from app.documents.context import BuildContext
from app.models import FinanceTransaction
from tests.factories import (
    make_current_user,
    make_finance_account,
    make_fine,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
    system_role_permissions,
)


def _world(db):
    tenant = make_tenant(db, "Verein Bussen-PDF")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="P-1", protocol_date=date(2026, 3, 1), status="abgeschlossen")
    account = make_finance_account(db, tenant.id)
    db.add(FinanceTransaction(account_id=account.id, amount=Decimal("4321.55"), description="Geheime Spende", transaction_date=date(2026, 2, 1)))
    me = make_participant(db, tenant.id, "Lea Leserin")
    other = make_participant(db, tenant.id, "Otto Andere")
    for person in (me, other):
        fine = make_fine(db, protocol_id=protocol.id, account_id=account.id, amount=Decimal("5.00"), participant_name_snapshot=person.display_name)
        fine.participant_id = person.id
    element = make_protocol_element(db, protocol.id, section_name="Kasse")
    make_protocol_element_block(db, element.id, {}, element_type_code="fine_list", sort_index=0)
    make_protocol_element_block(db, element.id, {"finance_account_id": account.id}, element_type_code="finance_balance", sort_index=1)
    make_protocol_element_block(db, element.id, {"finance_account_id": account.id}, element_type_code="finance_transactions", sort_index=2)
    db.flush()
    return tenant, protocol, me


def _export(db, tenant, protocol, user) -> str:
    ctx = BuildContext(db=db, tenant_id=tenant.id, language="de", protocol=protocol, today=date(2026, 3, 1), user=user)
    blocks = build_blocks(ctx, [BlockSpec(type="protocol_element")])
    return str([block.model_dump(mode="json") for block in blocks])


def test_reader_protocol_export_lists_only_own_fines(db):
    tenant, protocol, me = _world(db)
    reader = make_current_user(tenant.id, role="reader", user_id=me.id, permissions=system_role_permissions("reader"))

    dumped = _export(db, tenant, protocol, reader)

    assert "Lea Leserin" in dumped
    assert "Otto Andere" not in dumped


def test_protocol_export_without_finance_read_hides_balance_and_transactions(db):
    tenant, protocol, me = _world(db)
    no_finance = make_current_user(tenant.id, role="reader", user_id=me.id, permissions=frozenset({"meetings.read"}))

    dumped = _export(db, tenant, protocol, no_finance)

    assert "4321.55" not in dumped and "4’321.55" not in dumped and "4'321.55" not in dumped
    assert "Geheime Spende" not in dumped


def test_full_view_still_contains_everything(db):
    tenant, protocol, me = _world(db)
    admin = make_current_user(tenant.id, role="admin", user_id=me.id)

    dumped = _export(db, tenant, protocol, admin)

    assert "Lea Leserin" in dumped and "Otto Andere" in dumped
    assert "Geheime Spende" in dumped
