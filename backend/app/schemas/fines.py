from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, PlainSerializer

FinanceDecimal = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")]

# Fines are always a charge against a participant, never a rebate - unlike
# FinanceTransactionCreate.amount (app/schemas/finance.py), where a negative amount
# intentionally represents an expense. gt=0 rejects zero/negative fine amounts at the API boundary.
PositiveFineAmount = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json"), Field(gt=0)]


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
