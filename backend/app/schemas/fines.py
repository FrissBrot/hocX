from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, PlainSerializer

FinanceDecimal = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")]


class AttendanceFineCreate(BaseModel):
    protocol_id: int
    participant_id: int | None = None
    participant_name_snapshot: str
    fine_type: Literal["late", "absent"]
    amount: FinanceDecimal
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
    delete_comment: str | None = None
    created_at: datetime


class AttendanceFineListItem(AttendanceFineRead):
    protocol_number: str | None = None
    protocol_date: str | None = None
    currency_label: str | None = None


class CollectFinePayload(BaseModel):
    collecting_protocol_id: int | None = None


class DeleteFinePayload(BaseModel):
    delete_comment: str | None = None
    closing_protocol_id: int | None = None


class SetDeleteCommentPayload(BaseModel):
    delete_comment: str
