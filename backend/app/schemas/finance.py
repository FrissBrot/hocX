from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, PlainSerializer

# Decimal that serializes as a JSON number (float) so the frontend receives 3.50, not "3.50"
FinanceDecimal = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")]


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
