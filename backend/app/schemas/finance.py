from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import BaseModel, Field, PlainSerializer, StringConstraints

_CENTS = Decimal("0.01")


def _decimal_to_json_float(value: Decimal) -> float:
    """Quantizes to the DB's actual precision (Numeric(15,2)) before the JSON boundary, so a
    Decimal with stray extra digits (e.g. from any future intermediate computation) can't leak
    visible floating-point noise (like 3.499999999999998) into the API response instead of the
    clean 2-decimal value every caller expects."""
    return float(value.quantize(_CENTS, rounding=ROUND_HALF_UP))


# Decimal that serializes as a JSON number (float) so the frontend receives 3.50, not "3.50"
FinanceDecimal = Annotated[Decimal, PlainSerializer(_decimal_to_json_float, return_type=float, when_used="json")]


# Eingabegrenzen: Beträge passen in Numeric(15,2), Texte haben eine sinnvolle Länge. Sonst
# endeten zu grosse Werte als 400/500 aus der Datenbank statt als 422 mit Feldhinweis.
MAX_AMOUNT = Decimal("9999999999999.99")
AccountName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
CurrencyLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
AccountDescription = Annotated[str, StringConstraints(max_length=2000)]
TransactionDescription = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
AmountInput = Annotated[Decimal, Field(ge=-MAX_AMOUNT, le=MAX_AMOUNT)]


class FinanceAccountCreate(BaseModel):
    name: AccountName
    currency_label: CurrencyLabel = "CHF"
    description: AccountDescription | None = None


class FinanceAccountUpdate(BaseModel):
    name: AccountName | None = None
    currency_label: CurrencyLabel | None = None
    # null bzw. "" leert die Beschreibung (Repository wertet model_fields_set aus)
    description: AccountDescription | None = None


class FinanceAccountRead(BaseModel):
    # Built via explicit keyword construction in FinanceRepository (balance/provisional
    # come from aggregate queries, not plain ORM attributes) - id is set from the account
    # row's public_id there directly.
    id: uuid.UUID
    name: str
    currency_label: str
    description: str | None
    balance: FinanceDecimal
    provisional_balance: FinanceDecimal = Decimal(0)
    transaction_count: int
    created_at: datetime


class FinanceTransactionCreate(BaseModel):
    amount: AmountInput
    description: TransactionDescription
    transaction_date: date
    protocol_id: uuid.UUID | None = None


class FinanceTransactionUpdate(BaseModel):
    amount: AmountInput | None = None
    description: TransactionDescription | None = None
    transaction_date: date | None = None


class FinanceTransactionRead(BaseModel):
    # Built via explicit keyword construction (FinanceRepository._tx_read) - see
    # FinanceAccountRead's identical note.
    id: uuid.UUID
    account_id: uuid.UUID
    amount: FinanceDecimal
    description: str
    transaction_date: date
    protocol_id: uuid.UUID | None
    created_at: datetime
    # Cumulative account balance up to and including this transaction (chronological
    # order), computed server-side so pagination doesn't break the running total.
    # Only populated by list_transactions; single-transaction create/update responses
    # leave this None since it isn't cheap to recompute for one row in isolation.
    running_balance: FinanceDecimal | None = None
    # Gesperrte Buchung (nicht direkt änderbar): "fine_transaction" / "todo_fine_transaction"
    # (Name der Person in locked_detail) oder "protocol_finalized" (Protokollnummer).
    locked_reason: str | None = None
    locked_detail: str | None = None


class FinancePeriodSummary(BaseModel):
    """Jahressicht eines Kontos (Kassenbericht in der App): Einnahmen, Ausgaben (negativ),
    Saldo am Anfang/Ende des Zeitraums und die Jahre mit Buchungen."""
    year: int | None
    income: FinanceDecimal
    expenses: FinanceDecimal
    net: FinanceDecimal
    opening_balance: FinanceDecimal
    closing_balance: FinanceDecimal
    transaction_count: int
    years: list[int]
