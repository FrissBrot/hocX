from datetime import date, datetime

from pydantic import BaseModel


class ProtocolCreateFromTemplate(BaseModel):
    tenant_id: int = 1
    template_id: int
    protocol_number: str
    protocol_date: date
    created_by: int = 1
    title: str | None = None
    event_id: int | None = None


class ProtocolRead(BaseModel):
    id: int
    protocol_number: str
    title: str | None = None
    protocol_date: date
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

