from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class PublicLinkRead(BaseModel):
    kind: str
    id: str
    label: str
    params: dict[str, str | int]
    created_at: datetime | None
    created_by: str | None
    expiry: Literal["date", "never", "single_use", "window"]
    expires_at: datetime | None
    last_used_at: datetime | None
    manage_href: str | None
