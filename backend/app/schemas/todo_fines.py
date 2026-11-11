"""Pendenzen-Bussen: Tarife, Regeln, Bussen (app/services/todo_fine_service.py)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.fines import FinanceDecimal

SplitMode = Literal["each", "split"]
FineMode = Literal["auto", "rule", "fixed", "none"]
NonNegativeAmount = Annotated[Decimal, Field(ge=0, le=Decimal("1000000"), decimal_places=2)]
Name = Annotated[str, Field(min_length=1, max_length=120)]


def _clean_tags(tags: list[str]) -> list[str]:
    cleaned: list[str] = []
    for tag in tags:
        value = str(tag).strip()
        if value and value.lower() not in {t.lower() for t in cleaned}:
            cleaned.append(value[:80])
    return cleaned


# ── Tarife ───────────────────────────────────────────────────────────


class FineTariffGroupRead(BaseModel):
    id: uuid.UUID
    name: str
    sort_index: int
    is_default: bool
    member_count: int = 0


class FineTariffGroupWrite(BaseModel):
    name: Name
    is_default: bool = False

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return value


class FineTariffGroupOrder(BaseModel):
    ids: list[uuid.UUID] = Field(max_length=200)


class FineTariffMember(BaseModel):
    participant_id: uuid.UUID
    display_name: str
    tariff_group_id: uuid.UUID | None
    is_active: bool


class FineTariffAssignment(BaseModel):
    tariff_group_id: uuid.UUID | None = None


# ── Regeln ───────────────────────────────────────────────────────────


class TodoFineRuleRateWrite(BaseModel):
    tariff_group_id: uuid.UUID
    base_amount: NonNegativeAmount = Decimal("0")
    interval_amount: NonNegativeAmount = Decimal("0")


class TodoFineRuleRateRead(BaseModel):
    tariff_group_id: uuid.UUID
    base_amount: FinanceDecimal
    interval_amount: FinanceDecimal


class TodoFineRuleFilter(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=50)
    task_package_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    participant_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    role_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: list[str]) -> list[str]:
        return _clean_tags(value)


class TodoFineRuleWrite(BaseModel):
    name: Name
    is_active: bool = True
    applies_from: date
    interval_days: int = Field(default=1, ge=1, le=365)
    split_mode: SplitMode = "each"
    account_id: uuid.UUID | None = None
    filter: TodoFineRuleFilter = Field(default_factory=TodoFineRuleFilter)
    rates: list[TodoFineRuleRateWrite] = Field(default_factory=list, max_length=50)

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return value


class TodoFineRuleRead(BaseModel):
    id: uuid.UUID
    name: str
    sort_index: int
    is_active: bool
    applies_from: date
    interval_days: int
    split_mode: SplitMode
    account_id: uuid.UUID | None
    filter: TodoFineRuleFilter
    rates: list[TodoFineRuleRateRead]


class FilterOption(BaseModel):
    id: uuid.UUID
    name: str | None
    system_key: str | None = None


class TodoFineFilterOptions(BaseModel):
    """Auswahl für den Regelfilter - nur Name und ID, damit die Kasse ohne templates.manage/
    access.manage Aufgabenpakete und Rollen wählen kann."""

    tags: list[str]
    task_packages: list[FilterOption]
    roles: list[FilterOption]
    participants: list[FilterOption]


class TodoFineRuleOrder(BaseModel):
    ids: list[uuid.UUID] = Field(max_length=200)


# ── Bussen ───────────────────────────────────────────────────────────


class TodoFineLine(BaseModel):
    participant_id: uuid.UUID | None
    participant_name: str
    tariff_name: str | None
    amount: FinanceDecimal


class TodoFineEvaluation(BaseModel):
    """Busse eines Todos: ok (Betrag je Person), conflict (mehrere Regeln, Zuweisung von Hand),
    sonst ein Grund, warum keine Busse anfällt."""

    state: Literal[
        "ok", "conflict", "no_rule", "rule_missing", "none", "cancelled", "no_due_date", "on_time", "no_assignee",
    ]
    fine_mode: FineMode
    fine_rule_id: uuid.UUID | None = None
    fine_fixed_amount: FinanceDecimal | None = None
    fine_split_mode: SplitMode | None = None
    rule_id: uuid.UUID | None = None
    rule_name: str | None = None
    matching_rules: list["TodoFineRuleRef"] = Field(default_factory=list)
    due_date: date | None = None
    days_late: int = 0
    running: bool = False
    frozen: bool = False
    split_mode: SplitMode | None = None
    lines: list[TodoFineLine] = Field(default_factory=list)
    total: FinanceDecimal = Decimal("0")
    can_manage: bool = False


class TodoFineRuleRef(BaseModel):
    id: uuid.UUID
    name: str


class TodoFineSettings(BaseModel):
    fine_mode: FineMode
    fine_rule_id: uuid.UUID | None = None
    fine_fixed_amount: NonNegativeAmount | None = None
    fine_split_mode: SplitMode | None = None


class TodoFineListItem(BaseModel):
    """Eine Zeile der Bussenliste. Laufende Bussen (Todo offen) haben keine eigene ID und
    status "running"; Konflikte (status "conflict") warten auf eine Zuweisung von Hand."""

    id: uuid.UUID | None
    status: Literal["running", "conflict", "pending", "collected", "deleted"]
    todo_id: uuid.UUID | None
    task: str
    participant_id: uuid.UUID | None
    participant_name: str | None
    tariff_name: str | None = None
    rule_name: str | None = None
    matching_rules: list[TodoFineRuleRef] = Field(default_factory=list)
    due_date: date | None
    completed_on: date | None = None
    days_late: int
    amount: FinanceDecimal
    account_id: uuid.UUID | None = None
    currency_label: str | None = None
    collected_at: datetime | None = None
    collected_by_display_name: str | None = None
    delete_comment: str | None = None
    deleted_at: datetime | None = None
    deleted_by_display_name: str | None = None
    can_reopen: bool = False


class TodoFineDelete(BaseModel):
    reason: Annotated[str, Field(min_length=1, max_length=1000)]


TodoFineEvaluation.model_rebuild()
