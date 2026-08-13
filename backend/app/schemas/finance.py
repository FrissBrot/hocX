from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import BaseModel, PlainSerializer

_CENTS = Decimal("0.01")


def _decimal_to_json_float(value: Decimal) -> float:
    """Quantizes to the DB's actual precision (Numeric(15,2)) before the JSON boundary, so a
    Decimal with stray extra digits (e.g. from any future intermediate computation) can't leak
    visible floating-point noise (like 3.499999999999998) into the API response instead of the
    clean 2-decimal value every caller expects."""
    return float(value.quantize(_CENTS, rounding=ROUND_HALF_UP))


# Decimal that serializes as a JSON number (float) so the frontend receives 3.50, not "3.50"
FinanceDecimal = Annotated[Decimal, PlainSerializer(_decimal_to_json_float, return_type=float, when_used="json")]


class FinanceAccountCreate(BaseModel):
    name: str
    currency_label: str = "CHF"
    description: str | None = None


class FinanceAccountUpdate(BaseModel):
    name: str | None = None
    currency_label: str | None = None
    description: str | None = None


class FinanceAccountRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    currency_label: str
    description: str | None
    balance: FinanceDecimal
    provisional_balance: FinanceDecimal = Decimal(0)
    transaction_count: int
    created_at: datetime


class FinanceTransactionCreate(BaseModel):
    amount: FinanceDecimal
    description: str
    transaction_date: date
    protocol_id: int | None = None


class FinanceTransactionUpdate(BaseModel):
    amount: FinanceDecimal | None = None
    description: str | None = None
    transaction_date: date | None = None


class FinanceTransactionRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    account_id: int
    amount: FinanceDecimal
    description: str
    transaction_date: date
    protocol_id: int | None
    created_at: datetime
    # Cumulative account balance up to and including this transaction (chronological
    # order), computed server-side so pagination doesn't break the running total.
    # Only populated by list_transactions; single-transaction create/update responses
    # leave this None since it isn't cheap to recompute for one row in isolation.
    running_balance: FinanceDecimal | None = None
