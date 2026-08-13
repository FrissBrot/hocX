from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, PlainSerializer

_CENTS = Decimal("0.01")


def _decimal_to_json_float(value: Decimal) -> float:
    """Quantizes to the DB's actual precision (Numeric(15,2)) before the JSON boundary, so a
    Decimal with stray extra digits (e.g. from any future intermediate computation) can't leak
    visible floating-point noise (like 3.499999999999998) into the API response instead of the
    clean 2-decimal value every caller expects."""
    return float(value.quantize(_CENTS, rounding=ROUND_HALF_UP))


FinanceDecimal = Annotated[Decimal, PlainSerializer(_decimal_to_json_float, return_type=float, when_used="json")]

# Fines are always a charge against a participant, never a rebate - unlike
# FinanceTransactionCreate.amount (app/schemas/finance.py), where a negative amount
# intentionally represents an expense. gt=0 rejects zero/negative fine amounts at the API boundary.
PositiveFineAmount = Annotated[Decimal, PlainSerializer(_decimal_to_json_float, return_type=float, when_used="json"), Field(gt=0)]


class AttendanceFineCreate(BaseModel):
    protocol_id: int
    participant_id: int | None = None
    participant_name_snapshot: str
    fine_type: Literal["late", "absent"]
    amount: PositiveFineAmount
    account_id: int


class AttendanceFineRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    protocol_id: int
    participant_id: int | None
    participant_name_snapshot: str
    fine_type: str
    amount: FinanceDecimal
    account_id: int
    status: str
    collected_at: datetime | None
    collected_transaction_id: int | None
    closed_in_protocol_id: int | None = None
    collected_by_user_id: int | None = None
    collected_by_display_name: str | None = None
    can_reopen: bool = False
    created_at: datetime


class AttendanceFineListItem(AttendanceFineRead):
    protocol_number: str | None = None
    protocol_date: str | None = None
    currency_label: str | None = None


class CollectFinePayload(BaseModel):
    collecting_protocol_id: int | None = None
