from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CalendarFeedUpsert(BaseModel):
    # In der UI-Sprache vom Frontend uebersetzt (z. B. "hocX – Termine (Mandant)") - erscheint als
    # Kalendername in Apple/Google.
    calendar_name: str = Field(min_length=1, max_length=200)
    todo_scope: Literal["mine", "all"] = "mine"
    include_completed: bool = False
    hide_details: bool = False


class CalendarFeedRead(BaseModel):
    kind: Literal["events", "todos"]
    calendar_name: str
    # Relativer Pfad - das Frontend setzt die eigene Origin davor (wie ShareLinkRead.url).
    path: str
    todo_scope: Literal["mine", "all"]
    include_completed: bool
    hide_details: bool
    created_at: datetime
    token_created_at: datetime
    last_accessed_at: datetime | None = None
    # "invalid": nach Ausstellung der URL wurden alle Sitzungen widerrufen (Passwortwechsel,
    # "ueberall abmelden") - der Feed liefert dann 404, bis eine neue URL erzeugt wird.
    status: Literal["active", "invalid"]
