from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class ProtocolCreateFromTemplate(BaseModel):
    tenant_id: int = 1
    template_id: int
    protocol_number: str
    protocol_date: date
    created_by: int | None = None
    title: str | None = None
    event_id: int | None = None


class ProtocolUpdate(BaseModel):
    title: str | None = None
    protocol_date: date | None = None
    event_id: int | None = None
    status: str | None = None


class ProtocolRead(BaseModel):
    id: int
    tenant_id: int
    template_id: int
    template_version: int
    protocol_number: str
    title: str | None = None
    protocol_date: date
    event_id: int | None = None
    status: str
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
