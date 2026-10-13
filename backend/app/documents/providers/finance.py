"""Finanzen: Kontostände, Buchungen mit Zwischensummen, Bussen.

Setzt das Feature «Finanzen» und Leserecht voraus (Katalog: access="finance"). Konto-Referenzen
aus Parametern und ``configuration_snapshot_json`` sind benutzerkontrolliert und werden
mandantengebunden aufgelöst (Audit 2026-08-25)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select

from app.documents.catalog import BlockSpec, FinanceBalanceParams, FinanceTransactionsParams, FinesParams
from app.documents.context import BuildContext, format_amount, format_date
from app.documents.model import (
    BalanceLine,
    Cell,
    FinanceBalanceBlock,
    FinanceTransactionsBlock,
    FinesBlock,
    TableData,
    TableGroup,
    TableRow,
)
from app.documents.providers.common import amount_cell, col, sort_key, spec_fields, status_cell, text_cell
from app.models import AttendanceFine, FinanceAccount, FinanceTransaction, Protocol


def balance_line(ctx: BuildContext, account: FinanceAccount, as_of: date | None) -> BalanceLine:
    statement = select(func.coalesce(func.sum(FinanceTransaction.amount), 0)).where(FinanceTransaction.account_id == account.id)
    if as_of is not None:
        statement = statement.where(FinanceTransaction.transaction_date <= as_of)
    balance = float(ctx.db.scalar(statement) or 0)
    return BalanceLine(name=account.name, amount=format_amount(balance), currency=account.currency_label or "", negative=balance < 0, as_of=format_date(as_of) if as_of else None)


def provide_balance(ctx: BuildContext, spec: BlockSpec, params: FinanceBalanceParams):
    if params.account_ids:
        accounts = [ctx.require_entity(FinanceAccount, ref) for ref in params.account_ids]
    else:
        accounts = list(ctx.db.scalars(select(FinanceAccount).where(FinanceAccount.tenant_id == ctx.tenant_id).order_by(FinanceAccount.name.asc())))
    return [FinanceBalanceBlock(**spec_fields(spec), balances=[balance_line(ctx, account, params.as_of) for account in accounts])]


def transactions_table(account: FinanceAccount, transactions: list[FinanceTransaction], *, subtotals: str = "none", strings: dict[str, str] | None = None, opening_balance: float = 0.0) -> TableData:
    currency = account.currency_label or ""
    columns = [
        col("date", "col.date"),
        col("description", "col.description", width="fill"),
        col("amount", "col.amount", align="right"),
        col("balance", "col.balance", align="right"),
    ]
    running = opening_balance
    groups: list[TableGroup] = []
    current_key: str | None = None
    group_sum = 0.0

    def close_group() -> None:
        if groups and subtotals != "none":
            groups[-1].subtotal = [Cell(k="text", v="", note_key="label.subtotal"), text_cell(""), amount_cell(f"{format_amount(group_sum, sign=True)} {currency}"), amount_cell("")]

    for tx in transactions:
        amount = float(tx.amount)
        running += amount
        if subtotals == "month":
            key = tx.transaction_date.strftime("%Y-%m")
        elif subtotals == "year":
            key = tx.transaction_date.strftime("%Y")
        else:
            key = ""
        if key != current_key:
            close_group()
            current_key = key
            group_sum = 0.0
            label = None
            if subtotals == "month":
                label = f"{(strings or {}).get(f'month.{tx.transaction_date.month}', str(tx.transaction_date.month))} {tx.transaction_date.year}"
            elif subtotals == "year":
                label = str(tx.transaction_date.year)
            groups.append(TableGroup(label=label))
        group_sum += amount
        groups[-1].rows.append(
            TableRow(cells=[
                text_cell(format_date(tx.transaction_date)),
                text_cell(tx.description),
                amount_cell(f"{format_amount(amount, sign=True)} {currency}", tone="danger" if amount < 0 else "default"),
                amount_cell(f"{format_amount(running)} {currency}"),
            ])
        )
    close_group()
    total = sum(float(tx.amount) for tx in transactions)
    totals = [Cell(k="text", v="", note_key="label.total"), text_cell(""), amount_cell(f"{format_amount(total, sign=True)} {currency}"), amount_cell(f"{format_amount(running)} {currency}")] if transactions else None
    return TableData(columns=columns, groups=groups, totals=totals)


def provide_transactions(ctx: BuildContext, spec: BlockSpec, params: FinanceTransactionsParams):
    from app.documents.strings import strings_for

    if params.account_id is None:
        return [FinanceTransactionsBlock(**spec_fields(spec), table=TableData(columns=[col("date", "col.date")]))]
    account = ctx.require_entity(FinanceAccount, params.account_id)
    statement = select(FinanceTransaction).where(FinanceTransaction.account_id == account.id)
    if params.date_from is not None:
        statement = statement.where(FinanceTransaction.transaction_date >= params.date_from)
    if params.date_to is not None:
        statement = statement.where(FinanceTransaction.transaction_date <= params.date_to)
    transactions = list(ctx.db.scalars(statement.order_by(FinanceTransaction.transaction_date.asc(), FinanceTransaction.id.asc())))
    if params.last_n:
        transactions = transactions[-params.last_n:]
    opening = 0.0
    if transactions:
        first = transactions[0]
        opening = float(ctx.db.scalar(
            select(func.coalesce(func.sum(FinanceTransaction.amount), 0)).where(
                FinanceTransaction.account_id == account.id,
                (FinanceTransaction.transaction_date < first.transaction_date)
                | ((FinanceTransaction.transaction_date == first.transaction_date) & (FinanceTransaction.id < first.id)),
            )
        ) or 0)
    table = transactions_table(account, transactions, subtotals=params.subtotals, strings=strings_for(ctx.language), opening_balance=opening)
    return [FinanceTransactionsBlock(**spec_fields(spec, title=spec.title if spec.title is not None else account.name), table=table)]


FINE_STATUS = {"pending": "open", "collected": "collected"}


def fines_table(ctx: BuildContext, own: list[AttendanceFine], collected_here: list[AttendanceFine], *, group_by_person: bool = False) -> TableData:
    columns = [col("person", "col.person", width="fill"), col("reason", "col.reason"), col("amount", "col.amount", align="right"), col("status", "col.status")]
    accounts: dict[int, FinanceAccount | None] = {}

    def currency(fine: AttendanceFine) -> str:
        if fine.account_id not in accounts:
            accounts[fine.account_id] = ctx.db.get(FinanceAccount, fine.account_id)
        account = accounts[fine.account_id]
        return account.currency_label if account else ""

    def row(fine: AttendanceFine, status: Cell) -> TableRow:
        return TableRow(cells=[
            text_cell(fine.participant_name_snapshot),
            Cell(k="text", v="", note_key=f"fineType.{fine.fine_type}") if fine.fine_type in ("late", "absent") else text_cell(fine.fine_type),
            amount_cell(f"{format_amount(fine.amount)} {currency(fine)}"),
            status,
        ])

    items: list[tuple[str, TableRow, AttendanceFine]] = []
    for fine in own:
        if fine.status == "collected" and fine.closed_in_protocol_id is None:
            status = status_cell("fineStatus.collected")
        elif fine.status == "collected":
            status = status_cell("fineStatus.collectedLater")
        else:
            status = status_cell("fineStatus.open")
        items.append((fine.participant_name_snapshot, row(fine, status), fine))
    for fine in collected_here:
        # Offene Busse aus einem früheren Protokoll, hier kassiert: Herkunft als Zusatz.
        origin = ctx.db.get(Protocol, fine.protocol_id)
        status = Cell(k="status", status="fineStatus.collected", v=origin.protocol_number if origin is not None else "")
        items.append((fine.participant_name_snapshot, row(fine, status), fine))
    if group_by_person:
        items.sort(key=lambda item: sort_key(item[0]))
    rows = [item[1] for item in items]
    totals_by_currency: dict[str, float] = {}
    for _, _, fine in items:
        totals_by_currency[currency(fine)] = totals_by_currency.get(currency(fine), 0.0) + float(fine.amount)
    totals = None
    if items:
        totals = [Cell(k="text", v="", note_key="label.total"), text_cell(""), amount_cell(" · ".join(f"{format_amount(value)} {code}" for code, value in totals_by_currency.items())), text_cell("")]
    return TableData(columns=columns, groups=[TableGroup(rows=rows)] if rows else [], totals=totals)


def protocol_fines(ctx: BuildContext, protocol: Protocol, config: dict | None = None) -> TableData:
    """Bussen eines Protokolls mit den Optionen der Bussenliste (period.ts::filterFines)."""
    from app.services.protocol_period_service import protocol_period

    config = config or {}
    own = list(ctx.db.scalars(
        select(AttendanceFine).where(AttendanceFine.protocol_id == protocol.id, AttendanceFine.status.in_(["pending", "collected"])).order_by(AttendanceFine.created_at.asc())
    ))
    collected_here = list(ctx.db.scalars(select(AttendanceFine).where(AttendanceFine.closed_in_protocol_id == protocol.id).order_by(AttendanceFine.collected_at.asc())))
    account_filter = ctx.ref_to_internal_id(FinanceAccount, config.get("fine_list_account_id"))
    if account_filter:
        own = [fine for fine in own if fine.account_id == account_filter]
        collected_here = [fine for fine in collected_here if fine.account_id == account_filter]
    if config.get("fine_list_status") == "open":
        own = [fine for fine in own if fine.status == "pending"]
        collected_here = []
    fine_range = config.get("fine_list_range") or "all"
    if fine_range == "this_protocol":
        collected_here = []
    elif fine_range == "this_cycle":
        bounds = protocol_period(ctx.db, protocol)
        if bounds.get("cycle_start"):
            def in_cycle(fine: AttendanceFine) -> bool:
                origin = ctx.db.get(Protocol, fine.protocol_id)
                return origin is not None and bounds["cycle_start"] <= origin.protocol_date.isoformat() <= bounds["cycle_end"]

            collected_here = [fine for fine in collected_here if in_cycle(fine)]
    return fines_table(ctx, own, collected_here, group_by_person=config.get("fine_list_group_by") == "participant")


def provide_fines(ctx: BuildContext, spec: BlockSpec, params: FinesParams):
    protocol = ctx.entity_by_ref(Protocol, params.protocol_id) if params.protocol_id else None
    if params.protocol_id and protocol is None:
        from app.documents.context import DocumentNotFoundError

        raise DocumentNotFoundError("Protocol")
    if protocol is None and ctx.protocol is not None and params.date_from is None and params.date_to is None:
        protocol = ctx.protocol
    if protocol is not None:
        ctx.ensure_can_read_protocol(protocol.id)
        table = protocol_fines(ctx, protocol, {"fine_list_status": params.status, "fine_list_group_by": "participant" if params.group_by_person else ""})
        return [FinesBlock(**spec_fields(spec), table=table)]
    statement = (
        select(AttendanceFine)
        .join(Protocol, Protocol.id == AttendanceFine.protocol_id)
        .where(Protocol.tenant_id == ctx.tenant_id, AttendanceFine.status.in_(["pending", "collected"]))
    )
    if params.status == "open":
        statement = statement.where(AttendanceFine.status == "pending")
    if params.date_from is not None:
        statement = statement.where(Protocol.protocol_date >= params.date_from)
    if params.date_to is not None:
        statement = statement.where(Protocol.protocol_date <= params.date_to)
    fines = list(ctx.db.scalars(statement.order_by(Protocol.protocol_date.asc(), AttendanceFine.created_at.asc())))
    return [FinesBlock(**spec_fields(spec), table=fines_table(ctx, fines, [], group_by_person=params.group_by_person))]

