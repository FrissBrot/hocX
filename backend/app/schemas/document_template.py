from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

# code becomes a path segment (document_templates/tenant-{id}/{code}-v{version}, resp.
# document_template_parts/tenant-{id}/{part_type}/{code}) - restrict it to the same
# character set the auto-generator produces, plus underscores used by legacy built-in codes
# such as ``default_protocol``. Separators must be single and surrounded by alphanumerics,
# so the value can never contain "/", "..", or other path-traversal payloads.
_CODE_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")


def _validate_code(value: str | None) -> str | None:
    if value is not None and not _CODE_RE.match(value):
        raise ValueError(
            "code darf nur Kleinbuchstaben, Ziffern und einzelne Binde- oder Unterstriche enthalten"
        )
    return value


class DocumentTemplatePartBase(BaseModel):
    code: str | None = None
    name: str
    part_type: str
    description: str | None = None
    version: int = Field(default=1, ge=1)
    is_active: bool = True

    _validate_code = field_validator("code")(_validate_code)


class DocumentTemplatePartCreate(DocumentTemplatePartBase):
    pass


class DocumentTemplatePartUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    part_type: str | None = None
    description: str | None = None
    version: int | None = Field(default=None, ge=1)
    is_active: bool | None = None

    _validate_code = field_validator("code")(_validate_code)


class DocumentTemplatePartRead(DocumentTemplatePartBase):
    id: int
    tenant_id: int
    code: str
    storage_path: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentTemplateBase(BaseModel):
    code: str | None = None
    name: str
    description: str | None = None
    version: int = Field(default=1, ge=1)
    is_active: bool = True
    is_default: bool = False
    configuration_json: dict[str, Any] = Field(default_factory=dict)

    _validate_code = field_validator("code")(_validate_code)


class DocumentTemplateCreate(DocumentTemplateBase):
    pass


class DocumentTemplateUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    description: str | None = None
    version: int | None = Field(default=None, ge=1)
    is_active: bool | None = None
    is_default: bool | None = None
    configuration_json: dict[str, Any] | None = None

    _validate_code = field_validator("code")(_validate_code)


class DocumentTemplateRead(DocumentTemplateBase):
    id: int
    tenant_id: int
    code: str
    filesystem_path: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
