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


class PartnerHistoryRead(BaseModel):
    """Eintrag im Verlauf der Partner-Organisationen (app/public_links/partner_history.py):
    Partner nur als Organisationsname, eigene Personen mit Anzeigenamen, keine IP/E-Mail."""

    at: datetime
    event: Literal["invited", "accepted", "declined", "public_link_created"]
    actor: Literal["partner", "own"]
    partner: str
    person: str | None
    album: str
    link_name: str | None
    expires_at: datetime | None
