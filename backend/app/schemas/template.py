from datetime import datetime

from pydantic import BaseModel


class TemplateBase(BaseModel):
    name: str
    description: str | None = None
    version: int = 1
    status: str = "active"
    document_template_id: int | None = None


class TemplateCreate(TemplateBase):
    tenant_id: int = 1
    created_by: int | None = None


class TemplateRead(TemplateBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

